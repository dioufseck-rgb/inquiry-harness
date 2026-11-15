"""A5: premise triage. Recorded workers only; no source text reaches the classifier."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from inquiry.v1.contracts import InquiryValidationError
from inquiry.v1.runtime import Budget, IMPLEMENTATION_HASHES
from inquiry.v1.service import InquiryService
from inquiry.v1.triage import ROUTING, TRIAGE_CEILING, TriageResult, route_for, run_triage
from inquiry.v1.workers import RecordedWorker

from test_cost_cap import PRICES, TokenWorker


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "v1"


def request(name="equipment_temperature"):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def classification(premise_class, reason="One located record at the stated scope answers it."):
    return {"premise_class": premise_class, "reason": reason}


@pytest.mark.parametrize("premise_class,route", list(ROUTING.items()))
def test_each_class_maps_to_its_fixed_route(premise_class, route):
    public = request()
    worker = RecordedWorker([classification(premise_class)])
    result = run_triage(public, worker)
    triage = result["triage"]
    assert triage["premise_class"] == premise_class and triage["route"] == route
    assert triage["classification_authorship"] == "model" and triage["performer"].startswith("model:recorded:")
    assert triage["attempts"] == 1 and result["usage"]["model_calls"] == 1


def test_route_is_set_in_code_and_a_model_cannot_choose_it():
    public = request()
    forged = {**classification("state"), "route": "ask_counterparty"}
    worker = RecordedWorker([forged, classification("state")])
    result = run_triage(public, worker)
    assert result["triage"]["route"] == "lookup" and result["triage"]["attempts"] == 2
    assert result["usage"]["failed_calls"] == 1
    assert route_for("unclassified") == "inquire" and route_for("unclassified", "ask_person") == "ask_person"
    with pytest.raises(ValueError):
        route_for("unclassified", "state")
    with pytest.raises(ValueError):
        TriageResult(premise_class="state", route="lookup", reason="r", performer="p",
                     classification_authorship="model", attempts=1, verdict="go")


def test_two_invalid_outputs_give_unclassified_and_the_host_default():
    public = request()
    worker = RecordedWorker(["not json", {"premise_class": "oracle", "reason": "x"}])
    result = run_triage(public, worker)
    triage = result["triage"]
    assert triage["premise_class"] == "unclassified" and triage["route"] == "inquire"
    assert triage["classification_authorship"] == "controller_fallback" and triage["performer"] == "controller"
    assert triage["attempts"] == 2 and result["usage"]["failed_calls"] == 2
    configured = run_triage(public, RecordedWorker(["x", "y"]), unclassified_route="ask_person")
    assert configured["triage"]["route"] == "ask_person" and configured["triage"]["premise_class"] == "unclassified"


def test_triage_sees_the_manifest_but_no_source_text_and_adds_no_exposure():
    public = request()
    worker = RecordedWorker([classification("judgment")])
    result = run_triage(public, worker, action_context="Release pump A4 to service.")
    user = worker.calls[0]["user"]
    source = public["corpus"]["documents"][0]
    assert source["title"] in user and source["issuer_id"] in user and "Release pump A4" in user
    assert source["reading_blocks"][0]["text"] not in user
    assert result["exposures"] == []
    assert not any(e["kind"] == "tool_result" for e in result["events"])


def test_usage_and_cost_are_counted_against_a_budget():
    public = request()
    worker = TokenWorker([classification("state")], input_tokens=900, cached=0, output_tokens=40)
    result = run_triage(public, worker, prices=PRICES)
    assert result["usage"]["input_tokens"] == 900 and result["usage"]["output_tokens"] == 40
    assert result["usage"]["cost_usd"] == pytest.approx((900 * 2.0 + 40 * 10.0) / 1e6)
    assert result["usage"]["cost_complete"] is True and result["usage"]["price_entries"] == ["openai:priced-model"]
    capped = run_triage(public, TokenWorker([classification("state")]), prices=PRICES,
                        budget=Budget(**{**TRIAGE_CEILING.__dict__, "max_cost_usd": 0.0000001}))
    assert capped["triage"]["premise_class"] == "unclassified" and capped["usage"]["limit_reached"] == "cost"
    assert capped["usage"]["model_calls"] == 0


def test_triage_ceiling_is_one_call_plus_one_repair():
    assert TRIAGE_CEILING.max_model_calls == 2 and TRIAGE_CEILING.max_total_tokens == 4096
    assert TRIAGE_CEILING.max_output_tokens == 512 and TRIAGE_CEILING.max_tool_calls == 0
    assert "triage" in IMPLEMENTATION_HASHES


def test_service_triage_operation_validates_before_construction_and_records_authorship(tmp_path):
    public = request()
    called = []
    bad = deepcopy(public)
    bad["question"]["stakes"] = {"level": "high"}
    with pytest.raises(InquiryValidationError):
        InquiryService(lambda: called.append(True)).triage(bad)
    assert called == []
    service = InquiryService(lambda: RecordedWorker([classification("tacit", "The waiver was verbal; no record exists.")]),
                             record_root=tmp_path)
    out = service.triage(public, action_context="Release pump A4 to service.")
    assert out["operation"] == "triage" and out["triage"]["route"] == "ask_person"
    assert out["triage"]["classification_authorship"] == "model"
    assert "triage" in service.capabilities()["operations"]
    assert out["usage"]["model_calls"] == 1 and out["exposures"] == []
    assert {"approved", "all_clear", "proceed", "go", "cleared", "decision"}.isdisjoint(out)
    assert {"approved", "all_clear", "proceed", "go", "cleared", "decision"}.isdisjoint(out["triage"])
