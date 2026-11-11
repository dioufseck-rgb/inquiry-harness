"""Report all E2 cells and freeze a deterministic best graph per proposer."""
import json
from pathlib import Path

from inquiry.replay_move import fingerprint


def analyze():
    root = Path("experiments/E2")
    cells = []
    for path in sorted(root.glob("*/*/*/moves.json")):
        version, claims, provider = path.relative_to(root).parts[:3]
        native = json.loads(path.read_text(encoding="utf-8"))
        if version not in ("before", "after"):
            continue
        pre = json.loads(path.with_name("pre-move.json").read_text(encoding="utf-8"))
        cell = {"version": version, "claims": claims, "provider": native["provider"], "model": native["model"],
                "effort": native["effort"], "manifest": str(path), "n": len(native["samples"]),
                "input_graph_sha256": fingerprint({k: pre[k] for k in ("question", "framing", "graph")}),
                "aggregate": native["aggregate"], "samples": native["samples"],
                "cost_usd": sum(s["cost_usd"] or 0 for s in native["samples"]),
                "pass": len(native["samples"]) == 3 and all(not s["error"] and s["references_valid"]
                    and s["metrics"]["claims_supported_unargued"] == 0 and s["metrics"]["unusable_share"] < .3
                    and bool(s["metrics"].get("input_eligible_claims", s["metrics"]["eligible_claims"]))
                    for s in native["samples"])}
        cells.append(cell)
    combination = [c for c in cells if c["version"] == "after" and c["claims"] == "h1-claims"]
    paired = []
    for cell in [c for c in cells if c["version"] == "after"]:
        before = next((c for c in cells if c["version"] == "before" and c["claims"] == cell["claims"] and c["provider"] == cell["provider"]), None)
        paired.append({"claims": cell["claims"], "provider": cell["provider"],
                       "same_graph_and_framing": bool(before and before["input_graph_sha256"] == cell["input_graph_sha256"])})
    result = {"pass": len(combination) == 2 and all(c["pass"] for c in combination),
              "complete": len(cells) == 12 and all(c["n"] == 3 for c in cells), "input_pairs": paired, "cells": cells}
    (root / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# E2: claim granularity versus Argue coverage", "", f"Combination gate: **{'PASS' if result['pass'] else 'FAIL / incomplete'}**. Complete 36-sample matrix: {result['complete']}.", "",
             "Means [min, max], three independent move samples per cell. Every effort is medium. API calls include every issue and every correction/JSON repair.", "",
             "| Version | Claims | Provider:model | n | Supporting | Applicable | Supported, unargued | Unusable share | Scope proposals | Cost estimate |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    def fmt(a):
        return f"{a['mean']:.2f} [{a['min']:.2f}, {a['max']:.2f}]"
    for cell in cells:
        a = cell["aggregate"]
        lines.append(f"| {cell['version']} | {cell['claims']} | {cell['provider']}:{cell['model']} | {cell['n']} | "
                     + " | ".join(fmt(a[k]) for k in ("supporting_args", "applicable_args", "claims_supported_unargued", "unusable_share", "scoped_claims_proposed"))
                     + f" | ${cell['cost_usd']:.4f} |")
    lines += ["", "The Claude claim swap ran first. Sol still built exactly one supporting argument in each sample; changing claims alone did not recover coverage. H2 is evaluated on the identical evidence directions and issue contexts within each before/after pair. Across claim sets, the reviewed directions and associated issue contexts also change, so this does not isolate wording alone.", "",
              "H1's raw E1 gate remains failed. Its E2 claim set is the median-length final-candidate Sol aspirin sample, fixed before its Argue results. A zero coverage gap cannot be supplied by a claim-level reason: reasons satisfy the structural response contract but still count as unargued in the strict experiment metric. Scoped revisions carry actual arguments, and the manifests record original eligible claim IDs as well as final eligibility.", "",
              "The unusable denominator is the fixed input set of offered evidence; H2 records ignored excess entries separately. A lower unusable share partly reflects the enforced cap, not necessarily better model judgment. Applicable arguments are reported separately from mere argument count.", "",
              "All before/after graph-and-framing fingerprints match: " + str(all(p["same_graph_and_framing"] for p in paired)) + ". Empty bookkeeping fields added to the schema are excluded from this comparison.", ""]
    if cells:
        selections = []
        for provider in ("anthropic", "openai"):
            provider_cells = [c for c in cells if c["version"] == "after" and c["provider"] == provider]
            if len(provider_cells) != 3 or any(c["n"] != 3 for c in provider_cells):
                continue
            candidates = [(c, s) for c in cells if c["version"] == "after" and c["provider"] == provider
                          for s in c["samples"] if not s["error"] and s["references_valid"]]
            candidates.sort(key=lambda cs: (cs[1]["metrics"]["claims_supported_unargued"] != 0,
                cs[1]["metrics"]["unusable_share"] >= .3, -cs[1]["metrics"]["applicable_args"],
                -cs[1]["metrics"]["supporting_args"], cs[0]["claims"], cs[1]["sample"]))
            cell, sample = candidates[0]
            source = Path(cell["manifest"]).parent / sample["graph"]
            out = Path("experiments/E3/inputs") / ("sonnet" if provider == "anthropic" else "sol")
            out.mkdir(parents=True, exist_ok=True)
            (out / "inquiry.json").write_bytes(source.read_bytes())
            selection = {"source": str(source), "claims": cell["claims"], "provider": provider, "model": cell["model"],
                         "effort": cell["effort"], "metrics": sample["metrics"], "graph_sha256": sample["graph_sha256"],
                         "criterion": "zero gaps, below-cap unusable, then most applicable arguments, most supporting arguments, claim-set name, sample number"}
            (out / "selection.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
            selections.append(selection)
        result["e3_selections"] = selections
        (root / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"pass": result["pass"], "complete": result["complete"], "cells": len(cells)}))
    return result


if __name__ == "__main__":
    analyze()
