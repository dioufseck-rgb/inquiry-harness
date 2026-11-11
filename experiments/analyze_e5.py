"""Evaluate local-source appraisal against gold fixed before model outputs."""
import hashlib
import json
from pathlib import Path
import re

from inquiry.replay_move import load_run


def analyze():
    root = Path("experiments/E5")
    gold_path = root / "gold.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    adjudications = json.loads((root / "adjudications.json").read_text(encoding="utf-8"))
    cells = []
    for path in sorted(root.glob("*/*/moves.json")):
        native = json.loads(path.read_text(encoding="utf-8"))
        samples = []
        for sample in native["samples"]:
            inq, _ = load_run(path.parent / sample["graph"])
            evidence = [e for e in inq.graph.evidence if e.source_id == "S16"]
            manual = adjudications["matches"].get(f"{path.parent.parent.name}/{path.parent.name}/{sample['sample']}", {})
            pairs, facts = [], []
            for item in gold["items"]:
                matches = [e for e in evidence if all(re.search(p, e.text + " " + e.quote, re.I | re.S) for p in item["match_all"])]
                if item["id"] in manual:
                    matches = [e for e in evidence if e.id in manual[item["id"]]]
                facts.append({"gold_id": item["id"], "evidence_ids": [e.id for e in matches], "manually_adjudicated": item["id"] in manual})
                for cid, expected in item["directions"].items():
                    actual = sorted({e.bears_on[cid] for e in matches if cid in e.bears_on})
                    pairs.append({"gold_id": item["id"], "claim_id": cid, "expected": expected,
                                  "actual": actual, "fact_found": bool(matches),
                                  "agree": actual == [expected]})
            observed = [p for p in pairs if p["fact_found"] and p["actual"]]
            grade = any(f["gold_id"] == "G1" and f["evidence_ids"] for f in facts)
            m = sample["metrics"]
            samples.append({"sample": sample["sample"], "provider": sample["provider"], "model": sample["model"], "effort": sample["effort"],
                "tokens_in": sample["tokens_in"], "tokens_out": sample["tokens_out"], "cost_usd": sample["cost_usd"],
                "error": sample["error"], "evidence": m["evidence"], "quote_verified": m["quote_verified"],
                "grade_d_found": grade, "gold_facts_found": sum(bool(f["evidence_ids"]) for f in facts),
                "direction_agreement_observed": sum(p["agree"] for p in observed) / len(observed) if observed else None,
                "direction_pairs_observed": len(observed), "direction_pairs_total": len(pairs),
                "direction_pairs_correct": sum(p["agree"] for p in pairs), "fact_matches": facts, "directions": pairs,
                "pass": not sample["error"] and sample["references_valid"] and grade and m["quote_verified"] >= .9})
        cells.append({"version": path.parent.parent.name, "provider": native["provider"], "model": native["model"], "effort": native["effort"],
                      "manifest": str(path), "samples": samples, "pass": len(samples) == 3 and all(s["pass"] for s in samples)})
    guarded = [c for c in cells if c["version"] == "guarded"]
    result = {"gold_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(), "cells": cells,
              "direction_method": "Fixed regex fact matches plus separately recorded manual adjudications of semantic equivalence; frozen gold labels are unchanged. Exact comparison of explicitly reported hints, with missing facts/hints visible in coverage.",
              "pass": len(guarded) == 2 and all(c["pass"] for c in guarded)}
    (root / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# E5: local USPSTF appraisal", "", f"Gate: **{'PASS' if result['pass'] else 'FAIL / incomplete'}**. Gold was hand-labelled before outputs, with H1's fixed 17 claims.", "",
             "| Version | Provider:model (medium) | Sample | Evidence | Verified quotes | Grade D with recommendation | Gold facts / 10 | Direction agreement (observed pairs) | Explicit pairs / total | Cost estimate |",
             "|---|---|---:|---:|---:|---|---:|---:|---:|---:|"]
    for c in cells:
        for s in c["samples"]:
            agreement = f"{s['direction_agreement_observed']:.1%}" if s["direction_agreement_observed"] is not None else "n/a"
            lines.append(f"| {c['version']} | {s['provider']}:{s['model']} | {s['sample']} | {s['evidence']} | {s['quote_verified']:.1%} | {s['grade_d_found']} | {s['gold_facts_found']} | {agreement} | {s['direction_pairs_observed']}/{s['direction_pairs_total']} | ${s['cost_usd']:.4f} |")
    lines += ["", "Only S16 is read, from local text; no retrieval, gold injection into prompts, or held-out question is involved. Gold labels were frozen before outputs. Separate manual adjudications credit equivalent abbreviations/pronouns and a fact split across items; missing Grade D or numeric bounds are not inferred. The detailed matches and missing direction pairs are saved for review. Agreement is conditional on explicitly labelled matched pairs; pair coverage is shown alongside it.", "",
              "Quote verification uses literal source membership after whitespace/case folding, including any clipping in the stored quote. It does not assume that plausible paraphrases are verified quotations.", ""]
    lines += ["For a gold fact split across extracted items, direction comparison uses the union of their explicit hints. The combined lifetime-model gold fact spans two age bands; age-specific hints may differ and therefore disagree with its combined neutral label. This aggregation limitation is visible in the detailed directions, rather than resolved by changing the frozen labels.", ""]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"pass": result["pass"], "cells": len(cells)}))


if __name__ == "__main__":
    analyze()
