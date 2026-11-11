"""Budgeted, local-packet full-cycle experiment. No live retrieval is configured."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from inquiry.argument.evaluate import load_bearing
from inquiry import moves
from inquiry.bench import load_questions, score_shape
from inquiry.experiment_budget import ExperimentBudget
from inquiry.live import Harness
from inquiry.llm import AnthropicLLM, OpenAILLM
from inquiry.metrics import metrics, one_line
from inquiry.replay_move import RecordingLLM, fingerprint
from inquiry.state import Inquiry
from inquiry.store import InquiryStore
from inquiry.tools.replay import replay_tools


def require_gate(gate, question):
    if question.get("split") == "held_out":
        raise ValueError("held-out questions are not authorized")
    if not gate.get("full_run_allowed") or not all(gate.get(k) for k in ("e1_pass", "e2_pass", "n1_review_recorded", "n2_committed", "n3_committed")):
        raise ValueError("full-cycle preconditions are not recorded")
    if not gate.get("human_review_completed") and gate.get("review_kind") != "agent_provisional_user_authorized":
        raise ValueError("review authority is missing")


def run(args):
    question = next(q for q in load_questions(Path("bench/questions.yaml")) if q["id"] == args.question_id)
    gate_path = Path("experiments/E6/gate.json")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    require_gate(gate, question)
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite full-cycle experiment: {args.out}")
    from dotenv import load_dotenv
    load_dotenv(Path(".env"))
    # Tonight's explicit dollar cap controls requests; use the requested round
    # limit rather than an inherited token cap from an earlier campaign.
    os.environ["INQUIRY_MAX_TOKENS_RUN"] = "0"
    pricing = json.loads(Path("experiments/pricing.json").read_text(encoding="utf-8"))["models"]
    budget = ExperimentBudget(Path("runs/tonight-2/budget.json"), {"anthropic": 36, "openai": 10}, {"anthropic": 20})
    def llm(spec):
        provider, model = spec.split(":", 1)
        if spec not in pricing or provider not in ("anthropic", "openai"):
            raise ValueError("unpriced or unsupported provider")
        if "opus" in model.casefold():
            raise ValueError("Opus is not authorized in tonight's runs")
        delegate = AnthropicLLM(model, effort="medium") if provider == "anthropic" else OpenAILLM(model, reasoning_effort="medium")
        delegate.client = delegate.client.with_options(max_retries=0)
        return RecordingLLM(delegate, pricing[spec], budget, max_output_tokens=16000)
    proposer, critic = llm(args.proposer), llm(args.critic)
    search, fetcher = replay_tools(args.packet)
    if not fetcher.pages:
        raise ValueError("fixed packet contains no local source texts")
    args.out.mkdir(parents=True)
    packet = [{"url": url, "title": title, "characters": len(text), "text_sha256": fingerprint(text)}
              for url, (title, text) in fetcher.pages.items()]
    (args.out / "packet.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
    store = InquiryStore(args.out, "run")
    inq = Inquiry(id=args.out.name, question=question["question"])
    inq.notes.append(f"fixed local packet: {args.packet}; no live retrieval; {len(packet)} available sources")
    harness = Harness(inq, store, proposer, critic, search, fetcher, max_sources=len(packet),
                      queries_per_round=6, frame_samples=1, review_frame=False, interactive=False, literature_search=None)
    start = time.monotonic()
    error = None
    try:
        harness.run(rounds=2)
        score = score_shape(inq, inq.evaluation, question["expected"], critic)
        harness._record("shape_judge", score)
    except Exception as exc:
        error = {"type": type(exc).__name__}
        if getattr(exc, "status_code", None):
            error["status"] = exc.status_code
        elif isinstance(exc, (ValueError, RuntimeError)):
            error["message"] = str(exc)[:240]
        score = {}
        print(f"full-cycle error: {error}", flush=True)
    # Persist even a structural/budget failure, including calls made before a
    # failed move could be recorded by the ordinary harness ledger.
    ev = moves.evaluate_move(inq)
    harness._record("experiment_finalize", {"error": error, "question_id": args.question_id,
                                              "fixed_packet_sources": len(packet)})
    harness.write_report()
    m = metrics(inq, ev, question.get("gold"), question.get("expected"))
    m.update(score)
    m["error"] = error
    m["seconds"] = round(time.monotonic() - start, 2)
    m["packet_sources"] = len(packet)
    m["packet_path"] = str(args.packet)
    m["packet_sha256"] = fingerprint(packet)
    m["config"] = {"rounds": 2, "frame_samples": 1, "review_frame": False, "live_retrieval": False,
                   "proposer": args.proposer, "critic": args.critic, "effort": "medium"}
    m["implementation_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    m["runner_sha256"] = fingerprint(Path(__file__).read_text(encoding="utf-8"))
    m["cost_by_provider"] = {provider: sum(c["cost_usd"] or 0 for handle in (proposer, critic)
                                         if handle.provider == provider for c in handle.calls) for provider in ("anthropic", "openai")}
    m["cost_usd"] = sum(m["cost_by_provider"].values())
    m["api_calls"] = sum(len(handle.calls) for handle in (proposer, critic))
    m["references_valid"] = not inq.graph.validate_refs()
    m["ledger_valid"] = store.verify_ledger()
    m["search_queries"] = len(search.calls)
    m["fetched_urls"] = fetcher.calls
    m["accepted_main_claims"] = [{"id": c.id, "text": c.text, "target": c.target, "scope": c.answers_issue} for c in inq.main_claims()
                                 if c.answers_issue and ev.status(c.id) == "in"]
    m["accepted_components"] = [{"id": c.id, "text": c.text, "issue_id": c.issue_id} for c in inq.graph.live_claims()
                                if ev.status(c.id) == "in" and (not c.answers_issue or c.issue_id != inq.graph.main_issue_id)]
    m["main_load_bearing"] = {c.id: [x.model_dump() for x in load_bearing(inq.graph, c.id)] for c in inq.main_claims() if c.answers_issue}
    m["single_origin_flag_missing"] = []
    from inquiry.argument.evaluate import argument_origins
    flagged = {f.node_id for f in ev.flags if f.code == "single_origin"}
    for c in inq.graph.live_claims():
        if ev.status(c.id) != "in":
            continue
        origins = set().union(*(argument_origins(inq.graph, inq.graph.arg(aid)) for aid in ev.claims[c.id].pro_ids))
        if len(origins) <= 1 and c.id not in flagged:
            m["single_origin_flag_missing"].append(c.id)
    m["pass"] = (not error and m["references_valid"] and m["ledger_valid"] and not m["claims_supported_unargued"]
                 and not m["undecided_empty"] and not m["absence_assertions"] and not m["single_origin_flag_missing"]
                 and m["reopened_then_discharged"] >= 1)
    (args.out / "metrics.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    for role, handle in (("proposer", proposer), ("critic", critic)):
        (args.out / f"{role}-responses.json").write_text(json.dumps(handle.calls, indent=2), encoding="utf-8")
    print(one_line(m), flush=True)
    print(json.dumps({"out": str(args.out), "pass": m["pass"], "error": error, "cost_usd": m["cost_usd"]}), flush=True)
    return m


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--question-id", required=True)
    p.add_argument("--packet", type=Path, required=True)
    p.add_argument("--proposer", required=True)
    p.add_argument("--critic", required=True)
    p.add_argument("--out", type=Path, required=True)
    run(p.parse_args())
