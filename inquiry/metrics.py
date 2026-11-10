"""
One line of numbers per run, so that an edit to the harness can be judged
against the runs before it rather than by reading reports.

    metrics(inq, ev, gold, expected) -> dict

`gold` has `sources` (substrings matched against source titles and URLs)
and `facts` (substrings matched against evidence text and quotes).
`expected.shape` is one of:

    undecided                 no accepted claim on the main issue
    contested                 two or more main claims with IN pro arguments, none accepted
    accepted:<regex>          some accepted main claim's text matches the pattern
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .argument.evaluate import Evaluation, is_discharged
from .state import Inquiry


def _contains(hay: list[str], needle: str) -> bool:
    n = needle.lower()
    return any(n in h.lower() for h in hay)


def shape_match(inq: Inquiry, ev: Evaluation, shape: str) -> Optional[bool]:
    g = inq.graph
    main = inq.main_claims()
    accepted = [c for c in main if ev.status(c.id) == "in"]
    if shape == "undecided":
        return not accepted
    if shape == "contested":
        with_pro = [c for c in main if ev.claims[c.id].pro_ids]
        return len(with_pro) >= 2 and not accepted
    if shape.startswith("accepted:"):
        pat = re.compile(shape[len("accepted:"):], re.I)
        return any(pat.search(c.text) for c in accepted)
    return None


def metrics(inq: Inquiry, ev: Evaluation, gold: Optional[dict[str, Any]] = None,
            expected: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    g = inq.graph
    supporting = [a for a in g.arguments if not a.is_attack]
    attacks = [a for a in g.arguments if a.is_attack]
    flags = [f.code for f in ev.flags]
    m: dict[str, Any] = {
        "id": inq.id,
        "rounds": inq.round,
        "sources": len(g.sources),
        "origins": len({g.origin_key(s) for s in g.sources}),
        "duplicate_sources": flags.count("duplicate_source"),
        "evidence": len(g.evidence),
        "orphans": flags.count("orphan_evidence"),
        "supporting_args": len(supporting),
        "supporting_in": sum(1 for a in supporting if ev.labels.get(a.id) == "in"),
        "attacks": len(attacks),
        "attacks_out": sum(1 for a in attacks if ev.labels.get(a.id) == "out"),
        "attacks_discharged": sum(1 for a in attacks if is_discharged(g, a)),
        "accepted_claims": sum(1 for c in g.claims if ev.status(c.id) == "in"),
        "single_origin_accepts": flags.count("single_origin"),
        "main_status": {c.id: ev.status(c.id) for c in inq.main_claims()},
        "absence_assertions": len(inq.conclusion.flags) if inq.conclusion else 0,
        "provider_proposer": inq.llm_config.get("proposer", {}).get("provider", ""),
        "provider_critic": inq.llm_config.get("critic", {}).get("provider", ""),
        "model_proposer": inq.llm_config.get("proposer", {}).get("model", ""),
        "model_critic": inq.llm_config.get("critic", {}).get("model", ""),
        "effort_proposer": inq.llm_config.get("proposer", {}).get("effort", ""),
        "effort_critic": inq.llm_config.get("critic", {}).get("effort", ""),
        "tokens_in": sum(u["input_tokens"] for u in inq.llm_usage),
        "tokens_out": sum(u["output_tokens"] for u in inq.llm_usage),
        "calls": len(inq.llm_usage),
        "stop_reason": inq.stop_assessments[-1].reason if inq.stop_assessments else "",
    }
    if gold:
        src_hay = [s.title for s in g.sources] + [s.url for s in g.sources]
        ev_hay = [e.text for e in g.evidence] + [e.quote for e in g.evidence]
        gs, gf = gold.get("sources", []) or [], gold.get("facts", []) or []
        m["gold_sources_found"] = sum(1 for x in gs if _contains(src_hay, x))
        m["gold_sources_total"] = len(gs)
        m["gold_sources_missing"] = [x for x in gs if not _contains(src_hay, x)]
        m["gold_facts_found"] = sum(1 for x in gf if _contains(ev_hay, x))
        m["gold_facts_total"] = len(gf)
        m["gold_facts_missing"] = [x for x in gf if not _contains(ev_hay, x)]
    if expected and expected.get("shape"):
        m["shape_expected"] = expected["shape"]
        m["shape_match"] = shape_match(inq, ev, expected["shape"])
    return m


def one_line(m: dict[str, Any]) -> str:
    keys = ["provider_proposer", "model_proposer", "effort_proposer", "provider_critic", "model_critic", "effort_critic",
            "tokens_in", "tokens_out", "calls", "sources", "origins", "duplicate_sources", "evidence", "orphans", "supporting_args", "supporting_in",
            "attacks", "attacks_out", "attacks_discharged", "accepted_claims", "single_origin_accepts",
            "absence_assertions"]
    parts = [f"{k}={m[k]}" for k in keys if k in m]
    if "gold_sources_total" in m:
        parts.append(f"gold_sources={m['gold_sources_found']}/{m['gold_sources_total']}")
        parts.append(f"gold_facts={m['gold_facts_found']}/{m['gold_facts_total']}")
    if "shape_match" in m:
        parts.append(f"shape_match={m['shape_match']}")
    if m.get("stop_reason"):
        parts.append(f"stop_reason={m['stop_reason']!r}")
    parts.append("main=" + ",".join(f"{k}:{v}" for k, v in m["main_status"].items()))
    return "metrics " + " ".join(parts)
