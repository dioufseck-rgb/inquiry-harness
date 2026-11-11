"""Read-only checks of TONIGHT-3 artifacts and shared spend; no model calls."""
import hashlib
import json
from pathlib import Path

from inquiry.closure import whole_question_answer
from inquiry.replay_move import fingerprint
from inquiry.state import Inquiry
from inquiry.store import InquiryStore


def audit():
    manifest = json.loads(Path("experiments/E7/manifest.json").read_text(encoding="utf-8"))
    results = []
    for plan in manifest["runs"]:
        root = Path("experiments/E7-energy/sol" if plan["optional"] else f"experiments/E7/{plan['name']}")
        if not (root / "metrics.json").exists():
            results.append({"name": plan["name"], "status": "not complete"})
            continue
        m = json.loads((root / "metrics.json").read_text(encoding="utf-8"))
        store = InquiryStore(root, "run")
        inq = store.load()
        events = store.events()
        answer = whole_question_answer(inq.graph, inq.evaluation)
        raw = {role: json.loads((root / f"{role}-responses.json").read_text(encoding="utf-8"))
               for role in ("proposer", "critic")}
        counts_match = sum(len(calls) for calls in raw.values()) == m["api_calls"]
        costs = {provider: sum(call["cost_usd"] or 0 for role, calls in raw.items()
                              if m["config"][role].startswith(provider + ":") for call in calls)
                 for provider in ("anthropic", "openai")}
        costs_match = all(abs(costs[p] - m["cost_by_provider"][p]) < 1e-8 for p in costs)
        order_checks = []
        sequence = ["argue", "revise", "coverage_check", "critique", "respond", "evaluate"]
        for round_number in sorted({e["round"] for e in events if e["move"] == "stop"}):
            observed = [e["move"] for e in events if e["round"] == round_number and e["move"] in sequence]
            if "argue" in observed:
                order_checks.append(observed == sequence)
        capped_passes = sum(e["move"] == "critique_composed" for e in events)
        anchor = hashlib.sha256(inq.model_dump_json().encode("utf-8")).hexdigest()
        checks = {"references": not inq.graph.validate_refs(), "ledger": store.verify_ledger(),
                  "final_state_anchor": bool(events) and events[-1]["state_hash"] == anchor,
                  "packet_matches_plan": m["packet_sha256"] == plan["packet_sha256"],
                  "packet_manifest_intact": fingerprint(json.loads((root / "packet.json").read_text())) == m["packet_sha256"],
                  "usage_count": counts_match, "costs_reconcile": costs_match,
                  "new_move_order": all(order_checks), "capped_pass_at_most_one": capped_passes <= 1,
                  "closure_matches_graph": m["whole_question_answered"] == (answer is not None),
                  "no_live_retrieval": not m["config"]["live_retrieval"],
                  "no_opus": all("opus" not in m["config"][role].casefold() for role in ("proposer", "critic")),
                  "scope_fields_nonempty": all(c.scope.population and c.scope.outcome and c.scope.period for c in inq.graph.claims)}
        if m.get("continuations"):
            continuations = m["continuations"]
            resume_index = max(i for i, event in enumerate(events) if event["move"] == "budget_resume")
            resumed_moves = {event["move"] for event in events[resume_index + 1:]}
            checks["continuation_skips_appraisal"] = not resumed_moves & {"frame", "hypothesize", "plan", "gather", "compute"}
            checks["continuation_no_retrieval"] = all(c["additional_search_queries"] == c["additional_fetches"] == 0 for c in continuations)
            checks["continuation_stays_in_round_two"] = all(event["round"] == 2 for event in events[resume_index:])
        results.append({"name": plan["name"], "status": "recorded", "checks": checks,
                        "all_integrity_checks_pass": all(checks.values()), "rounds": inq.round,
                        "rounds_completed": len({s.round for s in inq.stop_assessments if s.round > 0}),
                        "phase": inq.phase,
                        "error": m["error"], "composed_claims": m["composed_claims"],
                        "composition_accepted": m["composition_accepted"],
                        "whole_question_answered": m["whole_question_answered"]})
    ledger = json.loads(Path("runs/tonight-3/budget.json").read_text())
    recomputed = {provider: sum(c["budget_debit_usd"] for c in ledger["calls"] if c["provider"] == provider)
                  for provider in manifest["budget_limits_usd"]}
    budget_checks = {"totals_reconcile": all(abs(recomputed[p] - ledger["spent"].get(p, 0)) < 1e-8 for p in recomputed),
                     "within_caps": all(ledger["spent"].get(p, 0) <= cap for p, cap in manifest["budget_limits_usd"].items()),
                     "pending_calls": len(ledger["pending"])}
    data = {"runs": results, "budget": budget_checks, "spent": ledger["spent"], "calls": len(ledger["calls"])}
    Path("experiments/E7/audit.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data))


if __name__ == "__main__":
    audit()
