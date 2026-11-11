"""Replay one move on a deterministic projection of a saved final graph.

This does not claim to recover a historical snapshot: later claim revisions
remain unless the requested projection removes them. No retrieval is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import mean
import sys
import time
from typing import Callable

from . import moves
from .experiment_budget import BudgetExceeded, ExperimentBudget, estimate_cost, token_counts
from .llm import AnthropicLLM, LLM, OpenAILLM, extract_json
from .state import Inquiry

MOVES = ("hypothesize", "argue", "critique", "respond", "appraise")


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_run(path: Path | str) -> tuple[Inquiry, Path]:
    path = Path(path).resolve()
    state = path if path.is_file() else path / "inquiry.json"
    return Inquiry.model_validate_json(state.read_text(encoding="utf-8")), state.parent


def _text_key(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def claim_fingerprint(inq: Inquiry) -> str:
    return fingerprint([(c.id, c.issue_id, c.text) for c in inq.graph.claims if c.live])


def _compact_ids(inq: Inquiry, kinds: tuple[str, ...]) -> Inquiry:
    data = inq.model_dump()
    mapping = {}
    for collection, prefix in (("evidence", "E"), ("arguments", "A")):
        if collection in kinds:
            mapping.update({obj["id"]: f"{prefix}{i}" for i, obj in enumerate(data["graph"][collection], 1)})
    def rewrite(value):
        if isinstance(value, str):
            return re.sub(r"\b(?:E|A)\d+\b", lambda m: mapping.get(m[0], m[0]), value)
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        if isinstance(value, dict):
            return {mapping.get(k, k): rewrite(v) for k, v in value.items()}
        return value
    return Inquiry.model_validate(rewrite(data))


def replace_claims(inq: Inquiry, other: Inquiry) -> dict:
    """Match issues by text, import unmatched issues, never alias claim ordinals."""
    g = inq.graph
    issues = {_text_key(i.text): i for i in g.issues}
    issue_map, imported = {}, []
    for issue in other.graph.issues:
        match = issues.get(_text_key(issue.text))
        if match is None:
            match = g.add_issue(issue.text, question_type=issue.question_type, answerhood=issue.answerhood,
                                search_topic=issue.search_topic)
            issues[_text_key(issue.text)] = match
            imported.append(match.id)
        issue_map[issue.id] = match.id
    for issue in other.graph.issues:
        if issue_map[issue.id] in imported:
            target = g.issue(issue_map[issue.id])
            target.parent_id = issue_map.get(issue.parent_id)
            target.depends_on = [issue_map[x] for x in issue.depends_on if x in issue_map]
    previous = {c.id: c for c in g.claims}
    selected = [c for c in other.graph.claims if c.live]
    mapping = {c.id: f"C{i}" for i, c in enumerate(selected, 1)}
    g.claims = [c.model_copy(deep=True, update={
        "id": mapping[c.id], "issue_id": issue_map.get(c.issue_id),
        "contrary_ids": [mapping[x] for x in c.contrary_ids if x in mapping],
        "superseded_by": None, "revision_of": None, "review_note": "",
    }) for c in selected]
    exact = {_text_key(c.text): c.id for c in g.claims}
    old_to_new = {cid: exact[_text_key(c.text)] for cid, c in previous.items() if _text_key(c.text) in exact}
    cleared = 0
    for evidence in g.evidence:
        rebound = {old_to_new[cid]: stance for cid, stance in evidence.bears_on.items() if cid in old_to_new}
        cleared += len(evidence.bears_on) - len(rebound)
        evidence.bears_on = rebound
    return {"issue_map": issue_map, "issues_imported": imported, "claim_map": mapping,
            "stale_bearings_cleared": cleared, "requires_evidence_map": bool(cleared or any(
                _text_key(c.text) not in {_text_key(old.text) for old in previous.values()} for c in selected))}


def reconstruct_pre_move(final: Inquiry, move: str, *, claims_from: Inquiry | None = None,
                         source_id: str | None = None) -> tuple[Inquiry, dict]:
    if move not in MOVES:
        raise ValueError(f"unsupported move: {move}")
    inq = Inquiry(id=final.id, question=final.question, created_at=final.created_at, framing=final.framing.model_copy(deep=True),
                  graph=final.graph.model_copy(deep=True), round=final.round,
                  phase="framed" if move == "hypothesize" else "inquiring")
    g, preparation = inq.graph, {"projection": move, "historical_snapshot": False}
    if move == "hypothesize":
        g.claims, g.evidence, g.sources, g.arguments = [], [], [], []
    elif move == "argue":
        g.arguments = []
        for evidence in g.evidence:
            evidence.provenance.pop("unusable", None)
        if claims_from is not None:
            preparation.update(replace_claims(inq, claims_from))
    elif move == "critique":
        g.arguments = [a for a in g.arguments if not a.is_attack]
        inq = _compact_ids(inq, ("arguments",))
    elif move == "respond":
        for argument in g.arguments:
            argument.note = re.sub(r"\s*\(conceded by proposer:[^)]*\)", "", argument.note)
            argument.note = re.sub(r"\s*\(discharge attempted by proposer:[^)]*\)", "", argument.note)
        preparation["dispositions_reset"] = True
    else:
        if not source_id or g.source(source_id) is None:
            raise ValueError("appraise needs --source with an existing source ID")
        if claims_from is not None:
            preparation.update(replace_claims(inq, claims_from))
            preparation["requires_evidence_map"] = False
            preparation["stance_policy"] = "selected source is reappraised; other stale hints are cleared"
        removed = {e.id for e in g.evidence if e.source_id == source_id}
        g.evidence = [e for e in g.evidence if e.id not in removed]
        affected = {a.id for a in g.arguments if set(a.premise_ids) & removed}
        while True:
            more = {a.id for a in g.arguments if a.is_attack and a.attacks.target_id in affected | removed}
            if more <= affected:
                break
            affected |= more
        g.arguments = [a for a in g.arguments if a.id not in affected]
        for argument in g.arguments:
            for qid, answer in list(argument.cq.items()):
                if set(answer.evidence_ids) & removed:
                    argument.cq[qid] = type(answer)()
        preparation["removed_evidence"] = sorted(removed)
        inq = _compact_ids(inq, ("evidence", "arguments"))
    if inq.graph.validate_refs():
        raise ValueError(f"projection has invalid references: {inq.graph.validate_refs()}")
    return inq, preparation


def mapping_template(inq: Inquiry) -> dict:
    return {"claims_sha256": claim_fingerprint(inq), "reviewed_by": "", "reviewed": False,
            "claims": [{"id": c.id, "issue_id": c.issue_id, "text": c.text} for c in inq.graph.claims if c.live],
            "evidence": [{"id": e.id, "source_id": e.source_id, "text": e.text, "quote": e.quote} for e in inq.graph.evidence],
            "directions": {e.id: {} for e in inq.graph.evidence}, "rationale": {}}


def apply_evidence_map(inq: Inquiry, data: dict) -> None:
    if not data.get("reviewed") or not data.get("reviewed_by"):
        raise ValueError("evidence remapping must be explicitly reviewed")
    if data.get("claims_sha256") != claim_fingerprint(inq):
        raise ValueError("evidence map belongs to a different claim set")
    if set(data.get("directions", {})) != {e.id for e in inq.graph.evidence}:
        raise ValueError("evidence map must explicitly cover every retained evidence ID")
    claims = {c.id for c in inq.graph.claims if c.live}
    for evidence in inq.graph.evidence:
        hints = data["directions"][evidence.id]
        if any(cid not in claims or value not in ("for", "against", "neutral") for cid, value in hints.items()):
            raise ValueError(f"invalid evidence directions for {evidence.id}")
        evidence.bears_on = dict(hints)


class RecordingLLM(LLM):
    def __init__(self, delegate: LLM, rate: dict | None = None, budget: ExperimentBudget | None = None,
                 *, max_output_tokens: int = 16000, use_reserved: bool = False):
        super().__init__()
        self.delegate, self.rate, self.budget = delegate, rate, budget
        self.provider = getattr(delegate, "provider", "fake")
        self.model = self.name = delegate.name
        self.effort = getattr(delegate, "reasoning_effort", getattr(delegate, "effort", ""))
        self.max_output_tokens, self.use_reserved = max_output_tokens, use_reserved
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, max_tokens: int = 16000) -> str:
        cap = min(max_tokens, self.max_output_tokens)
        token, usage_start, error, reply = None, len(self.delegate.usage), None, None
        if self.rate and self.budget:
            # Byte-level token upper bound plus framing overhead; the most
            # expensive applicable input/cache tier is reserved before sending.
            bound = len(system.encode()) + len(user.encode()) + 512
            tier = self.rate.get("long", self.rate) if bound > self.rate.get("long_above_tokens", math.inf) else self.rate
            cost = (bound * max(tier[k] for k in ("input", "cache_write", "cached_input")) + cap * tier["output"]) / 1e6
            token = self.budget.reserve(self.provider, cost, use_reserved=self.use_reserved)
        try:
            reply = self.delegate.complete(system, user, max_tokens=cap)
            return reply
        except Exception as exc:
            error = {"type": type(exc).__name__, "status": getattr(exc, "status_code", None)}
            if "credit balance" in str(exc).lower():
                error["reason"] = "insufficient_credits"
            raise
        finally:
            usage = self.delegate.usage[usage_start:]
            self.usage.extend(usage)
            actual = sum(estimate_cost(u, self.rate) for u in usage) if self.rate and usage else (0.0 if self.provider == "fake" else None)
            if error and error["status"] and 400 <= error["status"] < 500:
                actual = 0.0  # rejected request, no generated response
            record = {"system": system, "user": user, "reply": reply, "usage": usage,
                      "cost_usd": actual, "max_output_tokens": cap, "error": error}
            self.calls.append(record)
            if token:
                self.budget.finish(token, actual, {"model": self.model, "effort": self.effort,
                                                   "skill": system.splitlines()[0], "error": error})


def _proposals(llm: RecordingLLM) -> list[dict]:
    result = []
    for call in llm.calls:
        if call["reply"]:
            try:
                result.append(extract_json(call["reply"]))
            except ValueError:
                pass
    return result


def hypothesis_metrics(claims: list, issues: list) -> dict:
    from .specificity import claim_specificity_errors
    texts = [c.text if hasattr(c, "text") else c["text"] for c in claims]
    digits = [sum(ch.isdigit() for ch in text) for text in texts]
    issue_ids = [c.issue_id if hasattr(c, "issue_id") else c.get("issue_id") for c in claims]
    anchors = {i.id: i.answerhood for i in issues}
    return {"n_claims": len(texts), "avg_len": mean(map(len, texts)) if texts else 0,
            "avg_digits": mean(digits) if digits else 0, "max_len": max(map(len, texts), default=0),
            "n_over_guard": sum(bool(claim_specificity_errors(t, anchors.get(cid, ""))) for t, cid in zip(texts, issue_ids)),
            "n_with_null": sum(any((getattr(c, "issue_id", None) if not isinstance(c, dict) else c.get("issue_id")) == issue.id
                                      and (getattr(c, "kind", None) if not isinstance(c, dict) else c.get("kind")) == "null"
                                      for c in claims) for issue in issues), "n_issues": len(issues)}


def need_tag(text: str) -> dict:
    blocked = re.search(r"patient.level|individual.level|\bIPD\b|author request|contact.{0,12}author|behind.{0,12}paywall|paywalled", text, re.I)
    return {"text": text, "tag": "unobtainable" if blocked else "obtainable",
            "tag_basis": blocked[0] if blocked else "public document/search request; heuristic tag for review"}


CQ_OUTCOMES = ("satisfied", "unsatisfied", "defaulted", "open")


def cq_outcome_bucket(answer) -> str:
    """Four reporting buckets; raw status/outcome remain in the graph.

    An answered-but-unresolved check is still epistemically open. Older
    answered checks with an empty outcome mean satisfied, as in evaluation.
    """
    if answer is None or answer.status == "open":
        return "open"
    if answer.status == "defaulted":
        return "defaulted"
    if answer.outcome == "unsatisfied":
        return "unsatisfied"
    return "satisfied" if answer.satisfied else "open"


def argue_diagnostics(inq: Inquiry, evaluation=None) -> dict:
    """Read-only diagnostics for active supporting arguments, not attacks."""
    from .argument.evaluate import evaluate
    from .argument.schemes import SCHEMES
    ev = evaluation if evaluation is not None else evaluate(inq.graph)
    outcomes = Counter({key: 0 for key in CQ_OUTCOMES})
    by_kind = {kind: Counter({key: 0 for key in CQ_OUTCOMES}) for kind in ("assumption", "exception")}
    details, reasons = Counter(), Counter()
    for argument in inq.graph.arguments:
        if argument.is_attack or argument.withdrawn:
            continue
        for question in SCHEMES[argument.scheme].critical_questions:
            answer = argument.cq.get(question.id)
            bucket = cq_outcome_bucket(answer)
            outcomes[bucket] += 1
            by_kind[question.kind][bucket] += 1
            if answer and answer.status == "answered" and answer.outcome == "unresolved":
                details["answered_unresolved"] += 1
            if answer and answer.status == "answered" and not answer.outcome:
                details["legacy_answered_empty_outcome"] += 1
        for reason in ev.inapplicable_reasons.get(argument.id, []):
            if reason.startswith(("open assumption: ", "assumption unresolved: ")):
                reasons["open:" + reason.split(": ", 1)[1]] += 1
            elif reason.startswith(("assumption unsatisfied: ", "exception obtains: ")):
                reasons["unsatisfied:" + reason.split(": ", 1)[1]] += 1
            elif reason.startswith("premise claim not accepted: "):
                reasons["premise_claim_not_accepted"] += 1
            else:
                reasons["other:" + reason] += 1
    return {"inapplicable_reasons": dict(sorted(reasons.items())), "cq_outcomes": dict(outcomes),
            "cq_outcomes_by_kind": {kind: dict(counts) for kind, counts in by_kind.items()},
            "cq_outcome_details": dict(sorted(details.items()))}


def move_metrics(inq: Inquiry, move: str, summary: dict, llm: RecordingLLM,
                 *, source_id: str | None = None, source_text: str = "", gold_facts: list[str] | None = None) -> tuple[dict, dict]:
    g, proposals = inq.graph, _proposals(llm)
    ev = moves.evaluate_move(inq)
    raw = {}
    if move == "hypothesize":
        active = [i for i in g.issues if i.status != "dropped"]
        m = hypothesis_metrics([c for c in g.claims if c.live], active)
        m["exclusive_groups"] = summary.get("exclusive_groups", 0)
        if proposals:
            raw = hypothesis_metrics(proposals[0].get("claims", []), active)
            raw["exclusive_groups"] = len(proposals[0].get("exclusive_groups", []))
    elif move == "argue":
        supporting = [a for a in g.arguments if not a.is_attack and not a.withdrawn]
        offered = set()
        eligible = []
        for issue in g.issues:
            claims, ids = moves.issue_evidence(g, issue.id, include_unassigned=issue.id == g.main_issue_id)
            offered.update(ids)
            for cid in claims:
                if sum(g.ev(eid).bears_on.get(cid) == "for" for eid in ids) >= 3:
                    eligible.append(cid)
        supported = {a.claim_id for a in supporting}
        offered = set(summary.get("input_offered_evidence", offered))
        unusable = set(summary.get("unusable", [])) & offered
        m = {"supporting_args": len(supporting), "applicable_args": sum(ev.applicable.get(a.id, False) for a in supporting),
             "claims_supported_unargued": len(set(eligible) - supported), "eligible_claims": sorted(set(eligible)),
             "unusable_share": len(unusable) / len(offered) if offered else 0,
             "unusable_items": len(unusable), "offered_evidence": len(offered),
             "scoped_claims_proposed": sum(len(p.get("scoped_claims", [])) for p in proposals),
             "scoped_claims_added": len(summary.get("scoped_claims", [])),
             "claims_with_reason": len(summary.get("claim_reasons", {})),
             "ignored_unusable": len(summary.get("ignored_unusable", [])),
             "input_eligible_claims": summary.get("input_eligible_claims", sorted(set(eligible)))}
        m.update(argue_diagnostics(inq, ev))
    elif move == "critique":
        attacks = [a for a in g.arguments if a.is_attack]
        tags = [need_tag(t) for t in summary.get("needed_evidence", [])]
        m = {"attacks": len(attacks), "attacks_applicable": sum(ev.applicable.get(a.id, False) for a in attacks),
             "attacks_with_cq": sum(bool(a.attacks.raises_cq) for a in attacks),
             "needs_obtainable": sum(t["tag"] == "obtainable" for t in tags),
             "needs_unobtainable": sum(t["tag"] == "unobtainable" for t in tags), "needs_tags": tags}
    elif move == "respond":
        responses = [r for p in proposals for r in p.get("responses", [])]
        counters = [g.arg(aid) for aid in summary.get("countered", [])]
        m = {"concede": len(summary.get("conceded", [])), "discharge": len(set(summary.get("discharged", []))),
             "counter": len(counters), "counters_applicable": sum(ev.applicable.get(a.id, False) for a in counters if a),
             "concessions_justified": len(summary.get("concessions_justified", [])),
             "rejected_concessions": len(summary.get("rejected_concessions", [])),
             "discharge_attempts": len(summary.get("discharge_attempts", []))}
    else:
        evidence = [e for e in g.evidence if e.source_id == source_id]
        normal = lambda s: " ".join(s.casefold().split())
        text = normal(source_text)
        verified = sum(bool(e.quote.strip()) and normal(e.quote) in text for e in evidence)
        hay = " ".join(e.text + " " + e.quote for e in evidence).casefold()
        m = {"evidence": len(evidence), "for": sum(v == "for" for e in evidence for v in e.bears_on.values()),
             "against": sum(v == "against" for e in evidence for v in e.bears_on.values()),
             "neutral": sum(v == "neutral" for e in evidence for v in e.bears_on.values()),
             "quote_verified": verified / len(evidence) if evidence else 0, "quotes_verified": verified,
             "gold_facts_found": sum(f.casefold() in hay for f in gold_facts or []), "gold_facts": gold_facts or []}
    return m, raw


def aggregate(samples: list[dict]) -> dict:
    output = {}
    for section, prefix in (("metrics", ""), ("raw_metrics", "raw_")):
        keys = {k for sample in samples for k, v in sample[section].items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        for key in sorted(keys):
            values = [s[section][key] for s in samples if not s["error"] and isinstance(s[section].get(key), (int, float))]
            if values:
                output[prefix + key] = {"mean": mean(values), "min": min(values), "max": max(values), "n": len(values)}
    return output


def run_samples(prepared: Inquiry, move: str, factory: Callable[[], LLM], out: Path, *, n: int = 3,
                skill_dir: Path | None = None, rate: dict | None = None, budget: ExperimentBudget | None = None,
                max_output_tokens: int = 16000, source_id: str | None = None, source_text: str = "",
                gold_facts: list[str] | None = None, preparation: dict | None = None, use_reserved: bool = False) -> dict:
    if n < 1:
        raise ValueError("n must be positive")
    out = Path(out)
    if (out / "moves.json").exists():
        raise FileExistsError(f"refusing to overwrite experiment: {out}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "pre-move.json").write_text(prepared.model_dump_json(indent=2), encoding="utf-8")
    original_skills, samples = moves.SKILLS_DIR, []
    manifest = {"move": move, "run_id": prepared.id, "n_requested": n,
                "input_sha256": fingerprint(prepared.model_dump()), "preparation": preparation or {}, "samples": samples}
    try:
        if skill_dir:
            moves.SKILLS_DIR = Path(skill_dir).resolve()
        manifest["skill_sha256"] = hashlib.sha256(moves.skill_text(move).encode()).hexdigest()
        for index in range(1, n + 1):
            inq = prepared.model_copy(deep=True)
            delegate = factory()
            llm = RecordingLLM(delegate, rate, budget, max_output_tokens=max_output_tokens, use_reserved=use_reserved)
            sample_dir = out / f"sample-{index:03d}"
            sample_dir.mkdir()
            summary, error = {}, ""
            started = time.monotonic()
            try:
                if move in ("argue", "critique", "respond"):
                    moves.evaluate_move(inq)
                if move == "appraise":
                    summary = moves.appraise(inq, llm, inq.graph.source(source_id), source_text)
                else:
                    summary = getattr(moves, move)(inq, llm)
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:180]}" if not llm.calls or not llm.calls[-1]["error"] else json.dumps(llm.calls[-1]["error"])
            m, raw = move_metrics(inq, move, summary, llm, source_id=source_id, source_text=source_text, gold_facts=gold_facts)
            inq.llm_usage = list(llm.usage)
            inq.llm_config = {"replay": {"provider": llm.provider, "model": llm.model, "effort": llm.effort}}
            (sample_dir / "inquiry.json").write_text(inq.model_dump_json(indent=2), encoding="utf-8")
            (sample_dir / "responses.json").write_text(json.dumps(llm.calls, indent=2), encoding="utf-8")
            counts = [token_counts(u, (rate or {}).get("input_includes_cache", False)) for u in llm.usage]
            costs = [c["cost_usd"] for c in llm.calls]
            sample = {"sample": index, "provider": llm.provider, "model": llm.model, "effort": llm.effort,
                      "tokens_in": sum(sum(c[:3]) for c in counts), "tokens_out": sum(c[3] for c in counts),
                      "cost_usd": sum(costs) if all(c is not None for c in costs) else None,
                      "api_calls": len(llm.calls), "seconds": round(time.monotonic() - started, 2),
                      "metrics": m, "raw_metrics": raw, "move_summary": summary, "error": error,
                      "graph": str((sample_dir / "inquiry.json").relative_to(out)),
                      "graph_sha256": fingerprint(inq.model_dump()),
                      "references_valid": not inq.graph.validate_refs()}
            samples.append(sample)
            manifest.update(provider=llm.provider, model=llm.model, effort=llm.effort, aggregate=aggregate(samples))
            (out / "moves.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"{move} {llm.provider}:{llm.model} effort={llm.effort} sample={index}/{n} cost={sample['cost_usd']} error={bool(error)}", flush=True)
            if error:
                break  # no repeated charges after a failed call or structural failure
    finally:
        moves.SKILLS_DIR = original_skills
    return manifest


def local_source_text(run_dir: Path, inq: Inquiry, source_id: str, source_root: Path | None = None) -> str:
    candidates = [Path(source_root) / f"{source_id}.txt"] if source_root else [run_dir / "sources" / f"{source_id}.txt"]
    for parent in (run_dir, *run_dir.parents):
        if (parent / ".git").exists():
            candidates.append(parent / "runs" / inq.id / "sources" / f"{source_id}.txt")
            candidates.append(parent / "runs" / "bench" / inq.id / "sources" / f"{source_id}.txt")
            break
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise FileNotFoundError(f"no local text for {source_id}; use --source-root")
    return path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--move", choices=MOVES, required=True)
    p.add_argument("--provider", help="provider:model (required unless --prepare-only)")
    p.add_argument("--effort", default="medium")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--skill-dir", type=Path)
    p.add_argument("--claims-from", type=Path)
    p.add_argument("--evidence-map", type=Path)
    p.add_argument("--source")
    p.add_argument("--source-root", type=Path)
    p.add_argument("--gold-fact", action="append", default=[])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--env-file", type=Path, default=Path.cwd() / ".env")
    p.add_argument("--pricing", type=Path, default=Path("experiments/pricing.json"))
    p.add_argument("--budget-file", type=Path, default=Path("experiments/budget.json"))
    p.add_argument("--anthropic-budget", type=float, default=50.0)
    p.add_argument("--openai-budget", type=float, default=16.0)
    p.add_argument("--opus-reserve", type=float, default=20.0)
    p.add_argument("--use-reserved", action="store_true")
    p.add_argument("--max-output-tokens", type=int, default=16000)
    args = p.parse_args(argv)
    final, run_dir = load_run(args.run)
    other = load_run(args.claims_from)[0] if args.claims_from else None
    prepared, preparation = reconstruct_pre_move(final, args.move, claims_from=other, source_id=args.source)
    if args.evidence_map:
        data = json.loads(args.evidence_map.read_text(encoding="utf-8"))
        apply_evidence_map(prepared, data)
        preparation["evidence_map_sha256"] = fingerprint(data)
        preparation["requires_evidence_map"] = False
    if args.prepare_only or preparation.get("requires_evidence_map"):
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "pre-move.json").write_text(prepared.model_dump_json(indent=2), encoding="utf-8")
        (args.out / "preparation.json").write_text(json.dumps(preparation, indent=2), encoding="utf-8")
        if other:
            (args.out / "mapping-template.json").write_text(json.dumps(mapping_template(prepared), indent=2), encoding="utf-8")
        if args.prepare_only:
            return 0
        p.error("changed claims require a reviewed --evidence-map; mapping-template.json was written without calling a provider")
    if not args.provider or ":" not in args.provider:
        p.error("--provider must be provider:model")
    from dotenv import load_dotenv
    load_dotenv(args.env_file)
    provider, model = args.provider.split(":", 1)
    if provider not in ("anthropic", "openai"):
        p.error("provider must be anthropic or openai")
    card = json.loads(args.pricing.read_text(encoding="utf-8"))
    rate = card["models"].get(args.provider)
    if rate is None:
        p.error("model has no verified rate card; add pricing before making requests")
    def factory():
        llm = AnthropicLLM(model, effort=args.effort) if provider == "anthropic" else OpenAILLM(model, reasoning_effort=args.effort)
        llm.client = llm.client.with_options(max_retries=0)
        return llm
    budget = ExperimentBudget(args.budget_file, {"anthropic": args.anthropic_budget, "openai": args.openai_budget},
                              {"anthropic": args.opus_reserve})
    text = local_source_text(run_dir, final, args.source, args.source_root) if args.move == "appraise" else ""
    result = run_samples(prepared, args.move, factory, args.out, n=args.n, skill_dir=args.skill_dir, rate=rate,
                         budget=budget, max_output_tokens=args.max_output_tokens, source_id=args.source,
                         source_text=text, gold_facts=args.gold_fact, preparation=preparation, use_reserved=args.use_reserved)
    return 1 if any(s["error"] for s in result["samples"]) else 0


if __name__ == "__main__":
    sys.exit(main())
