"""B3: issuer_interest, an optional declared stake on a source. Shown to workers, ignored by the kernel."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from inquiry.v1.contracts import InquiryValidationError, request_json_schema, validate_inquiry_request
from inquiry.v1.evidence import EvidenceEnvironment
from inquiry.v1.kernel import evaluate
from inquiry.v1.models import InquiryGraph, Profile
from inquiry.v1.runtime import starter_graph
from inquiry.v1.workers import RecordedWorker
from inquiry.v1.service import InquiryService

from test_stakes import reply


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "v1"
INTEREST = "Paid on completion of the inspection it reports."


def base():
    return json.loads((EXAMPLES / "equipment_temperature.json").read_text(encoding="utf-8"))


def with_interest(public, text=INTEREST):
    public = deepcopy(public)
    public["corpus"]["documents"][0]["issuer_interest"] = text
    return public


def test_issuer_interest_validates_as_optional_nonempty_text():
    public = base()
    first = public["corpus"]["documents"][0]
    validate_inquiry_request(with_interest(public))
    for bad in ("", "   ", 3, None, ["x"]):
        with pytest.raises(InquiryValidationError, match="issuer_interest"):
            validate_inquiry_request(with_interest(public, bad))
    unknown = deepcopy(public)
    unknown["corpus"]["documents"][0]["issuer_stake"] = INTEREST
    with pytest.raises(InquiryValidationError, match="unknown"):
        validate_inquiry_request(unknown)
    schema = request_json_schema()
    source = schema["$defs"]["source"]
    assert source["properties"]["issuer_interest"] == source["properties"]["title"]
    assert "issuer_interest" not in source["required"]
    assert "issuer_interest" not in first  # the shipped example is unchanged


def test_issuer_interest_is_shown_in_manifest_search_and_open():
    public = with_interest(base())
    first = public["corpus"]["documents"][0]
    for mode in ("documents", "search"):
        env = EvidenceEnvironment(public, mode)
        shown = {(s["source_id"], s["version"]): s for s in env.manifest()}
        assert shown[(first["id"], first["version"])]["issuer_interest"] == INTEREST
        assert all("issuer_interest" not in s for key, s in shown.items() if key != (first["id"], first["version"]))
        opened = env.open(first["id"], first["version"])
        assert opened["issuer_interest"] == INTEREST
        hit = next(h for h in env.search(first["title"], limit=20)["hits"] if h["source_id"] == first["id"])
        assert hit["issuer_interest"] == INTEREST
    plain = EvidenceEnvironment(base(), "documents")
    assert all("issuer_interest" not in s for s in plain.manifest())
    assert "issuer_interest" not in plain.open(first["id"], first["version"])
    # the documents view carries the field to the proposer up front
    assert any(s.get("issuer_interest") == INTEREST
               for s in EvidenceEnvironment(public, "documents").initial_input("proposer")["source_manifest"])


def test_kernel_ignores_issuer_interest():
    public = base()
    marked = with_interest(public)
    graphs = [InquiryGraph.model_validate(starter_graph(case)) for case in (public, marked)]
    profile = Profile(id="p", authority="test")
    results = [evaluate(graph, profile, evidence_context=EvidenceEnvironment(case))
               for graph, case in zip(graphs, (public, marked))]
    assert results[0].model_dump() == results[1].model_dump()


def test_a_recorded_run_with_the_field_completes_and_replays(tmp_path):
    public = with_interest(base())
    service = InquiryService(lambda: RecordedWorker([reply(public)]), record_root=tmp_path)
    out = service.inquire(public, mode="supplied")
    assert out["execution_status"] == "complete"
    assert service.replay(out["inquiry_id"])["evaluation_reproduced"] is True
