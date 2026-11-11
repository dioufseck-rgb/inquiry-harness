"""Shared TONIGHT-3 caps; all calls retain usage and raw replies locally."""
import json
from pathlib import Path

from inquiry.experiment_budget import ExperimentBudget
from inquiry.llm import AnthropicLLM, OpenAILLM
from inquiry.replay_move import RecordingLLM


def budget():
    return ExperimentBudget(Path("runs/tonight-3/budget.json"), {"anthropic": 12, "openai": 8})


def make_llm(spec):
    from dotenv import load_dotenv
    load_dotenv(Path(".env"))
    pricing = json.loads(Path("experiments/pricing.json").read_text(encoding="utf-8"))["models"]
    provider, model = spec.split(":", 1)
    if spec not in pricing or "opus" in model.casefold() or provider not in ("anthropic", "openai"):
        raise ValueError("Only priced non-Opus providers are authorized")
    delegate = (AnthropicLLM(model, effort="medium") if provider == "anthropic"
                else OpenAILLM(model, reasoning_effort="medium"))
    delegate.client = delegate.client.with_options(max_retries=0)
    return RecordingLLM(delegate, pricing[spec], budget(), max_output_tokens=16000)
