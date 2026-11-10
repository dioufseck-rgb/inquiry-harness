"""
Benchmark runner.

    python -m inquiry.bench bench/questions.yaml --split held_in|held_out|all [--rounds N] [--ids a,b]

Runs each selected question through the Harness with the live tools, collects
the metrics line for each, prints a table, and writes bench/results/<date>.json.
The question marked `split: regression` runs with every split.

Acceptance rule for an edit (from NEXT.md): no metric regresses on held_out,
and on held_in at least one of gold_sources_found, attacks_discharged or
shape_match improves while single_origin_accepts and absence_assertions do
not increase.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .live import Harness, _load_env
from .llm import llm_from_env
from .metrics import metrics, one_line
from .state import Inquiry
from .store import InquiryStore


def load_questions(path: Path) -> list[dict[str, Any]]:
    import yaml  # part of the dev extra

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("questions file must be a list")
    return data


def select(questions: list[dict[str, Any]], split: str, ids: list[str] | None) -> list[dict[str, Any]]:
    if ids:
        return [q for q in questions if q["id"] in ids]
    if split == "all":
        return questions
    return [q for q in questions if q.get("split") in (split, "regression")]


def run_question(q: dict[str, Any], root: Path, rounds: int, tag: str, **harness_kw) -> dict[str, Any]:
    from .tools.fetch import HttpFetcher
    from .tools.search import SerperSearch

    run_id = f"{q['id']}-{tag}"
    store = InquiryStore(root, run_id)
    inq = Inquiry(id=run_id, question=" ".join(q["question"].split()))
    h = Harness(inq, store, llm_from_env("proposer"), llm_from_env("critic"), SerperSearch(), HttpFetcher(),
                **harness_kw)
    t0 = time.time()
    error = ""
    try:
        h.run(rounds=rounds)
    except Exception as e:  # noqa: BLE001 — one failed question must not end the bench
        error = f"{type(e).__name__}: {str(e)[:200]}"
    ev = inq.evaluation
    if ev is None:
        from .moves import evaluate_move
        ev = evaluate_move(inq)
    m = metrics(inq, ev, q.get("gold"), q.get("expected"))
    m["seconds"] = round(time.time() - t0)
    m["split"] = q.get("split", "")
    m["error"] = error or m.get("error", "")
    m["run_dir"] = str(store.dir)
    (store.dir / "metrics.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


def table(rows: list[dict[str, Any]]) -> str:
    cols = ["id", "sources", "origins", "evidence", "supporting_in", "attacks", "attacks_out",
            "attacks_discharged", "accepted_claims", "single_origin_accepts", "absence_assertions",
            "gold_sources", "gold_facts", "shape_match", "seconds"]
    out = []
    for r in rows:
        r = dict(r)
        if "gold_sources_total" in r:
            r["gold_sources"] = f"{r['gold_sources_found']}/{r['gold_sources_total']}"
            r["gold_facts"] = f"{r['gold_facts_found']}/{r['gold_facts_total']}"
        out.append([str(r.get(c, "")) for c in cols])
    widths = [max(len(c), *(len(row[i]) for row in out)) for i, c in enumerate(cols)]
    lines = [" ".join(c.ljust(w) for c, w in zip(cols, widths))]
    for row in out:
        lines.append(" ".join(v.ljust(w) for v, w in zip(row, widths)))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="inquiry.bench")
    p.add_argument("questions", type=Path)
    p.add_argument("--split", default="held_in", choices=["held_in", "held_out", "all", "regression"])
    p.add_argument("--ids", default="", help="Comma-separated question ids; overrides --split.")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--max-sources", type=int, default=6)
    p.add_argument("--queries", type=int, default=6)
    p.add_argument("--hits", type=int, default=4)
    p.add_argument("--root", default="runs/bench")
    p.add_argument("--results", default="bench/results")
    args = p.parse_args(argv)

    _load_env()
    questions = load_questions(args.questions)
    chosen = select(questions, args.split, [x for x in args.ids.split(",") if x] or None)
    tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rows = []
    for q in chosen:
        print(f"== {q['id']} ({q.get('split')})", file=sys.stderr)
        m = run_question(q, Path(args.root), args.rounds, tag, max_sources=args.max_sources,
                         queries_per_round=args.queries, hits_per_query=args.hits)
        print(one_line(m), file=sys.stderr)
        rows.append(m)
    print(table(rows))
    out_dir = Path(args.results)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{tag}.json"
    out.write_text(json.dumps({"split": args.split, "rounds": args.rounds, "runs": rows}, indent=2), encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
