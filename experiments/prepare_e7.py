"""Prepare reviewable E7 payload metadata and commands without network or API clients."""
import json
from pathlib import Path
import subprocess

from inquiry.bench import load_questions
from inquiry.replay_move import fingerprint
from inquiry.tools.replay import replay_tools
from experiments.run_fixed_cycle import require_gate
from experiments.run_scope_replay import prepare as prepare_scope


def prepare():
    root = Path("experiments/E7")
    root.mkdir(exist_ok=True)
    questions = {q["id"]: q for q in load_questions(Path("bench/questions.yaml"))}
    gate = json.loads(Path("experiments/E6/gate.json").read_text(encoding="utf-8"))
    specs = [("sonnet", "health-aspirin", "runs/bench/health-aspirin-20261110-0209", "anthropic:claude-sonnet-5-5", "openai:gpt-6.1-sol", False),
             ("sol", "health-aspirin", "runs/bench/health-aspirin-20261110-0209", "openai:gpt-6.1-sol", "anthropic:claude-sonnet-5-5", False),
             ("energy", "energy-pjm", "runs/bench/energy-pjm-tonight-openai-t7", "openai:gpt-6.1-sol", "anthropic:claude-sonnet-5-5", True)]
    plans = []
    for name, question_id, packet_path, proposer, critic, optional in specs:
        require_gate(gate, questions[question_id])
        search, fetcher = replay_tools(packet_path)
        if not fetcher.pages:
            raise ValueError(f"Empty local packet: {packet_path}")
        packet = [{"url": url, "title": title, "characters": len(text), "text_sha256": fingerprint(text)}
                  for url, (title, text) in fetcher.pages.items()]
        out = "experiments/E7-energy/sol" if optional else f"experiments/E7/{name}"
        argv = ["python", "-m", "experiments.run_fixed_cycle", "--question-id", question_id,
                "--packet", packet_path, "--proposer", proposer, "--critic", critic,
                "--out", out, "--budget-campaign", "tonight-3"]
        plans.append({"name": name, "question_id": question_id, "question": questions[question_id]["question"],
                      "split": questions[question_id]["split"], "optional": optional, "packet_path": packet_path,
                      "packet_sha256": fingerprint(packet), "sources": packet, "proposer": proposer, "critic": critic,
                      "rounds": 2, "capped_composition_review_passes": 1, "argv": argv,
                      "transmitted_data": "Question/frame, cached source-text appraisal chunks, evidence, scopes, arguments, critiques and evolving inquiry state. No environment variables or API keys in model prompts."})
    manifest = {"status": "awaiting_explicit_payload_approval", "api_calls": 0,
                "prepared_from_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "budget_limits_usd": {"anthropic": 12, "openai": 8}, "budget_ledger": "runs/tonight-3/budget.json",
                "pricing_snapshot": "experiments/pricing.json", "live_retrieval": False, "held_out_questions": False,
                "opus": False, "runs": plans}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    prepare_scope()
    print(json.dumps({"manifest": str(root / "manifest.json"), "api_calls": 0,
                      "packets": [{"name": p["name"], "sources": len(p["sources"])} for p in plans]}))


if __name__ == "__main__":
    prepare()
