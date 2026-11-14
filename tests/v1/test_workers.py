import copy
import json
import sys
from types import SimpleNamespace

import pytest

from inquiry.v1.protocol import OutputProtocolError, parse_single_json_object
from inquiry.v1.workers import LLMWorker, ProviderOutputError


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
    return SimpleNamespace(id="response_1", _request_id="request_1", model="resolved-model-snapshot",
        status="completed", incomplete_details=None, error=None,
        output=[SimpleNamespace(type="message", id="message_1", role="assistant", status="completed",
            phase="final_answer", content=[SimpleNamespace(type="output_text", text='{"ok": true}')])],
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


@pytest.mark.parametrize("provider,refusal", [
    ("openai", False), ("openai", True), ("anthropic", False), ("anthropic", True)])
def test_response_failure_keeps_sdk_usage_and_distinguishes_transport_success(provider, refusal):
    response = openai_response() if provider == "openai" else anthropic_response()
    if provider == "openai":
        response.output[0].content = ([SimpleNamespace(type="refusal", refusal="Declined")]
                                      if refusal else [])
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


def dynamic_graph_schema():
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "operation": {"type": "string", "enum": ["submit", "finish"]},
            "graph": {"type": "object", "additionalProperties": {
                "type": "object", "additionalProperties": True,
                "properties": {"scope": {"type": "object", "additionalProperties": True}},
            }},
        },
        "required": ["operation"],
    }


def test_openai_role_schemas_preserve_dynamic_graph_maps_and_change_between_calls():
    client = MockClient(openai_response())
    worker = LLMWorker(handle("openai", client))
    schema = dynamic_graph_schema()
    expected = copy.deepcopy(schema)
    worker.set_output_schema("inquiry_proposer", schema)
    schema["properties"]["graph"]["additionalProperties"] = False
    worker.complete("Proposer instructions", "Proposer input")
    assert client.requests[0]["text"]["format"] == {
        "type": "json_schema", "name": "inquiry_proposer", "schema": expected, "strict": False}
    assert client.requests[0]["instructions"] == "Proposer instructions"
    assert client.requests[0]["input"] == "Proposer input"
    critic = {"type": "object", "additionalProperties": False,
              "properties": {"observations": {"type": "array", "items": {"type": "string"}},
                             "attacks": {"type": "object", "additionalProperties": True}},
              "required": ["observations", "attacks"]}
    worker.set_output_schema("inquiry_critic", critic, strict=False)
    worker.complete("Critic instructions", "Critic input")
    assert client.requests[1]["text"]["format"]["schema"] == critic
    assert client.requests[1]["text"]["format"]["name"] == "inquiry_critic"
    assert [row["output_schema"]["name"] for row in worker.usage] == ["inquiry_proposer", "inquiry_critic"]
    assert worker.usage[0]["output_schema"]["sha256"] != worker.usage[1]["output_schema"]["sha256"]
    assert len(client.requests) == 2


@pytest.mark.parametrize("effort", [None, "medium"])
def test_anthropic_schema_and_effort_share_output_config_without_schema_rewriting(effort):
    client = MockClient(anthropic_response())
    worker = LLMWorker(handle("anthropic", client, effort=effort))
    schema = dynamic_graph_schema()
    worker.set_output_schema("inquiry_proposer", schema)
    worker.complete("Instructions", "Case")
    expected = {"format": {"type": "json_schema", "schema": schema}}
    if effort is not None:
        expected["effort"] = effort
    assert client.requests[0]["output_config"] == expected
    assert worker.usage[0]["output_schema"]["strict"] is None


