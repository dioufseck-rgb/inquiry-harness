"""Command line for controlled development, experiments, export and replay."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
from typing import Any

from . import __version__
from .experiments import ExperimentCase, run_experiments
from .packets import DEFAULT_PACKET_PATH, load_packet
from .persistence import digest, load_run, save_run
from .runtime import Budget, build_prompt, replay_run, run_inquiry
from .scoring import hardship_smoke_expectation, score_run
from .workers import LLMWorker


def _write_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _worker(args: argparse.Namespace):
    if args.demo:
        from .demo import DemoWorker
        return DemoWorker()
    return LLMWorker.from_spec(args.model, effort=args.effort)


def _budget(args: argparse.Namespace) -> Budget:
    return Budget(max_model_calls=args.calls, max_tool_calls=args.tool_calls,
                  max_total_tokens=args.tokens, max_output_tokens=args.output_tokens,
                  timeout_seconds=args.timeout)


def _execution_options(parser: argparse.ArgumentParser) -> None:
    workers = parser.add_mutually_exclusive_group(required=True)
    workers.add_argument("--demo", action="store_true", help="Explicit deterministic development worker; no LLM experiment.")
    workers.add_argument("--model", help="Explicit provider:model; uses the corresponding environment key.")
    parser.add_argument("--critic-model", help="Optional provider:model for critique, counted in the same budget.")
    parser.add_argument("--effort", default="none", choices=["none", "low", "medium", "high"],
                        help="Omit provider reasoning parameters by default; opt in only for a supporting model.")
    parser.add_argument("--calls", type=int, default=10)
    parser.add_argument("--tool-calls", type=int, default=30)
    parser.add_argument("--tokens", type=int, default=200000)
    parser.add_argument("--output-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=180)


def _code_version() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return __version__


def _code_dirty() -> bool | None:
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=3, check=True)
        return bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


def _module_hash(module_name: str) -> str:
    import importlib
    module = importlib.import_module(module_name)
    return digest(Path(module.__file__).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controlled inquiry v1: known evidence, explicit warrant and honest evaluation.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate the authoring packet and every declared mutation.")
    validate.add_argument("--packet", default=str(DEFAULT_PACKET_PATH))
    export = commands.add_parser("export", help="Export one public case without hidden-world or oracle annotations.")
    export.add_argument("--packet", default=str(DEFAULT_PACKET_PATH))
    export.add_argument("--question", default="question_004")
    export.add_argument("--mutation")
    export.add_argument("--out", required=True)
    run = commands.add_parser("run", help="Complete one inquiry; save its record, readable response and trace.")
    run.add_argument("--packet", default=str(DEFAULT_PACKET_PATH))
    run.add_argument("--question", default="question_004")
    run.add_argument("--mutation")
    run.add_argument("--arm", choices=["ordinary", "repertoire", "harness"], default="harness")
    run.add_argument("--mode", choices=["supplied", "documents", "search"], default="supplied")
    run.add_argument("--out", default="runs/v1/single")
    _execution_options(run)
    bench = commands.add_parser("bench", help="Run matched controlled cases; smoke checks and human review are separate.")
    bench.add_argument("--packet", default=str(DEFAULT_PACKET_PATH))
    bench.add_argument("--arms", nargs="+", choices=["ordinary", "repertoire", "harness"], default=["ordinary", "repertoire", "harness"])
    bench.add_argument("--modes", nargs="+", choices=["supplied", "documents", "search"], default=["supplied"])
    bench.add_argument("--questions", nargs="+")
    bench.add_argument("--baseline-only", action="store_true")
    bench.add_argument("--repetitions", type=int, default=1)
    bench.add_argument("--order-seed", type=int, default=0)
    bench.add_argument("--out", default="runs/v1/experiment")
    _execution_options(bench)
    replay = commands.add_parser("replay", help="Verify ledger and re-evaluate a run without model calls.")
    replay.add_argument("directory")
    args = parser.parse_args(argv)
    try:
        if args.command in {"run", "bench"}:
            if args.demo and args.critic_model:
                raise ValueError("--demo cannot be combined with a live --critic-model")
            args.effort = None if args.effort == "none" else args.effort
        if args.command == "replay":
            result = replay_run(load_run(args.directory))
            print(json.dumps({key: value for key, value in result.items() if key != "evaluation"}, indent=2))
            return 0 if result.get("evaluation_reproduced") is not False else 1
        packet = load_packet(args.packet)
        if args.command == "validate":
            for mutation in (None, *packet.mutation_ids):
                for question in packet.question_ids:
                    packet.public(question, mutation)
            print(json.dumps({"valid": True, "packet_hash": packet.packet_hash,
                              "questions": len(packet.question_ids), "mutations": len(packet.mutation_ids),
                              "status": "development fixture, not human-adjudicated gold"}, indent=2))
            return 0
        if args.command == "export":
            _write_json(args.out, packet.public(args.question, args.mutation))
            print(str(Path(args.out).resolve()))
            return 0
        budget = _budget(args)
        if args.command == "run":
            public = packet.public(args.question, args.mutation)
            critic = LLMWorker.from_spec(args.critic_model, effort=args.effort) if args.critic_model else None
            result = run_inquiry(public, _worker(args), arm=args.arm, mode=args.mode, budget=budget, critic=critic)
            path = save_run(result, args.out)
            score = score_run(result, public, answer_spec=packet.oracle(args.question, args.mutation),
                              smoke_expectation=hardship_smoke_expectation(args.question, args.mutation))
            _write_json(path / "assessment.json", score)
            print(result["response"]["text"])
            print(f"\nRun: {result['status']} | stop: {result['stop_reason']} | output: {path.resolve()}")
            print("Development test instrument; no model-quality inference." if args.demo else "Human semantic adjudication remains pending.")
            return 1 if result["status"] == "failed" else 0
        cases = []
        questions = args.questions or packet.question_ids
        variants = (None,) if args.baseline_only else (None, *packet.mutation_ids)
        for mutation in variants:
            for question in questions:
                cases.append(ExperimentCase(case_id=f"{question}/{mutation or 'baseline'}", family_id=packet.fixture_id,
                    public_case=packet.public(question, mutation), oracle=packet.oracle(question, mutation),
                    question_id=question, variant_id=mutation or "baseline",
                    smoke_expectation=hardship_smoke_expectation(question, mutation)))
        worker_description = "deterministic-demo" if args.demo else args.model
        manifest = {"model_pool": [worker_description] + ([args.critic_model] if args.critic_model else []),
                    "effort": args.effort,
                    "prompt_hashes": {arm: digest(build_prompt(arm)) for arm in args.arms},
                    "tool_hash": _module_hash("inquiry.v1.evidence"),
                    "kernel_hash": _module_hash("inquiry.v1.kernel"), "code_version": _code_version(),
                    "code_dirty": _code_dirty(),
                    "implementation_hashes": {name: _module_hash("inquiry.v1." + name)
                                              for name in ("runtime", "workers", "scoring", "experiments", "models", "packets")},
                    "resource_envelope": asdict(budget), "oracle_version": "development-0.1",
                    "execution_kind": "scripted_smoke" if args.demo else "model_experiment"}
        def run_case(public_case, *, arm, mode):
            critic = LLMWorker.from_spec(args.critic_model, effort=args.effort) if args.critic_model else None
            return run_inquiry(public_case, _worker(args), arm=arm, mode=mode, budget=budget, critic=critic)
        result = run_experiments(cases, run_case, arms=args.arms, modes=args.modes,
                                 repetitions=args.repetitions, manifest=manifest,
                                 order_seed=args.order_seed, output_dir=args.out)
        print(json.dumps(result.get("summary", {"output": str(Path(args.out).resolve())}), indent=2))
        print("Human outcome adjudication is pending. Scripted smoke results are not evidence of architectural superiority.")
        summary = result.get("summary", {})
        unsuccessful = (summary.get("failed_runs", 0)
                        or summary.get("structural_status_counts", {}).get("fail", 0)
                        or summary.get("structural_status_counts", {}).get("error", 0)
                        or summary.get("smoke_status_counts", {}).get("fail", 0)
                        or summary.get("smoke_status_counts", {}).get("not_checkable", 0))
        return 1 if unsuccessful else 0
    except (ValueError, KeyError, OSError, ImportError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
