"""Run the user's six bare questions through the unchanged live Harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from inquiry import moves
from inquiry.argument.evaluate import argument_origins
from inquiry.closure import whole_question_answer
from inquiry.experiment_budget import ExperimentBudget
from inquiry.live import Harness, _load_env
from inquiry.llm import AnthropicLLM, OpenAILLM
from inquiry.metrics import metrics
from inquiry.replay_move import RecordingLLM, fingerprint
from inquiry.state import Inquiry
from inquiry.store import InquiryStore
from inquiry.tools.fetch import HttpFetcher
from inquiry.tools.search import EuropePMCSearch, SerperSearch

ROOT = Path("experiments/agent-questions-20261112")
QUESTIONS = ROOT / "questions.json"
LEDGER = Path("runs/agent-questions-20261112/budget.json")
LIMITS = {"anthropic": 12, "openai": 18}
MODELS = {"proposer": "openai:gpt-6.1-sol", "critic": "anthropic:claude-sonnet-5-5"}


def questions():
    rows = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    if len(rows) != 6 or any(set(row) != {"id", "question"} for row in rows):
        raise ValueError("Each input must contain only its id and bare question")
    return rows


def prepare():
    data = {"client_date": "2026-11-12", "timezone": "America/New_York", "rounds": 2,
            "models": MODELS, "effort": "medium", "live_retrieval": True,
            "tools": ["SerperSearch", "HttpFetcher", "EuropePMCSearch"],
            "cli_defaults": {"max_sources": 8, "queries": 6, "hits": 5, "read_parts": 36, "frame_samples": 1},
            "budget_target_usd_per_question": [1, 3], "budget_is_flexible": True,
            "operational_guards_usd": LIMITS, "budget_ledger": str(LEDGER),
            "questions_sha256": fingerprint(questions()),
            "surrounding_context_sent": False, "expected_results_sent": False, "shape_judge": False,
            "opus_used": False, "implementation_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}
    (ROOT / "manifest.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps({"prepared": str(ROOT), "questions": len(questions()), "api_calls": 0}))


def run(question_id):
    row = next(row for row in questions() if row["id"] == question_id)
    out = ROOT / question_id
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite {out}")
    _load_env()
    os.environ["INQUIRY_MAX_TOKENS_RUN"] = "0"
    rates = json.loads(Path("experiments/pricing.json").read_text(encoding="utf-8"))["models"]
    budget = ExperimentBudget(LEDGER, LIMITS)
    def model(role):
        spec = MODELS[role]
        provider, name = spec.split(":", 1)
        delegate = OpenAILLM(name, reasoning_effort="medium") if provider == "openai" else AnthropicLLM(name, effort="medium")
        delegate.client = delegate.client.with_options(max_retries=0)
        return RecordingLLM(delegate, rates[spec], budget, max_output_tokens=16000)
    proposer, critic = model("proposer"), model("critic")
    search, fetcher, literature = SerperSearch(), HttpFetcher(), EuropePMCSearch()
    out.mkdir(parents=True)
    store = InquiryStore(out, "run")
    # No scenario, expected label, action, benchmark gold, or external answer
    # enters Inquiry. Standard Harness skills create all later views.
    inq = Inquiry(id=question_id, question=row["question"])
    harness = Harness(inq, store, proposer, critic, search, fetcher, literature_search=literature,
                      max_sources=8, queries_per_round=6, hits_per_query=5, read_parts=36,
                      frame_samples=1, review_frame=False, interactive=False)
    started = time.monotonic()
    error = None
    try:
        harness.run(rounds=2)
    except Exception as exc:
        error = {"type": type(exc).__name__}
        if getattr(exc, "status_code", None):
            error["status"] = exc.status_code
        elif isinstance(exc, (ValueError, RuntimeError)):
            error["message"] = str(exc)[:300]
        print(json.dumps({"question_id": question_id, "error": error}), flush=True)
    ev = moves.evaluate_move(inq)
    if error is None and not inq.graph.evidence:
        error = {"type": "NoEvidence"}
    harness._record("experiment_finalize", {"question_id": question_id, "error": error,
        "bare_question_only": True, "live_retrieval": True, "expected_results_supplied": False})
    harness.write_report()
    data = metrics(inq, ev)
    answer = whole_question_answer(inq.graph, ev)
    data.update({"question": row["question"], "error": error, "phase": inq.phase,
        "seconds": round(time.monotonic() - started, 2),
        "rounds_completed": len({s.round for s in inq.stop_assessments if s.round > 0}),
        "config": {"models": MODELS, "rounds": 2, "effort": "medium", "live_retrieval": True,
                   "max_sources": 8, "queries": 6, "hits": 5, "read_parts": 36,
                   "frame_samples": 1, "surrounding_context_sent": False, "shape_judge": False},
        "implementation_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "runner_sha256": fingerprint(Path(__file__).read_text(encoding="utf-8")),
        "question_sha256": fingerprint(row["question"]),
        "api_calls": len(proposer.calls) + len(critic.calls),
        "cost_by_provider": {provider: sum(c["cost_usd"] or 0 for handle in (proposer, critic)
            if handle.provider == provider for c in handle.calls) for provider in LIMITS},
        "references_valid": not inq.graph.validate_refs(), "ledger_valid": store.verify_ledger(),
        "final_state_anchor_valid": store.events()[-1]["state_hash"] == hashlib.sha256(inq.model_dump_json().encode()).hexdigest(),
        "question_exact": inq.question == row["question"],
        "accepted_main_claims": [{"id": c.id, "text": c.text, "scope": c.scope.model_dump()} for c in inq.main_claims()
            if ev.status(c.id) == "in" and (c.answers_issue or c == answer)],
        "accepted_components": [{"id": c.id, "text": c.text, "issue_id": c.issue_id, "scope": c.scope.model_dump()}
            for c in inq.graph.live_claims() if c != answer and ev.status(c.id) == "in"
            and (not c.answers_issue or c.issue_id != inq.graph.main_issue_id)],
        "issue_results": [{"id": issue.id, "text": issue.text, "accepted": ev.issues.get(issue.id, []),
            "claims": [{"id": c.id, "text": c.text, "label": ev.claims[c.id].label,
                        "answers_issue": c.answers_issue, "pro_strength": ev.claims[c.id].pro_strength}
                       for c in inq.graph.claims_for_issue(issue.id)]} for issue in inq.graph.issues],
        "sources_detail": [{"id": s.id, "url": s.url, "title": s.title, "date": s.date, "kind": s.kind,
             "fetched_at": s.fetched_at, "read_fully": s.read_fully, "derived_from": s.derived_from,
             "origin": inq.graph.origin_key(s)} for s in inq.graph.sources]})
    data["cost_usd"] = sum(data["cost_by_provider"].values())
    flagged = {f.node_id for f in ev.flags if f.code == "single_origin"}
    data["single_origin_flag_missing"] = []
    for claim in inq.graph.live_claims():
        if ev.status(claim.id) == "in":
            origins = set().union(*(argument_origins(inq.graph, inq.graph.arg(aid), labels=ev.labels)
                                  for aid in ev.claims[claim.id].pro_ids))
            if len(origins) <= 1 and claim.id not in flagged:
                data["single_origin_flag_missing"].append(claim.id)
    (out / "metrics.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (out / "inquiry.json").write_text(inq.model_dump_json(indent=2), encoding="utf-8")
    for role, handle in (("proposer", proposer), ("critic", critic)):
        (out / f"{role}-responses.json").write_text(json.dumps(handle.calls, indent=2), encoding="utf-8")
    print(json.dumps({"question_id": question_id, "phase": inq.phase, "rounds_completed": data["rounds_completed"],
                      "whole_question_answered": data["whole_question_answered"],
                      "cost_usd": data["cost_usd"], "error": error}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", choices=[f"q{i}" for i in range(1, 7)])
    args = parser.parse_args()
    run(args.id) if args.id else prepare()
