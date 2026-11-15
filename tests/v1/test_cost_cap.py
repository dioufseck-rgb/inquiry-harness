"""A3: a dollar cap on an inquiry, enforced from a host price table. No live calls."""
from copy import deepcopy
import json
from math import nan
from pathlib import Path
from types import SimpleNamespace

import pytest

from inquiry.v1 import cli
from inquiry.v1.runtime import Budget, record_cost, run_inquiry, validate_prices
from inquiry.v1.service import InquiryService
from inquiry.v1.workers import RecordedWorker

from test_stakes import reply, stakes


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "v1"
PRICES = {"openai:priced-model": {"input": 2.0, "cached_input": 0.5, "output": 10.0}}


def request(name="equipment_temperature"):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


class TokenWorker:
    """Reports tokens like an SDK worker but no cost, as LLMWorker does today."""
    provider = "openai"
    model = name = "priced-model"
    is_test_instrument = False

    def __init__(self, replies, input_tokens=1000, cached=200, output_tokens=100):
        self.replies = list(replies)
        self.calls = []
        self.usage = []
        self.tokens = (input_tokens, cached, output_tokens)

    def complete(self, system, user, max_tokens=4096):
        self.calls.append(user)
        reply_value = self.replies.pop(0)
        inp, cached, out = self.tokens
        self.usage.append({"provider": self.provider, "model": self.model, "input_tokens": inp,
                           "cached_input_tokens": cached, "output_tokens": out, "usage_known": True, "cost_usd": None})
        return json.dumps(reply_value)


# -- budget and price validation ------------------------------------------------------

@pytest.mark.parametrize("value", [-0.01, nan, float("inf"), True, "1"])
def test_cost_cap_must_be_a_finite_nonnegative_number_or_none(value):
    with pytest.raises(ValueError):
        Budget(max_cost_usd=value)
    assert Budget().max_cost_usd is None and Budget(max_cost_usd=0.0).max_cost_usd == 0.0


@pytest.mark.parametrize("prices", [
    {"openai:m": {"input": 1.0, "output": 2.0}},                       # missing cached_input
    {"openai:m": {"input": -1.0, "cached_input": 0.0, "output": 2.0}},  # negative
    {"m": {"input": 1.0, "cached_input": 0.0, "output": 2.0}},          # not provider:model
    {"openai:m": {"input": 1.0, "cached_input": 0.0, "output": 2.0, "tier": "x"}},
])
def test_price_table_is_validated(prices):
    with pytest.raises(ValueError):
        validate_prices(prices)
    assert validate_prices(PRICES) == PRICES


# -- cost from tokens -----------------------------------------------------------------

def test_cost_is_computed_from_recorded_tokens_when_the_worker_reports_none():
    public = request()
    worker = TokenWorker([reply(public)], input_tokens=1000, cached=200, output_tokens=100)
    result = run_inquiry(public, worker, mode="supplied", prices=PRICES)
    expected = ((1000 - 200) * 2.0 + 200 * 0.5 + 100 * 10.0) / 1e6
    assert result["usage"]["cost_usd"] == pytest.approx(expected)
    assert result["usage"]["cost_complete"] is True
    record = worker.usage[0]
    assert record["cost_usd"] == pytest.approx(expected) and record["price_entry"] == "openai:priced-model"
    assert record["cost_source"] == "computed_from_recorded_tokens"
    usage_event = next(e["data"] for e in result["events"] if e["kind"] == "worker_usage")
    assert usage_event["records"][0]["price_entry"] == "openai:priced-model"


