"""A2: budget tiers selected by declared stakes level. Recorded workers only."""
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from inquiry.v1.runtime import Budget
from inquiry.v1.service import InquiryService, _FOCUSED_LIMITS
from inquiry.v1.workers import RecordedWorker

from test_stakes import reply, stakes


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "v1"


def request(name="equipment_temperature"):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def test_default_tiers_follow_the_host_ceiling():
    ceiling = Budget(max_model_calls=20, max_tool_calls=9, max_total_tokens=300_000, max_output_tokens=8192,
                     timeout_seconds=100.0, max_consecutive_errors=3, max_critique_calls=1)
    tiers = InquiryService(lambda: None, max_budget=ceiling).capabilities()["budget_tiers"]
    assert set(tiers) == {"low", "medium", "high"}
    assert tiers["high"] == asdict(ceiling)
    assert tiers["low"] == {key: min(value, _FOCUSED_LIMITS[key]) for key, value in asdict(ceiling).items()}
    # medium: half the ceiling per field, rounded down, never below low
    assert tiers["medium"]["max_model_calls"] == 10 and tiers["medium"]["max_tool_calls"] == 4
    assert tiers["medium"]["max_total_tokens"] == 150_000
    assert tiers["medium"]["max_output_tokens"] == 4096        # half of 8192 equals low
    assert tiers["medium"]["timeout_seconds"] == 60.0          # half of 100 is below low's 60
    assert tiers["medium"]["max_consecutive_errors"] == 2      # floor(3/2)=1 is below low's 2
    assert tiers["medium"]["max_critique_calls"] == 1          # floor(1/2)=0 is below low's 1


def test_tier_above_the_host_ceiling_is_rejected_at_construction():
    with pytest.raises(ValueError, match="ceiling"):
        InquiryService(lambda: None, max_budget=Budget(max_model_calls=5),
                       tiers={"medium": Budget(max_model_calls=6)})
    with pytest.raises(ValueError, match="tier"):
        InquiryService(lambda: None, tiers={"urgent": Budget()})


def test_stakes_level_selects_the_tier_budget():
    public = request()
    public["question"]["stakes"] = stakes(level="medium")
    service = InquiryService(lambda: RecordedWorker([reply(public)]), max_budget=Budget(max_model_calls=8, max_tool_calls=10))
    out = service.inquire(public, mode="supplied", include_record=True)
    budget = out["record"]["manifest"]["budget"]
    assert budget["max_model_calls"] == 4 and budget["max_tool_calls"] == 5
    assert out["response"]["meets_declared_standing"] is True


def test_explicit_budget_wins_over_the_tier_and_is_still_capped():
    public = request()
    public["question"]["stakes"] = stakes(level="low")
    service = InquiryService(lambda: RecordedWorker([reply(public)]), max_budget=Budget(max_model_calls=8))
    out = service.inquire(public, budget={"max_model_calls": 7}, mode="supplied", include_record=True)
    assert out["record"]["manifest"]["budget"]["max_model_calls"] == 7
    called = []
    with pytest.raises(ValueError, match="host ceiling"):
        InquiryService(lambda: called.append(True), max_budget=Budget(max_model_calls=8)).inquire(
            public, budget={"max_model_calls": 9})
    assert called == []


def test_without_stakes_the_host_ceiling_applies_as_before():
    public = request()
    service = InquiryService(lambda: RecordedWorker([reply(public)]), max_budget=Budget(max_model_calls=8))
    out = service.inquire(public, mode="supplied", include_record=True)
    assert out["record"]["manifest"]["budget"]["max_model_calls"] == 8


def test_check_keeps_its_focused_ceiling_regardless_of_level():
    public = request()
    public["question"]["stakes"] = stakes(level="high")
    service = InquiryService(lambda: RecordedWorker([reply(public)]), max_budget=Budget(max_model_calls=8))
    out = service.check(public, include_record=True)
    assert out["record"]["manifest"]["budget"]["max_model_calls"] == _FOCUSED_LIMITS["max_model_calls"]


def test_host_can_override_tiers_within_the_ceiling():
    public = request()
    public["question"]["stakes"] = stakes(level="high")
    service = InquiryService(lambda: RecordedWorker([reply(public)]), max_budget=Budget(max_model_calls=8),
                             tiers={"high": {"max_model_calls": 6}})
    assert service.capabilities()["budget_tiers"]["high"]["max_model_calls"] == 6
    out = service.inquire(public, mode="supplied", include_record=True)
    assert out["record"]["manifest"]["budget"]["max_model_calls"] == 6
