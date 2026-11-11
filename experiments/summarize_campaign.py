"""Audit saved campaign artifacts and write the final report; never calls a model."""
import json
from pathlib import Path

from inquiry.experiment_budget import ExperimentBudget
from inquiry.replay_move import fingerprint, load_run


def summarize():
    root = Path("experiments")
    analyses = {e: json.loads((root / e / "analysis.json").read_text(encoding="utf-8")) for e in ("E1", "E2", "E3", "E4", "E5")}
    totals, failures, audit = {}, [], []
    for path in sorted(root.rglob("moves.json")):
        experiment = path.relative_to(root).parts[0]
        if experiment not in analyses:
            continue
        native = json.loads(path.read_text(encoding="utf-8"))
        group = totals.setdefault(experiment, {"samples": 0, "api_calls": 0, "tokens_in": 0, "tokens_out": 0,
                                                "cost_usd": {"anthropic": 0.0, "openai": 0.0}})
        for sample in native["samples"]:
            source = path.parent / sample["graph"]
            data = json.loads(source.read_text(encoding="utf-8"))
            assert fingerprint(data) == sample["graph_sha256"], f"graph changed: {source}"
            inq, _ = load_run(source)
            assert not inq.graph.validate_refs(), f"invalid references: {source}"
            assert sample["provider"] in ("openai", "anthropic") and sample["model"] and sample["effort"] == "medium"
            assert sample["cost_usd"] is not None
            group["samples"] += 1
            group["api_calls"] += sample["api_calls"]
            group["tokens_in"] += sample["tokens_in"]
            group["tokens_out"] += sample["tokens_out"]
            group["cost_usd"][sample["provider"]] += sample["cost_usd"]
            if sample["error"]:
                failures.append({"manifest": str(path), "sample": sample["sample"], "error": sample["error"]})
            audit.append({"graph": str(source), "graph_sha256": sample["graph_sha256"], "references_valid": True})
    ledger = ExperimentBudget(root / "budget.json", {}).status()
    assert not ledger["pending"], "a model request is still pending"
    costs = {p: sum(t["cost_usd"][p] for t in totals.values()) for p in ("anthropic", "openai")}
    for provider, usd in costs.items():
        assert abs(usd - ledger["spent"].get(provider, 0)) < 1e-7, f"cost reconciliation failed: {provider}"
    assert sum(t["api_calls"] for t in totals.values()) == len(ledger["calls"])
    gate = {"status": "not_run", "e1_pass": analyses["E1"]["pass"], "e2_pass": analyses["E2"]["pass"],
            "full_run_allowed": analyses["E1"]["pass"] and analyses["E2"]["pass"],
            "reason": "E1 raw specificity gate failed on one Sonnet aspirin sample; both E1 and E2 are required.",
            "sonnet_full_run": "not_run", "sol_full_run": "not_run", "opus_full_run": "not_run",
            "opus_condition": "Sonnet must first pass its E6 full run", "anthropic_opus_reserve_usd": 20,
            "held_out_runs": 0, "live_full_harness_runs": 0,
            "metrics_ready": ["claims_supported_unargued", "main_supporting_in", "main_component_supporting_in", "undecided_empty", "undecided_supported"],
            "validation": "125 local tests passed, including empty, supported, withdrawn and component-only main-answer cases"}
    assert not gate["full_run_allowed"], "the campaign gate changed; reassess E6 before reporting it skipped"
    (root / "E6").mkdir(exist_ok=True)
    (root / "E6/gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    result = {"providers": [{"provider": "openai", "model": "gpt-6.1-sol", "effort": "medium"},
                            {"provider": "anthropic", "model": "claude-sonnet-5-5", "effort": "medium"}],
              "gates": {e: a["pass"] for e, a in analyses.items()}, "E6": gate,
              "totals": totals, "estimated_cost_usd": costs, "cost_reconciled": True,
              "api_calls": len(ledger["calls"]), "failed_samples": failures, "graph_audit": audit,
              "limits_usd": {"anthropic": 50, "openai": 16}, "protected_opus_reserve_usd": 20,
              "tests_passed": 125}
    (root / "campaign.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    e2 = [c for c in analyses["E2"]["cells"] if c["claims"] == "h1-claims"]
    lines = ["# Move experiments: two providers, fixed graphs", "",
             "E2, E4 and E5 pass their stated gates. E1's raw specificity gate and E3's attack-count gate fail. E6 was therefore skipped, including Opus. No held-out question or live full-harness run was made during this campaign.", "",
             "Both providers use medium effort: `openai:gpt-6.1-sol` and `anthropic:claude-sonnet-5-5`. Every sample records provider, model, effort, usage, cost estimate, graph hash and errors. All costs below are usage estimates, not invoice totals.", "",
             "| Experiment | Result | Evidence |", "|---|---|---|",
             "| [E1](../../experiments/E1/report.md) | Fail | All final retained claims pass the code guard and retain nulls per issue. One of three final-candidate Sonnet aspirin raw proposals still invented an endpoint recipe. The other 11 final-candidate samples pass. |",
             "| [E2](../../experiments/E2/report.md) | Pass | All 36 samples complete; H1 + H2 has zero supported-but-unargued claims and unusable share below 30% on both providers. |",
             "| [E3](../../experiments/E3/report.md) | Fail | Applicable attacks average 2.00–4.33 across the four critic/proposer cells. Only one sample reaches six; the five-attack condition is not met on both. Needs were manually tagged. |",
             "| [E4](../../experiments/E4/report.md) | Pass | Final candidate answers every standing attack; all concessions have validated CQ/check/reason records; mean defenses exceed concessions on both providers. |",
             "| [E5](../../experiments/E5/report.md) | Pass | Grade D is extracted in all six guarded samples and 100% of retained quotes verify on both providers. Direction agreement is reported separately. |",
             "| [E6](../../experiments/E6/gate.json) | Skipped | E1 and E2 must both pass. The $20 Anthropic Opus reserve remains unused. Requested full metrics are implemented and tested locally. |", "",
             "## What changed", "",
             "The infrastructure replays one move from a deterministic saved-state projection, with no retrieval. H1 rejects claims above 250 characters, above eight digits, or with detected unrequested protocol details; it allows one correction, then drops failures. Frame and the Hypothesize view use source-based answerhood. Five H1 candidates were tested on both providers and both frames; failures were retained rather than hidden by post-guard metrics.", "",
             "H2 caps per-evidence unusable dispositions, requests one coverage correction, requires an argument or claim-level reason for covered claims, and installs narrower revisions only with an argument. Component findings cannot defeat whole-issue answers through inherited rivalry. Evidence directions were explicitly reviewed against the 22 Claude claims and the 17 selected H1 claims; old claim ordinals were never treated as meanings.", "",
             "E2(b) ran first: replacing the original claims with Claude's claims left Sol at one supporting argument per sample. H1's simpler claims alone partially recover coverage; H2 further improves it. Within each before/after pair, graph and framing fingerprints match. Across claim sets, the reviewed directions and associated issues also change, so wording alone is not isolated.", "",
             "| H1 claim set | Provider | Supporting, mean | Applicable, mean | Unargued, mean | Unusable share, mean |",
             "|---|---|---:|---:|---:|---:|"]
    for c in e2:
        a = c["aggregate"]
        lines.append(f"| {c['version']} H2 | {c['provider']}:{c['model']} | {a['supporting_args']['mean']:.2f} | {a['applicable_args']['mean']:.2f} | {a['claims_supported_unargued']['mean']:.2f} | {a['unusable_share']['mean']:.1%} |")
    lines += ["", "Sonnet's applicable argument count falls despite its improved coverage. Passing E2 therefore does not establish better overall inference. Critique was tested unchanged; extra attacks were not manufactured to meet its count threshold.", "",
              "Respond now validates concession CQ routing, cited checks and reasons, records the attempt before conceding, and counts only actual new discharges. Already discharged attacks are excluded from its view. For an attack with no valid named CQ, the attack's own grounds question is required; unrelated target CQs cannot substitute. Failed intermediate candidates remain in E4's report.", "",
              "Appraise now verifies contiguous quotations, allows one correction and drops remaining failures. Its general skill preserves explicit decision grades and separates propositions that require different passages. The ten gold labels were fixed before model outputs; separately recorded manual adjudications credit equivalent abbreviations and facts split across items without changing the labels.", "",
              "| Guarded E5 | Direction agreement on explicit matched pairs | Explicit pairs / gold pairs |",
              "|---|---:|---:|"]
    for c in analyses["E5"]["cells"]:
        if c["version"] != "guarded":
            continue
        observed = sum(s["direction_pairs_observed"] for s in c["samples"])
        correct = sum(s["direction_pairs_correct"] for s in c["samples"])
        total = sum(s["direction_pairs_total"] for s in c["samples"])
        lines.append(f"| {c['provider']}:{c['model']} | {correct / observed:.1%} | {observed}/{total} |")
    lines += ["", "Direction agreement remains lower on Sonnet; missing hints, fact aggregation and differences in label coverage make these conditional rates incomplete measures of extraction quality. In particular, merging age-specific items for the combined lifetime-model gold fact can expose conflicting directions that a combined item would mark neutral. Quote membership and structured concession checks do not prove semantic entailment. These limitations remain visible in the artifacts.", "",
              "## Cost and validation", "",
              "| Experiment, including failed candidates | Move samples | API calls | Anthropic estimate | OpenAI estimate |",
              "|---|---:|---:|---:|---:|"]
    for e, t in sorted(totals.items()):
        lines.append(f"| {e} | {t['samples']} | {t['api_calls']} | ${t['cost_usd']['anthropic']:.4f} | ${t['cost_usd']['openai']:.4f} |")
    lines += [f"| Total | {sum(t['samples'] for t in totals.values())} | {result['api_calls']} | ${costs['anthropic']:.4f} | ${costs['openai']:.4f} |", "",
              f"Total estimate: **${sum(costs.values()):.4f}**. All manifest costs and API-call counts reconcile with the shared ledger; no requests remain pending. Limits were $50 Anthropic, including a protected $20 Opus reserve, and $16 OpenAI. The dated rates and official source links are in [pricing.json](../../experiments/pricing.json).", "",
              "**125 local tests pass.** Every saved sample graph hash and graph reference was checked, including the one structurally failed Respond sample. Full replies and per-sample graphs are saved locally in ignored directories; metrics manifests, reviewed maps, gold labels and selected input graphs are committed. The pre-existing `bench/results/20261110-0233.json` is untouched.", "",
              "Fixes were committed separately after their experiments. The E6 metrics distinguish an empty undecided main issue from one with surviving support for a claim that actually answers it. Accepted component findings are counted separately and cannot satisfy either deterministic or model-judged main-answer shape checks.", "",
              "Machine-readable campaign totals and the artifact audit are in [campaign.json](../../experiments/campaign.json). Analysis scripts under `experiments/` reproduce the reports locally without model calls.", ""]
    Path("bench/results/move-experiments.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"gates": result["gates"], "samples": len(audit), "api_calls": result["api_calls"], "cost_usd": costs, "failures": len(failures)}))


if __name__ == "__main__":
    summarize()