def test_record_cost_uses_anthropic_cache_read_partition():
    record = {"provider": "anthropic", "model": "a", "input_tokens": 1000, "cache_read_input_tokens": 400,
              "output_tokens": 10, "usage_known": True, "cost_usd": None}
    prices = {"anthropic:a": {"input": 1.0, "cached_input": 0.1, "output": 5.0}}
    assert record_cost(record, prices) == pytest.approx((600 * 1.0 + 400 * 0.1 + 10 * 5.0) / 1e6)
    assert record_cost({"provider": "x", "model": "y", "input_tokens": 1, "output_tokens": 1, "cost_usd": None}, prices) is None
    assert record_cost({"provider": "x", "model": "y", "cost_usd": 0.25}, prices) == 0.25


def test_without_a_cap_cost_semantics_are_unchanged():
    public = request()
    worker = TokenWorker([reply(public)])
    result = run_inquiry(public, worker, mode="supplied")  # no price table
    assert result["usage"]["cost_usd"] is None and result["usage"]["cost_complete"] is False
    assert result["usage"]["known_cost_usd"] == 0.0 and result["usage"]["limit_reached"] is None
    assert result["status"] == "complete"


# -- the cap ---------------------------------------------------------------------------

def test_cap_stops_the_run_before_the_call_that_would_exceed_it():
    public = request()
    worker = TokenWorker([reply(public)])
    # worst case for one call: the input reservation priced at 2 $/M plus 4096 output tokens at 10 $/M
    result = run_inquiry(public, worker, mode="supplied", prices=PRICES, budget=Budget(max_cost_usd=0.00001))
    assert result["stop_reason"] == "resource_limit" and result["status"] == "partial"
    assert worker.calls == [] and result["usage"]["model_calls"] == 0
    assert result["usage"]["limit_reached"] == "cost"
    assert any(e["kind"] == "limit_reached" and e["data"]["limit"] == "cost" for e in result["events"])
    assert result["response"]["resolution_state"] == "budget_limited"


def test_cap_that_covers_the_run_lets_it_complete_and_records_actual_cost():
    public = request()
    worker = TokenWorker([reply(public)])
    result = run_inquiry(public, worker, mode="supplied", prices=PRICES, budget=Budget(max_cost_usd=5.0))
    assert result["status"] == "complete" and result["usage"]["limit_reached"] is None
    assert 0 < result["usage"]["cost_usd"] < 5.0 and result["manifest"]["budget"]["max_cost_usd"] == 5.0


def test_cap_without_a_price_for_a_live_worker_is_rejected_before_any_call():
    public = request()
    worker = TokenWorker([reply(public)])
    with pytest.raises(ValueError, match="price"):
        run_inquiry(public, worker, mode="supplied", prices={}, budget=Budget(max_cost_usd=1.0))
    assert worker.calls == []


def test_recorded_and_demo_workers_cost_zero_under_a_cap():
    public = request()
    worker = RecordedWorker([reply(public)])
    result = run_inquiry(public, worker, mode="supplied", prices={}, budget=Budget(max_cost_usd=0.0))
    assert result["status"] == "complete" and result["usage"]["cost_usd"] == 0.0


@pytest.mark.parametrize("budget,limit", [(Budget(max_model_calls=0), "calls"), (Budget(max_total_tokens=1), "tokens")])
def test_the_limit_that_ended_a_run_is_recorded(budget, limit):
    public = request()
    result = run_inquiry(public, RecordedWorker([]), mode="supplied", budget=budget)
    assert result["stop_reason"] == "resource_limit" and result["usage"]["limit_reached"] == limit


def test_the_time_limit_is_recorded(monkeypatch):
    from inquiry.v1 import runtime
    ticks = iter([0.0, 5.0, 10.0, 15.0, 20.0, 25.0])  # the clock is driven, not awaited
    monkeypatch.setattr(runtime.time, "monotonic", lambda: next(ticks))
    public = request()
    result = run_inquiry(public, RecordedWorker([]), mode="supplied", budget=Budget(timeout_seconds=2.0))
    assert result["stop_reason"] == "resource_limit" and result["usage"]["limit_reached"] == "time"


# -- service and hosts ---------------------------------------------------------------------