def test_explicit_openai_strict_flag_does_not_rewrite_caller_schema():
    client = MockClient(openai_response())
    worker = LLMWorker(handle("openai", client))
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    worker.set_output_schema("empty", schema, strict=True)
    worker.complete("Instructions", "Case")
    assert client.requests[0]["text"]["format"]["strict"] is True
    assert client.requests[0]["text"]["format"]["schema"] == schema


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_unsupported_schema_is_one_visible_failed_request_without_fallback(provider):
    client = MockClient(error=ValueError("unsupported schema"))
    worker = LLMWorker(handle(provider, client))
    worker.set_output_schema("inquiry_proposer", dynamic_graph_schema())
    with pytest.raises(ValueError, match="unsupported schema"):
        worker.complete("Instructions", "Case")
    assert len(client.requests) == len(worker.usage) == 1
    assert worker.usage[0]["api_attempts"] == worker.usage[0]["failed_api_attempts"] == 1
    assert worker.usage[0]["output_schema"]["name"] == "inquiry_proposer"


@pytest.mark.parametrize("name,schema,strict", [
    ("invalid name", {"type": "object"}, False),
    ("x" * 65, {"type": "object"}, False),
    ("schema", {"type": "array"}, False),
    ("schema", {"type": "object", "default": float("nan")}, False),
    ("schema", {"type": "object"}, "false"),
])
def test_invalid_schema_configuration_fails_before_a_request(name, schema, strict):
    client = MockClient(openai_response())
    worker = LLMWorker(handle("openai", client))
    with pytest.raises(ValueError):
        worker.set_output_schema(name, schema, strict=strict)
    assert client.requests == []


def test_openai_reads_indexed_items_and_never_uses_flattened_convenience_text():
    class NoFlattenedText(SimpleNamespace):
        @property
        def output_text(self):
            raise AssertionError("Flattening SDK output items discards protocol boundaries")

    response = NoFlattenedText(**vars(openai_response()))
    response.output.insert(0, SimpleNamespace(
        type="reasoning", id="reasoning_1", status="completed",
        summary=[{"type": "summary_text", "text": "PRIVATE_REASONING_SENTINEL"}],
        encrypted_content="PRIVATE_ENCRYPTED_SENTINEL"))
    worker = LLMWorker(handle("openai", MockClient(response)))
    assert worker.complete("Instructions", "Case") == '{"ok": true}'
    usage = worker.usage[0]
    assert usage["provider_status"] == "completed"
    assert usage["provider_output_boundaries_known"] is True
    assert usage["provider_output_text_count"] == 1
    assert usage["provider_output_items"][0] == {
        "index": 0, "type": "reasoning", "id": "reasoning_1", "status": "completed",
        "role": None, "phase": None, "payload_omitted": True}
    assert usage["provider_output_items"][1]["content"] == [
        {"index": 0, "type": "output_text", "text": '{"ok": true}'}]
    assert "PRIVATE_" not in json.dumps(usage)


def test_anthropic_preserves_text_block_indexes_without_thinking_content():
    response = anthropic_response()
    response.content.insert(0, SimpleNamespace(
        type="thinking", thinking="PRIVATE_THINKING_SENTINEL", signature="PRIVATE_SIGNATURE_SENTINEL"))
    response.content.insert(1, SimpleNamespace(type="redacted_thinking", data="PRIVATE_REDACTED_SENTINEL"))
    worker = LLMWorker(handle("anthropic", MockClient(response)))
    assert worker.complete("Instructions", "Case") == '{"ok": true}'
    usage = worker.usage[0]
    assert usage["provider_stop_reason"] == "end_turn"
    assert usage["provider_output_items"][2] == {"index": 2, "type": "text", "text": '{"ok": true}'}
    assert all(item["payload_omitted"] for item in usage["provider_output_items"][:2])
    assert "PRIVATE_" not in json.dumps(usage)


@pytest.mark.parametrize("separate_messages", [False, True])
def test_openai_multiple_answer_blocks_are_rejected_and_all_boundaries_persist(separate_messages):
    response = openai_response()
    second_text = '{"ok": false}'
    if separate_messages:
        second = copy.deepcopy(response.output[0])
        second.id = "message_2"
        second.content[0].text = second_text
        response.output.append(second)
    else:
        response.output[0].content.append(SimpleNamespace(type="output_text", text=second_text))
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "multiple_text_blocks"
    usage = worker.usage[0]
    assert usage["provider_output_text_count"] == 2
    assert [block["text"] for item in usage["provider_output_items"] for block in item["content"]] == [
        '{"ok": true}', second_text]
    assert usage["request_status"] == "completed"
    assert usage["failed_api_attempts"] == 0
    assert usage["usage_known"] is True
    assert usage["invocation_succeeded"] is False


