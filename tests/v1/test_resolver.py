"""A4: who could resolve an information need. Recorded workers only."""
from copy import deepcopy
import json
from pathlib import Path
import zipfile

import pytest

from inquiry.v1.persistence import load_run
from inquiry.v1.runtime import (Budget, InformationNeed, RESOLVER_KINDS, _render_harness, _response_defects,
                                build_prompt, replay_run, run_inquiry)
from inquiry.v1.scoring import structural_audit
from inquiry.v1.workers import RecordedWorker

from test_stakes import reply


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "v1"
LIVE_RECORDS = Path(__file__).resolve().parents[2] / "experiments" / "v1" / "live_20261114" / "inquiry_v1_live_records_20261114.zip"


def request(name="equipment_temperature"):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def need(**overrides):
    base = {"condition_id": "K_applicability", "question": "Examine applicability",
            "what_would_resolve": "The procedure's scope statement.", "resolver_kind": "source",
            "resolver_hint": "the release procedure document, scope section"}
    return {**base, **overrides}


def with_need(public, **overrides):
    value = reply(public, open_condition="applicability")
    value["response"]["information_needs"] = [need(**overrides)]
    return value


def test_resolver_vocabulary_and_defaults_keep_stored_shapes_loading():
    assert RESOLVER_KINDS == ("source", "person", "counterparty", "caller", "unspecified")
    legacy = InformationNeed(condition_id="c", question="q", what_would_resolve="w")
    assert legacy.resolver_kind == "unspecified" and legacy.resolver_hint == ""
    with pytest.raises(ValueError):
        InformationNeed(condition_id="c", question="q", what_would_resolve="w", resolver_kind="oracle")


def test_a_need_with_a_resolver_completes_and_is_rendered():
    public = request()
    result = run_inquiry(public, RecordedWorker([with_need(public)]), mode="supplied")
    assert result["status"] == "complete"
    rendered = result["response"]["information_needs"][0]
    assert rendered["resolver_kind"] == "source" and rendered["resolver_hint"].startswith("the release procedure")
    assert "resolver: source" in result["response"]["text"]
    assert "the release procedure document" in result["response"]["text"]


@pytest.mark.parametrize("overrides", [{"resolver_kind": "unspecified"}, {"resolver_hint": ""}, {"resolver_hint": "   "}])
def test_a_harness_need_without_a_resolver_gets_one_repair_then_fails_closed(overrides):
    public = request()
    worker = RecordedWorker([with_need(public, **overrides), with_need(public, **overrides)])
    result = run_inquiry(public, worker, mode="supplied", budget=Budget(max_consecutive_errors=1))
    repairs = [e for e in result["events"] if e["kind"] == "response_repair_requested"]
    assert len(repairs) == 1
    assert any(d.startswith("information_need_resolver_missing:") for d in repairs[0]["data"]["defects"])
    assert result["stop_reason"] == "execution_failure" and result["response"]["inquiry_completed"] is False
    assert result["response"]["resolution_state"] == "execution_failed"


def test_the_repair_message_names_the_resolver_contract():
    public = request()
    worker = RecordedWorker([with_need(public, resolver_kind="unspecified"), with_need(public)])
    result = run_inquiry(public, worker, mode="supplied")
    assert result["status"] == "complete"
    repair_prompt = [e["data"]["user"] for e in result["events"] if e["kind"] == "worker_input"][1]
    assert "resolver_kind" in repair_prompt and "resolver_hint" in repair_prompt


def test_non_harness_arms_do_not_require_a_resolver():
    draft_need = InformationNeed(condition_id="c", question="q", what_would_resolve="w")
    from inquiry.v1.runtime import ResponseDraft
    draft = ResponseDraft(target_claim_id="c1", inquiry_completed=True, information_needs=[draft_need])
    assert _response_defects(draft) == []
    assert any(d.startswith("information_need_resolver_missing") for d in _response_defects(draft, None, require_resolver=True))


def test_prompt_and_audit_know_the_resolver_fields():
    assert "resolver_kind" in build_prompt("harness") and "resolver_hint" in build_prompt("harness")
    public = request()
    result = run_inquiry(public, RecordedWorker([with_need(public)]), mode="supplied")
    audit = structural_audit(result, public)
    assert "information_needs_are_records" not in audit["failed_checks"]
    bad = deepcopy(result)
    bad["response"]["information_needs"][0]["resolver_kind"] = "oracle"
    assert "information_needs_are_records" in structural_audit(bad, public)["failed_checks"]


A5_RECORD = Path(__file__).resolve().parents[2] / "experiments" / "v1" / "a5_record_question_004"


def test_stored_a5_record_still_loads_and_replays_natively():
    """A record frozen from the 1.0.0a5 implementation: no stakes, no resolver, no derived fields."""
    record = load_run(A5_RECORD)
    assert record["manifest"]["runtime_version"] == "1.0.0a5"
    assert "resolution_state" not in record["response"] and "meets_declared_standing" not in record["response"]
    for item in record["response"].get("information_needs", []):
        assert InformationNeed.model_validate(item).resolver_kind == "unspecified"
    replay = replay_run(record)
    assert replay["ledger_valid"] is True and replay["evaluation_reproduced"] is True
    assert replay["replay_mode"] == "native"


def test_stored_a1_live_records_still_load_and_replay_through_their_adapter(tmp_path):
    if not LIVE_RECORDS.exists():
        pytest.skip("stored live records are not present")
    from inquiry.v1.adapters.hardship import to_inquiry_request
    checked = 0
    with zipfile.ZipFile(LIVE_RECORDS) as archive:
        members = [m for m in archive.namelist() if m.endswith("result.json")]
        for member in members[:4]:
            folder = member.rsplit("/", 1)[0]
            for name in (member, folder + "/ledger.jsonl"):
                target = tmp_path / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
            record = load_run(tmp_path / folder)
            for item in record["response"].get("information_needs", []):
                InformationNeed.model_validate(item)
            replay = replay_run(record, request_adapter=to_inquiry_request)
            assert replay["ledger_valid"] is True and replay["replay_mode"] == "adapted_request"
            checked += 1
    assert checked > 0
