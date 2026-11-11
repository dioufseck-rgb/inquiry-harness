"""Reconcile the completed TONIGHT-2 artifacts without model calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic_core import to_json

from inquiry.argument.evaluate import evaluate
from inquiry.experiment_budget import ExperimentBudget
from inquiry.replay_move import fingerprint
from inquiry.state import Inquiry
from inquiry.store import InquiryStore


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit():
    budget = ExperimentBudget(Path("runs/tonight-2/budget.json"), {"anthropic": 36, "openai": 10}, {"anthropic": 20}).status()
    assert not budget["pending"], "wait for all authorized calls to finish"
    human_path = Path("experiments/E2/cq_adjudication.json")
    human = read(human_path)
    human_blank = sum(not case["adjudication"] and not case["note"] for case in human["cases"])
    assert human_blank == len(human["cases"]) == 10, "human review state changed; report it explicitly"
    totals = {"anthropic": 0.0, "openai": 0.0}
    calls = 0
    replay_audits = []
    for path in sorted(Path("experiments/E3_1").glob("sample-*/*/moves.json")):
        manifest = read(path)
        for sample in manifest["samples"]:
            totals[sample["provider"]] += sample["cost_usd"]
            calls += sample["api_calls"]
            state_path = path.parent / f"sample-{sample['sample']:03d}" / "inquiry.json"
            inq = Inquiry.model_validate_json(state_path.read_text(encoding="utf-8"))
            assert not inq.graph.validate_refs()
            replay_audits.append({"manifest": str(path), "references_valid": True,
                                  "state_file_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
                                  "cost_usd": sample["cost_usd"], "api_calls": sample["api_calls"]})
    cycles = []
    for path in (Path("experiments/E6/sonnet"), Path("experiments/E6/sol"),
                 Path("experiments/E6-generalisation/energy"), Path("experiments/E6-generalisation/genai")):
        m = read(path / "metrics.json")
        store = InquiryStore(path, "run")
        state_bytes = store.state_path.read_bytes()
        raw = read(store.state_path)
        inq = Inquiry.model_validate(raw)
        assert store.verify_ledger(), path
        final_event = store.events()[-1]
        # Serialize the native raw mapping, avoiding schema defaults introduced
        # after an experiment was run. Pydantic's own serializer made the anchor.
        state_hash = hashlib.sha256(to_json(raw)).hexdigest()
        assert final_event["state_hash"] == state_hash, (path, "final state anchor")
        assert not inq.graph.validate_refs(), path
        fresh = evaluate(inq.graph)
        assert {cid: d.status for cid, d in inq.evaluation.claims.items()} == {cid: d.status for cid, d in fresh.claims.items()}, path
        assert inq.evaluation.applicable == fresh.applicable and inq.evaluation.labels == fresh.labels, path
        packet = read(path / "packet.json")
        assert fingerprint(packet) == m["packet_sha256"]
        packet_urls = {item["url"] for item in packet}
        assert set(m["fetched_urls"]) <= packet_urls, path
        assert m["config"]["live_retrieval"] is False and m["rounds"] <= 2
        for provider, amount in m["cost_by_provider"].items():
            totals[provider] += amount
        calls += m["api_calls"]
        for role in ("proposer", "critic"):
            role_calls = read(path / f"{role}-responses.json")
            assert all("opus" not in call.get("model", "").casefold() for call in role_calls)
        snapshot = path / "inquiry.json"
        if snapshot.exists():
            assert snapshot.read_bytes() == state_bytes, (path, "snapshot differs")
        else:
            snapshot.write_bytes(state_bytes)
        cycles.append({"path": str(path), "question_id": final_event["summary"]["question_id"],
                       "implementation_commit": m["implementation_commit"], "runner_sha256": m["runner_sha256"],
                       "state_file_sha256": hashlib.sha256(state_bytes).hexdigest(), "state_anchor_valid": True,
                       "final_ledger_hash": final_event["hash"], "ledger_events": len(store.events()),
                       "references_valid": True, "evaluation_reproduced": True, "packet_urls_only": True,
                       "pass": m["pass"], "error": m["error"], "api_calls": m["api_calls"],
                       "cost_by_provider": m["cost_by_provider"], "seconds": m["seconds"]})
    assert calls == len(budget["calls"]), (calls, len(budget["calls"]))
    for provider, amount in totals.items():
        assert abs(amount - budget["spent"].get(provider, 0)) < 1e-9, (provider, amount, budget["spent"])
        assert amount <= {"anthropic": 16, "openai": 10}[provider]
    assert all("opus" not in c["model"].casefold() for c in budget["calls"])
    result = {"campaign": "TONIGHT-2", "review_kind": "agent_provisional_user_authorized",
              "human_review_completed": False, "human_blank_cases": human_blank,
              "human_review_file_sha256": hashlib.sha256(human_path.read_bytes()).hexdigest(),
              "held_out_runs": 0, "live_retrieval_runs": 0,
              "spendable_limits_usd": {"anthropic": 16, "openai": 10}, "protected_opus_reserve_usd": 20,
              "cost_by_provider": totals, "cost_usd": sum(totals.values()), "api_calls": calls,
              "pending_calls": 0, "unknown_cost_calls": sum(c["cost_usd"] is None for c in budget["calls"]),
              "api_error_calls": sum(bool(c["error"]) for c in budget["calls"]),
              "costs_reconcile": True, "E3_1": replay_audits, "full_cycles": cycles}
    target = Path("experiments/tonight-2-audit.json")
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("E3_1", "full_cycles")}))
    return result


if __name__ == "__main__":
    audit()
