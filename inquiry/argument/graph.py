"""
The argument graph — primary state of the research harness.

Node kinds (AIF vocabulary in brackets):

    Issue      a question under inquiry; IBIS-style, with candidate claims as answers
    Claim      a proposition that may answer an issue           [I-node]
    Evidence   a proposition grounded in a source, with Schum credentials   [I-node]
    Argument   premises -> claim through a named scheme         [RA-node]
               or, when `attacks` is set, an attack on another node [CA-node]

Relations are carried on the nodes:
    Argument.premise_ids      evidence or claims used as premises
    Argument.claim_id         the conclusion (for supporting arguments)
    Argument.attacks          {target_id, type} for attack arguments
    Claim.contrary_ids        rival claims (mutually exclusive answers)
    Claim.issue_id            the issue this claim answers

Everything is plain pydantic so the graph serializes to JSON and the
ledger can hash it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


Strength = Literal["weak", "moderate", "strong"]
STRENGTH_ORDER: dict[str, int] = {"weak": 1, "moderate": 2, "strong": 3}

ProofStandard = Literal["scintilla", "preponderance", "clear_and_convincing", "beyond_reasonable_doubt"]
QuestionType = Literal["empirical", "causal", "predictive", "evaluative", "conceptual", "design", "mixed"]

DEFAULT_STANDARD: dict[str, ProofStandard] = {
    "empirical": "preponderance",
    "causal": "clear_and_convincing",
    "predictive": "preponderance",
    "evaluative": "preponderance",
    "conceptual": "preponderance",
    "design": "preponderance",
    "mixed": "preponderance",
}

AttackType = Literal["undermine", "rebut", "undercut"]
Status = Literal["in", "out", "undecided"]
Origin = Literal["proposer", "critic", "human", "instrument"]

_DOI = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.I)


# ---------------------------------------------------------------------------
# Issues and claims
# ---------------------------------------------------------------------------

class Issue(BaseModel):
    id: str
    text: str
    answerhood: str = Field(default="", description="What a complete answer would contain.")
    question_type: QuestionType = "mixed"
    parent_id: Optional[str] = None
    depends_on: list[str] = Field(default_factory=list)
    status: Literal["open", "answered", "dropped"] = "open"
    presuppositions: list[str] = Field(default_factory=list)
    search_topic: str = ""


class Claim(BaseModel):
    id: str
    text: str
    issue_id: Optional[str] = None
    kind: Literal["substantive", "null", "deflationary"] = "substantive"
    contrary_ids: list[str] = Field(default_factory=list)
    proof_standard: Optional[ProofStandard] = Field(
        default=None, description="Override; otherwise derived from the issue's question type."
    )
    credence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Optional numeric credence. Not used by evaluation in v1; checked for coherence only.",
    )
    origin: Origin = "proposer"
    rationale: str = ""
    target: dict[str, str] = Field(
        default_factory=dict,
        description="What the claim is about, where changing it would change the answer: population, intervention, "
                    "comparator, outcome, horizon, quantity, scope, evidence_status.")
    superseded_by: Optional[str] = Field(default=None, description="Set when a revision replaced this claim.")
    revision_of: Optional[str] = Field(default=None, description="The claim this one narrowed or split from.")
    review_note: str = Field(default="", description="Why a criticism did or did not change this claim.")
    answers_issue: bool = Field(
        default=True,
        description="False when a revision narrowed the claim to a population, outcome or horizon that no longer "
                    "answers the issue as posed; it is then a component finding, not an answer.")

    @property
    def live(self) -> bool:
        return self.superseded_by is None


# ---------------------------------------------------------------------------
# Evidence (Schum credentials)
# ---------------------------------------------------------------------------

EvidenceKind = Literal["tangible", "testimonial", "statistical", "model_output", "missing", "negative"]


class Credentials(BaseModel):
    """
    Schum's three credentials of evidence.

    relevance   how directly the item bears on the claim it is used for
    credibility for testimonial evidence: the source's veracity, objectivity
                and access to the facts; for tangible evidence: authenticity
                and accuracy
    force       the inferential force the item carries once relevance and
                credibility are taken into account — the weakest link rules
    """
    relevance: Strength = "moderate"
    credibility: Strength = "moderate"
    force: Strength = "moderate"
    credibility_notes: str = ""

    def effective(self) -> Strength:
        lo = min(STRENGTH_ORDER[self.relevance], STRENGTH_ORDER[self.credibility], STRENGTH_ORDER[self.force])
        return {1: "weak", 2: "moderate", 3: "strong"}[lo]  # type: ignore[return-value]


class Evidence(BaseModel):
    id: str
    text: str = Field(description="What the source establishes, in our words.")
    kind: EvidenceKind = "tangible"
    source_id: Optional[str] = None
    quote: str = Field(default="", description="Short verbatim passage, under 300 characters.")
    location: str = ""
    credentials: Credentials = Field(default_factory=Credentials)
    independence_group: str = Field(
        default="", description="Shared by evidence tracing to one origin; counted once."
    )
    origin: Origin = "proposer"
    provenance: dict[str, str] = Field(
        default_factory=dict,
        description="For model_output: model version, parameters, seed, run id.",
    )
    bears_on: dict[str, Literal["for", "against", "neutral"]] = Field(
        default_factory=dict,
        description="claim id -> direction this item bears on it, as appraised. A hint for Argue, not an argument.",
    )
    role: Literal["evidence", "context", "indirect", "lead"] = Field(
        default="evidence",
        description="evidence grounds arguments; context informs but grounds nothing; indirect bears on a claim only "
                    "through a stated bridge; lead points to something worth retrieving.")


class Source(BaseModel):
    id: str
    url: str = ""
    title: str = ""
    publisher: str = ""
    date: str = ""
    fetched_at: str = Field(default_factory=now_iso)
    kind: Literal["primary", "secondary", "derivative", "unknown"] = "unknown"
    derived_from: Optional[str] = Field(default=None, description="Source id of the original, for derivative sources.")
    derived_from_note: str = Field(default="", description="Named origin that is not (yet) a source in the graph.")
    competence: str = ""
    incentives: str = ""
    text_path: str = ""
    query: str = ""
    read_fully: bool = Field(default=False, description="True when every part of the text has been appraised.")


# ---------------------------------------------------------------------------
# Arguments and attacks
# ---------------------------------------------------------------------------

CQStatus = Literal["open", "answered", "defaulted"]
CQOutcome = Literal["", "satisfied", "unsatisfied", "unresolved"]


class CQAnswer(BaseModel):
    """
    Three things are kept apart: whether the check was performed (status),
    what it established (outcome), and what followed (the evaluator's use of
    it). An answer that establishes the condition does NOT hold ("this
    measures a different outcome") is `unsatisfied`; it makes the argument
    inapplicable rather than counting as a discharged question. An empty
    outcome on an answered question means satisfied, for older graphs.
    """
    status: CQStatus = "open"
    outcome: CQOutcome = ""
    answer: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    revision: int = 0
    answer_move: str = ""

    @property
    def satisfied(self) -> bool:
        return self.status == "answered" and self.outcome in ("", "satisfied")


class Attack(BaseModel):
    target_id: str
    type: AttackType
    note: str = ""
    basis: Literal["presence", "absence", "answer_inadequate"] = "presence"
    challenged_revision: int = -1
    answer_quote: str = ""
    was_reopened: bool = False
    raises_cq: str = Field(
        default="",
        description="For an undercut: the critical question of the target it raises. Answering that question "
                    "with evidence discharges the attack.")


class Argument(BaseModel):
    id: str
    scheme: str
    premise_ids: list[str] = Field(default_factory=list)
    claim_id: Optional[str] = Field(default=None, description="Conclusion, for supporting arguments.")
    attacks: Optional[Attack] = Field(default=None, description="Set for attack arguments.")
    cq: dict[str, CQAnswer] = Field(
        default_factory=dict, description="critical question id -> status and answer."
    )
    strength_override: Optional[Strength] = None
    origin: Origin = "proposer"
    note: str = ""
    round: int = 0
    withdrawn: str = Field(default="", description="Set when the support relation was removed on review; the reason. "
                                                  "A withdrawn argument neither supports nor attacks; its evidence stays.")

    @property
    def is_attack(self) -> bool:
        return self.attacks is not None


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

class ArgumentGraph(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    arguments: list[Argument] = Field(default_factory=list)
    main_issue_id: Optional[str] = None

    # -- lookups ------------------------------------------------------------

    def issue(self, iid: str) -> Optional[Issue]:
        return next((x for x in self.issues if x.id == iid), None)

    def claim(self, cid: str) -> Optional[Claim]:
        return next((x for x in self.claims if x.id == cid), None)

    def ev(self, eid: str) -> Optional[Evidence]:
        return next((x for x in self.evidence if x.id == eid), None)

    def source(self, sid: str) -> Optional[Source]:
        return next((x for x in self.sources if x.id == sid), None)

    def arg(self, aid: str) -> Optional[Argument]:
        return next((x for x in self.arguments if x.id == aid), None)

    def node(self, nid: str):
        return self.issue(nid) or self.claim(nid) or self.ev(nid) or self.arg(nid) or self.source(nid)

    def arguments_for(self, claim_id: str) -> list[Argument]:
        return [a for a in self.arguments if a.claim_id == claim_id and not a.is_attack]

    def attacks_on(self, target_id: str) -> list[Argument]:
        return [a for a in self.arguments if a.is_attack and a.attacks.target_id == target_id]

    def claims_for_issue(self, issue_id: str, live_only: bool = True) -> list[Claim]:
        issue = self.issue(issue_id)
        if issue is not None and issue.status == "dropped":
            return []
        return [c for c in self.claims if c.issue_id == issue_id and (c.live or not live_only)]

    def live_claims(self) -> list[Claim]:
        return [c for c in self.claims if c.live]

    def supersede_claim(self, old_id: str, texts: list[str], carry_arguments: list[str] | None = None,
                        kind: Optional[str] = None, target: Optional[dict[str, str]] = None,
                        reason: str = "", answers_issue: bool = True) -> list[Claim]:
        """
        Replace a claim with one (narrow) or several (split) revised claims on
        the same issue. Rivals of the old claim become rivals of each new one;
        supporting arguments listed in carry_arguments move to the first new
        claim (or to the one named as "<id>@<index>"); the rest are withdrawn
        with the reason, keeping their evidence. Attacks on the old claim stay
        where they are and become inert with it.
        """
        old = self.claim(old_id)
        if old is None:
            raise KeyError(old_id)
        if not old.live:
            raise ValueError(f"{old_id} is already superseded by {old.superseded_by}")
        texts = [t.strip() for t in texts if t.strip()]
        if not texts:
            raise ValueError("a revision needs at least one claim text")
        new: list[Claim] = []
        for t in texts:
            c = self.add_claim(t, issue_id=old.issue_id, kind=kind or old.kind, origin=old.origin,
                               rationale=f"revision of {old.id}: {reason}" if reason else f"revision of {old.id}",
                               target=dict(target or {}), revision_of=old.id, answers_issue=answers_issue)
            new.append(c)
        rivals = [self.claim(o) for o in old.contrary_ids if self.claim(o) is not None and self.claim(o).live]
        for c in new:
            for r in rivals:
                if len(new) == 1 or r.kind in ("null", "deflationary"):
                    self.set_contraries(c.id, r.id)
        old.superseded_by = new[0].id
        old.review_note = reason
        carry: dict[str, int] = {}
        for item in carry_arguments or []:
            aid, _, idx = item.partition("@")
            carry[aid] = int(idx) if idx.isdigit() and int(idx) < len(new) else 0
        for a in self.arguments:
            if a.is_attack or a.claim_id != old.id:
                continue
            if a.id in carry:
                a.claim_id = new[carry[a.id]].id
            else:
                a.withdrawn = f"claim {old.id} revised to {', '.join(c.id for c in new)}; not carried over" + (f": {reason}" if reason else "")
        return new

    def standard_for(self, claim: Claim) -> ProofStandard:
        if claim.proof_standard:
            return claim.proof_standard
        # "the body recommends X" or "the report states X" is a matter of record, whatever the issue's
        # own standard: it is settled by showing the body said it, not by establishing X causally
        if claim.target.get("evidence_status", "").strip().lower() in ("recommended", "reported"):
            return "preponderance"
        issue = self.issue(claim.issue_id) if claim.issue_id else None
        return DEFAULT_STANDARD[issue.question_type if issue else "mixed"]

    # -- origins ------------------------------------------------------------------

    def origin_key(self, src: Source, _seen: Optional[set[str]] = None) -> str:
        """
        What a source ultimately traces to, for counting independent origins.
        DOI if the URL or title carries one; else the origin of the source it
        derives from; else its normalised title; else its publisher; else itself.
        """
        m = _DOI.search(src.url) or _DOI.search(src.title)
        if m:
            return "doi:" + m.group(0).lower().rstrip(".,;)")
        if src.derived_from:
            seen = _seen or set()
            if src.id not in seen:
                orig = self.source(src.derived_from)
                if orig is not None:
                    return self.origin_key(orig, seen | {src.id})
        t = re.sub(r"[^a-z0-9]+", "", src.title.lower())
        if len(t) >= 25:
            return "title:" + t[:60]
        if src.publisher.strip():
            return "publisher:" + src.publisher.strip().lower()
        return f"source:{src.id}"

    def evidence_origin(self, e: Evidence) -> Optional[str]:
        """
        Origin of one evidence item, or None when it cannot count as an origin:
        a derivative source that does not say what it derives from.
        """
        if e.independence_group:
            return e.independence_group
        src = self.source(e.source_id) if e.source_id else None
        if src is None:
            return f"evidence:{e.id}"
        if src.kind == "derivative" and not src.derived_from:
            return None
        return self.origin_key(src)

    # -- construction helpers ---------------------------------------------------

    def _next(self, prefix: str, items: list) -> str:
        return f"{prefix}{len(items) + 1}"

    def add_issue(self, text: str, **kw) -> Issue:
        x = Issue(id=self._next("Q", self.issues), text=text, **kw)
        self.issues.append(x)
        if self.main_issue_id is None:
            self.main_issue_id = x.id
        return x

    def add_claim(self, text: str, **kw) -> Claim:
        x = Claim(id=self._next("C", self.claims), text=text, **kw)
        self.claims.append(x)
        return x

    def set_contraries(self, *claim_ids: str) -> None:
        """Mark a set of claims as mutually exclusive answers."""
        for cid in claim_ids:
            c = self.claim(cid)
            if c is None:
                raise KeyError(cid)
            c.contrary_ids = sorted({*c.contrary_ids, *(o for o in claim_ids if o != cid)})

    def add_evidence(self, text: str, **kw) -> Evidence:
        x = Evidence(id=self._next("E", self.evidence), text=text, **kw)
        self.evidence.append(x)
        return x

    def add_source(self, **kw) -> Source:
        x = Source(id=self._next("S", self.sources), **kw)
        self.sources.append(x)
        return x

    def add_argument(self, scheme: str, premise_ids: list[str], claim_id: str, **kw) -> Argument:
        from .schemes import SCHEMES  # local import to avoid a cycle

        if scheme not in SCHEMES:
            raise KeyError(f"unknown scheme {scheme!r}")
        for pid in premise_ids:
            if self.ev(pid) is None and self.claim(pid) is None:
                raise KeyError(f"premise {pid!r} is not evidence or a claim")
        if self.claim(claim_id) is None:
            raise KeyError(f"claim {claim_id!r} not found")
        x = Argument(id=self._next("A", self.arguments), scheme=scheme, premise_ids=premise_ids,
                     claim_id=claim_id, **kw)
        # open every critical question of the scheme by default
        for cq in SCHEMES[scheme].critical_questions:
            x.cq.setdefault(cq.id, CQAnswer())
        self.arguments.append(x)
        return x

    def add_attack(self, target_id: str, type: AttackType, premise_ids: list[str] | None = None,
                   scheme: str = "attack", **kw) -> Argument:
        """
        An attack is an argument whose conclusion is that the target fails.
        undermine -> target is evidence (or a claim used as a premise)
        rebut     -> target is a claim or a supporting argument
        undercut  -> target is an argument (its inference is challenged)
        """
        target = self.node(target_id)
        if target is None:
            raise KeyError(f"target {target_id!r} not found")
        if type == "undercut" and not isinstance(target, Argument):
            raise ValueError("undercut must target an argument")
        if type == "undermine" and not isinstance(target, (Evidence, Claim)):
            raise ValueError("undermine must target evidence or a claim used as a premise")
        if type == "rebut" and not isinstance(target, (Claim, Argument)):
            raise ValueError("rebut must target a claim or an argument")
        from .schemes import SCHEMES

        for pid in premise_ids or []:
            if self.ev(pid) is None and self.claim(pid) is None:
                raise KeyError(f"premise {pid!r} is not evidence or a claim")
            if pid == target_id:
                raise ValueError(f"attack on {target_id} cannot use {target_id} as its own grounds")
            if type == "undermine" and isinstance(target, Evidence):
                p = self.ev(pid)
                if (p is not None and p.source_id and p.source_id == target.source_id
                        and p.location.strip() and p.location.strip().lower() == target.location.strip().lower()):
                    raise ValueError(f"undermine of {target_id} cannot be grounded in {pid}: the same passage "
                                     f"({target.location}) used against itself")
        x = Argument(id=self._next("A", self.arguments), scheme=scheme,
                     premise_ids=premise_ids or [], attacks=Attack(target_id=target_id, type=type), **kw)
        for cq in SCHEMES[scheme].critical_questions:
            x.cq.setdefault(cq.id, CQAnswer())
        # An attack needs grounds. Supplied premises discharge the assumption;
        # so does a human reviewer raising it, who is answerable for the grounds.
        if scheme == "attack" and "grounds" in x.cq:
            if premise_ids:
                x.cq["grounds"] = CQAnswer(status="answered", answer="premises supplied", evidence_ids=list(premise_ids))
            elif x.origin == "human":
                x.cq["grounds"] = CQAnswer(status="answered", answer="raised by human reviewer")
        self.arguments.append(x)
        return x

    def answer_cq(self, argument_id: str, cq_id: str, answer: str, evidence_ids: list[str] | None = None,
                  defaulted: bool = False, outcome: CQOutcome = "", answer_move: str = "") -> None:
        a = self.arg(argument_id)
        if a is None:
            raise KeyError(argument_id)
        revision = a.cq[cq_id].revision + 1 if cq_id in a.cq else 1
        a.cq[cq_id] = CQAnswer(status="defaulted" if defaulted else "answered", outcome=outcome,
                               answer=answer, evidence_ids=evidence_ids or [], revision=revision, answer_move=answer_move)

    # -- integrity ------------------------------------------------------------------

    def validate_refs(self) -> list[str]:
        """Return dangling references, if any."""
        problems = []
        ids = {n.id for n in [*self.issues, *self.claims, *self.evidence, *self.arguments, *self.sources]}
        for c in self.claims:
            if c.issue_id and c.issue_id not in ids:
                problems.append(f"{c.id}: issue {c.issue_id} missing")
            for o in c.contrary_ids:
                if o not in ids:
                    problems.append(f"{c.id}: contrary {o} missing")
        for e in self.evidence:
            if e.source_id and e.source_id not in ids:
                problems.append(f"{e.id}: source {e.source_id} missing")
        for a in self.arguments:
            for p in a.premise_ids:
                if p not in ids:
                    problems.append(f"{a.id}: premise {p} missing")
            if a.claim_id and a.claim_id not in ids:
                problems.append(f"{a.id}: claim {a.claim_id} missing")
            if a.attacks and a.attacks.target_id not in ids:
                problems.append(f"{a.id}: attack target {a.attacks.target_id} missing")
        return problems
