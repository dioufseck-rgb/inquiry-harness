import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from inquiry import llm


class BadRequest(Exception):
    def __init__(self, param):
        self.body = {"param": param, "message": f"Unsupported parameter: {param}"}


@pytest.fixture
def client(monkeypatch):
    response = SimpleNamespace(output_text='{"ok": true}',
                               usage=SimpleNamespace(input_tokens=12, output_tokens=7))
    client = SimpleNamespace(responses=SimpleNamespace(create=Mock(return_value=response)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda: client, BadRequestError=BadRequest))
    return client


@pytest.mark.parametrize("role", ["proposer", "critic"])
@pytest.mark.parametrize("configured,provider,model", [
    ("claude-test", "anthropic", "claude-test"),
    ("anthropic:claude-test", "anthropic", "claude-test"),
    ("openai:reasoner-test", "openai", "reasoner-test"),
])
def test_provider_parsing(monkeypatch, configured, provider, model, role):
    monkeypatch.setenv(f"INQUIRY_{role.upper()}_MODEL", configured)
    monkeypatch.delenv(f"INQUIRY_{role.upper()}_EFFORT", raising=False)
    anthropic, openai = Mock(), Mock()
    monkeypatch.setattr(llm, "AnthropicLLM", anthropic)
    monkeypatch.setattr(llm, "OpenAILLM", openai)
    llm.llm_from_env(role)
    if provider == "openai":
        openai.assert_called_once_with(model=model, reasoning_effort="medium")
    else:
        anthropic.assert_called_once_with(model=model, effort="high" if role == "critic" else "medium")


def test_openai_complete_and_usage(client):
    model = llm.OpenAILLM("reasoner-test", temperature=0.4)
    assert model.complete("system", "user", max_tokens=123) == '{"ok": true}'
    params = client.responses.create.call_args.kwargs
    assert params["reasoning"] == {"effort": "medium"}
    assert params["text"] == {"format": {"type": "json_object"}}
    assert params["max_output_tokens"] == 123
    assert "JSON" in params["input"]
    assert "temperature" not in params
    assert model.usage == [{"provider": "openai", "model": "reasoner-test", "input_tokens": 12, "output_tokens": 7}]


def test_openai_negotiates_nonreasoning_and_temperature_once(client):
    response = client.responses.create.return_value
    client.responses.create.side_effect = [BadRequest("reasoning.effort"), BadRequest("temperature"), response, response]
    model = llm.OpenAILLM("text-test", temperature=0.2)
    model.complete("JSON", "user")
    model.complete("JSON", "user")
    calls = client.responses.create.call_args_list
    assert "reasoning" in calls[0].kwargs and "temperature" not in calls[0].kwargs
    assert "reasoning" not in calls[1].kwargs and calls[1].kwargs["temperature"] == 0.2
    assert all("temperature" not in c.kwargs and "reasoning" not in c.kwargs for c in calls[2:])
    assert len(model.usage) == 2


def test_openai_does_not_retry_unrelated_bad_request(client):
    client.responses.create.side_effect = BadRequest("input")
    with pytest.raises(BadRequest):
        llm.OpenAILLM("text-test").complete("JSON", "user")
    assert client.responses.create.call_count == 1


def test_anthropic_usage(monkeypatch):
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text='{"ok": true}')],
                               stop_reason="end_turn", usage=SimpleNamespace(input_tokens=5, output_tokens=3))
    client = SimpleNamespace(messages=SimpleNamespace(create=Mock(return_value=response)))
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda: client))
    model = llm.AnthropicLLM("claude-test")
    assert model.complete("JSON", "user") == '{"ok": true}'
    assert model.usage[0] == {"provider": "anthropic", "model": "claude-test", "input_tokens": 5, "output_tokens": 3}
