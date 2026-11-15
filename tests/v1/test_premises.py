"""A6: the premise check. Recorded workers only; no go/no-go value anywhere."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from inquiry.v1.contracts import InquiryValidationError
from inquiry.v1.premises import can_fund, examination_order, premise_budget, remaining_budget, validate_premise_set
from inquiry.v1.runtime import Budget
from inquiry.v1.service import InquiryService, _BUSINESS_RESPONSE_FIELDS
from inquiry.v1.workers import RecordedWorker

from test_stakes import reply, stakes
from test_triage import classification


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "v1"
FORBIDDEN = {"approved", "all_clear", "proceed", "go", "cleared", "decision", "next_action", "authorization"}


def base():
    return json.loads((EXAMPLES / "equipment_temperature.json").read_text(encoding="utf-8"))


def premise(pid, level="high", examine=None, text="Does the supplied logger record a coolant temperature of 82 C for pump A4 at 14:00 on 4 April 2026?"):
    question = deepcopy(base()["question"])
    question["id"] = pid
    question["question"] = text
    question["stakes"] = stakes(level=level)
    if examine:
        question["examine"] = examine
    return question


def premise_set(premises, action_context="Return pump A4 to service after inspection."):
    public = base()
    return {"shared_context": public["shared_context"], "corpus": public["corpus"],
            "premises": premises, "action_context": action_context}


class Factory:
    """Hands out one recorded worker per factory call, in the order the service asks."""

    def __init__(self, workers):
        self.workers = list(workers)
        self.handed = []

    def __call__(self):
        worker = self.workers.pop(0)
        self.handed.append(worker)
        return worker


def single(pid):
    public = base()
    public["question"]["id"] = pid
    return public


# -- validation ------------------------------------------------------------------------------

def test_whole_set_is_validated_before_any_worker_is_constructed():
    called = []
    service = InquiryService(lambda: called.append(True))
    good = premise("p1")
    for bad_set, match in [
        (premise_set([good, deepcopy(good)]), "duplicate"),
        (premise_set([{**good, "examine": "never"}]), "examine"),
        (premise_set([{key: value for key, value in good.items() if key != "stakes"}]), "stakes"),
        ({**premise_set([good]), "mode": "fast"}, "unknown"),
        (premise_set([]), "nonempty"),
        (premise_set([premise(f"p{i}") for i in range(9)]), "at most 8"),
        ({**premise_set([good]), "action_context": ""}, "action_context"),
    ]:
        with pytest.raises(InquiryValidationError, match=match):
            service.examine_premises(bad_set)
    broken = premise("p2")
    broken["profile"]["kernel"]["min_origins"] = -1
    with pytest.raises(InquiryValidationError):
        service.examine_premises(premise_set([good, broken]))
    assert called == []
    validated = validate_premise_set(premise_set([good]), max_premises=8)
    assert validated["examine"] == ["auto"] and validated["questions"][0]["question"]["id"] == "p1"


# -- budgets -------------------------------------------------------------------------------------

def test_examination_order_is_by_stakes_then_request_order():
    questions = [{"question": {"stakes": {"level": lvl}}} for lvl in ("low", "high", "medium", "high")]
    assert examination_order(questions, [0, 1, 2, 3]) == [1, 3, 2, 0]


def test_premise_budget_is_the_smaller_of_tier_and_remainder():
    total = Budget(max_model_calls=10, max_tool_calls=10, max_total_tokens=50_000, timeout_seconds=100.0, max_cost_usd=1.0)
    rest = remaining_budget(total, {"model_calls": 7, "tool_calls": 2, "input_tokens": 20_000, "output_tokens": 5_000,
                                    "elapsed_seconds": 30.0, "cost_usd": 0.4})
    assert rest["max_model_calls"] == 3 and rest["max_total_tokens"] == 25_000 and rest["max_cost_usd"] == pytest.approx(0.6)
    tier = Budget(max_model_calls=8, max_tool_calls=1, max_total_tokens=30_000, timeout_seconds=60.0)
    chosen = premise_budget(tier, rest)
    assert chosen.max_model_calls == 3 and chosen.max_tool_calls == 1 and chosen.max_total_tokens == 25_000
    assert chosen.timeout_seconds == 60.0 and chosen.max_cost_usd == pytest.approx(0.6)
    low = Budget(max_model_calls=4, max_tool_calls=4, max_total_tokens=32_000, timeout_seconds=60.0)
    assert can_fund(rest, low) is False  # 3 calls left, low needs 4
    assert can_fund(remaining_budget(total, {}), low) is True
    assert can_fund(remaining_budget(total, {"elapsed_seconds": 50.0}), low) is False  # 50 s left, low needs 60


# -- the check -------------------------------------------------------------------------------------

def test_mixed_set_routes_and_examines_only_what_it_should(tmp_path):
    premises = [premise("reading", level="low"), premise("inspection", level="high"),
                premise("waiver", level="medium"), premise("delivery", level="low"),
                premise("forced-lookup", level="low", examine="always")]
    triages = [classification("state"), classification("judgment"), classification("tacit"),
               classification("intent"), classification("state")]
    # factory order: five triage workers, then the inquiry workers for the two examined premises
    factory = Factory([RecordedWorker([t]) for t in triages]
                      + [RecordedWorker([reply(single("inspection"))]), RecordedWorker([reply(single("forced-lookup"))])])
    service = InquiryService(factory, record_root=tmp_path)
    out = service.examine_premises(premise_set(premises), mode="supplied")
    by_id = {p["premise_id"]: p for p in out["premises"]}
    assert [p["premise_id"] for p in out["premises"]] == ["reading", "inspection", "waiver", "delivery", "forced-lookup"]
    assert by_id["reading"]["examined"] is False and by_id["reading"]["not_examined_reason"] == "routed"
    assert by_id["waiver"]["triage"]["route"] == "ask_person" and by_id["waiver"]["examined"] is False
    assert by_id["delivery"]["triage"]["route"] == "ask_counterparty"
    assert by_id["inspection"]["examined"] is True and by_id["inspection"]["finding_status"] == "established"
    assert by_id["inspection"]["meets_declared_standing"] is True and by_id["inspection"]["resolution_state"] == "settled"
    assert by_id["forced-lookup"]["examined"] is True and by_id["forced-lookup"]["triage"]["route"] == "lookup"
    assert by_id["inspection"]["record_ref"].startswith("inquiry://records/")
    assert set(by_id["inspection"]) >= {"inquiry_id", "execution_status", "stop_reason", "finding_status",
                                        "meets_declared_standing", "resolution_state", "information_needs", "record_ref"}
    assert out["unmet_premise_ids"] == [] and out["unexamined_premise_ids"] == ["reading", "waiver", "delivery"]
    assert out["usage"]["model_calls"] == 7
    assert out["premise_set_id"] and out["record_ref"].startswith("inquiry://premise-sets/")
    assert FORBIDDEN.isdisjoint(out) and all(FORBIDDEN.isdisjoint(p) for p in out["premises"])
    assert {"approved", "all_clear", "proceed", "go", "cleared"} <= _BUSINESS_RESPONSE_FIELDS
    # the examination order was high first: inspection before forced-lookup
    assert [w for w in factory.handed[5:]] == factory.workers[-2:] if factory.workers else True
    stored = service.read_premise_set(out["premise_set_id"])
    assert [p["premise_id"] for p in stored["premises"]] == [p["premise_id"] for p in out["premises"]]


def test_unmet_and_open_premises_are_reported_not_decided():
    unmet = premise("unmet", level="high")
    factory = Factory([RecordedWorker([classification("judgment")]),
                       RecordedWorker([reply(single("unmet"), open_condition="applicability")])])
    out = InquiryService(factory).examine_premises(premise_set([unmet]), mode="supplied")
    p = out["premises"][0]
    assert p["examined"] and p["meets_declared_standing"] is False and p["resolution_state"] == "open_needs"
    assert p["information_needs"][0]["resolver_kind"] == "source"
    assert out["unmet_premise_ids"] == ["unmet"]


def test_budget_exhaustion_leaves_later_premises_unexamined():
    premises = [premise("a", level="high"), premise("b", level="high"), premise("c", level="medium")]
    factory = Factory([RecordedWorker([classification("judgment")]) for _ in range(3)]
                      + [RecordedWorker([reply(single("a"))]), RecordedWorker([reply(single("b"))]), RecordedWorker([reply(single("c"))])])
    # the set allows the three triage calls plus exactly one inquiry worth of calls at the low tier
    service = InquiryService(factory, max_budget=Budget(max_model_calls=4),
                             max_set_budget=Budget(max_model_calls=3 + 4))
    out = service.examine_premises(premise_set(premises), mode="supplied")
    by_id = {p["premise_id"]: p for p in out["premises"]}
    assert by_id["a"]["examined"] is True
    assert by_id["b"]["examined"] is False and by_id["b"]["not_examined_reason"] == "budget"
    assert by_id["c"]["examined"] is False and by_id["c"]["not_examined_reason"] == "budget"
    assert out["unexamined_premise_ids"] == ["b", "c"] and len(factory.workers) == 2  # their workers were never constructed


def test_premises_never_share_an_environment_or_workers():
    premises = [premise("x", level="high"), premise("y", level="high")]
    workers = [RecordedWorker([classification("judgment")]), RecordedWorker([classification("judgment")]),
               RecordedWorker([reply(single("x"))]), RecordedWorker([reply(single("y"))])]
    factory = Factory(list(workers))
    out = InquiryService(factory, record_root=None).examine_premises(premise_set(premises), mode="supplied", include_record=True)
    assert len(set(map(id, factory.handed))) == 4
    records = [p["record"] for p in out["premises"]]
    assert records[0]["run_id"] != records[1]["run_id"]
    assert records[0]["manifest"]["public_case_hash"] != records[1]["manifest"]["public_case_hash"]


def test_maintenance_release_example_validates_with_one_premise_per_class():
    example = json.loads((EXAMPLES / "premise_set_maintenance_release.json").read_text(encoding="utf-8"))
    validated = validate_premise_set(example, max_premises=8)
    ids = [q["question"]["id"] for q in validated["questions"]]
    assert ids == ["premise:coolant-reading", "premise:inspection-satisfies-rts7",
                   "premise:pressure-test-waived", "premise:seal-delivery-by-15-april"]
    assert [q["question"]["stakes"]["level"] for q in validated["questions"]] == ["low", "high", "high", "medium"]
    assert validated["action_context"].startswith("Release pump A4")
    # the four premises are one per triage class once classified; the example carries no classification itself
    assert all("premise_class" not in p for p in example["premises"])


def test_caller_set_budget_is_capped_by_the_host_set_ceiling():
    called = []
    service = InquiryService(lambda: called.append(True), max_set_budget=Budget(max_model_calls=5))
    with pytest.raises(ValueError, match="ceiling"):
        service.examine_premises(premise_set([premise("p")]), budget={"max_model_calls": 6})
    assert called == []
    assert service.capabilities()["premise_check"]["max_premises"] == 8
