"""E6/E7 comparison from local artifacts; pending experiments stay visibly pending."""
import json
from pathlib import Path

from inquiry.closure import whole_question_answer, answer_scope
from inquiry.state import Inquiry


def read_run(path):
    path = Path(path)
    if not (path / "metrics.json").exists():
        return None
    m = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
    state = path / "run/inquiry.json"
    if not state.exists():
        state = path / "inquiry.json"
    inq = Inquiry.model_validate_json(state.read_text(encoding="utf-8"))
    answer = whole_question_answer(inq.graph, inq.evaluation)
    m["whole_question_answered_derived"] = answer is not None
    m["answer_scope_derived"] = answer_scope(answer) if answer else ""
    m["answer_derived"] = f"{answer.id}: {answer.text}" if answer else "none"
    m["contract_corrections_derived"] = sum(n.startswith("contract repair in ") for n in inq.notes)
    return m, inq


def render():
    columns = [("E6 Sonnet", "experiments/E6/sonnet"), ("E6 Sol", "experiments/E6/sol"),
               ("E7 Sonnet", "experiments/E7/sonnet"), ("E7 Sol", "experiments/E7/sol")]
    runs = [(name, read_run(path)) for name, path in columns]
    fields = [
        ("rounds completed (limit 2 + capped review)", lambda m: m["rounds"]),
        ("sources / evidence", lambda m: f"{m['sources']} / {m['evidence']}"),
        ("supporting_original / supporting_scoped", lambda m: f"{m['supporting_original']} / {m['supporting_scoped']}"),
        ("applicable_original / applicable_scoped", lambda m: f"{m['applicable_original']} / {m['applicable_scoped']}"),
        ("attacks / reopened CQs / discharged", lambda m: f"{m['attacks']} / {m['reopened_cqs']} / {m['attacks_discharged']}"),
        ("reopened_then_discharged", lambda m: m["reopened_then_discharged"]),
        ("contract corrections (derived)", lambda m: m["contract_corrections_derived"]),
        ("main_supporting_in_original", lambda m: m["main_supporting_in_original"]),
        ("accepted main answer at stated scope (current closure rule)", lambda m: m["answer_derived"]),
        ("main issue scope label", lambda m: m.get("main_issue_scope_label", "historical; see derived labels")),
        ("undecided_empty / undecided_supported (native)", lambda m: f"{m['undecided_empty']} / {m['undecided_supported']}"),
        ("accepted component findings", lambda m: ", ".join(c["id"] for c in m["accepted_components"]) or "none"),
        ("composed_claims", lambda m: m.get("composed_claims", 0)),
        ("composition_accepted", lambda m: m.get("composition_accepted", 0)),
        ("whole_question_answered", lambda m: m.get("whole_question_answered", m["whole_question_answered_derived"])),
        ("answer_scope", lambda m: m.get("answer_scope", m["answer_scope_derived"]) or "none"),
        ("shape regex / judge", lambda m: f"{m.get('shape_match_regex')} / {m.get('shape_match_judge')}"),
        ("absence_assertions", lambda m: m["absence_assertions"]),
        ("claims_supported_unargued", lambda m: m["claims_supported_unargued"]),
        ("unflagged single-origin accepts", lambda m: m["single_origin_flag_missing"]),
        ("cost estimate USD / seconds", lambda m: f"{m['cost_usd']:.4f} / {m['seconds']:.1f}"),
        ("references / ledger", lambda m: f"{m['references_valid']} / {m['ledger_valid']}"),
        ("E6 structural gate / error", lambda m: f"{m['pass']} / {m['error']}"),
        ("stop reason", lambda m: m["stop_reason"]),
    ]
    pending = any(data is None for name, data in runs if name.startswith("E7"))
    manifest_path = Path("experiments/E7/manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    approved = bool(manifest.get("authorization"))
    scope_results = {name: json.loads(path.read_text(encoding="utf-8")) for name in ("sonnet", "sol")
                     if (path := Path("experiments/C3") / f"{name}.json").exists()}
    lines = ["# E7: whole-question closure on the fixed aspirin packet", "",
             ("Status: authorized; fixed-packet runs in progress." if approved else "Status: awaiting explicit approval for external model payloads.") if pending else "Status: both fixed-packet runs recorded.", "",
             "The planned runs use `runs/bench/health-aspirin-20261110-0209`, two rounds, at most one final composition review, opposite-provider critics and medium effort. Shared TONIGHT-3 caps include C3: $12 Anthropic and $8 OpenAI. No live retrieval, held-out question or Opus call is configured. Pricing uses the existing local snapshot, so costs are estimates.", "",
             "Predictions, recorded before calls: neither provider stops in round one; bleeding, mortality and nonfatal-event components are accepted; a main-issue composition at ASPREE's community-dwelling 70+ population and approximately five-year follow-up survives review. Expected direction is net harm, with code-satisfied same_scope, an answered commensurable CQ, and an explicit untested 60–69 gap. Expected whole_question_answered=true and absence_assertions=0. These predictions are not acceptance criteria enforced on model replies.", "",
             "E6 costs and native metrics remain historical. The accepted-answer and whole-question rows apply the new closure rule to the saved graph; they do not claim an E6 rerun.", "",
             "| Metric | " + " | ".join(name for name, _ in runs) + " |", "|---|" + "---|" * len(runs)]
    if not pending:
        aspirin = [data[0] for name, data in runs if name.startswith("E7")]
        observed = ("Observed: both aspirin runs reached two rounds and exhausted their round limit without a whole-question answer. "
                    "Neither constructed a composition, so answer_scope is empty and the predicted accepted 70+ answer did not occur. "
                    "Both recorded zero supported-but-unargued claims and zero absence assertions. "
                    "The live same_scope composition check and capped final review were not exercised; their passing tests are deterministic coverage only.")
        if all(m["rounds"] == 2 and not m["whole_question_answered"] and m["composed_claims"] == 0 for m in aspirin):
            lines[4:4] = [observed, ""]
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    for label, get in fields:
        lines.append("| " + label + " | " + " | ".join("not run" if data is None else cell(get(data[0])) for _, data in runs) + " |")
    for name, data in runs:
        if not name.startswith("E7"):
            continue
        lines += ["", "## " + name, ""]
        if data is None:
            lines.append("No completed E7 result is available yet. " + ("The user explicitly approved C3, both aspirin runs and optional Energy; execution uses the shared caps." if approved else "Explicit payload approval is pending.") + " No experimental result is inferred from the passing deterministic tests.")
            continue
        m, inq = data
        compositions = m.get("composition_details", [])
        if not compositions:
            lines.append("No composition was constructed. " + " ".join(m.get("cannot_compose", [])))
        for composition in compositions:
            claim = inq.graph.claim(composition["claim_id"])
            attacks = [a for a in inq.graph.arguments if a.is_attack
                       and a.attacks.target_id in (claim.id, composition["argument_id"])]
            lines.append(f"{claim.id}: {claim.text} Scope: {claim.scope.summary()}. Premises: {', '.join(composition['premise_claim_ids'])}; status {composition['status']}; same_scope {composition['cq']['same_scope']['outcome']}. Critic: "
                         + ("; ".join(f"{a.id} {a.attacks.type} ({inq.evaluation.labels.get(a.id, 'inapplicable')}): {a.note}; response={inq.response_dispositions.get(a.id, 'none')}" for a in attacks) if attacks else "no attack on the composed claim or argument recorded") + ".")
        if inq.conclusion:
            lines += ["", "Answer: " + inq.conclusion.answer]
        cross_scope = [(c.id, rival.id) for c in inq.main_claims() if not c.answers_issue
                       for rid in c.contrary_ids if (rival := inq.graph.claim(rid)) and rival.live and rival.answers_issue]
        if cross_scope:
            lines += ["", "Recorded limitation: component claims retain contrary links to broader candidates: "
                      + ", ".join(f"{c} → {r}" for c, r in cross_scope)
                      + ". Those links can refute broad candidates in the saved evaluation; they do not establish whole-question closure. The run is retained without tuning or rerunning from its result."]
    audit_path = Path("experiments/C3/legacy-answerhood-audit.json")
    lines += ["", "## C3 scope replays", ""]
    if not scope_results:
        lines.append("Not run; no C3 model call was sent. Explicit payload approval is pending.")
    for name, result in scope_results.items():
        lines.append(f"- {name}: fields_filled={result['fields_filled']}, estimated cost ${result['cost_usd']:.4f}; {len(result['apply']['claims']) if 'claims' in result['apply'] else len(result['claims'])} retained claims.")
    if scope_results and not all(result["fields_filled"] for result in scope_results.values()):
        lines += ["", "The original Sonnet scope replay failed field emission while Sol passed. The failure is retained. Before E7, commit ca7d1e6 made explicit scope fields mandatory for fresh model output, with the existing single contract-correction attempt; legacy graph loading stays compatible. No additional C3 replay was run."]
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        lines += ["", "## C3 compatibility audit", "", "Legacy scope migration is deterministic and conservative. These stored answerhood flags differ after migration; the saved inputs are unchanged:", ""]
        for folder, changes in audit.items():
            lines.append(f"- {folder}: " + (", ".join(f"{c['claim_id']} {c['stored']} → {c['derived']}" for c in changes) or "no changes"))
        lines += ["", "The four Energy main claims already store answers_issue=false; the audit preserves them. New frames supply typed scope fields rather than relying on migration of free text."]
    lines += ["", "## Optional E7-energy", "", "Prediction: cannot_compose names the missing no-new-gas counterfactual; the main issue remains unsupported and the attempted component chain is visible.", ""]
    energy = read_run("experiments/E7-energy/sol")
    if energy is None:
        lines.append("No completed Energy result is recorded. Sol proposer and Sonnet critic are authorized after the aspirin runs, subject to the shared budget.")
    else:
        m, inq = energy
        lines.append(f"Sol proposer / Sonnet critic: rounds={m['rounds']}, whole_question_answered={m['whole_question_answered']}, main scope={m['main_issue_scope_label']}, composed_claims={m['composed_claims']}, composition_accepted={m['composition_accepted']}, absence_assertions={m['absence_assertions']}, claims_supported_unargued={m['claims_supported_unargued']}, error={m['error']}; estimated cost ${m['cost_usd']:.4f}.")
        lines += ["", "Stop: " + m["stop_reason"], "", "Composition attempts: " + (" ".join(m.get("cannot_compose", [])) or "no cannot_compose explanation recorded")]
        for c in m.get("composition_details", []):
            claim = inq.graph.claim(c["claim_id"])
            lines.append(f"- {claim.id} ({c['status']}): {claim.text}; premises {c['premise_claim_ids']}; scope {claim.scope.summary()}")
        if inq.conclusion:
            lines += ["", "Answer: " + inq.conclusion.answer]
    ledger_path = Path("runs/tonight-3/budget.json")
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        lines += ["", "## Budget and provenance", "", f"Shared estimated spend: {ledger['spent']}; {len(ledger['pending'])} pending reservations; {len(ledger['calls'])} completed API requests. Opus reserve untouched. Each run records implementation commit, packet fingerprint, validated references and hash-chained ledger checks. Raw replies remain local."]
    path = Path("bench/results/E7.md")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(path), "pending": pending}))


if __name__ == "__main__":
    render()
