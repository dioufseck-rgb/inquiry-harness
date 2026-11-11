"""Render fixed-cycle metrics and composition evidence without new model calls."""
import argparse
import json
from pathlib import Path

from inquiry.metrics import one_line
from inquiry.argument.evaluate import claim_status_label
from inquiry.argument.render import summary
from inquiry.state import Inquiry


def render(paths, report_path, title):
    runs = []
    for name, path in paths:
        path = Path(path)
        if not (path / "metrics.json").exists():
            print(json.dumps({"waiting_for": str(path / "metrics.json")}))
            return False
        m = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
        inq = Inquiry.model_validate_json((path / "run/inquiry.json").read_text(encoding="utf-8"))
        labels = {}
        for claim in inq.graph.live_claims():
            label, reason = claim_status_label(inq.graph, inq.evaluation, claim.id)
            labels[claim.id] = {"label": label, "reason": reason, "status": inq.evaluation.status(claim.id),
                                "text": claim.text, "issue_id": claim.issue_id, "answers_issue": claim.answers_issue}
            inq.evaluation.claims[claim.id].label = label
            inq.evaluation.claims[claim.id].label_reason = reason
        # Derived reports only: never rewrite the experimental state or ledger.
        (path / "claim-labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
        (path / "labelled-summary.md").write_text(summary(inq.graph, inq.evaluation).rstrip() + "\n", encoding="utf-8")
        m["main_labels_derived"] = {c.id: labels[c.id]["label"] for c in inq.main_claims() if c.answers_issue}
        runs.append((name, path, m))
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    def ids(items):
        return "; ".join(f"{c['id']}: {c['text']}" for c in items) or "none"
    fields = [
        ("rounds completed (limit 2)", lambda m: m['rounds']),
        ("sources / evidence (fixed local packet)", lambda m: f"{m['sources']} / {m['evidence']} ({m['packet_sources']} source texts available)"),
        ("supporting_original / supporting_scoped", lambda m: f"{m['supporting_original']} / {m['supporting_scoped']}"),
        ("applicable_original / applicable_scoped", lambda m: f"{m['applicable_original']} / {m['applicable_scoped']}"),
        ("attacks / reopened_cqs / attacks_out / discharged", lambda m: f"{m['attacks']} / {m['reopened_cqs']} / {m['attacks_out']} / {m['attacks_discharged']}"),
        ("reopened_then_discharged", lambda m: m['reopened_then_discharged']),
        ("main_supporting_in_original", lambda m: m['main_supporting_in_original']),
        ("accepted main claims (IDs, stated scope)", lambda m: ids(m['accepted_main_claims'])),
        ("main answer labels (N5)", lambda m: m['main_labels_derived']),
        ("undecided_empty / undecided_supported", lambda m: f"{m['undecided_empty']} / {m['undecided_supported']}"),
        ("component findings accepted", lambda m: ids(m['accepted_components'])),
        ("shape regex / judge", lambda m: f"{m.get('shape_match_regex')} / {m.get('shape_match_judge')}"),
        ("absence_assertions", lambda m: m['absence_assertions']),
        ("claims_supported_unargued", lambda m: m['claims_supported_unargued']),
        ("unflagged single-origin accepted claims", lambda m: m['single_origin_flag_missing']),
        ("cost estimate / seconds", lambda m: f"${m['cost_usd']:.4f} / {m['seconds']:.1f}"),
        ("references / ledger", lambda m: f"{m['references_valid']} / {m['ledger_valid']}"),
        ("pass / error", lambda m: f"{m['pass']} / {m['error']}"),
    ]
    lines = [f"# {title}", "", "Each run uses local stored source text, with the opposite provider as critic, medium effort for both roles, a two-round limit, one Frame sample and no human frame edits. The source text packet is fixed; appraisal creates new evidence items. No live retrieval or held-out question is run. Opus remains unused.", "",
             "| | " + " | ".join(name for name, _, _ in runs) + " |", "|---|" + "---|" * len(runs)]
    for label, value in fields:
        lines.append("| " + label + " | " + " | ".join(cell(value(m)) for _, _, m in runs) + " |")
    for name, path, m in runs:
        lines += ["", f"## {name}", "", f"Proposer: `{m['config']['proposer']}`; critic: `{m['config']['critic']}`; both medium. Input: `{m['packet_path']}`. Packet fingerprint: `{m['packet_sha256']}`. Core implementation: `{m['implementation_commit']}`.", "", "```text", one_line(m), "```", ""]
        graph = json.loads((path / "run/inquiry.json").read_text(encoding="utf-8"))
        ev, g = graph["evaluation"], graph["graph"]
        main = g["main_issue_id"]
        claims = [c for c in g["claims"] if c["issue_id"] == main and c["superseded_by"] is None and c["answers_issue"]]
        args = [a for a in g["arguments"] if not a["attacks"] and not a["withdrawn"]]
        accepted = m["accepted_main_claims"]
        state = "accepted main answer" if accepted else "undecided with surviving main-answer support" if m["undecided_supported"] else "no accepted or surviving supported main answer"
        blockers = [f"{a['id']} ({a['claim_id']}): {', '.join(ev['inapplicable_reasons'].get(a['id'], []))}" for a in args
                    if a['claim_id'] in {c['id'] for c in claims} and not ev['applicable'].get(a['id'], False)]
        lb = [f"{item['node_id']} → {cid} ({item['effect']})" for cid, items in m["main_load_bearing"].items() for item in items]
        components = m["accepted_components"]
        blood = [c['id'] for c in components if any(w in c['text'].casefold() for w in ('bleed', 'hemorr', 'haemorr'))]
        cardiovascular = [c['id'] for c in components if any(w in c['text'].casefold() for w in ('myocard', 'cardiovascular', 'stroke'))]
        medical = "health-aspirin" in m["packet_path"]
        component_text = (f"Accepted findings mentioning bleeding: {', '.join(blood) or 'none'}; accepted findings mentioning cardiovascular topics: {', '.join(cardiovascular) or 'none'}. "
                          if medical else f"Accepted component findings: {', '.join(c['id'] for c in components) or 'none'}. ")
        lines.append(f"The main issue ends with **{state}**. Accepted main claims: {', '.join(c['id'] for c in accepted) or 'none'}. "
                     f"Formal load-bearing probes identify {('; '.join(lb[:12])) if lb else 'no single node whose removal changes the main claim status'}. "
                     f"Main-support applicability blockers: {('; '.join(blockers[:6])) if blockers else 'none recorded'}. "
                     + component_text
                     + ("The graph has no accepted composed answer to the main issue; accepted components alone do not establish the requested whole-question comparison." if not accepted else "The accepted main proposition is stated above and must be read at that recorded scope."))
    interpretation = Path("experiments/E6-generalisation/interpretation.md" if "generalisation" in str(report_path) else "experiments/E6/interpretation.md")
    if interpretation.exists():
        lines += ["", interpretation.read_text(encoding="utf-8").strip(), ""]
    lines += ["", "## Seven status labels (C6)", "",
              "Labels are derived from the saved evaluation without changing its compatible in/out/undecided proof statuses. Accepted means the proof standard is met; refuted means a contrary is accepted; defeated means every constructed supporting argument is out, withdrawn or inapplicable; contested requires standing pro and con support; unsupported means evidence without an argument; untested means no bearing evidence or constructed support.", "",
              "Insufficient means standing, unopposed support below the proof standard; unsupported means evidence without an argument. Insufficient support never earns a contested shape match. An expected undecided verdict requires an actual contested main answer. Each run includes claim-labels.json and labelled-summary.md; native metrics and state from earlier runs remain unchanged."]
    lines += ["", "## Review authority and limits", "",
              "The user's instruction to continue while asleep authorized separate provisional agent adjudication for N1. No Mamadou hand review is claimed; his blank file is preserved. N1 contains no same-claim cross-provider pairs, and E3.1's ≥70% against-Sol overlap has no valid denominator. E3.1's attack-count criterion was unmet and remains reported. N4's stated preconditions require that result recorded, not a fabricated pass.", "",
              "A passing per-run result requires zero supported-but-unargued claims, a nonempty accepted/supported main issue, no missing single-origin flags, no absence assertions and at least one reopened CQ discharged in Respond. Failure is retained. Costs are API-usage estimates; local raw replies, state snapshots and hash-chained ledgers remain alongside the compact metrics.", ""]
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "runs": [{"name": n, "pass": m['pass'], "cost_usd": m['cost_usd'], "error": m['error']} for n, _, m in runs]}))
    return True


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--generalisation", action="store_true")
    p.add_argument("--labels-only", action="store_true", help="Refresh only derived labels for all four saved E6 graphs.")
    args = p.parse_args()
    if args.labels_only:
        for folder in ("E6/sonnet", "E6/sol", "E6-generalisation/energy", "E6-generalisation/genai"):
            path = Path("experiments") / folder
            inq = Inquiry.model_validate_json((path / "inquiry.json").read_text(encoding="utf-8"))
            labels = {c.id: {"label": claim_status_label(inq.graph, inq.evaluation, c.id)[0],
                            "reason": claim_status_label(inq.graph, inq.evaluation, c.id)[1],
                            "status": inq.evaluation.status(c.id), "text": c.text,
                            "issue_id": c.issue_id, "answers_issue": c.answers_issue} for c in inq.graph.live_claims()}
            for cid, label in labels.items():
                inq.evaluation.claims[cid].label = label["label"]
                inq.evaluation.claims[cid].label_reason = label["reason"]
            (path / "claim-labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
            (path / "labelled-summary.md").write_text("Derived with C3 scope migration and C6 labels; historical state and metrics are unchanged.\n\n" + summary(inq.graph, inq.evaluation).rstrip() + "\n", encoding="utf-8")
            print(json.dumps({"folder": folder, "insufficient": [cid for cid, label in labels.items() if label["label"] == "insufficient"]}))
    elif args.generalisation:
        render([("Energy: Sol proposer", "experiments/E6-generalisation/energy"), ("GenAI: Sol proposer", "experiments/E6-generalisation/genai")],
               "bench/results/E6-generalisation.md", "E6 generalisation: fixed energy and GenAI packets")
    else:
        render([("Sonnet proposer", "experiments/E6/sonnet"), ("Sol proposer", "experiments/E6/sol")],
               "bench/results/E6.md", "E6: full fixed-evidence aspirin replay")