# Exact ordinary answer text from the stopped live run's question_004-baseline,
# worker_usage sequence 3. The response contained two completed assistant
# final_answer messages with different IDs and this same complete JSON text.
LIVE_DUPLICATE_OPEN = (
    '{"operation":"open","arguments":{"source_id":"doc_001","version":"1.0","locator":"section_1"},'
    '"graph":null,"response":null,"rationale":"Need policy text for intake-stage next permitted response and evidence rules."}'
)


def duplicate_final_response(text=LIVE_DUPLICATE_OPEN, count=2):
    response = openai_response()
    message = response.output[0]
    response.output = [SimpleNamespace(type="reasoning", id="reasoning_1",
                                      summary=[{"text": "PRIVATE_REASONING_SENTINEL"}])]
    for index in range(count):
        duplicate = copy.deepcopy(message)
        duplicate.id = f"message_{index + 1}"
        duplicate.content[0].text = text
        response.output.append(duplicate)
    return response


@pytest.mark.parametrize("count", [2, 3])
def test_exact_duplicate_completed_final_messages_normalize_once_with_raw_items_preserved(count):
    client = MockClient(duplicate_final_response(count=count))
    worker = LLMWorker(handle("openai", client))
    reply = worker.complete("Instructions", "Case")
    assert reply == LIVE_DUPLICATE_OPEN
    assert parse_single_json_object(reply)["operation"] == "open"
    assert len(client.requests) == 1
    usage = worker.usage[0]
    assert usage["adapter_version"] == "v1-single-request-4"
    assert usage["provider_output_text_count"] == count
    assert usage["provider_output_normalization"] == {
        "kind": "exact_duplicate_final_answer_messages",
        "retained": {"item_index": 1, "content_index": 0},
        "duplicates": [{"item_index": index, "content_index": 0} for index in range(2, count + 1)],
        "duplicate_count": count - 1,
    }
    messages = usage["provider_output_items"][1:]
    assert [item["id"] for item in messages] == [f"message_{index + 1}" for index in range(count)]
    assert all(item["content"] == [{"index": 0, "type": "output_text", "text": LIVE_DUPLICATE_OPEN}]
               for item in messages)
    assert all(item["status"] == "completed" and item["role"] == "assistant"
               and item["phase"] == "final_answer" for item in messages)
    assert usage["invocation_succeeded"] is True
    assert "PRIVATE_" not in json.dumps(usage)


