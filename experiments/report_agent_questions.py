"""Summarize recorded bare-question runs without supplying expected answers."""
import hashlib
import json
from pathlib import Path

from experiments.run_agent_questions import ROOT, LEDGER, questions
from inquiry import moves
from inquiry.argument.evaluate import argument_origins
from inquiry.state import Inquiry
from inquiry.store import InquiryStore


def render():
    rows, audit = [], []
    for row in questions():
        path = ROOT / row["id"]
        if not (path / "metrics.json").exists():
            rows.append((row, None, None))
            continue
        m = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
        inq = Inquiry.model_validate_json((path / "inquiry.json").read_text(encoding="utf-8"))
        store = InquiryStore(path, "run")
        calls = {role: json.loads((path / f"{role}-responses.json").read_text(encoding="utf-8"))
                 for role in ("proposer", "critic")}
        frame = next((c for c in calls["proposer"] if c["system"].startswith("# SKILL: frame")), None)
        bare_view = moves.frame_view(Inquiry(id=row["id"], question=row["question"]))
        checks = {"question_exact": inq.question == row["question"],
                  "initial_frame_is_bare_question": bool(frame) and frame["user"] == bare_view,
                  "no_expected_answer_judge": not any(c["system"].startswith("# SKILL: shape_judge") for role in calls for c in calls[role]),
                  "references": not inq.graph.validate_refs(), "ledger": store.verify_ledger(),
                  "state_anchor": store.events()[-1]["state_hash"] == hashlib.sha256(inq.model_dump_json().encode()).hexdigest(),
                  "api_call_count": sum(len(v) for v in calls.values()) == m["api_calls"]}
        cost = {provider: sum(c["cost_usd"] or 0 for role in calls
                 if m["config"]["models"][role].startswith(provider + ":") for c in calls[role])
                for provider in m["cost_by_provider"]}
        checks["costs_reconcile"] = all(abs(cost[p] - m["cost_by_provider"][p]) < 1e-8 for p in cost)
        audit.append({"id": row["id"], "checks": checks, "all_pass": all(checks.values()),
                      "phase": m["phase"], "error": m["error"]})
        rows.append((row, m, inq))
    lines = ["# Six bare-question live inquiries — 2026-11-12", "",
        "Only the six question texts were supplied. The surrounding situations, expected outcomes and action notes were excluded, including from scoring. Each inquiry uses the standard live Harness, a two-round limit, Sol proposer / Sonnet critic at medium effort, SerperSearch, HttpFetcher and the default Europe PMC recall path. No Opus or held-out benchmark question is run. The harness implementation is unchanged during these runs.", "",
        "These are recorded harness results rather than independently adjudicated ground truth. Dates, scopes, origin flags, gaps and execution failures remain visible. Costs use the repository's price snapshot and exclude separately billed search-service charges.", "",
        "The requested-scope label aggregates live candidate-claim labels; it does not by itself establish that the whole question was answered. Source/origin counts are the harness's source identity keys. Per-claim origin groups and corroboration flags below expose the recorded proof lineage without asserting that those classifications are correct.", "",
        "| Question | Completed rounds | Whole question answered | Requested-scope label | Sources/origins | Accepted components | Single-origin flags | Supported/unargued | Absence assertions | Est. USD | Error |",
        "|---|---:|---|---|---|---:|---:|---:|---:|---:|---|"]
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    for row, m, inq in rows:
        if m is None:
            lines.append(f"| {row['id']} | pending | | | | | | | | | |")
        else:
            lines.append("| " + " | ".join(map(cell, [row["id"], m["rounds_completed"], m["whole_question_answered"],
                m["main_issue_scope_label"], f"{m['sources']}/{m['origins']}", m["components_accepted"], m["single_origin_accepts"],
                m["claims_supported_unargued"], m["absence_assertions"], f"{m['cost_usd']:.4f}", m["error"]])) + " |")
    for row, m, inq in rows:
        lines += ["", f"## {row['id']}", "", row["question"], ""]
        if m is None:
            lines.append("Pending.")
            continue
        lines.append(f"Phase: {m['phase']}; rounds entered/completed: {m['rounds']}/{m['rounds_completed']}; implementation `{m['implementation_commit']}`.")
        lines += ["", inq.conclusion.answer if inq.conclusion else "No conclusion was produced.", "",
                  f"Stop assessment: {m['stop_reason'] or 'none recorded'}. Error: {m['error']}.", "",
                  "Accepted findings:", ""]
        accepted = m["accepted_main_claims"] + m["accepted_components"]
        single_flags = {flag.node_id for flag in inq.evaluation.flags if flag.code == "single_origin"}
        for c in accepted:
            detail = inq.evaluation.claims[c["id"]]
            routes = {aid: sorted(argument_origins(inq.graph, inq.graph.arg(aid), labels=inq.evaluation.labels))
                      for aid in detail.pro_ids}
            lines.append(f"- {c['id']}: {c['text']} Scope: {json.dumps(c['scope'], ensure_ascii=False)} "
                         f"Proof: pro strength={detail.pro_strength}, corroborated={detail.corroborated}, "
                         f"single-origin flag={c['id'] in single_flags}; argument origins={json.dumps(routes, ensure_ascii=False)}.")
        if not accepted:
            lines.append("- None.")
        lines += ["", "Issue and claim labels:", ""]
        for issue in m["issue_results"]:
            labels = "; ".join(f"{c['id']} {c['label']}" + (" (component)" if not c["answers_issue"] else "") for c in issue["claims"])
            lines.append(f"- {issue['id']}: {issue['text']} — {labels or 'no live claims'}")
        lines += ["", "Retrieved sources and origins:", ""]
        for src in m["sources_detail"]:
            lines.append(f"- {src['id']} [{src['title'] or src['url']}]({src['url']}) — {src['kind']}; source date {src['date'] or 'unstated'}; fetched {src['fetched_at']}; origin `{src['origin']}`; derived_from={src['derived_from']}; cached text fully appraised={src['read_fully']}.")
        if not m["sources_detail"]:
            lines.append("- None retained.")
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else {"spent": {}, "pending": {}, "calls": []}
    complete = len(audit) == 6
    recorded = [m for _, m, _ in rows if m is not None]
    costs_match = all(abs(sum(m["cost_by_provider"].get(provider, 0) for m in recorded) - spent) < 1e-8
                      for provider, spent in ledger["spent"].items()) if complete else None
    summary = {"complete": complete,
        "all_runs_concluded": complete and all(m["phase"] == "concluded" and m["error"] is None for m in recorded),
        "all_input_and_artifact_checks_pass": complete and all(r["all_pass"] for r in audit),
        "whole_question_answered": [row["id"] for row, m, _ in rows if m is not None and m["whole_question_answered"]],
        "partial_or_unanswered": [row["id"] for row, m, _ in rows if m is not None and not m["whole_question_answered"]],
        "cost_by_provider": ledger["spent"], "cost_usd": sum(ledger["spent"].values()),
        "costs_reconcile": costs_match,
        "api_calls_reconcile": sum(m["api_calls"] for m in recorded) == len(ledger["calls"]) if complete else None,
        "api_calls": len(ledger["calls"]), "pending_reservations": len(ledger["pending"]),
        "per_question": [{"id": row["id"], "rounds_completed": m["rounds_completed"], "cost_usd": m["cost_usd"],
                          "whole_question_answered": m["whole_question_answered"], "error": m["error"]}
                         for row, m, _ in rows if m is not None]}
    spend = "; ".join(f"{p} ${value:.4f}" for p, value in ledger["spent"].items())
    lines += ["", "## Cost and input audit", "", f"Estimated model spend: {spend}; total ${sum(ledger['spent'].values()):.4f}; {len(ledger['pending'])} pending reservations; {len(ledger['calls'])} completed model requests.",
              "", f"Recorded input/artifact integrity checks: {sum(r['all_pass'] for r in audit)}/{len(audit)} pass. Full calls and search/fetch artifacts remain local.", ""]
    report = Path("bench/results/agent-questions-20261112.md")
    report.write_text("\n".join(lines), encoding="utf-8")
    (ROOT / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    (ROOT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report), "recorded": len(audit), "pending": 6 - len(audit),
                      "integrity_pass": all(r["all_pass"] for r in audit), "spent": ledger["spent"]}))


if __name__ == "__main__":
    render()
