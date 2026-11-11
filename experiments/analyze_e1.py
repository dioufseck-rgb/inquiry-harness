"""Rescore saved E1 replies with one checker, without modifying native results."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from inquiry.llm import extract_json
from inquiry.replay_move import aggregate, hypothesis_metrics, load_run
from inquiry.specificity import claim_specificity_errors


def analyze(root: Path = Path("experiments/E1"), accepted_version: str = "after-v5") -> dict:
    cells = []
    for path in sorted(root.glob("*/*/*/moves.json")):
        version, frame, provider = path.relative_to(root).parts[:3]
        native = json.loads(path.read_text(encoding="utf-8"))
        samples = []
        for sample in native["samples"]:
            graph, _ = load_run(path.parent / sample["graph"])
            issues = [i for i in graph.graph.issues if i.status != "dropped"]
            calls = json.loads((path.parent / sample["graph"]).with_name("responses.json").read_text(encoding="utf-8"))
            proposals = []
            for call in calls:
                try:
                    proposal = extract_json(call["reply"] or "")
                except ValueError:
                    continue
                if isinstance(proposal, dict) and "claims" in proposal:
                    proposals.append(proposal)
            raw = hypothesis_metrics(proposals[0]["claims"], issues) if proposals else {}
            raw["exclusive_groups"] = len(proposals[0].get("exclusive_groups", [])) if proposals else 0
            kept = hypothesis_metrics([c for c in graph.graph.claims if c.live], issues)
            kept["exclusive_groups"] = sample["metrics"]["exclusive_groups"]
            anchors = {i.id: i.answerhood for i in issues}
            violations = [{"text": c["text"], "reasons": reasons} for c in proposals[0]["claims"]
                          if (reasons := claim_specificity_errors(c["text"], anchors.get(c.get("issue_id"), "")))] if proposals else []
            passed = (not sample["error"] and sample["references_valid"] and bool(raw)
                      and raw["n_over_guard"] == 0 and raw["avg_digits"] <= 5
                      and kept["n_with_null"] == len(issues)
                      and any(c.live and c.kind == "substantive" and c.issue_id == graph.graph.main_issue_id
                              for c in graph.graph.claims))
            samples.append({"sample": sample["sample"], "error": sample["error"], "metrics": kept,
                            "raw_metrics": raw, "raw_violations": violations, "pass": passed})
        cells.append({"version": version, "frame": frame, "provider": native["provider"],
                      "model": native["model"], "effort": native["effort"],
                      "native_manifest": str(path), "input_sha256": native["input_sha256"],
                      "skill_sha256": native["skill_sha256"], "samples": samples,
                      "tokens_in": sum(s["tokens_in"] for s in native["samples"]),
                      "tokens_out": sum(s["tokens_out"] for s in native["samples"]),
                      "cost_usd": sum(s["cost_usd"] for s in native["samples"]),
                      "api_calls": sum(s["api_calls"] for s in native["samples"]),
                      "aggregate": aggregate(samples), "pass": len(samples) == 3 and all(s["pass"] for s in samples)})
    accepted = [c for c in cells if c["version"] == accepted_version]
    result = {"checker_sha256": hashlib.sha256(Path("inquiry/specificity.py").read_bytes()).hexdigest(),
              "method": "First parseable Hypothesize proposal before the policy guard; same current checker for every version. Native manifests and replies are unchanged.",
              "candidate_version": accepted_version, "pass": len(accepted) == 4 and all(c["pass"] for c in accepted),
              "cells": cells}
    (root / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# E1: claim granularity", "", f"Gate: **{'PASS' if result['pass'] else 'FAIL'}** for {accepted_version}, both frames and providers, three independent samples per cell.", "",
             "Raw proposals are scored before the guard or repair acts. Every version uses the same checker, including unrequested protocol details. Native metrics and replies remain unchanged. Values below are means [min, max]. All efforts are medium.", "",
             "| Version | Frame | Provider:model | Raw length | Raw digits | Raw violations | Final nulls/issues | Cost estimate |", "|---|---|---|---:|---:|---:|---:|---:|"]
    def fmt(a):
        return f"{a['mean']:.2f} [{a['min']:.2f}, {a['max']:.2f}]"
    for cell in cells:
        a = cell["aggregate"]
        lines.append(f"| {cell['version']} | {cell['frame']} | {cell['provider']}:{cell['model']} | {fmt(a['raw_avg_len'])} | {fmt(a['raw_avg_digits'])} | {fmt(a['raw_n_over_guard'])} | {fmt(a['n_with_null'])}/{a['n_issues']['mean']:.0f} | ${cell['cost_usd']:.4f} |")
    lines += ["", "The first H1 candidate (`after`) failed the pre-guard ULEZ test on Sonnet. Later versions improved the numeric budget but Sonnet still proposed endpoint recipes for a conceptual issue. All failed candidates are retained. The final revision normalizes legacy answerhood in the view without changing the saved input graph. It also fixes Frame's recognition of unrequested endpoint-construction instructions. Every revision was run on both providers and both frames. JSON/policy repairs add visible API calls.", "",
              "The code rejects excessive specificity, returns the reasons once, then drops remaining failures. Actual null answers are retained per issue. Frame sanitation is tested separately; the saved E1 frames are identical before and after, so this experiment isolates Hypothesize.", "",
              "E2(c) uses the median-length Sol aspirin sample from the final candidate, chosen by raw average length then sample number before observing Argue results. Both Argue providers receive this same guarded claim set. This tests the lineage that originally produced the empty graph. Passing the retained-output guard does not turn the failed raw E1 gate into a pass; E6 remains gated.", ""]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    if len(accepted) == 4 and all(len(c["samples"]) == 3 for c in accepted):
        cell = next(c for c in accepted if c["frame"] == "aspirin" and c["provider"] == "openai")
        selected = sorted(cell["samples"], key=lambda s: (s["raw_metrics"]["avg_len"], s["sample"]))[1]
        native = json.loads(Path(cell["native_manifest"]).read_text(encoding="utf-8"))
        sample = next(s for s in native["samples"] if s["sample"] == selected["sample"])
        source = Path(cell["native_manifest"]).parent / sample["graph"]
        out = Path("experiments/E2/h1-claims")
        out.mkdir(parents=True, exist_ok=True)
        (out / "inquiry.json").write_bytes(source.read_bytes())
        (out / "selection.json").write_text(json.dumps({"source": str(source), "graph_sha256": sample["graph_sha256"],
            "provider": cell["provider"], "model": cell["model"], "effort": cell["effort"],
            "e1_gate": result["pass"], "criterion": "median raw average length, then sample number, final-candidate Sol aspirin samples; chosen before E2(c)"}, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    result = analyze()
    print(json.dumps({"pass": result["pass"], "cells": len(result["cells"])}))