def test_normalized_duplicate_open_executes_one_controller_operation_only():
    from inquiry.v1.packets import load_packet
    from inquiry.v1.runtime import Budget, run_inquiry

    client = MockClient(duplicate_final_response())
    worker = LLMWorker(handle("openai", client))
    result = run_inquiry(load_packet().public("question_004"), worker, mode="documents",
                         budget=Budget(max_model_calls=1))
    assert len(client.requests) == 1
    assert result["usage"]["model_calls"] == 1
    assert result["usage"]["tool_calls"] == 1
    assert result["usage"]["failed_calls"] == 0
    operations = [event["data"] for event in result["events"] if event["kind"] == "operation"]
    assert len(operations) == 1
    assert operations[0]["operation"] == "open"
    tool_results = [event for event in result["events"] if event["kind"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["data"]["arguments"] == {
        "source_id": "doc_001", "version": "1.0", "locator": "section_1"}


def test_distinct_commentary_is_recorded_nonoperative_before_exact_final_duplicate_normalization():
    # Exact shapes/text from question_004-mutation_002 worker_usage sequence 3.
    final_text = (
        '{"operation":"open","arguments":{"source_id":"doc_001","version":"1.0","locator":"section_1"},'
        '"rationale":"Read policy section governing intake evidence rules and next response."}'
    )
    commentary_text = (
        '{"operation":"open","arguments":{"source_id":"doc_001","version":"1.0","locator":"section_1"},'
        '"graph":null,"response":null,"rationale":"Read policy section governing intake evidence rules and next response."}'
    )
    response = duplicate_final_response(final_text)
    commentary = copy.deepcopy(response.output[1])
    commentary.id = "commentary_message"
    commentary.phase = "commentary"
    commentary.content[0].text = commentary_text
    response.output.insert(1, commentary)
    worker = LLMWorker(handle("openai", MockClient(response)))
    assert worker.complete("Instructions", "Case") == final_text
    usage = worker.usage[0]
    assert usage["provider_output_admission"] == {
        "policy": "openai_final_answer_v1", "channel": "final_answer",
        "candidate_final_item_indexes": [2, 3], "candidate_item_indexes": [2, 3],
        "excluded_commentary": [{"item_index": 1, "content_indexes": [0],
                                 "reason": "phase_commentary_nonoperative"}],
        "selected": {"item_index": 2, "content_index": 0},
    }
    assert usage["provider_output_normalization"] == {
        "kind": "exact_duplicate_final_answer_messages",
        "retained": {"item_index": 2, "content_index": 0},
        "duplicates": [{"item_index": 3, "content_index": 0}], "duplicate_count": 1,
    }
    assert usage["provider_output_text_count"] == 3
    messages = usage["provider_output_items"][1:]
    assert [item["phase"] for item in messages] == ["commentary", "final_answer", "final_answer"]
    assert [item["content"][0]["text"] for item in messages] == [commentary_text, final_text, final_text]


@pytest.mark.parametrize("commentary_first", [True, False])
def test_commentary_operation_never_executes_and_only_final_operation_reaches_controller(commentary_first):
    from inquiry.v1.packets import load_packet
    from inquiry.v1.runtime import Budget, run_inquiry

    response = duplicate_final_response(count=1)
    commentary = copy.deepcopy(response.output[1])
    commentary.id = "commentary_message"
    commentary.phase = "commentary"
    commentary.content[0].text = '{"operation":"open","arguments":{"source_id":"doc_003","version":"1.0"}}'
    response.output.insert(1 if commentary_first else 2, commentary)
    client = MockClient(response)
    worker = LLMWorker(handle("openai", client))
    result = run_inquiry(load_packet().public("question_004"), worker, mode="documents",
                         budget=Budget(max_model_calls=1))

    assert len(client.requests) == result["usage"]["model_calls"] == 1
    assert result["usage"]["tool_calls"] == 1
    assert result["usage"]["failed_calls"] == 0
    operations = [event["data"] for event in result["events"] if event["kind"] == "operation"]
    assert len(operations) == 1
    assert operations[0]["arguments"] == {"source_id": "doc_001", "version": "1.0", "locator": "section_1"}
    tool_results = [event["data"] for event in result["events"] if event["kind"] == "tool_result"]
    assert [item["result"]["source_id"] for item in tool_results] == ["doc_001"]
    assert not any(segment["source_id"] == "doc_003" for exposure in result["exposures"]
                   for segment in exposure["segments"])
    output = next(event["data"]["reply"] for event in result["events"] if event["kind"] == "worker_output")
    assert output == LIVE_DUPLICATE_OPEN
    record = worker.usage[0]
    admission = record["provider_output_admission"]
    commentary_index, final_index = (1, 2) if commentary_first else (2, 1)
    assert admission["excluded_commentary"] == [{
        "item_index": commentary_index, "content_indexes": [0], "reason": "phase_commentary_nonoperative"}]
    assert admission["candidate_final_item_indexes"] == [final_index]
    assert admission["selected"] == {"item_index": final_index, "content_index": 0}
    assert record["provider_output_items"][commentary_index]["content"][0]["text"] == commentary.content[0].text


def test_only_commentary_is_not_an_answer_even_when_it_contains_a_valid_operation():
    response = openai_response()
    response.output[0].phase = "commentary"
    response.output[0].content[0].text = LIVE_DUPLICATE_OPEN
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "missing_final_answer"
    record = worker.usage[0]
    assert record["provider_output_items"][0]["content"][0]["text"] == LIVE_DUPLICATE_OPEN
    assert record["provider_output_admission"]["candidate_final_item_indexes"] == []
    assert record["provider_output_admission"]["excluded_commentary"] == [{
        "item_index": 0, "content_indexes": [0], "reason": "phase_commentary_nonoperative"}]
    assert record["provider_output_admission"]["selected"] is None


def test_single_legacy_unphased_message_has_an_explicit_admission_channel():
    response = openai_response()
    response.output[0].phase = None
    worker = LLMWorker(handle("openai", MockClient(response)))
    assert worker.complete("Instructions", "Case") == '{"ok": true}'
    assert worker.usage[0]["provider_output_admission"] == {
        "policy": "openai_final_answer_v1", "channel": "legacy_single_unphased",
        "candidate_final_item_indexes": [], "candidate_item_indexes": [0],
        "excluded_commentary": [], "selected": {"item_index": 0, "content_index": 0},
    }


@pytest.mark.parametrize("phases", [(None, None), ("commentary", None), ("commentary", "unknown")])
def test_multiple_unphased_or_unknown_phase_messages_cannot_use_legacy_admission(phases):
    response = duplicate_final_response()
    for message, phase in zip(response.output[1:], phases):
        message.phase = phase
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "invalid_output_phase"
    assert worker.usage[0]["provider_output_admission"]["channel"] == "final_answer"
    assert worker.usage[0]["provider_output_admission"]["selected"] is None


@pytest.mark.parametrize("phase", ["unknown", False])
def test_single_unknown_phase_is_not_reinterpreted_as_missing_phase(phase):
    response = openai_response()
    response.output[0].phase = phase
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "invalid_output_phase"
    assert worker.usage[0]["provider_output_admission"]["selected"] is None


def test_commentary_text_blocks_are_retained_without_json_parsing_or_fragment_assembly():
    response = openai_response()
    commentary = copy.deepcopy(response.output[0])
    commentary.id = "commentary_message"
    commentary.phase = "commentary"
    commentary.content = [SimpleNamespace(type="output_text", text="I am checking the record."),
                          SimpleNamespace(type="output_text", text='{"unfinished commentary":')]
    response.output.insert(0, commentary)
    worker = LLMWorker(handle("openai", MockClient(response)))
    assert worker.complete("Instructions", "Case") == '{"ok": true}'
    record = worker.usage[0]
    assert record["provider_output_text_count"] == 3
    assert record["provider_output_admission"]["excluded_commentary"] == [{
        "item_index": 0, "content_indexes": [0, 1], "reason": "phase_commentary_nonoperative"}]
    assert [block["text"] for block in record["provider_output_items"][0]["content"]] == [
        "I am checking the record.", '{"unfinished commentary":']


def test_malformed_final_cannot_fall_back_to_a_well_formed_commentary_object():
    response = openai_response()
    commentary = copy.deepcopy(response.output[0])
    commentary.id = "commentary_message"
    commentary.phase = "commentary"
    response.output[0].content[0].text = '{"operation":'
    response.output.insert(0, commentary)
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(OutputProtocolError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "invalid_json"
    record = worker.usage[0]
    assert record["provider_output_admission"]["candidate_final_item_indexes"] == [1]
    assert record["provider_output_admission"]["selected"] is None
    assert record["output_error_code"] == "invalid_json"
    assert record["provider_output_items"][0]["content"][0]["text"] == '{"ok": true}'
    assert record["provider_output_items"][1]["content"][0]["text"] == '{"operation":'


@pytest.mark.parametrize("defect,expected_code", [
    ("incomplete", "provider_incomplete"), ("refusal", "provider_refusal"),
])
def test_commentary_exclusion_cannot_hide_incomplete_or_refused_provider_output(defect, expected_code):
    response = openai_response()
    commentary = copy.deepcopy(response.output[0])
    commentary.id = "commentary_message"
    commentary.phase = "commentary"
    if defect == "incomplete":
        commentary.status = "incomplete"
    else:
        commentary.content = [SimpleNamespace(type="refusal", refusal="Declined")]
    response.output.insert(0, commentary)
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == expected_code
    record = worker.usage[0]
    assert record["provider_output_admission"]["candidate_final_item_indexes"] == [1]
    assert record["provider_output_admission"]["selected"] is None
    assert record["usage_known"] is True


@pytest.mark.parametrize("field,value,expected_code", [
    ("phase", None, "invalid_output_phase"), ("phase", "unknown", "invalid_output_phase"),
    ("role", "user", "invalid_output_message"), ("role", None, "invalid_output_message"),
    ("status", None, "invalid_output_message"), ("id", None, "invalid_output_message"),
])
def test_exact_text_alone_cannot_override_message_phase_role_status_or_identity(field, value, expected_code):
    response = duplicate_final_response()
    setattr(response.output[1], field, value)
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == expected_code
    assert worker.usage[0]["provider_output_normalization"] is None


@pytest.mark.parametrize("text", [
    '{"operation":', '{"operation":"open"}{"operation":"finish"}',
    '{"operation":"open","operation":"finish"}', '[{"operation":"open"}]', " ",
])
def test_identical_fragments_multiple_objects_or_ambiguous_json_cannot_be_normalized(text):
    worker = LLMWorker(handle("openai", MockClient(duplicate_final_response(text))))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "multiple_text_blocks"
    assert worker.usage[0]["provider_output_normalization"] is None


def test_json_equivalent_but_textually_distinct_messages_are_not_duplicates():
    response = duplicate_final_response()
    response.output[2].content[0].text = json.dumps(json.loads(LIVE_DUPLICATE_OPEN), indent=2)
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "multiple_text_blocks"
    assert worker.usage[0]["provider_output_normalization"] is None


def test_identical_blocks_within_one_message_are_not_duplicate_completed_messages():
    response = openai_response()
    response.output[0].content.append(copy.deepcopy(response.output[0].content[0]))
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "multiple_text_blocks"
    assert worker.usage[0]["provider_output_normalization"] is None


@pytest.mark.parametrize("defect,expected_code", [
    ("incomplete_response", "provider_incomplete"), ("incomplete_message", "provider_incomplete"),
    ("unknown_response_status", "provider_incomplete"), ("refusal", "provider_refusal"),
    ("extra_content", "invalid_output_content"), ("extra_item", "unexpected_output_items"),
])
def test_duplicate_text_never_hides_provider_failure_refusal_or_additional_content(defect, expected_code):
    response = duplicate_final_response()
    if defect == "incomplete_response":
        response.status = "incomplete"
        response.incomplete_details = SimpleNamespace(reason="max_output_tokens")
    elif defect == "incomplete_message":
        response.output[2].status = "incomplete"
    elif defect == "unknown_response_status":
        response.status = None
    elif defect == "refusal":
        response.output[1].content.append(SimpleNamespace(type="refusal", refusal="Declined"))
    elif defect == "extra_content":
        response.output[1].content.append(SimpleNamespace(type="unknown_content", data="PRIVATE_UNKNOWN_SENTINEL"))
    else:
        response.output.append(SimpleNamespace(type="function_call", arguments="PRIVATE_ARGUMENTS_SENTINEL"))
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == expected_code
    usage = worker.usage[0]
    assert usage["provider_output_normalization"] is None
    assert usage["provider_output_text_count"] == 2
    assert usage["usage_known"] is True
    assert usage["failed_api_attempts"] == 0
    assert usage["invocation_succeeded"] is False
    assert "PRIVATE_" not in json.dumps(usage)


@pytest.mark.parametrize("second_text", ['{"second": true}', '{"ok": true}'])
def test_anthropic_multiple_text_blocks_are_never_concatenated(second_text):
    response = anthropic_response()
    response.content.append(SimpleNamespace(type="text", text=second_text))
    worker = LLMWorker(handle("anthropic", MockClient(response)))
    with pytest.raises(ProviderOutputError, match="multiple answer text blocks"):
        worker.complete("Instructions", "Case")
    assert worker.usage[0]["provider_output_items"] == [
        {"index": 0, "type": "text", "text": '{"ok": true}'},
        {"index": 1, "type": "text", "text": second_text}]


@pytest.mark.parametrize("status,reason", [
    ("incomplete", "max_output_tokens"), ("incomplete", "content_filter"),
    ("cancelled", None), ("in_progress", None), ("queued", None),
])
def test_noncompleted_openai_response_is_rejected_even_if_text_is_valid_json(status, reason):
    response = openai_response()
    response.status = status
    response.incomplete_details = SimpleNamespace(reason=reason) if reason else None
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "provider_incomplete"
    usage = worker.usage[0]
    assert usage["provider_status"] == status
    assert usage["provider_incomplete_details"] == ({"reason": reason} if reason else None)
    assert usage["provider_output_items"][0]["content"][0]["text"] == '{"ok": true}'
    assert usage["usage_known"] is True
    assert usage["failed_api_attempts"] == 0


def test_incomplete_message_is_rejected_even_when_openai_response_status_is_completed():
    response = openai_response()
    response.output[0].status = "incomplete"
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "provider_incomplete"
    assert worker.usage[0]["provider_output_items"][0]["status"] == "incomplete"


def test_openai_generation_failure_preserves_status_code_usage_and_safe_text_only():
    response = openai_response()
    response.status = "failed"
    response.error = SimpleNamespace(code="server_error", message="PRIVATE_PROVIDER_ERROR_SENTINEL")
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "provider_error"
    usage = worker.usage[0]
    assert usage["provider_status"] == "failed"
    assert usage["provider_error_code"] == "server_error"
    assert usage["request_status"] == "completed"
    assert usage["failed_api_attempts"] == 0
    assert usage["usage_known"] is True
    assert "PRIVATE_" not in json.dumps(usage)


@pytest.mark.parametrize("stop_reason", ["max_tokens", "pause_turn", "model_context_window_exceeded", "tool_use", "stop_sequence"])
def test_anthropic_stopped_response_is_rejected_even_if_text_is_valid_json(stop_reason):
    response = anthropic_response()
    response.stop_reason = stop_reason
    response.stop_sequence = "END" if stop_reason == "stop_sequence" else None
    worker = LLMWorker(handle("anthropic", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "provider_incomplete"
    usage = worker.usage[0]
    assert usage["provider_stop_reason"] == stop_reason
    assert usage["provider_stop_sequence"] == response.stop_sequence
    assert usage["usage_known"] is True


def test_missing_openai_output_items_cannot_fall_back_to_flattened_text():
    response = openai_response()
    del response.output
    response.output_text = '{"ok": true}'
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(ProviderOutputError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "missing_output_items"
    assert worker.usage[0]["provider_output_boundaries_known"] is False


def test_multiple_objects_inside_one_final_text_block_are_rejected_with_raw_text_intact():
    response = openai_response()
    raw = '{"operation":"open","arguments":{"source_id":"first"}}{"operation":"finish"}'
    response.output[0].content[0].text = raw
    worker = LLMWorker(handle("openai", MockClient(response)))
    with pytest.raises(OutputProtocolError) as exc:
        worker.complete("Instructions", "Case")
    assert exc.value.code == "trailing_data"
    assert worker.usage[0]["provider_output_items"][0]["content"][0]["text"] == raw
    assert worker.usage[0]["provider_output_admission"]["selected"] is None
    assert worker.usage[0]["invocation_succeeded"] is False
