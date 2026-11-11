"""Summarize critic crossings and select E4's fixed attack graph."""
import json
from pathlib import Path
from inquiry.replay_move import aggregate


def analyze():
    root = Path("experiments/E3")
    review = json.loads((root / "needs-review.json").read_text(encoding="utf-8"))
    cells, candidates = [], []
    for path in sorted(root.glob("runs/*/*/moves.json")):
        native = json.loads(path.read_text(encoding="utf-8"))
        input_name = path.parent.parent.name
        for sample in native["samples"]:
            tags = sample["metrics"]["needs_tags"]
            labels = review["cells"][f"{input_name}/{path.parent.name}"][str(sample["sample"])]
            assert len(tags) == len(labels), "need review belongs to a different output"
            sample["metrics"]["needs_tags"] = [dict(t, native_tag=t["tag"], tag=label, tag_basis=review["policy"]) for t, label in zip(tags, labels)]
            sample["metrics"]["needs_obtainable"] = labels.count("obtainable")
            sample["metrics"]["needs_unobtainable"] = labels.count("unobtainable")
            sample["metrics"]["not_requests"] = labels.count("not_request")
        proposer = json.loads((root / "inputs" / input_name / "selection.json").read_text(encoding="utf-8"))
        cells.append({"input": input_name, "proposer": {k: proposer[k] for k in ("provider", "model", "effort")},
                      "critic": {k: native[k] for k in ("provider", "model", "effort")},
                      "manifest": str(path), "n": len(native["samples"]), "aggregate": aggregate(native["samples"]),
                      "native_aggregate": native["aggregate"],
                      "pass": len(native["samples"]) == 3 and all(not s["error"] and s["references_valid"] and s["metrics"]["attacks_applicable"] >= 5 for s in native["samples"]),
                      "needs": [{"sample": s["sample"], **tag} for s in native["samples"] for tag in s["metrics"]["needs_tags"]],
                      "cost_usd": sum(s["cost_usd"] or 0 for s in native["samples"])})
        candidates.extend((path, native, s) for s in native["samples"] if not s["error"] and s["references_valid"])
    result = {"pass": len(cells) == 4 and all(c["pass"] for c in cells), "needs_review": review, "cells": cells}
    if len(cells) == 4 and all(c["n"] == 3 for c in cells):
        candidates.sort(key=lambda item: (-item[2]["metrics"]["attacks"], -item[2]["metrics"]["attacks_applicable"], str(item[0]), item[2]["sample"]))
        path, native, sample = candidates[0]
        out = Path("experiments/E4/input")
        out.mkdir(parents=True, exist_ok=True)
        source = path.parent / sample["graph"]
        (out / "inquiry.json").write_bytes(source.read_bytes())
        selection = {"source": str(source), "critic": {k: native[k] for k in ("provider", "model", "effort")},
                     "metrics": sample["metrics"], "graph_sha256": sample["graph_sha256"],
                     "criterion": "most attacks, then most applicable attacks, manifest path, sample number"}
        (out / "selection.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
        result["e4_selection"] = selection
    (root / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# E3: Critique across proposers and critics", "", f"Applicable-attack gate: **{'PASS' if result['pass'] else 'FAIL / incomplete'}** (at least five in each sample).", "",
             "All efforts are medium. Values are means [min, max]. The 12 samples include both within-provider and cross-provider critics, as requested by the 2 × 2 matrix.", "",
             "| Proposer graph | Critic | n | Attacks | Applicable | With CQ | Obtainable needs | Unobtainable needs | Cost estimate |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    def fmt(a):
        return f"{a['mean']:.2f} [{a['min']:.2f}, {a['max']:.2f}]"
    for c in cells:
        a = c["aggregate"]
        lines.append(f"| {c['proposer']['provider']}:{c['proposer']['model']} | {c['critic']['provider']}:{c['critic']['model']} | {c['n']} | "
                     + " | ".join(fmt(a[k]) for k in ("attacks", "attacks_applicable", "attacks_with_cq", "needs_obtainable", "needs_unobtainable")) + f" | ${c['cost_usd']:.4f} |")
    lines += ["", "Critique code and skill are unchanged. Groundless attacks and unverified absence attacks remain rejected by code. All needs were manually reviewed in needs-review.json: public document/search routes are obtainable, custom participant-level endpoints or author access are unobtainable. A public route is not a claim that the exact requested estimate exists. Independence notes that request no new evidence are excluded from need counts. Native heuristic tags and reviewed tags are both retained in analysis.json.", "",
              "The count gate failed; it would be inappropriate to manufacture extra attacks just to reach five. E4 uses the six-attack sample under the predeclared most-attacks rule.", ""]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"pass": result["pass"], "cells": len(cells)}))
    return result


if __name__ == "__main__":
    analyze()
