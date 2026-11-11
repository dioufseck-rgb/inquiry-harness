"""Continue E7-energy's saved round-two Argue without replaying appraisal."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from inquiry import moves
from inquiry.argument.evaluate import argument_origins, load_bearing
from inquiry.bench import load_questions, score_shape
from inquiry.closure import whole_question_answer
from inquiry.live import Harness
from inquiry.metrics import metrics, one_line
from inquiry.replay_move import fingerprint
from inquiry.store import InquiryStore
from inquiry.tools.replay import replay_tools
from experiments.tonight3 import make_llm

ROOT = Path("experiments/E7-energy/sol")
LIMITS = {"anthropic": 12, "openai": 12}


def finish_saved_round(harness: Harness, remaining_issues: set[str]):
    """Finish the current round; never Frame, Plan, Gather or Compute again."""
    inq = harness.inq
    if inq.phase != "inquiring" or inq.round != 2:
        raise ValueError("Continuation requires the in-progress second round")
    result = moves.argue(inq, harness.proposer, issue_ids=remaining_issues)
    result["continued_issue_ids"] = sorted(remaining_issues)
    harness._record("argue", result)
    moves.evaluate_move(inq)
    harness._record("revise", moves.revise(inq, harness.proposer))
    harness._record("coverage_check", moves.coverage_check(inq, harness.proposer))
    moves.evaluate_move(inq)
    crit = moves.critique(inq, harness.critic)
    harness._record("critique", crit)
    inq.notes.extend(f"critic needs: {q}" for q in crit["needed_evidence"])
    moves.evaluate_move(inq)
    harness._record("respond", moves.respond(inq, harness.proposer))
    ev = moves.evaluate_move(inq)
    harness._record("evaluate", {"accepted": {k: v for k, v in ev.issues.items() if v},
                                  "flags": [f.code for f in ev.flags if f.code != "inapplicable_argument"]})
    composed = moves.compose(inq, harness.proposer)
    if composed is not None:
        harness._record("compose", composed)
        ev = moves.evaluate_move(inq)
        if composed["composed_claims"]:
            focus = set(composed["composed_claims"])
            crit = moves.critique(inq, harness.critic, claim_ids=focus)
            harness._record("critique_composed", crit)
            inq.notes.extend(f"critic needs: {q}" for q in crit["needed_evidence"])
            moves.evaluate_move(inq)
            harness._record("respond_composed", moves.respond(inq, harness.proposer, claim_ids=focus))
            ev = moves.evaluate_move(inq)
            harness._record("evaluate_composed", {"claim_ids": sorted(focus),
                "accepted": [cid for cid in focus if ev.status(cid) == "in"]})
    reflection = moves.reflect(inq, ev)
    harness._record("reflect", {"established": reflection.established, "assumed": reflection.assumed,
        "load_bearing": reflection.load_bearing_node_ids, "directive": reflection.directive})
    assessment = moves.stop(inq, ev, rounds_left=0, new_evidence_this_round=0)
    harness._record("stop", {"decision": assessment.decision, "reason": assessment.reason})
    harness._record("conclude", moves.conclude(inq, harness.proposer))


def main():
    old = json.loads((ROOT / "metrics.json").read_text(encoding="utf-8"))
    if (old.get("error") or {}).get("type") != "BudgetExceeded":
        raise ValueError("Expected the original budget-limited Energy checkpoint")
    store = InquiryStore(ROOT, "run")
    if not store.verify_ledger():
        raise ValueError("Checkpoint ledger is invalid")
    inq = store.load()
    events = store.events()
    if inq.round != 2 or inq.phase != "inquiring" or events[-1]["move"] != "experiment_finalize":
        raise ValueError("Unexpected checkpoint phase")
    prior_calls = {role: json.loads((ROOT / f"{role}-responses.json").read_text(encoding="utf-8"))
                   for role in ("proposer", "critic")}
    # Successful round-two Argue replies were applied before the third issue's
    # preflight failed. Preserve that work, including its original raw replies.
    after_compute = []
    for call in reversed(prior_calls["proposer"]):
        if not call["system"].startswith("# SKILL: argue"):
            break
        match = re.search(r"# Issue under argument\s+(Q\d+)", call["user"])
        if match:
            after_compute.append(match[1])
    completed = set(after_compute)
    if completed != {"Q1", "Q2"}:
        raise ValueError(f"Unexpected completed Argue issues: {completed}")
    remaining = {i.id for i in inq.graph.issues if i.status != "dropped"} - completed
    if remaining != {"Q3"}:
        raise ValueError(f"Unexpected remaining issues: {remaining}")
    archive = ROOT / "budget-stop"
    archive.mkdir(exist_ok=False)
    for filename in ("metrics.json", "inquiry.json", "packet.json", "proposer-responses.json", "critic-responses.json"):
        shutil.copy2(ROOT / filename, archive / filename)
    shutil.copy2(store.ledger_path, archive / "ledger.jsonl")
    question = next(q for q in load_questions(Path("bench/questions.yaml")) if q["id"] == "energy-pjm")
    proposer = make_llm(old["config"]["proposer"], limits=LIMITS)
    critic = make_llm(old["config"]["critic"], limits=LIMITS)
    search, fetcher = replay_tools(old["packet_path"])
    h = Harness(inq, store, proposer, critic, search, fetcher, literature_search=None)
    provenance = {"user_authorization": "cap is flexible", "budget_limits": LIMITS,
                  "checkpoint": str(archive), "completed_argue_issues": sorted(completed),
                  "remaining_argue_issues": sorted(remaining), "prior_error": old["error"],
                  "implementation_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  "runner_sha256": fingerprint(Path(__file__).read_text(encoding="utf-8"))}
    h._record("budget_resume", provenance)
    start = time.monotonic()
    error, score = None, {}
    try:
        finish_saved_round(h, remaining)
        score = score_shape(inq, inq.evaluation, question["expected"], critic)
        h._record("shape_judge", score)
    except Exception as exc:
        error = {"type": type(exc).__name__}
        if getattr(exc, "status_code", None):
            error["status"] = exc.status_code
        elif isinstance(exc, (ValueError, RuntimeError)):
            error["message"] = str(exc)[:240]
        print(f"continuation error: {error}", flush=True)
    ev = moves.evaluate_move(inq)
    h._record("experiment_finalize", {"error": error, "question_id": "energy-pjm", "continuation": True})
    h.write_report()
    m = {**old, **metrics(inq, ev, question.get("gold"), question.get("expected")), **score}
    m["error"] = error
    provenance.update({"seconds": round(time.monotonic() - start, 2), "additional_api_calls": len(proposer.calls) + len(critic.calls),
                       "additional_search_queries": len(search.calls), "additional_fetches": len(fetcher.calls)})
    m["continuations"] = [*old.get("continuations", []), provenance]
    m["seconds"] = old["seconds"] + provenance["seconds"]
    m["config"] = {**old["config"], "budget_limits": LIMITS}
    m["implementation_commit"] = provenance["implementation_commit"]
    calls_by_role = {role: prior_calls[role] + handle.calls for role, handle in (("proposer", proposer), ("critic", critic))}
    m["cost_by_provider"] = {provider: sum(call["cost_usd"] or 0 for role, calls in calls_by_role.items()
        if m["config"][role].startswith(provider + ":") for call in calls) for provider in LIMITS}
    m["cost_usd"] = sum(m["cost_by_provider"].values())
    m["api_calls"] = sum(map(len, calls_by_role.values()))
    m["references_valid"], m["ledger_valid"] = not inq.graph.validate_refs(), store.verify_ledger()
    answer = whole_question_answer(inq.graph, ev)
    m["accepted_main_claims"] = [{"id": c.id, "text": c.text, "scope": c.scope.model_dump(), "answers_issue": c.answers_issue}
        for c in inq.main_claims() if (c.answers_issue or c == answer) and ev.status(c.id) == "in"]
    m["accepted_components"] = [{"id": c.id, "text": c.text, "issue_id": c.issue_id} for c in inq.graph.live_claims()
        if c != answer and ev.status(c.id) == "in" and (not c.answers_issue or c.issue_id != inq.graph.main_issue_id)]
    m["main_load_bearing"] = {c.id: [x.model_dump() for x in load_bearing(inq.graph, c.id)] for c in inq.main_claims() if c.answers_issue}
    m["composition_details"] = [{"claim_id": a.claim_id, "argument_id": a.id, "premise_claim_ids": a.premise_ids,
        "scope": inq.graph.claim(a.claim_id).scope.model_dump(), "status": ev.status(a.claim_id),
        "applicable": ev.applicable[a.id], "critique_round": inq.graph.claim(a.claim_id).critique_round,
        "cq": {qid: ans.model_dump() for qid, ans in a.cq.items()}, "attacks": [x.id for x in inq.graph.attacks_on(a.id)]}
        for a in inq.graph.arguments if a.scheme == "composition"]
    m["cannot_compose"] = [n for n in inq.notes if n.startswith("cannot_compose ")]
    flagged = {f.node_id for f in ev.flags if f.code == "single_origin"}
    m["single_origin_flag_missing"] = []
    for c in inq.graph.live_claims():
        if ev.status(c.id) == "in":
            origins = set().union(*(argument_origins(inq.graph, inq.graph.arg(aid), labels=ev.labels) for aid in ev.claims[c.id].pro_ids))
            if len(origins) <= 1 and c.id not in flagged:
                m["single_origin_flag_missing"].append(c.id)
    m["pass"] = (not error and m["references_valid"] and m["ledger_valid"] and not m["claims_supported_unargued"]
        and not m["undecided_empty"] and not m["absence_assertions"] and not m["single_origin_flag_missing"]
        and m["reopened_then_discharged"] >= 1)
    for role, calls in calls_by_role.items():
        (ROOT / f"{role}-responses.json").write_text(json.dumps(calls, indent=2), encoding="utf-8")
    (ROOT / "metrics.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    shutil.copy2(store.state_path, ROOT / "inquiry.json")
    print(one_line(m), flush=True)
    print(json.dumps({"error": error, "additional_calls": provenance["additional_api_calls"],
                      "cost_usd": m["cost_usd"], "phase": inq.phase}), flush=True)


if __name__ == "__main__":
    main()
