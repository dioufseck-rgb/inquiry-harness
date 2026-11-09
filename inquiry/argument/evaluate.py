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

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .graph import (
    STRENGTH_ORDER, Argument, ArgumentGraph, Claim, ProofStandard, Status, Strength,
)
from .schemes import SCHEMES

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

    def status(self, claim_id: str) -> Status:
        return self.claims[claim_id].status if claim_id in self.claims else "undecided"


# ---------------------------------------------------------------------------
# Strength
# ---------------------------------------------------------------------------

def argument_strength(g: ArgumentGraph, a: Argument) -> Strength:
    base = STRENGTH_ORDER[a.strength_override or SCHEMES[a.scheme].default_strength]
    for pid in a.premise_ids:
        e = g.ev(pid)
        if e is not None:
            base = min(base, STRENGTH_ORDER[e.credentials.effective()])
    # an assumption accepted without evidence weakens the argument one level
    sch = SCHEMES[a.scheme]
    if any(a.cq.get(q.id) and a.cq[q.id].status == "defaulted" for q in sch.assumptions()):
        base = max(1, base - 1)
    return _LEVEL[base]  # type: ignore[return-value]


def _independence_groups(g: ArgumentGraph, args: list[Argument]) -> set[str]:
    """
    Distinct origins among the evidence used by `args`. A derivative source
    that does not name its origin contributes no origin: it repeats something,
    and we do not know what, so it cannot corroborate anything.
    """
    groups: set[str] = set()
    for a in args:
        for pid in a.premise_ids:
            e = g.ev(pid)
            if e is None:
                continue
            src = g.source(e.source_id) if e.source_id else None
            if src is not None and src.kind == "derivative" and not src.derived_from:
                continue
            groups.add(e.independence_group or f"source:{e.source_id or e.id}")
    return groups


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------

def _applicability(g: ArgumentGraph, accepted: set[str]) -> tuple[dict[str, bool], dict[str, list[str]]]:
    applicable: dict[str, bool] = {}
    reasons: dict[str, list[str]] = {}
    for a in g.arguments:
        why: list[str] = []
        sch = SCHEMES[a.scheme]
        for q in sch.assumptions():
            st = a.cq.get(q.id)
            if st is None or st.status == "open":
                why.append(f"open assumption: {q.id}")
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

def _attack_edges(g: ArgumentGraph, applicable: dict[str, bool]) -> dict[str, set[str]]:
    """target argument id -> set of attacker argument ids (undercuts and undermines only)."""
    attackers: dict[str, set[str]] = {a.id: set() for a in g.arguments if applicable[a.id]}
    for atk in g.arguments:
        if not atk.is_attack or not applicable[atk.id]:
            continue
        t = atk.attacks
        if t.type == "undercut":
            if t.target_id in attackers:
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
        corroborated = len(_independence_groups(g, pro)) >= 2
        if corroborated and pro_s:
            pro_s = min(3, pro_s + 1)
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

def evaluate(g: ArgumentGraph, max_iter: int = 10) -> Evaluation:
    accepted: set[str] = set()
    strengths = {a.id: argument_strength(g, a) for a in g.arguments}
    applicable: dict[str, bool] = {}
    reasons: dict[str, list[str]] = {}
    labels: dict[str, Status] = {}
    details: dict[str, ClaimDetail] = {}
    converged = False
    for _ in range(max_iter):
        applicable, reasons = _applicability(g, accepted)
        labels = grounded_labelling(_attack_edges(g, applicable))
        details = _claim_pass(g, labels, strengths)
        new_accepted = {cid for cid, d in details.items() if d.status == "in"}
        if new_accepted == accepted:
            converged = True
            break
        accepted = new_accepted

    ev = Evaluation(applicable=applicable, inapplicable_reasons=reasons, argument_strength=strengths,
                    labels=labels, claims=details, converged=converged)
    for iss in g.issues:
        ev.issues[iss.id] = [c.id for c in g.claims_for_issue(iss.id) if details[c.id].status == "in"]
    ev.flags = _flags(g, ev)
    return ev


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
        if e.id not in used and not e.provenance.get("unusable"):
            flags.append(Flag(code="orphan_evidence", node_id=e.id, detail="evidence used in no argument"))
    for c in g.claims:
        d = ev.claims[c.id]
        if d.status == "in":
            pro = [g.arg(x) for x in d.pro_ids]
            if len(_independence_groups(g, pro)) == 1:
                flags.append(Flag(code="single_origin", node_id=c.id, detail="accepted on evidence from one origin"))
        if c.credence is not None:
            if c.credence >= 0.7 and d.status != "in":
                flags.append(Flag(code="credence_status_mismatch", node_id=c.id, detail=f"credence {c.credence:.2f} but status {d.status}"))
            if c.credence <= 0.3 and d.status != "out":
                flags.append(Flag(code="credence_status_mismatch", node_id=c.id, detail=f"credence {c.credence:.2f} but status {d.status}"))
        if d.met and any(ev.claims[o].met for o in c.contrary_ids if o in ev.claims):
            flags.append(Flag(code="contraries_both_meet_standard", node_id=c.id, detail="raise the standard or find discriminating evidence"))
    if g.main_issue_id and not ev.issues.get(g.main_issue_id):
        flags.append(Flag(code="main_issue_unresolved", node_id=g.main_issue_id, detail="no accepted claim answers the main issue"))
    return flags


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
