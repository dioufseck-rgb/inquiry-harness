"""Historical-only v1 a4 registered experiment driver.

This protocol belongs to commit 6c99cdb34a2a5777c65939bd2ff0f0b5539a93ab.
Use that frozen checkout to repeat it. The later epistemic-service contract is a
different protocol; this script must not silently reinterpret its actions,
letters, completion gates, or scores as current service outputs.

The user-authorized provider calls receive only Packet.public() projections of
fictional records. No real applicants, private documents, or hidden oracle
annotations are sent. Credentials come from the environment or a hidden prompt,
are never written, and are removed from this process after the run.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import types
from zoneinfo import ZoneInfo
import zipfile

FROZEN_PROTOCOL_COMMIT = "6c99cdb34a2a5777c65939bd2ff0f0b5539a93ab"


BASELINE_COMMIT = "7712518621b36e1debf32be04a64faaf88d82acf"
BASELINE_ARCHIVE = Path("experiments/v1/live_20261114/inquiry_v1_live_records_20261114.zip")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def main() -> int:
    raise SystemExit(
        "This is a historical-only a4 experiment protocol. Use the unchanged "
        f"script and runtime from frozen commit {FROZEN_PROTOCOL_COMMIT}; "
        "register a separate protocol for the epistemic service. No provider call was made."
    )


def _historical_main() -> int:
    # Retained as a readable protocol record, not an executable migration path.
    # Imports deliberately stay inside this unreachable historical entry point.
    from inquiry.v1.experiments import summarize_runs
    from inquiry.v1.packets import load_packet
    from inquiry.v1.persistence import digest, inspect_journal, save_run
    from inquiry.v1.runtime import Budget, IMPLEMENTATION_HASHES, build_critic_prompt, build_prompt, replay_run, run_inquiry
    from inquiry.v1.scoring import SCORER_VERSION, hardship_smoke_expectation, score_run
    from inquiry.v1.workers import LLMWorker

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="New run directory; existing output is never overwritten.")
    args = parser.parse_args()
    if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
        raise SystemExit("Freeze and commit the implementation before the live batch; checkout is dirty.")
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(BASELINE_ARCHIVE) as archive:
        previous_protocol = json.loads(archive.read("protocol.json"))
        baseline_records = {}
        for job in previous_protocol["order"]:
            name = job["question"] + "-" + (job["mutation"] or "baseline")
            baseline_records[name] = {
                "result": json.loads(archive.read(name + "/result.json")),
                "score": json.loads(archive.read(name + "/assessment.json")),
            }
    packet = load_packet()
    assert packet.packet_hash == previous_protocol["packet_hash"], "The fixed evidence packet changed."
    legacy_source = subprocess.check_output(["git", "show", BASELINE_COMMIT + ":inquiry/v1/scoring.py"], text=True)
    legacy_scoring = types.ModuleType("frozen_legacy_scoring")
    exec(compile(legacy_source, "frozen_legacy_scoring.py", "exec"), legacy_scoring.__dict__)
    budget = Budget(**previous_protocol["budget"])
    protocol = {
        "kind": "prespecified_frozen_repair_development_batch", "version": 1,
        "created_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_clean": True, "implementation_hashes": IMPLEMENTATION_HASHES,
        "baseline_commit": BASELINE_COMMIT, "baseline_protocol_hash": digest(previous_protocol),
        "packet_hash": packet.packet_hash, "arm": previous_protocol["arm"], "mode": previous_protocol["mode"],
        "proposer": previous_protocol["proposer"], "critic": previous_protocol["critic"],
        "effort": previous_protocol["effort"], "budget": asdict(budget),
        "order": previous_protocol["order"], "repetitions": 1,
        "prompt_hash": digest(build_prompt("harness")), "critic_prompt_hash": digest(build_critic_prompt()),
        "scorer_version": SCORER_VERSION,
        "legacy_scorer_sha256": hashlib.sha256(legacy_source.encode()).hexdigest(),
        "expectations": [{**job, "smoke": hardship_smoke_expectation(job["question"], job["mutation"])}
                         for job in previous_protocol["order"]],
        "predictions": [
            "Every model reply is admitted as exactly one role-valid envelope or explicitly rejected; no suffix operations are silently lost.",
            "Local record defects are repaired before substantive critique; a valid explicit reply can resolve a challenge without erasing it.",
            "Both intake cases return the applicable response and an actual draft, with the missing-details variant requesting only the two absent details.",
            "The employer-trace case acquires the source as reading blocks and can produce the scoped causal finding.",
            "The baseline causal, eligibility and universal settings return useful limited assessments without unsupported closure.",
        ],
        "interpretation": "Development regression run, not held-out research. Same cases, packet, model snapshots, effort and total resource caps as baseline. Critic acquisition/retry calls share those caps; only a valid final critique counts as completed review. No code/prompt changes or completed-case reruns within the batch. Old and new scorers are both retained; human adjudication remains pending.",
    }
    write_json(root / "protocol.json", protocol)
    baseline_rescored = []
    for job in protocol["order"]:
        q, m = job["question"], job["mutation"]
        name = q + "-" + (m or "baseline")
        old = baseline_records[name]
        public = packet.public(q, m)
        assert "synthetic" in public["shared_context"]["fiction_notice"]
        baseline_rescored.append({"case_id": name, "original_score": old["score"],
                                  "current_score": score_run(old["result"], public, answer_spec=packet.oracle(q, m),
                                                             smoke_expectation=hardship_smoke_expectation(q, m))})
    write_json(root / "baseline_rescored.json", baseline_rescored)
    print("Frozen eight-case rerun: every applicant, programme, document and amount is synthetic.", flush=True)
    key = os.environ.get("OPENAI_API_KEY") or getpass.getpass("Temporary API credential (hidden): ")
    os.environ["OPENAI_API_KEY"] = key
    del key
    records = []
    try:
        for number, job in enumerate(protocol["order"], 1):
            question, mutation = job["question"], job["mutation"]
            case_id = question + "-" + (mutation or "baseline")
            directory = root / case_id
            public = packet.public(question, mutation)
            print(json.dumps({"starting": number, "of": len(protocol["order"]), "case": case_id}), flush=True)
            result = run_inquiry(public,
                                 LLMWorker.from_spec(protocol["proposer"], effort=protocol["effort"]),
                                 arm=protocol["arm"], mode=protocol["mode"], budget=budget,
                                 critic=LLMWorker.from_spec(protocol["critic"], effort=protocol["effort"]),
                                 event_path=directory / "events.live.jsonl")
            save_run(result, directory)
            score = score_run(result, public, answer_spec=packet.oracle(question, mutation),
                              smoke_expectation=hardship_smoke_expectation(question, mutation))
            legacy_score = legacy_scoring.score_run(result, public, answer_spec=packet.oracle(question, mutation),
                                                   smoke_expectation=legacy_scoring.hardship_smoke_expectation(question, mutation))
            write_json(directory / "assessment.json", score)
            write_json(directory / "assessment_legacy.json", legacy_score)
            replay = {k: v for k, v in replay_run(result).items() if k != "evaluation"}
            journal = inspect_journal(directory / "events.live.jsonl")
            record = {"case_id": case_id, "question_id": question, "mutation_id": mutation,
                      "result": result, "score": score, "legacy_score": legacy_score,
                      "replay": replay, "journal": journal,
                      "attempt_elapsed_seconds": result["usage"]["elapsed_seconds"]}
            records.append(record)
            with (root / "runs.jsonl").open("a") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            target = next((f for f in result["response"]["findings"]
                           if f["claim_id"] == result["response"]["target_claim_id"]), {})
            print(json.dumps({"finished": number, "case": case_id, "status": result["status"],
                              "standing": target.get("status"), "next_action": result["response"]["next_action"],
                              "delivery_completed": result["response"].get("delivery_completed"),
                              "review_completed": result["response"].get("review_completed"),
                              "structural": score["structural"]["status"], "smoke": score["smoke"]["status"],
                              "legacy_smoke": legacy_score["smoke"]["status"], "usage": result["usage"],
                              "errors": result["errors"], "replay": replay}), flush=True)
            if any(any(marker in error for marker in ("AuthenticationError", "insufficient_quota", "BadRequestError"))
                   for error in result["errors"]):
                print("Stopped on provider configuration/authentication/quota failure; later cases were not attempted.", flush=True)
                break
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        summary = {"protocol": protocol, "summary": summarize_runs(records), "saved_cases": len(records),
                   "planned_cases": len(protocol["order"]), "human_adjudicated": False}
        write_json(root / "summary.json", summary)
        print(json.dumps(summary["summary"], indent=2), flush=True)
    return 0 if len(records) == len(protocol["order"]) and all(r["result"]["status"] == "complete" for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
