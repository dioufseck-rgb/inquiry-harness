import sys
from types import SimpleNamespace

import pytest

from inquiry.v1.workers import LLMWorker


class MockClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.options = []
        self.requests = []
        self.responses = SimpleNamespace(create=self.create)
        self.messages = SimpleNamespace(create=self.create)

    def with_options(self, **options):
        self.options.append(options)
        return self

    def create(self, **params):
        self.requests.append(params)
        if self.error:
            raise self.error
        return self.response


def handle(provider, client, effort="medium"):
    def forbidden_legacy_complete(*args, **kwargs):
        raise AssertionError("Legacy complete and its hidden retry loop must never run")
    return SimpleNamespace(provider=provider, model="explicit-test-model", name="test", client=client,
                           effort=effort, usage=[], complete=forbidden_legacy_complete)


def openai_response(usage=True):
    return SimpleNamespace(id="response_1", _request_id="request_1", model="resolved-model-snapshot", output_text='{"ok": true}',
        usage=SimpleNamespace(input_tokens=100, output_tokens=30,
            input_tokens_details=SimpleNamespace(cached_tokens=70),
            output_tokens_details=SimpleNamespace(reasoning_tokens=10)) if usage else None)


def anthropic_response():
    return SimpleNamespace(id="message_1", _request_id="request_1", stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text='{"ok": true}')],
        usage=SimpleNamespace(input_tokens=5, cache_creation_input_tokens=10,
            cache_read_input_tokens=100, output_tokens=20,
            cache_creation=SimpleNamespace(ephemeral_5m_input_tokens=10, ephemeral_1h_input_tokens=0)))


def test_openai_single_request_preserves_cached_partition_without_double_counting():
    client = MockClient(openai_response())
    worker = LLMWorker(handle("openai", client))
    worker.set_timeout(2.75)
    assert worker.complete("Instructions", "Case", max_tokens=200) == '{"ok": true}'
    assert len(client.requests) == len(worker.usage) == 1
    assert client.options == [{"timeout": 2.75, "max_retries": 0}]
    assert client.requests[0]["reasoning"] == {"effort": "medium"}
    assert client.requests[0]["max_output_tokens"] == 200
    usage = worker.usage[0]
    assert usage["api_attempts"] == 1
    assert usage["failed_api_attempts"] == 0
    assert usage["input_tokens"] == 100
    assert usage["cached_input_tokens"] == 70
    assert usage["output_tokens"] == 30
    assert usage["reasoning_output_tokens"] == 10
    assert usage["usage_known"] is True
    assert usage["cost_usd"] is None
    assert usage["requested_model"] == "explicit-test-model"
    assert usage["resolved_model"] == "resolved-model-snapshot"


def test_anthropic_input_counts_all_disjoint_cache_partitions():
    client = MockClient(anthropic_response())
    worker = LLMWorker(handle("anthropic", client))
    worker.complete("Instructions", "Case")
    usage = worker.usage[0]
    assert usage["input_tokens"] == 115
    assert usage["raw_input_tokens"] == 5
    assert usage["cache_creation_input_tokens"] == 10
    assert usage["cache_read_input_tokens"] == 100
    assert usage["cache_creation"]["ephemeral_5m_input_tokens"] == 10
    assert usage["output_tokens"] == 20
    assert client.requests[0]["output_config"] == {"effort": "medium"}


def test_unsupported_argument_surfaces_as_one_failed_attempt_without_negotiation():
    client = MockClient(error=ValueError("unsupported reasoning argument"))
    worker = LLMWorker(handle("openai", client))
    with pytest.raises(ValueError, match="unsupported"):
        worker.complete("Instructions", "Case")
    assert len(client.requests) == 1
    usage = worker.usage[0]
    assert usage["api_attempts"] == usage["failed_api_attempts"] == 1
    assert usage["request_status"] == "failed"
    assert usage["usage_known"] is False
    assert usage["input_tokens"] is None
    assert usage["output_tokens"] is None
    assert usage["cost_usd"] is None


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_optional_effort_omits_the_provider_argument(provider):
    client = MockClient(openai_response() if provider == "openai" else anthropic_response())
    worker = LLMWorker(handle(provider, client, effort=None))
    worker.complete("Instructions", "Case")
    assert "reasoning" not in client.requests[0]
    assert "output_config" not in client.requests[0]