def test_service_rejects_a_capped_request_whose_worker_has_no_price_before_construction():
    public = request()
    called = []
    service = InquiryService(lambda: called.append(True), max_budget=Budget(max_cost_usd=1.0),
                             prices={}, worker_identities=["openai:unpriced"])
    with pytest.raises(ValueError, match="price"):
        service.inquire(public)
    assert called == []
    anonymous = InquiryService(lambda: called.append(True), max_budget=Budget(max_cost_usd=1.0), prices=PRICES)
    with pytest.raises(ValueError, match="identities"):
        anonymous.inquire(public)
    assert called == []


def test_service_enforces_the_cap_and_reports_prices_in_capabilities():
    public = request()
    service = InquiryService(lambda: RecordedWorker([reply(public)]), max_budget=Budget(max_cost_usd=2.0),
                             prices=PRICES, worker_identities=["recorded:recorded-test-worker"])
    capabilities = service.capabilities()
    assert capabilities["per_inquiry_ceiling"]["max_cost_usd"] == 2.0
    assert capabilities["price_entries"] == ["openai:priced-model"]
    assert capabilities["budget_tiers"]["medium"]["max_cost_usd"] == 2.0  # never below low, which has no focused cap
    out = service.inquire(public, mode="supplied", include_record=True)
    assert out["record"]["manifest"]["budget"]["max_cost_usd"] == 2.0 and out["usage"]["cost_usd"] == 0.0
    with pytest.raises(ValueError, match="host ceiling"):
        service.inquire(public, budget={"max_cost_usd": 3.0})
    with pytest.raises(ValueError, match="host ceiling"):
        service.inquire(public, budget={"max_cost_usd": None})  # a caller cannot lift the host cap


def test_cli_run_accepts_prices_and_cost_cap(monkeypatch, tmp_path):
    public = request()
    public["question"]["stakes"] = stakes()
    source = tmp_path / "request.json"
    source.write_text(json.dumps(public))
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps(PRICES))
    captured = {}

    def run(public_case, worker, **settings):
        captured.update(settings)
        return {"status": "complete", "stop_reason": "settled_for_purpose", "response": {"text": "mocked"}}

    monkeypatch.setattr(cli.LLMWorker, "from_spec", staticmethod(lambda *a, **k: SimpleNamespace(name="recorded")))
    monkeypatch.setattr(cli, "run_inquiry", run)
    monkeypatch.setattr(cli, "save_run", lambda result, out: Path(out))
    monkeypatch.setattr(cli, "score_run", lambda *a, **k: {"smoke": {"status": "not_configured"}})
    assert cli.main(["run", "--request", str(source), "--model", "openai:priced-model", "--out", str(tmp_path),
                     "--prices", str(prices), "--max-cost-usd", "0.5"]) == 0
    assert captured["budget"].max_cost_usd == 0.5 and captured["prices"] == PRICES


def test_mcp_host_builds_a_service_with_prices_and_identities(tmp_path, monkeypatch):
    from inquiry.v1 import mcp_server
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({**PRICES, "openai:critic": {"input": 1.0, "cached_input": 0.1, "output": 2.0}}))
    monkeypatch.setattr(mcp_server.LLMWorker, "from_spec", staticmethod(lambda *a, **k: RecordedWorker([])))
    service = mcp_server.build_service(mcp_server.parse_args([
        "--model", "openai:priced-model", "--critic-model", "openai:critic",
        "--prices", str(prices), "--max-cost-usd", "1.5", "--record-root", str(tmp_path)]))
    capabilities = service.capabilities()
    assert capabilities["per_inquiry_ceiling"]["max_cost_usd"] == 1.5
    assert capabilities["worker_identities"] == ["openai:priced-model", "openai:critic"]
    with pytest.raises(ValueError, match="price"):
        mcp_server.build_service(mcp_server.parse_args([
            "--model", "openai:unpriced", "--prices", str(prices), "--max-cost-usd", "1.5"]))
