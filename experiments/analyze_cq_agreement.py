"""N1: audit saved CQ outcomes without model calls or semantic ID aliases.

Run: python -m experiments.analyze_cq_agreement
The human adjudication file is never overwritten with blank answers.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from inquiry.argument.evaluate import evaluate
from inquiry.argument.schemes import SCHEMES
from inquiry.replay_move import CQ_OUTCOMES, argue_diagnostics, cq_outcome_bucket, fingerprint, load_run


def root_claim(graph, claim_id):
    seen = set()
    claim = graph.claim(claim_id)
    while claim and claim.revision_of:
        if claim.id in seen:
            raise ValueError("claim revision cycle")
        seen.add(claim.id)
        claim = graph.claim(claim.revision_of)
    if claim is None:
        raise ValueError("claim lineage has an unknown parent")
    return claim.id


def question_rows(inq, metadata):
    ev, g = evaluate(inq.graph), inq.graph
    rows = []
    for argument in g.arguments:
        if argument.is_attack:
            continue
        claim = g.claim(argument.claim_id)
        for question in SCHEMES[argument.scheme].critical_questions:
            answer = argument.cq.get(question.id)
            rows.append({**metadata, "argument_id": argument.id, "premise_ids": sorted(set(argument.premise_ids)),
                "claim_id": claim.id, "claim_text": claim.text, "issue_id": claim.issue_id,
                "main_issue": claim.issue_id == g.main_issue_id, "answers_issue": claim.answers_issue,
                "root_claim_id": root_claim(g, claim.id), "revision_of": claim.revision_of,
                "claim_live": claim.live, "scheme": argument.scheme, "cq_id": question.id, "cq_kind": question.kind,
                "cq_text": question.text, "status": answer.status if answer else "open",
                "outcome": answer.outcome if answer else "", "bucket": cq_outcome_bucket(answer),
                "answer": answer.answer if answer else "", "evidence_ids": list(answer.evidence_ids) if answer else [],
                "argument_applicable": ev.applicable.get(argument.id, False), "withdrawn": argument.withdrawn,
                "inapplicable_reasons": ev.inapplicable_reasons.get(argument.id, [])})
    return rows


def match_arguments(sol, sonnet):
    """One-to-one exact keys first, then loose keys; ID collisions are explicit."""
    candidates, collisions = [], []
    for a in sol:
        for b in sonnet:
            if (a["claim_id"], a["scheme"]) != (b["claim_id"], b["scheme"]):
                continue
            if a["claim_text"] != b["claim_text"] or a["issue_id"] != b["issue_id"] or a["answers_issue"] != b["answers_issue"]:
                collisions.append({"sol": a["argument_id"], "sonnet": b["argument_id"], "claim_id": a["claim_id"],
                                   "reason": "same ordinal has different claim meaning or answerhood role"})
                continue
            exact = set(a["premise_ids"]) == set(b["premise_ids"])
            union = set(a["premise_ids"]) | set(b["premise_ids"])
            overlap = len(set(a["premise_ids"]) & set(b["premise_ids"])) / max(1, len(union))
            candidates.append((not exact, -overlap, a["argument_id"], b["argument_id"], a, b))
    used_sol, used_sonnet, matches = set(), set(), []
    for loose, _, aid, bid, a, b in sorted(candidates, key=lambda x: x[:4]):
        if aid in used_sol or bid in used_sonnet:
            continue
        used_sol.add(aid)
        used_sonnet.add(bid)
        matches.append({"kind": "loose_premises" if loose else "exact", "sol": a, "sonnet": b})
    return matches, collisions


def compare_rows(matches, rows_sol, rows_sonnet):
    lookup_sol = {(r["argument_id"], r["cq_id"]): r for r in rows_sol}
    lookup_sonnet = {(r["argument_id"], r["cq_id"]): r for r in rows_sonnet}
    comparisons = []
    for match in matches:
        for question in SCHEMES[match["sol"]["scheme"]].critical_questions:
            a = lookup_sol[(match["sol"]["argument_id"], question.id)]
            b = lookup_sonnet[(match["sonnet"]["argument_id"], question.id)]
            comparisons.append({"match_kind": match["kind"], "cq_id": question.id, "cq_kind": question.kind,
                                "scheme": a["scheme"], "sol": a, "sonnet": b,
                                "disagree": a["bucket"] != b["bucket"],
                                "raw_status_outcome_differ": (a["status"], a["outcome"]) != (b["status"], b["outcome"])})
    return comparisons


def lineage_contrasts(rows_sol, rows_sonnet):
    """Supplemental review candidates; these are never counted as matched disagreements."""
    candidates = []
    for a in rows_sol:
        for b in rows_sonnet:
            if (a["root_claim_id"], a["scheme"], a["cq_id"]) != (b["root_claim_id"], b["scheme"], b["cq_id"]):
                continue
            shared = sorted(set(a["premise_ids"]) & set(b["premise_ids"]))
            if (not shared or a["bucket"] == b["bucket"] or a["withdrawn"] or b["withdrawn"]
                    or a["claim_text"] == b["claim_text"]):
                continue
            candidates.append({"match_kind": "lineage_contrast_different_claims", "comparable_as_same_claim": False,
                               "cq_id": a["cq_id"], "cq_kind": a["cq_kind"], "scheme": a["scheme"],
                               "shared_premises": shared, "sol": a, "sonnet": b})
    return candidates


def priority(case):
    a, b = case["sol"], case["sonnet"]
    main = a["main_issue"] and b["main_issue"]
    population = a["scheme"] == "study_result" and a["cq_id"] == "directness"
    return (not (main and population), not main, not population, a["cq_kind"] != "assumption",
            a["argument_applicable"] == b["argument_applicable"],
            b["bucket"] != "unsatisfied", -len(set(a["premise_ids"]) & set(b["premise_ids"])),
            a["sample"], a["argument_id"], b["argument_id"], a["cq_id"])


def review_case(case, graphs):
    a, b = case["sol"], case["sonnet"]
    evidence_ids = sorted(set(a["premise_ids"] + b["premise_ids"] + a["evidence_ids"] + b["evidence_ids"]))
    g = graphs[("openai", a["sample"])].graph
    evidence = []
    for eid in evidence_ids:
        item = g.ev(eid)
        if item:
            source = g.source(item.source_id) if item.source_id else None
            evidence.append({"id": eid, "text": item.text, "quote": item.quote, "source_id": item.source_id,
                             "source_title": source.title if source else "", "location": item.location})
    identity = {"sol_graph": a["graph_sha256"], "sonnet_graph": b["graph_sha256"],
                "sol_argument": a["argument_id"], "sonnet_argument": b["argument_id"], "cq_id": a["cq_id"]}
    def answer(row):
        return {k: row[k] for k in ("status", "outcome", "bucket", "answer", "evidence_ids", "argument_applicable", "inapplicable_reasons")}
    def argument(row):
        return {k: row[k] for k in ("provider", "model", "effort", "sample", "argument_id", "premise_ids", "claim_id", "claim_text",
                                   "root_claim_id", "revision_of", "issue_id", "main_issue", "answers_issue", "graph", "graph_sha256")}
    return {"case_id": fingerprint(identity)[:16], "comparison_kind": case["match_kind"],
            "comparable_as_same_claim": case["match_kind"] in ("exact", "loose_premises"),
            "argument": {"scheme": a["scheme"], "sol": argument(a), "sonnet": argument(b)},
            "cq_id": a["cq_id"], "cq_kind": a["cq_kind"], "cq_text": a["cq_text"],
            "sol_answer": answer(a), "sonnet_answer": answer(b), "evidence_ids": evidence_ids, "evidence": evidence,
            "adjudication": "", "note": ""}


def write_adjudication(path, payload):
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        old = {c["case_id"]: c for c in previous["cases"]}
        current = {c["case_id"] for c in payload["cases"]}
        if any((c.get("adjudication") or c.get("note")) and cid not in current for cid, c in old.items()):
            raise ValueError("refusing to discard a human adjudication for a changed review case")
        for case in payload["cases"]:
            if case["case_id"] in old:
                case["adjudication"] = old[case["case_id"]].get("adjudication", "")
                case["note"] = old[case["case_id"]].get("note", "")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extend_saved_metrics(root):
    """Add diagnostics without changing native totals, raw replies or graphs."""
    extensions = {}
    for path in sorted(root.glob("*/*/*/moves.json")):
        native = json.loads(path.read_text(encoding="utf-8"))
        if native.get("move") != "argue":
            continue
        for sample in native["samples"]:
            graph = path.parent / sample["graph"]
            if fingerprint(json.loads(graph.read_text(encoding="utf-8"))) != sample["graph_sha256"]:
                raise ValueError(f"saved graph fingerprint changed: {graph}")
            inq, _ = load_run(graph)
            sample["metrics"].update(argue_diagnostics(inq))
        native["metrics_extensions"] = {**native.get("metrics_extensions", {}), "N1": {
            "fields": ["inapplicable_reasons", "cq_outcomes", "cq_outcomes_by_kind", "cq_outcome_details"],
            "method": "Read-only rescore of saved graphs; native totals, costs and graph hashes unchanged"}}
        path.write_text(json.dumps(native, indent=2) + "\n", encoding="utf-8")
        extensions[(path.parent.parent.name, path.parent.name, path.parent.parent.parent.name)] = native
    analysis_path = root / "analysis.json"
    if analysis_path.exists():
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        for cell in analysis["cells"]:
            name = "sol" if cell["provider"] == "openai" else "sonnet"
            native = extensions.get((cell["claims"], name, cell["version"]))
            if native:
                cell["samples"] = native["samples"]
        analysis["metrics_extensions"] = ["N1: inapplicable reasons and CQ outcomes; native numeric totals unchanged"]
        analysis_path.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")


def analyze(root=Path("experiments/E2"), *, update_metrics=True, autonomous_continuation=False):
    root = Path(root)
    graphs, rows, inputs = {}, [], []
    for name in ("sol", "sonnet"):
        manifest_path = root / "after/h1-claims" / name / "moves.json"
        native = json.loads(manifest_path.read_text(encoding="utf-8"))
        if len(native["samples"]) != 3 or any(s["error"] for s in native["samples"]):
            raise ValueError(f"need three successful saved samples: {manifest_path}")
        for sample in native["samples"]:
            path = manifest_path.parent / sample["graph"]
            if not path.exists():
                raise FileNotFoundError(f"saved graph missing: {path}; rerun only this provider cell before analysis")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if fingerprint(raw) != sample["graph_sha256"]:
                raise ValueError(f"saved graph fingerprint changed: {path}")
            inq, _ = load_run(path)
            if inq.graph.validate_refs():
                raise ValueError(f"invalid graph references: {path}")
            metadata = {k: sample[k] for k in ("provider", "model", "effort", "sample", "graph_sha256")}
            metadata["graph"] = str(path)
            graphs[(sample["provider"], sample["sample"])] = inq
            inputs.append(metadata)
            rows.extend(question_rows(inq, metadata))
    matches, comparisons, collisions, contrasts, pairing = [], [], [], [], []
    for sol_sample in range(1, 4):
        for sonnet_sample in range(1, 4):
            a = [r for r in rows if r["provider"] == "openai" and r["sample"] == sol_sample]
            b = [r for r in rows if r["provider"] == "anthropic" and r["sample"] == sonnet_sample]
            aa = list({r["argument_id"]: r for r in a if not r["withdrawn"]}.values())
            bb = list({r["argument_id"]: r for r in b if not r["withdrawn"]}.values())
            matched, rejected = match_arguments(aa, bb)
            matches.extend(matched)
            collisions.extend(dict(item, sol_sample=sol_sample, sonnet_sample=sonnet_sample) for item in rejected)
            comparisons.extend(compare_rows(matched, a, b))
            if sol_sample == sonnet_sample:
                contrasts.extend(lineage_contrasts(a, b))
            pairing.append({"sol_sample": sol_sample, "sonnet_sample": sonnet_sample,
                            "sol_arguments": len(aa), "sonnet_arguments": len(bb),
                            "exact_matches": sum(m["kind"] == "exact" for m in matched),
                            "loose_matches": sum(m["kind"] == "loose_premises" for m in matched), "id_collisions": len(rejected)})
    disagreements = [c for c in comparisons if c["disagree"]]
    candidates = sorted(disagreements, key=priority)
    supplemental = sorted(contrasts, key=priority)
    selected = candidates[:10]
    # No matched disagreements must never become an invented agreement rate.
    # Separately labelled lineage contrasts give the human useful scope checks.
    selected += supplemental[:max(0, 10 - len(selected))]
    cases = [review_case(case, graphs) for case in selected]
    counts = {}
    rates = {}
    for kind in ("assumption", "exception"):
        counts[kind] = {p: {bucket: sum(r["provider"] == p and not r["withdrawn"] and r["cq_kind"] == kind and r["bucket"] == bucket for r in rows)
                            for bucket in CQ_OUTCOMES} for p in ("openai", "anthropic")}
        questions = sorted({(r["scheme"], r["cq_id"]) for r in rows if r["cq_kind"] == kind})
        rates[kind] = []
        for scheme, qid in questions:
            compared = [c for c in comparisons if (c["scheme"], c["cq_id"], c["cq_kind"]) == (scheme, qid, kind)]
            rates[kind].append({"scheme": scheme, "cq_id": qid, "compared": len(compared),
                                "disagreements": sum(c["disagree"] for c in compared),
                                "rate": sum(c["disagree"] for c in compared) / len(compared) if compared else None})
    paired_contingency = {kind: {a: {b: sum(c["cq_kind"] == kind and c["sol"]["bucket"] == a and c["sonnet"]["bucket"] == b for c in comparisons)
                                    for b in CQ_OUTCOMES} for a in CQ_OUTCOMES} for kind in ("assumption", "exception")}
    result = {"item": "N1", "model_calls": 0, "inputs": inputs, "records": len(rows), "sample_pairing": pairing,
              "method": "All nine cross-provider sample pairings; exact claim_id/scheme/premise set, then one-to-one claim_id/scheme with maximum premise overlap within each sample pairing. Different claim text, issue or answerhood role rejects an ordinal collision. Graphs are reused across pairings; these are not nine independent observations. Supplemental lineage contrasts use only same-index pairs.",
              "buckets": "answered+satisfied (or legacy empty)=satisfied; unsatisfied=unsatisfied; defaulted=defaulted; open or answered+unresolved=open. Raw status/outcome are exported unchanged.",
              "outcome_counts": counts, "paired_contingency": paired_contingency, "per_cq_rates": rates,
              "matched_argument_pairs": len(matches), "matched_cq_pairs": len(comparisons), "comparisons": comparisons,
              "disagreements": disagreements, "rejected_id_collisions": collisions,
              "diagnostic_lineage_contrasts": contrasts, "original_brief_human_gate": True,
              "human_adjudication_required_before_N2": not autonomous_continuation,
              "autonomous_continuation_authorized": autonomous_continuation}
    review = {"item": "N1", "status": "awaiting_mamadou", "matched_disagreements_available": len(disagreements),
              "diagnostic_contrasts_available": len(contrasts), "instructions": [
                  "Fill adjudication and note for each case, leaving factual records unchanged.",
                  "No same-claim argument matches exist in these six graphs. Lineage-linked contrasts are not same-claim disagreements.",
                  "Judge each CQ answer against that provider's stated conclusion and premises; both answers may be appropriate at different scopes.",
                  "Use sol_inadequate, sonnet_overstrict, both_scope_appropriate, neither, or not_comparable, with an explanation in note.",
                  ("The user subsequently authorized autonomous continuation while asleep; a separate, explicitly agent-authored provisional review is used for execution. This file remains blank for later human review."
                   if autonomous_continuation else "Do not proceed to N2/E3.1 or E6 until Mamadou has adjudicated these cases.")],
              "selection": "Matched disagreements first; then explicitly labelled source-overlapping, same-index lineage contrasts. Prefer main-issue study_result/directness, other main-issue questions, study_result/directness, and applicability differences.",
              "catalogue_note": "study_result uses directness for population/setting/intervention/outcome alignment; there are no separate population or outcome CQ IDs.",
              "cases": cases}
    write_adjudication(root / "cq_adjudication.json", review)
    (root / "cq_records.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    (root / "cq_agreement.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# N1: critical-question outcome agreement", "",
             ("**Human review deferred by the user's instruction to continue while asleep.** The separate cq_adjudication_provisional.json is agent-authored; the human review file stays blank."
              if autonomous_continuation else "**Awaiting Mamadou's hand adjudication before N2.**")
             + " All six saved graphs are present and verified; no model calls or retrieval were needed.", "",
             f"There are **{len(matches)} comparable argument pairs and {len(comparisons)} matched CQ pairs** under the requested exact/loose keys. Sol chiefly argues scoped revisions; Sonnet chiefly argues the original claims. Provider outcome distributions therefore do not measure agreement on the same inference. A zero denominator is reported as n/a, never as zero disagreement.", "",
             "All nine cross-provider sample pairings are searched, so the result does not depend on pairing samples by index. The same six independent graphs are reused; these are not nine independent observations. Exact matches use claim ID, scheme and sorted premise set. Loose matches retain claim ID/scheme and maximize premise overlap one-to-one within each sample pairing. Claim meanings and answerhood roles must also match. Every supporting argument/CQ, including any withdrawn support, is exported in cq_records.jsonl; active support is used for metrics and tables.", "",
             "| Sol sample | Sonnet sample | Sol arguments | Sonnet arguments | Exact pairs | Loose pairs | Rejected ordinal collisions |", "|---|---|---:|---:|---:|---:|---:|"]
    for item in pairing:
        lines.append("| " + " | ".join(str(item[k]) for k in ("sol_sample", "sonnet_sample", "sol_arguments", "sonnet_arguments", "exact_matches", "loose_matches", "id_collisions")) + " |")
    for kind in ("assumption", "exception"):
        lines += ["", f"## {kind.title()} outcomes", "", "| Outcome | OpenAI gpt-6.1-sol (medium) | Anthropic claude-sonnet-5-5 (medium) |", "|---|---:|---:|"]
        for bucket in CQ_OUTCOMES:
            lines.append(f"| {bucket} | {counts[kind]['openai'][bucket]} | {counts[kind]['anthropic'][bucket]} |")
        lines += ["", "| Scheme | CQ ID | Matched pairs | Disagreements | Disagreement rate |", "|---|---|---:|---:|---:|"]
        for item in rates[kind]:
            rate = f"{item['rate']:.1%}" if item["rate"] is not None else "n/a"
            lines.append(f"| {item['scheme']} | {item['cq_id']} | {item['compared']} | {item['disagreements']} | {rate} |")
    unresolved = Counter(r["provider"] for r in rows if r["status"] == "answered" and r["outcome"] == "unresolved")
    lines += ["", f"The four requested buckets classify answered-but-unresolved as open: Sol {unresolved['openai']}, Sonnet {unresolved['anthropic']}. Their raw answered/unresolved values remain in the records and cq_outcome_details. Exceptions left open are not failed assumptions and are tabulated separately. Rates are broken down by scheme as well as CQ ID to avoid conflating identically named questions.", "",
              "## Matched disagreements and human review", "",
              "No matched disagreements are available. The complete paired outcome contingency matrices contain no observations and are saved in cq_agreement.json. The ten cases in cq_adjudication.json are explicitly labelled lineage-linked diagnostic contrasts, not matched disagreements. They share an original claim ancestor and at least one premise, use the same scheme/CQ, and record different outcomes for different conclusions. Both conclusions, answer texts, checked evidence and source quotations are included.", "",
              "There are no main-issue study_result lineage pairs: Sonnet's main-issue arguments use document_record. The catalogue's directness question combines population and outcome checks. The selection therefore includes available main-issue record-reading contrasts and component study_result/directness contrasts.", "",
              "| Case | Sample | Sol argument/claim | Sonnet argument/claim | Original ancestor | Scheme / CQ | Sol → Sonnet |", "|---|---:|---|---|---|---|---|"]
    for index, case in enumerate(cases, 1):
        a, b = case["argument"]["sol"], case["argument"]["sonnet"]
        lines.append(f"| {index} ({case['case_id']}) | {a['sample']} | {a['argument_id']} / {a['claim_id']} | {b['argument_id']} / {b['claim_id']} | {a['root_claim_id']} | {case['argument']['scheme']} / {case['cq_id']} | {case['sol_answer']['bucket']} → {case['sonnet_answer']['bucket']} |")
    lines += ["", "Fill each case's blank adjudication and note. In particular, a satisfied answer for a source-scoped result and an unsatisfied answer for the original all-adults claim can both be appropriate. These distributions alone cannot establish Sol self-certification or Sonnet over-strictness. Human review must evaluate Sol's actual narrower conclusion, not silently substitute the original claim.", "",
              "## Move metrics", "",
              "Argue now emits inapplicable_reasons (open:<cq_id>, unsatisfied:<cq_id>, premise_claim_not_accepted) and cq_outcomes per provider/sample, with assumption/exception splits and answered-unresolved details. Histograms count reason occurrences, so one inapplicable argument can contribute more than one reason. Saved E2 metrics are extended from local graphs; existing totals, costs, prompts and graph files remain unchanged. Inference and applicability rules are unchanged.", "",
              "N1 spend: **$0**, with the Opus reserve untouched. At the N1 checkpoint, N2–N6 have not started. The original brief says: “Stop and ask him to fill it before N2.”"
              + (" The subsequent instruction, “i will be asleep. i need tou to move forward,” authorizes provisional agent adjudication and continuation; it is not recorded as Mamadou's hand adjudication." if autonomous_continuation else ""), ""]
    (root / "cq_agreement.md").write_text("\n".join(lines), encoding="utf-8")
    if update_metrics:
        extend_saved_metrics(root)
    print(json.dumps({"graphs": len(inputs), "cq_records": len(rows), "matched_arguments": len(matches),
                      "matched_disagreements": len(disagreements), "lineage_contrasts": len(contrasts), "review_cases": len(cases), "model_calls": 0}))
    return result, review


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments/E2"))
    parser.add_argument("--no-update-metrics", action="store_true")
    parser.add_argument("--autonomous-continuation", action="store_true")
    args = parser.parse_args()
    analyze(args.root, update_metrics=not args.no_update_metrics, autonomous_continuation=args.autonomous_continuation)