def test_timeout_is_not_retried_and_records_unknown_billing():
    client = MockClient(error=TimeoutError("Request timed out"))
    worker = LLMWorker(handle("anthropic", client))
    worker.set_timeout(0.025)
    with pytest.raises(TimeoutError):
        worker.complete("Instructions", "Case")
    assert len(client.requests) == 1
    assert client.options[0] == {"timeout": 0.025, "max_retries": 0}
    assert worker.usage[0]["failed_api_attempts"] == 1
    assert worker.usage[0]["cost_usd"] is None


@pytest.mark.parametrize("provider,refusal", [("openai", False), ("anthropic", False), ("anthropic", True)])
def test_response_failure_keeps_sdk_usage_and_distinguishes_transport_success(provider, refusal):
    response = openai_response() if provider == "openai" else anthropic_response()
    if provider == "openai":
        response.output_text = ""
    elif refusal:
        response.stop_reason = "refusal"
    else:
        response.content = []
    client = MockClient(response)
    worker = LLMWorker(handle(provider, client))
    with pytest.raises(RuntimeError):
        worker.complete("Instructions", "Case")
    usage = worker.usage[0]
    assert usage["request_status"] == "completed"
    assert usage["failed_api_attempts"] == 0
    assert usage["invocation_succeeded"] is False
    assert usage["usage_known"] is True
    assert usage["input_tokens"] > 0


def test_missing_sdk_usage_is_unknown_even_when_text_was_returned():
    worker = LLMWorker(handle("openai", MockClient(openai_response(usage=False))))
    assert worker.complete("Instructions", "Case")
    assert worker.usage[0]["usage_known"] is False
    assert worker.usage[0]["input_tokens"] is None


def test_usage_retains_installed_sdk_version_without_client_secrets(monkeypatch):
    monkeypatch.setattr("inquiry.v1.workers.package_version", lambda package: "test-distribution-9.1")
    worker = LLMWorker(handle("openai", MockClient(openai_response())))
    worker.complete("Instructions", "Case")
    entry = worker.usage[0]
    assert entry["sdk_version"] == "test-distribution-9.1"
    assert entry["sdk_package"] == "openai"
    assert "client" not in entry and "api_key" not in entry


@pytest.mark.parametrize("provider,constructor", [("openai", "OpenAI"), ("anthropic", "Anthropic")])
def test_from_spec_imports_only_selected_sdk_and_disables_retries(monkeypatch, provider, constructor):
    constructor_options = []
    client = MockClient(openai_response() if provider == "openai" else anthropic_response())

    def construct(**options):
        constructor_options.append(options)
        return client

    monkeypatch.setitem(sys.modules, provider, SimpleNamespace(**{constructor: construct}))
    worker = LLMWorker.from_spec(provider + ":explicit-model", effort=None)
    assert constructor_options == [{"max_retries": 0, "timeout": 60.0}]
    assert worker.model == "explicit-model"
    assert worker.effort is None
    worker.complete("Instructions", "Case")
    assert len(client.requests) == 1


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True, None])
def test_invalid_timeout_cannot_silently_remove_the_limit(value):
    worker = LLMWorker(handle("openai", MockClient(openai_response())))
    with pytest.raises(ValueError):
        worker.set_timeout(value)


def test_uncontrolled_client_is_rejected_before_any_request():
    with pytest.raises(ValueError, match="with_options"):
        LLMWorker(handle("openai", SimpleNamespace()))
