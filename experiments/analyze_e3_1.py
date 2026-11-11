"""Score E3.1 against the explicitly provisional N1 references."""
import json
from pathlib import Path
from statistics import mean

from inquiry.argument.evaluate import evaluate
from inquiry.replay_move import fingerprint, load_run


def analyze():
    root = Path("experiments/E3_1")
    review = json.loads(Path("experiments/E2/cq_adjudication_provisional.json").read_text(encoding="utf-8"))
    protected = {(r["sample"], r["argument_id"], r["cq_id"]) for r in review["for_sol_reference"]}
    against = {(r["sample"], r["argument_id"], r["cq_id"]) for r in review["against_sol_reference"]}
    results = []
    for path in sorted(root.glob("*/*/moves.json")):
        source_sample = int(path.parent.parent.name.split("-")[-1])
        native = json.loads(path.read_text(encoding="utf-8"))
        sample = native["samples"][0]
        inq, _ = load_run(path.parent / sample["graph"])
        ev = evaluate(inq.graph)
        reopened = {(source_sample, target, qid) for target, ids in ev.reopened_cqs.items() for qid in ids}
        original, _ = load_run(f"experiments/E2/after/h1-claims/sol/sample-{source_sample:03d}")
        assert not original.graph.validate_refs()
        before = evaluate(original.graph)
        attacks = [a for a in inq.graph.arguments if a.is_attack]
        results.append({"source_sample": source_sample, "critic": {k: sample[k] for k in ("provider", "model", "effort")},
            "manifest": str(path), "metrics": sample["metrics"], "error": sample["error"], "cost_usd": sample["cost_usd"],
            "supporting_applicable_before": sum(before.applicable.get(a.id, False) for a in original.graph.arguments if not a.is_attack and not a.withdrawn),
            "supporting_applicable_after": sum(ev.applicable.get(a.id, False) for a in inq.graph.arguments if not a.is_attack and not a.withdrawn),
            "reopenings": [{"argument_id": aid, "cq_id": qid, "claim_id": inq.graph.arg(aid).claim_id} for _, aid, qid in sorted(reopened)],
            "protected_reopened": [list(x) for x in sorted(reopened & protected)],
            "against_sol_overlap": len(reopened & against) / len(reopened) if reopened and against else None,
            "attack_details": [{"id": a.id, "target": a.attacks.target_id, "cq_id": a.attacks.raises_cq,
                                "basis": a.attacks.basis, "note": a.note} for a in attacks]})
    summaries = []
    for provider, baseline in (("openai", 2.0), ("anthropic", 4.333333333333333)):
        cells = [r for r in results if r["critic"]["provider"] == provider]
        summaries.append({"provider": provider, "n": len(cells), "prior_E3_applicable_attacks_mean": baseline,
            "applicable_attacks_mean": mean(r["metrics"]["attacks_applicable"] for r in cells) if cells else None,
            "reopened_mean": mean(r["metrics"]["reopened_cqs"] for r in cells) if cells else None,
            "supporting_applicable_before": mean(r["supporting_applicable_before"] for r in cells) if cells else None,
            "supporting_applicable_after": mean(r["supporting_applicable_after"] for r in cells) if cells else None})
    complete = len(results) == 6 and all(not r["error"] for r in results)
    result = {"experiment": "E3.1", "complete": complete, "reference_kind": "agent_provisional; no human adjudication claimed",
        "against_sol_reference_count": len(against), "protected_reference_count": len(protected),
        "overlap_rate": None if not against else "see per-sample results",
        "overlap_status": "not_estimable: N1 has no same-claim disagreements and zero adjudicated-against-Sol references",
        "protected_reopening_violations": sum(len(r["protected_reopened"]) for r in results),
        "attack_increase_pass": complete and all(s["applicable_attacks_mean"] > s["prior_E3_applicable_attacks_mean"] for s in summaries),
        "pass": False, "summaries": summaries, "samples": results}
    (root / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["## E3.1: audit answered assumptions (N2)", "",
        "Six calls: one critique per saved Sol H1 graph for each critic (three graph samples per critic), all medium effort. The critics see each actual claim and the answered/defaulted assumption text and evidence IDs. No retrieval or new Argue move is run.", "",
        "N1's separate **agent-provisional** review protects ten specific Sol CQ answers at their narrower stated scope. It provides zero against-Sol same-claim references. The requested ≥70% overlap is therefore **not estimable**; this is not labelled a pass. Applicable-attack means also fail to rise above the prior E3 means. No protected CQ was reopened.", "",
        "| Critic | n | Prior E3 applicable attacks | E3.1 applicable attacks | Reopened CQs | Sol support applicable before → after |",
        "|---|---:|---:|---:|---:|---:|"]
    for s in summaries:
        lines.append(f"| {s['provider']} | {s['n']} | {s['prior_E3_applicable_attacks_mean']:.2f} | {s['applicable_attacks_mean']:.2f} | {s['reopened_mean']:.2f} | {s['supporting_applicable_before']:.2f} → {s['supporting_applicable_after']:.2f} |")
    lines += ["", "Both critics identify a population/treatment-contrast concern in the remaining unscoped C5 argument about adding extracranial bleeding. The mechanism works, but the result does not support the prediction that most of Sol's applicable scoped findings should fall to Sonnet's count. N3 makes the original/scoped split explicit before E6 is read.", "",
        "A challenge snapshots the CQ revision: its old answer cannot discharge itself. Only a newer satisfied, evidence-backed Respond answer discharges answer_inadequate. Grounded labels determine active reopenings before target applicability, with reopenings included in the bounded fixed point. Counterattacks can restore the target without changing the original CQ answer. Exact quoted proposer contradictions can ground an internal attack without fabricating a source item.", "",
        "E3.1 is recorded with its unmet count/overlap criterion. N4 requires N2 committed with E3.1 recorded, rather than requiring a fabricated overlap denominator. The user's autonomous-continuation instruction supplies provisional review authority; the human-review blanks remain untouched.", ""]
    report = Path("experiments/E3/report.md")
    original = report.read_text(encoding="utf-8").split("\n## E3.1:", 1)[0].rstrip()
    report.write_text(original + "\n\n" + "\n".join(lines), encoding="utf-8")
    print(json.dumps({"complete": complete, "pass": False, "protected_violations": result["protected_reopening_violations"], "summaries": summaries}))


if __name__ == "__main__":
    analyze()
