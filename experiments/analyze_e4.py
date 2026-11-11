"""Compare Respond versions using actual new discharges, not answer attempts."""
import json
from pathlib import Path
from statistics import mean

from inquiry.argument.evaluate import is_discharged
from inquiry.llm import extract_json
from inquiry import moves
from inquiry.replay_move import aggregate, load_run


def analyze():
    root = Path("experiments/E4")
    cells = []
    for path in sorted(root.glob("*/*/moves.json")):
        native = json.loads(path.read_text(encoding="utf-8"))
        pre, _ = load_run(path.with_name("pre-move.json"))
        initially_discharged = {a.id for a in pre.graph.arguments if a.is_attack and is_discharged(pre.graph, a)}
        required = {a.id for a in moves.standing_attacks(pre, moves.evaluate_move(pre))}
        samples = []
        for sample in native["samples"]:
            graph_path = path.parent / sample["graph"]
            inq, _ = load_run(graph_path)
            calls = json.loads(graph_path.with_name("responses.json").read_text(encoding="utf-8"))
            proposed = []
            for call in calls:
                try:
                    proposed.extend(extract_json(call["reply"] or "").get("responses", []))
                except (ValueError, AttributeError):
                    pass
            summary = sample["move_summary"]
            conceded = set(summary.get("conceded", []))
            actual_discharges = {aid for aid in summary.get("discharged", []) if aid not in initially_discharged
                                 and inq.graph.arg(aid) and is_discharged(inq.graph, inq.graph.arg(aid))}
            concessions = []
            for aid in sorted(conceded):
                response = next((r for r in reversed(proposed) if r.get("attack_id") == aid and r.get("action") == "concede"), {})
                errors = moves.concession_errors(inq.graph, inq.graph.arg(aid), moves.ResponseProposal.model_validate(response))
                concessions.append({"attack_id": aid, "response": response, "errors": errors, "justified": not errors})
            counters = [inq.graph.arg(aid) for aid in summary.get("countered", [])]
            ev = moves.evaluate_move(inq)
            applicable = [a for a in counters if a and ev.applicable.get(a.id) and a.attacks.target_id not in initially_discharged]
            responded = conceded | actual_discharges | {a.attacks.target_id for a in counters if a}
            m = {"concede": len(conceded), "discharge": len(actual_discharges), "counter": len(counters),
                 "counters_applicable": len(applicable), "concessions_justified": sum(c["justified"] for c in concessions),
                 "native_discharge_count": sample["metrics"]["discharge"], "discharge_attempts_recorded": len(summary.get("discharge_attempts", [])),
                 "unanswered_standing": len(required - responded)}
            samples.append({"sample": sample["sample"], "provider": sample["provider"], "model": sample["model"], "effort": sample["effort"],
                            "tokens_in": sample["tokens_in"], "tokens_out": sample["tokens_out"], "cost_usd": sample["cost_usd"],
                            "error": sample["error"], "metrics": m, "raw_metrics": {}, "concessions": concessions,
                            "defenses_exceed_concessions": m["discharge"] + m["counters_applicable"] > m["concede"],
                            "concessions_pass": m["concessions_justified"] == m["concede"] and m["unanswered_standing"] == 0})
        cells.append({"version": path.parent.parent.name, "provider": native["provider"], "model": native["model"], "effort": native["effort"],
                      "manifest": str(path), "initially_discharged": sorted(initially_discharged), "required_standing": sorted(required),
                      "samples": samples, "aggregate": aggregate(samples),
                      "complete": len(samples) == 3 and all(not s["error"] for s in samples),
                      "mean_defense_balance": mean(s["metrics"]["discharge"] + s["metrics"]["counters_applicable"] - s["metrics"]["concede"] for s in samples if not s["error"])
                                              if any(not s["error"] for s in samples) else 0,
                      "concessions_pass": len(samples) == 3 and all(s["concessions_pass"] for s in samples)})
    after = [c for c in cells if c["version"] == "after-v3"]
    result = {"pass": len(after) == 2 and all(c["complete"] and c["concessions_pass"] for c in after)
              and any(c["mean_defense_balance"] > 0 for c in after), "cells": cells,
              "discharge_method": "Only a newly satisfied, evidence-backed raised CQ counts. Already discharged input attacks and merely written answers are excluded from discharge counts for both versions.",
              "balance_method": "Mean discharges plus applicable counters must exceed mean concessions on at least one provider; all individual results remain visible."}
    (root / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# E4: Respond concession justification", "", f"Gate for after-v3: **{'PASS' if result['pass'] else 'FAIL / incomplete'}**.", "",
             "Means [min, max], three samples per provider/version, all medium effort. Both versions start from the same six-attack graph. A true discharge is distinguished from writing a CQ answer that leaves the attack active.", "",
             "| Version | Provider:model | Successful samples | Concede | Newly discharged | Counters | Applicable counters | Justified concessions | Unanswered standing | Mean defense balance |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    def fmt(a):
        return f"{a['mean']:.2f} [{a['min']:.2f}, {a['max']:.2f}]"
    for c in cells:
        a = c["aggregate"]
        lines.append(f"| {c['version']} | {c['provider']}:{c['model']} | {sum(not s['error'] for s in c['samples'])}/3 | " + " | ".join(fmt(a[k]) for k in
            ("concede", "discharge", "counter", "counters_applicable", "concessions_justified", "unanswered_standing")) + f" | {c['mean_defense_balance']:.2f} |")
    lines += ["", "The new code validates the named CQ, checks that cited evidence IDs exist and intersect the attack context, requires an attempted discharge and a reason the listed evidence does not answer it, records the attempt before the concession, and allows one correction. It also excludes already discharged attacks from the standing view. The common scorer applies actual-discharge semantics to both versions; native attempted-answer counts are preserved in analysis.json.", "",
              "These checks enforce an auditable justification structure, not the semantic truth of a claim that no evidence answers a CQ. The saved concession texts are available for review. A failed defense-balance gate is not repaired by inventing a counter or unsupported discharge.", ""]
    lines += ["The first candidate is retained as `after`: Sol's third sample tried twice to discharge an attack that had no valid named CQ, leaving it unresolved. The general view and retry now explain this structural limit and require a counter or justified concession. The revised candidate was rerun on both providers. Means/ranges exclude failed samples; their errors remain in analysis.json.", ""]
    lines += ["A review of `after-v2` found that concessions to an unnamed attack could cite arbitrary CQs from the target argument. The final candidate requires the attack scheme's `grounds` question in that case; only an explicitly valid raised CQ may select a target's question. Both providers were retested after this code correction.", ""]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"pass": result["pass"], "cells": len(cells)}))
    return result


if __name__ == "__main__":
    analyze()
