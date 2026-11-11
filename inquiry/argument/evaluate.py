"""
Evaluation of an argument graph. Pure code; no model calls.

Four stages:

1. Applicability. An argument is applicable when every assumption-type
   critical question of its scheme is answered or explicitly defaulted,
   and every claim it uses as a premise is itself accepted. Inapplicable
   arguments neither support nor attack.

2. Grounded labelling (Dung 1995) over applicable arguments, with edges
   from undercutting attacks (attacker -> target argument) and undermining
   attacks (attacker -> every argument using the attacked premise). These
   are one-directional, as in ASPIC+. Grounded semantics is skeptical and
   unique: a mutual attack leaves both undecided.

3. Claim status by proof standard (Carneades). Pro arguments are the IN
   supporting arguments for the claim. Con arguments are the IN supporting
   arguments for its contraries plus IN rebutting attacks on the claim or
   on its arguments. Strength is ordinal (weak < moderate < strong); the
   weakest premise rules; two independent pro arguments corroborate and
   raise effective pro strength one level. A claim is IN when its surviving
   pro arguments clear its standard, OUT when a contrary is IN or only con
   arguments survive, otherwise UNDECIDED.

4. Coherence flags and load-bearing analysis.

Because applicability depends on accepted premise claims and acceptance
depends on applicability, stages 1–3 iterate to a fixed point.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .graph import (
    STRENGTH_ORDER, Argument, ArgumentGraph, Claim, ProofStandard, Status, Strength,
)
from .schemes import SCHEMES
from .scope import canonical, sub_scope

_LEVEL = {1: "weak", 2: "moderate", 3: "strong"}


class ClaimDetail(BaseModel):
    standard: ProofStandard
    status: Status
    pro_ids: list[str] = Field(default_factory=list)
    con_ids: list[str] = Field(default_factory=list)
    pro_strength: int = 0
    con_strength: int = 0
    corroborated: bool = False
    met: bool = False
    label: Literal["", "accepted", "refuted", "defeated", "contested", "unsupported", "untested"] = ""
    label_reason: str = ""


class Flag(BaseModel):
    code: str
    node_id: str = ""
    detail: str = ""


class LoadBearing(BaseModel):
    node_id: str
    kind: Literal["evidence", "argument", "cq_answer"]
    detail: str = ""
    effect: str = Field(description="Status of the watched claim if this node were removed or reopened.")
    claim_id: str = Field(default="", description="The watched claim.")


class Evaluation(BaseModel):
    applicable: dict[str, bool] = Field(default_factory=dict)
    inapplicable_reasons: dict[str, list[str]] = Field(default_factory=dict)
    argument_strength: dict[str, Strength] = Field(default_factory=dict)
    labels: dict[str, Status] = Field(default_factory=dict, description="Grounded labelling of applicable arguments.")
    claims: dict[str, ClaimDetail] = Field(default_factory=dict)
    issues: dict[str, list[str]] = Field(default_factory=dict, description="issue id -> accepted claim ids.")
    flags: list[Flag] = Field(default_factory=list)
    converged: bool = True
    reopened_cqs: dict[str, list[str]] = Field(default_factory=dict)

    def status(self, claim_id: str) -> Status:
        return self.claims[claim_id].status if claim_id in self.claims else "undecided"


# ---------------------------------------------------------------------------
# Strength
# ---------------------------------------------------------------------------

def argument_strength(g: ArgumentGraph, a: Argument, details: dict[str, ClaimDetail] | None = None) -> Strength:
    base = STRENGTH_ORDER[a.strength_override or SCHEMES[a.scheme].default_strength]
    if a.scheme == "composition" and details and a.premise_ids:
        base = min((details[pid].pro_strength if pid in details else 0) for pid in a.premise_ids)
        base = max(1, base)
        if a.strength_override:
            base = min(base, STRENGTH_ORDER[a.strength_override])
    for pid in a.premise_ids:
        e = g.ev(pid)
        if e is not None:
            base = min(base, STRENGTH_ORDER[e.credentials.effective()])
    # an assumption accepted without evidence weakens the argument one level
    sch = SCHEMES[a.scheme]
    if any(a.cq.get(q.id) and a.cq[q.id].status == "defaulted" for q in sch.assumptions()):
        base = max(1, base - 1)
    return _LEVEL[base]  # type: ignore[return-value]


def argument_origins(g: ArgumentGraph, a: Argument, _seen: set[str] | None = None,
                     labels: dict[str, Status] | None = None) -> set[str]:
    """
    Origins of the evidence an argument rests on. A derivative source that
    does not name its origin contributes none: it repeats something, and we
    do not know what, so it cannot corroborate anything.
    """
    out: set[str] = set()
    seen = (_seen or set()) | {a.id}
    for pid in a.premise_ids:
        e = g.ev(pid)
        if e is None:
            if a.scheme == "composition" and g.claim(pid):
                for support in g.arguments_for(pid):
                    if support.id not in seen and not support.withdrawn and (labels is None or labels.get(support.id) == "in"):
                        out.update(argument_origins(g, support, seen, labels))
            continue
        o = g.evidence_origin(e)
        if o is not None:
            out.add(o)
    return out


def _corroborated(origins: dict[str, set[str]]) -> bool:
    """Two distinct IN pro arguments whose origins are both non-empty and disjoint."""
    ids = list(origins)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if origins[a] and origins[b] and not (origins[a] & origins[b]):
                return True
    return False


def _all_origins(origins: dict[str, set[str]]) -> set[str]:
    out: set[str] = set()
    for s in origins.values():
        out |= s
    return out


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------

def _applicability(g: ArgumentGraph, accepted: set[str], reopened: set[tuple[str, str]] | None = None) -> tuple[dict[str, bool], dict[str, list[str]]]:
    applicable: dict[str, bool] = {}
    reasons: dict[str, list[str]] = {}
    for a in g.arguments:
        why: list[str] = []
        sch = SCHEMES[a.scheme]
        if a.withdrawn:
            why.append(f"withdrawn: {a.withdrawn}")
        for q in sch.assumptions():
            st = a.cq.get(q.id)
            if reopened and (a.id, q.id) in reopened:
                why.append(f"reopened assumption: {q.id}")
            elif st is None or st.status == "open":
                why.append(f"open assumption: {q.id}")
            elif st.status == "answered" and st.outcome == "unsatisfied":
                why.append(f"assumption unsatisfied: {q.id}")
            elif st.status == "answered" and st.outcome == "unresolved":
                why.append(f"assumption unresolved: {q.id}")
        for q in sch.exceptions():
            st = a.cq.get(q.id)
            if st is not None and st.status == "answered" and st.outcome == "unsatisfied":
                why.append(f"exception obtains: {q.id}")  # the proponent's own check found the exception holds
        for pid in a.premise_ids:
            if g.claim(pid) is not None and pid not in accepted:
                why.append(f"premise claim not accepted: {pid}")
        applicable[a.id] = not why
        if why:
            reasons[a.id] = why
    return applicable, reasons


# ---------------------------------------------------------------------------
# Grounded labelling
# ---------------------------------------------------------------------------

def _discharged(g: ArgumentGraph, atk: Argument) -> bool:
    """
    An undercut that raises a named critical question is discharged when the
    target has answered that question with evidence. An answer without
    evidence, or a defaulted one, does not discharge it (Carneades: the
    proponent must meet a raised exception, not merely deny it).
    """
    qid = atk.attacks.raises_cq
    if not qid:
        return False
    target = g.arg(atk.attacks.target_id)
    if target is None:
        return False
    ans = target.cq.get(qid)
    if atk.attacks.basis == "answer_inadequate" and (ans is None or ans.revision <= atk.attacks.challenged_revision
                                                    or ans.answer_move != "respond"):
        return False  # the answer being challenged cannot discharge its own challenge
    return ans is not None and ans.satisfied and bool(ans.evidence_ids)


def is_discharged(g: ArgumentGraph, atk: Argument) -> bool:
    return atk.is_attack and _discharged(g, atk)


def reopening_metrics(g: ArgumentGraph, ev: Evaluation) -> dict:
    attacks = [a for a in g.arguments if a.is_attack and a.attacks.basis == "answer_inadequate"]
    historical = {(a.attacks.target_id, a.attacks.raises_cq) for a in attacks if a.attacks.was_reopened}
    active = {(target, qid) for target, questions in ev.reopened_cqs.items() for qid in questions}
    discharged = {(a.attacks.target_id, a.attacks.raises_cq) for a in attacks
                  if a.attacks.was_reopened and is_discharged(g, a)}
    return {"reopened_cqs": len(historical | active), "reopened_cqs_active": len(active),
            "reopened_then_discharged": len(discharged)}


def _attack_edges(g: ArgumentGraph, applicable: dict[str, bool]) -> dict[str, set[str]]:
    """target argument id -> set of attacker argument ids (undercuts and undermines only)."""
    attackers: dict[str, set[str]] = {a.id: set() for a in g.arguments if applicable[a.id]}
    for atk in g.arguments:
        if not atk.is_attack or not applicable[atk.id]:
            continue
        t = atk.attacks
        if t.type == "undercut":
            if t.target_id in attackers and not _discharged(g, atk):
                attackers[t.target_id].add(atk.id)
        elif t.type == "undermine":
            for a in g.arguments:
                if applicable[a.id] and t.target_id in a.premise_ids:
                    attackers[a.id].add(atk.id)
        # rebuts are handled at the claim level
    return attackers


def grounded_labelling(attackers: dict[str, set[str]]) -> dict[str, Status]:
    labels: dict[str, Status] = {n: "undecided" for n in attackers}
    changed = True
    while changed:
        changed = False
        for n, atks in attackers.items():
            if labels[n] != "undecided":
                continue
            if all(labels[x] == "out" for x in atks):
                labels[n] = "in"
                changed = True
            elif any(labels[x] == "in" for x in atks):
                labels[n] = "out"
                changed = True
    return labels


# ---------------------------------------------------------------------------
# Proof standards
# ---------------------------------------------------------------------------

def _meets(standard: ProofStandard, pro: int, con: int, n_pro: int) -> bool:
    if n_pro == 0:
        return False
    if standard == "scintilla":
        return True
    if standard == "preponderance":
        return pro > con
    if standard == "clear_and_convincing":
        return pro >= 3 and pro - con >= 1
    if standard == "beyond_reasonable_doubt":
        return pro >= 3 and con == 0
    raise ValueError(standard)


def _claim_pass(g: ArgumentGraph, labels: dict[str, Status], strengths: dict[str, Strength]) -> dict[str, ClaimDetail]:
    details: dict[str, ClaimDetail] = {}

    def in_support(cid: str) -> list[Argument]:
        return [a for a in g.arguments_for(cid) if labels.get(a.id) == "in"]

    def in_rebuts(cid: str) -> list[Argument]:
        out: list[Argument] = []
        for a in g.arguments:
            if not a.is_attack or a.attacks.type != "rebut" or labels.get(a.id) != "in":
                continue
            tgt = a.attacks.target_id
            if tgt == cid:
                out.append(a)
            else:
                ta = g.arg(tgt)
                if ta is not None and ta.claim_id == cid:
                    out.append(a)
        return out

    for c in g.claims:
        pro = in_support(c.id)
        con = in_rebuts(c.id)
        for other in c.contrary_ids:
            con.extend(in_support(other))
        pro_s = max((STRENGTH_ORDER[strengths[a.id]] for a in pro), default=0)
        con_s = max((STRENGTH_ORDER[strengths[a.id]] for a in con), default=0)
        corroborated = _corroborated({a.id: argument_origins(g, a, labels=labels) for a in pro})
        if corroborated and pro_s:
            pro_s = min(3, pro_s + 1)
        if pro and all(a.scheme == "composition" for a in pro):
            # Recombining the same findings cannot amplify their strength.
            pro_s = max(STRENGTH_ORDER[strengths[a.id]] for a in pro)
        standard = g.standard_for(c)
        met = _meets(standard, pro_s, con_s, len(pro))
        details[c.id] = ClaimDetail(
            standard=standard, status="undecided",
            pro_ids=[a.id for a in pro], con_ids=[a.id for a in con],
            pro_strength=pro_s, con_strength=con_s, corroborated=corroborated, met=met,
        )

    # status: IN if met and no contrary met; OUT if a contrary is IN or only con survives
    for c in g.claims:
        d = details[c.id]
        contrary_met = any(details[o].met for o in c.contrary_ids if o in details)
        if d.met and not contrary_met:
            d.status = "in"
        elif contrary_met and not d.met:
            d.status = "out"
        elif not d.pro_ids and d.con_ids:
            d.status = "out"
        else:
            d.status = "undecided"
    return details


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def check_composition_scope(g: ArgumentGraph, a: Argument) -> bool:
    """Project different outcomes onto the conclusion, then forbid extrapolation.

    Sub-scope alone would permit 70+ premises to license 60+. Composition
    instead requires equality on the dimensions shared by the components.
    """
    conclusion = g.claim(a.claim_id)
    components = [g.claim(pid) for pid in a.premise_ids]
    valid = conclusion is not None and len(components) >= 2 and all(components)
    if valid:
        for c in components:
            projected = c.scope.model_copy(update={"outcome": conclusion.scope.outcome,
                                                   "relation": conclusion.scope.relation})
            valid = valid and sub_scope(projected, conclusion.scope) and all(
                canonical(getattr(c.scope, field)) == canonical(getattr(conclusion.scope, field))
                for field in ("population", "period", "comparison"))
    outcome = "satisfied" if valid else "unsatisfied"
    answer = "Components share the conclusion's population, comparison and period" if valid else "Components do not share the conclusion's scope; extrapolation is not licensed"
    previous = a.cq.get("same_scope")
    if previous is None or previous.outcome != outcome or previous.answer_move != "evaluate":
        g.answer_cq(a.id, "same_scope", answer, outcome=outcome, answer_move="evaluate")
    return bool(valid)


def evaluate(g: ArgumentGraph, max_iter: int = 10) -> Evaluation:
    g.refresh_answerhood()
    for a in g.arguments:
        if a.scheme == "composition":
            check_composition_scope(g, a)
    accepted: set[str] = set()
    strengths = {a.id: argument_strength(g, a) for a in g.arguments}
    applicable: dict[str, bool] = {}
    reasons: dict[str, list[str]] = {}
    labels: dict[str, Status] = {}
    details: dict[str, ClaimDetail] = {}
    converged = False
    reopened: set[tuple[str, str]] = set()

    def reopenings(applicable_, labels_):
        return {(a.attacks.target_id, a.attacks.raises_cq) for a in g.arguments
                if a.is_attack and a.attacks.basis == "answer_inadequate" and a.attacks.type == "undercut"
                and applicable_.get(a.id, False) and labels_.get(a.id) == "in" and not _discharged(g, a)}

    for _ in range(max_iter):
        prior_strengths = strengths
        strengths = {a.id: argument_strength(g, a, details) for a in g.arguments}
        # Label attacks before deriving reopenings; then re-evaluate targets.
        # Include reopenings in convergence so accepted-set stability cannot
        # prematurely stop a counterattack from restoring its target.
        attack_applicable, _ = _applicability(g, accepted, reopened)
        attack_labels = grounded_labelling(_attack_edges(g, attack_applicable))
        next_reopened = reopenings(attack_applicable, attack_labels)
        applicable, reasons = _applicability(g, accepted, next_reopened)
        labels = grounded_labelling(_attack_edges(g, applicable))
        details = _claim_pass(g, labels, strengths)
        new_accepted = {cid for cid, d in details.items() if d.status == "in"}
        if (new_accepted == accepted and strengths == prior_strengths and next_reopened == reopened
                and reopenings(applicable, labels) == next_reopened):
            converged = True
            break
        accepted = new_accepted
        reopened = next_reopened

    ev = Evaluation(applicable=applicable, inapplicable_reasons=reasons, argument_strength=strengths,
                    labels=labels, claims=details, converged=converged,
                    reopened_cqs={aid: sorted(qid for target, qid in next_reopened if target == aid)
                                  for aid in sorted({target for target, _ in next_reopened})} if max_iter else {})
    for iss in g.issues:
        # live claims that still answer the issue as posed; a component finding does not answer it
        ev.issues[iss.id] = [c.id for c in g.claims_for_issue(iss.id) if details[c.id].status == "in" and c.answers_issue]
    for claim in g.claims:
        details[claim.id].label, details[claim.id].label_reason = claim_status_label(g, ev, claim.id)
    ev.flags = _flags(g, ev)
    return ev


def claim_status_label(g: ArgumentGraph, ev: Evaluation, claim_id: str) -> tuple[str, str]:
    """Six report labels, without changing the compatible proof statuses."""
    claim = g.claim(claim_id)
    detail = ev.claims[claim_id]
    if detail.status == "in":
        return "accepted", "surviving support meets the proof standard"
    if any(ev.status(cid) == "in" and g.claim(cid) and g.claim(cid).live for cid in claim.contrary_ids):
        return "refuted", "a contrary claim is accepted"
    built = g.arguments_for(claim_id)
    def standing(argument):
        return not argument.withdrawn and ev.applicable.get(argument.id, False) and ev.labels.get(argument.id) != "out"
    pro = [a for a in built if standing(a)]
    contrary = {a.id: a for cid in claim.contrary_ids for a in g.arguments_for(cid) if standing(a)}
    for a in g.arguments:
        if not a.is_attack or a.attacks.type != "rebut" or not standing(a):
            continue
        target = g.arg(a.attacks.target_id)
        if a.attacks.target_id == claim_id or (target and target.claim_id == claim_id):
            contrary[a.id] = a
    if pro and contrary:
        return "contested", "standing pro and con arguments prevent an accepted answer"
    if built and all(a.withdrawn or not ev.applicable.get(a.id, False) or ev.labels.get(a.id) == "out" for a in built):
        return "defeated", "all constructed support is out, withdrawn or inapplicable"
    bearing = any(claim_id in e.bears_on for e in g.evidence) or bool(built)
    if not bearing:
        return "untested", "no evidence bears on the claim and no argument tests it"
    if not built:
        return "unsupported", "evidence bears on the claim but no supporting argument was built"
    # The requested six labels do not name weak, unopposed support below its
    # proof standard. Keep it explicit and never reward it as contested.
    return "unsupported", "constructed support is insufficient for the proof standard without a standing pro/con contest"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

def _flags(g: ArgumentGraph, ev: Evaluation) -> list[Flag]:
    flags: list[Flag] = []
    if not ev.converged:
        flags.append(Flag(code="not_converged", detail="acceptance did not reach a fixed point; check for cycles through premise claims"))
    for aid, why in ev.inapplicable_reasons.items():
        flags.append(Flag(code="inapplicable_argument", node_id=aid, detail="; ".join(why)))
    used = {pid for a in g.arguments for pid in a.premise_ids}
    for e in g.evidence:
        if e.id not in used and not e.provenance.get("unusable") and e.role == "evidence":
            flags.append(Flag(code="orphan_evidence", node_id=e.id, detail="evidence used in no argument"))
    for a in g.arguments:
        if a.is_attack or a.withdrawn:
            continue
        bad = [p for p in a.premise_ids if g.ev(p) is not None and g.ev(p).role in ("context", "lead")]
        if bad:
            flags.append(Flag(code="context_as_premise", node_id=a.id,
                              detail=f"{', '.join(bad)} reclassified as context or lead but still used as grounds"))
    for a in g.arguments:
        if a.is_attack or not a.claim_id:
            continue
        for pid in a.premise_ids:
            e = g.ev(pid)
            src = g.source(e.source_id) if e is not None and e.source_id else None
            if src is None or not src.derived_from:
                continue
            if any(x.source_id == src.derived_from and a.claim_id in x.bears_on for x in g.evidence):
                flags.append(Flag(code="derivative_premise", node_id=a.id,
                                  detail=f"{pid} relays {src.derived_from}, whose own evidence bears on {a.claim_id}"))
                break
    keys: dict[str, list[str]] = {}
    for s in g.sources:
        keys.setdefault(g.origin_key(s), []).append(s.id)
    for key, ids in keys.items():
        if len(ids) < 2:
            continue
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                sa, sb = g.source(a), g.source(b)
                if sa.derived_from == b or sb.derived_from == a:
                    continue
                flags.append(Flag(code="duplicate_source", node_id=f"{a},{b}",
                                  detail=f"same origin ({key}) and neither is marked as derived from the other"))
    for c in g.claims:
        d = ev.claims[c.id]
        if not c.live:
            continue
        if d.status == "in":
            origins = _all_origins({x: argument_origins(g, g.arg(x)) for x in d.pro_ids})
            if len(origins) <= 1:
                flags.append(Flag(code="single_origin", node_id=c.id, detail="accepted on evidence from one origin"))
        if c.credence is not None:
            if c.credence >= 0.7 and d.status != "in":
                flags.append(Flag(code="credence_status_mismatch", node_id=c.id, detail=f"credence {c.credence:.2f} but status {d.status}"))
            if c.credence <= 0.3 and d.status != "out":
                flags.append(Flag(code="credence_status_mismatch", node_id=c.id, detail=f"credence {c.credence:.2f} but status {d.status}"))
        if d.met and any(ev.claims[o].met for o in c.contrary_ids if o in ev.claims):
            flags.append(Flag(code="contraries_both_meet_standard", node_id=c.id, detail="raise the standard or find discriminating evidence"))
    if g.main_issue_id and not ev.issues.get(g.main_issue_id):
        components = [c.id for c in g.claims_for_issue(g.main_issue_id)
                      if ev.claims[c.id].status == "in" and not c.answers_issue]
        detail = "no accepted claim answers the main issue"
        if components:
            detail += f"; accepted component findings that do not answer it as posed: {', '.join(components)}"
        flags.append(Flag(code="main_issue_unresolved", node_id=g.main_issue_id, detail=detail))
    for c in g.claims:
        if c.live and ev.claims[c.id].status == "in" and c.revision_of is None:
            # an accepted claim that carries a number should say what it is a number of
            if _NUMBER.search(c.text) and not c.target:
                flags.append(Flag(code="untyped_quantity", node_id=c.id,
                                  detail="accepted claim states a quantity but no target (population, outcome, horizon, quantity) is recorded"))
    return flags


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|µg|ug|mg|per\b|/\s*1,?000|percentage points|pp\b|µ)", re.I)


# ---------------------------------------------------------------------------
# Load-bearing analysis
# ---------------------------------------------------------------------------

def load_bearing(g: ArgumentGraph, claim_id: str) -> list[LoadBearing]:
    """
    Which single node, if removed or reopened, changes the status of `claim_id`?
    This is the computable core of the reflect move: the load-bearing
    assumption is a node on this list, not an introspective guess.
    """
    base = evaluate(g).status(claim_id)
    out: list[LoadBearing] = []

    def probe(mutate, kind, node_id, detail):
        g2 = g.model_copy(deep=True)
        mutate(g2)
        s = evaluate(g2).status(claim_id)
        if s != base:
            out.append(LoadBearing(node_id=node_id, kind=kind, detail=detail, effect=s, claim_id=claim_id))

    for e in g.evidence:
        def drop_ev(g2, eid=e.id):
            g2.evidence = [x for x in g2.evidence if x.id != eid]
            for a in g2.arguments:
                if eid in a.premise_ids:
                    a.premise_ids = [p for p in a.premise_ids if p != eid]
                    # an argument that lost a premise can no longer be applied
                    for q in SCHEMES[a.scheme].assumptions():
                        a.cq[q.id].status = "open"
        probe(drop_ev, "evidence", e.id, e.text[:80])

    for a in g.arguments:
        def drop_arg(g2, aid=a.id):
            g2.arguments = [x for x in g2.arguments if x.id != aid]
        probe(drop_arg, "argument", a.id, f"{a.scheme} -> {a.claim_id or a.attacks.target_id}")
        for qid, ans in a.cq.items():
            if ans.status == "open":
                continue
            def reopen(g2, aid=a.id, qid=qid):
                g2.arg(aid).cq[qid].status = "open"
            probe(reopen, "cq_answer", f"{a.id}:{qid}", SCHEMES[a.scheme].cq(qid).text)

    return out


# ---------------------------------------------------------------------------
# What would settle an undecided claim
# ---------------------------------------------------------------------------

SettlerKind = Literal[
    "no_argument",        # nothing supports the claim yet
    "open_assumption",    # a supporting argument has an unanswered assumption
    "premise_claim",      # a supporting argument rests on a claim not yet accepted
    "defeated_by",        # a supporting argument is out because an attack on it is in
    "strength_short",     # surviving support does not reach the proof standard
    "corroboration",      # a second independent origin would raise strength one level
    "rebutted",           # an in rebuttal counts against the claim
    "contrary_supported", # a contrary claim has surviving support
]


class Settler(BaseModel):
    claim_id: str
    kind: SettlerKind
    node_id: str = ""
    detail: str = ""


_REQUIRED = {"scintilla": 1, "clear_and_convincing": 3, "beyond_reasonable_doubt": 3}


def what_would_settle(g: ArgumentGraph, claim_id: str, ev: Optional[Evaluation] = None) -> list[Settler]:
    """
    For a claim that is not IN, list the concrete things that stand between it
    and acceptance. This is what Plan should target next and what Stop checks:
    if nothing on this list can be addressed by obtainable evidence, further
    search has no value.
    """
    ev = ev or evaluate(g)
    if claim_id not in ev.claims:
        raise KeyError(claim_id)
    d = ev.claims[claim_id]
    out: list[Settler] = []
    if d.status == "in":
        return out

    pro_args = g.arguments_for(claim_id)
    if not pro_args:
        out.append(Settler(claim_id=claim_id, kind="no_argument",
                           detail="no argument supports this claim; evidence bearing on it is needed"))

    for a in pro_args:
        if not ev.applicable.get(a.id, False):
            for why in ev.inapplicable_reasons.get(a.id, []):
                if why.startswith("open assumption: "):
                    qid = why.split(": ", 1)[1]
                    out.append(Settler(claim_id=claim_id, kind="open_assumption", node_id=f"{a.id}:{qid}",
                                       detail=SCHEMES[a.scheme].cq(qid).text))
                elif why.startswith("premise claim not accepted: "):
                    pid = why.split(": ", 1)[1]
                    out.append(Settler(claim_id=claim_id, kind="premise_claim", node_id=pid,
                                       detail=f"{a.id} rests on {pid}, which is not accepted"))
        elif ev.labels.get(a.id) == "out":
            for atk in g.arguments:
                if not atk.is_attack or ev.labels.get(atk.id) != "in":
                    continue
                t = atk.attacks
                hits = (t.type == "undercut" and t.target_id == a.id) or \
                       (t.type == "undermine" and t.target_id in a.premise_ids)
                if hits:
                    out.append(Settler(claim_id=claim_id, kind="defeated_by", node_id=atk.id,
                                       detail=f"{a.id} is out because {atk.id} ({t.type}) stands: {atk.note or 'answer or undercut it'}"))

    if d.pro_ids and not d.met:
        required = _REQUIRED.get(d.standard, d.con_strength + 1)
        out.append(Settler(claim_id=claim_id, kind="strength_short",
                           detail=f"pro strength {d.pro_strength} vs con {d.con_strength}; {d.standard} needs {required}"))
        if not d.corroborated:
            out.append(Settler(claim_id=claim_id, kind="corroboration",
                               detail="support comes from one origin; an independent second origin would raise strength one level"))

    for cid in d.con_ids:
        a = g.arg(cid)
        if a is None:
            continue
        if a.is_attack:
            out.append(Settler(claim_id=claim_id, kind="rebutted", node_id=a.id,
                               detail=f"rebuttal {a.id} stands: {a.note or 'answer or undercut it'}"))
        else:
            out.append(Settler(claim_id=claim_id, kind="contrary_supported", node_id=a.id,
                               detail=f"{a.id} supports contrary {a.claim_id}"))
    return out
