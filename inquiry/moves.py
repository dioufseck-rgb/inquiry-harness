"""
Moves of the cycle.

A model-backed move has three parts:

    view      a typed rendering of the relevant subgraph; this is the user
              message. The model never sees the transcript, only the view.
    contract  a pydantic schema the reply must satisfy; LLM.complete_json
              validates and retries once.
    apply     the deterministic update of the inquiry from a valid reply.
              Dangling ids are dropped, duplicates merged, and anything the
              model got wrong is recorded in the returned summary.

The skill text (inquiry/skills/<name>.md) is the system prompt. The
contracts here are the source of truth; skill text is adjusted to match.

Code-only moves (evaluate, reflect, stop) live here too so the cycle in
live.py is just sequencing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .argument.evaluate import Evaluation, Settler, evaluate, load_bearing, what_would_settle
from .argument.graph import (
    STRENGTH_ORDER, Argument, ArgumentGraph, AttackType, CQAnswer, Credentials, EvidenceKind, Issue, ProofStandard,
    QuestionType, Source, Strength,
)
from .argument.schemes import SCHEMES
from .llm import LLM
from .state import (
    Conclusion, Framing, Inquiry, Judgement, PlannedTest, Reflection, StopAssessment,
)
from .tools.compute import INSTRUMENT_VERSION, ComputeError, safe_eval

SKILLS_DIR = Path(__file__).parent / "skills"


def skill_text(name: str) -> str:
    return (SKILLS_DIR / f"{name}.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# View fragments
# ---------------------------------------------------------------------------

def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _framing_block(inq: Inquiry) -> str:
    f = inq.framing
    lines = [f"# Question\n\n{inq.question}", ""]
    if f.restatement:
        lines += [f"Restated: {f.restatement}", f"Type: {f.question_type}"]
        if f.answerhood:
            lines.append(f"A complete answer contains: {f.answerhood}")
        if f.scope_in:
            lines.append("In scope: " + "; ".join(f.scope_in))
        if f.scope_out:
            lines.append("Out of scope: " + "; ".join(f.scope_out))
        if f.presuppositions:
            lines.append("Presuppositions: " + "; ".join(f.presuppositions))
    return "\n".join(lines)


def _issues_block(inq: Inquiry, ev: Optional[Evaluation] = None, with_claims: bool = True) -> str:
    g = inq.graph
    lines = ["# Issues and claims", ""]
    for iss in g.issues:
        tag = " (main)" if iss.id == g.main_issue_id else ""
        dep = f" depends on {', '.join(iss.depends_on)}" if iss.depends_on else ""
        lines.append(f"- {iss.id}{tag} [{iss.question_type}]{dep}: {iss.text}")
        if iss.answerhood:
            lines.append(f"  complete answer: {iss.answerhood}")
        if with_claims:
            for c in g.claims_for_issue(iss.id):
                st = f" [{ev.status(c.id)}]" if ev else ""
                lines.append(f"  - {c.id} ({c.kind}){st}: {c.text}")
    return "\n".join(lines)


def _sources_block(g: ArgumentGraph) -> str:
    if not g.sources:
        return "# Sources\n\n(none yet)"
    lines = ["# Sources", ""]
    for s in g.sources:
        bits = [s.kind]
        if s.publisher:
            bits.append(s.publisher)
        if s.date:
            bits.append(s.date)
        lines.append(f"- {s.id} ({', '.join(bits)}): {s.title or s.url}  <{s.url}>")
    return "\n".join(lines)


def _evidence_block(g: ArgumentGraph, ids: Optional[list[str]] = None, title: str = "Evidence",
                    mark_unused: bool = False) -> str:
    items = [e for e in g.evidence if ids is None or e.id in ids]
    if not items:
        return f"# {title}\n\n(none)"
    used: dict[str, list[str]] = {}
    for a in g.arguments:
        for p in a.premise_ids:
            used.setdefault(p, []).append(a.id)
    lines = [f"# {title}", ""]
    for e in items:
        src = g.source(e.source_id) if e.source_id else None
        cred = e.credentials
        tag = ""
        if mark_unused and e.id not in used:
            tag = " UNUSED: no argument uses this item; attacking it changes nothing"
        if e.provenance.get("unusable"):
            tag = f" UNUSABLE: {e.provenance['unusable']}"
        origin = g.evidence_origin(e) or "none (derivative of an unnamed original)"
        lines.append(f"- {e.id} [{e.kind}; relevance {cred.relevance}, credibility {cred.credibility}, "
                     f"force {cred.force}; origin {origin}]"
                     f" from {src.id + ' ' + (src.title or src.url) if src else 'no source'}{tag}")
        lines.append(f"  text: {e.text}")
        if e.quote:
            lines.append(f"  quote: \"{_clip(e.quote, 300)}\" ({e.location or 'no location'})")
        if cred.credibility_notes:
            lines.append(f"  credibility notes: {cred.credibility_notes}")
        if e.bears_on:
            lines.append("  bears on: " + ", ".join(f"{k} {v}" for k, v in e.bears_on.items()))
        if e.id in used and used[e.id]:
            lines.append("  used in: " + ", ".join(used[e.id]))
    return "\n".join(lines)


def _schemes_block() -> str:
    lines = ["# Scheme catalogue", ""]
    for name, s in SCHEMES.items():
        if name == "attack":
            continue
        lines.append(f"## {name}: {s.title}")
        lines.append(s.description)
        lines.append("premises: " + "; ".join(s.premises))
        for q in s.critical_questions:
            lines.append(f"- {q.id} ({q.kind}, probes {q.probes}): {q.text}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _arguments_block(g: ArgumentGraph, ev: Optional[Evaluation], show_exceptions: bool = False) -> str:
    if not g.arguments:
        return "# Arguments\n\n(none yet)"
    lines = ["# Arguments", ""]
    for a in g.arguments:
        sch = SCHEMES[a.scheme]
        if a.is_attack:
            head = f"{a.id} {a.attacks.type} attack on {a.attacks.target_id} (origin {a.origin})"
        else:
            head = f"{a.id} {a.scheme} → {a.claim_id} (origin {a.origin})"
        if ev is not None:
            if not ev.applicable.get(a.id, True):
                head += " — INAPPLICABLE: " + "; ".join(ev.inapplicable_reasons.get(a.id, []))
            else:
                head += f" — {ev.labels.get(a.id, '?')}, strength {ev.argument_strength.get(a.id, '?')}"
        lines.append(f"- {head}")
        lines.append("  premises: " + (", ".join(a.premise_ids) or "(none)"))
        if a.note:
            lines.append(f"  note: {a.note}")
        for q in sch.critical_questions:
            st = a.cq.get(q.id)
            if q.kind == "exception" and not show_exceptions:
                continue
            status = st.status if st else "open"
            if st and st.status == "answered" and st.outcome and st.outcome != "satisfied":
                status = f"answered, {st.outcome}"
            ans = f" — {st.answer}" if st and st.answer else ""
            evs = f" [{', '.join(st.evidence_ids)}]" if st and st.evidence_ids else ""
            lines.append(f"  cq {q.id} ({q.kind}, probes {q.probes}) [{status}]: {q.text}{ans}{evs}")
    return "\n".join(lines)


def _settlers_block(inq: Inquiry, ev: Evaluation) -> str:
    g = inq.graph
    lines = ["# What stands between undecided claims and acceptance", ""]
    any_ = False
    for c in g.claims:
        if ev.status(c.id) == "in":
            continue
        settlers = what_would_settle(g, c.id, ev)
        if not settlers:
            continue
        any_ = True
        lines.append(f"- {c.id}: {c.text}")
        for s in settlers:
            node = f" ({s.node_id})" if s.node_id else ""
            lines.append(f"  - {s.kind}{node}: {s.detail}")
    if not any_:
        lines.append("(nothing recorded)")
    return "\n".join(lines)


def _tests_block(inq: Inquiry) -> str:
    if not inq.tests:
        return "# Tests already planned\n\n(none)"
    lines = ["# Tests already planned", ""]
    for t in inq.tests:
        lines.append(f"- {t.id} [{t.status}, round {t.round}, {t.diagnosticity}] on {', '.join(t.claim_ids)}: {t.observation}")
        lines.append("  queries: " + "; ".join(t.queries))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------

class SubIssue(BaseModel):
    text: str
    question_type: QuestionType = "mixed"
    answerhood: str = ""
    depends_on: list[int] = Field(default_factory=list, description="Zero-based indexes into sub_issues.")


class FrameOutput(BaseModel):
    restatement: str
    question_type: QuestionType = "mixed"
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    presuppositions: list[str] = Field(default_factory=list)
    answerhood: str = ""
    standard_override: Optional[ProofStandard] = None
    sub_issues: list[SubIssue] = Field(default_factory=list)


def frame_view(inq: Inquiry) -> str:
    return _framing_block(inq)


# a sub-issue about the inquiry itself rather than the world: robustness, sufficiency, reliability,
# meeting a standard, or whether sources are independent (not what independent sources report)
_META_ISSUE = re.compile(
    r"\b(robust|sufficien|reliab)|\bmeets?\s+(?:the\s+)?(?:\w+\s+){0,3}standard\b|"
    r"\b(?:are|is|were|was|whether|how)\b[^?.]{0,60}\bindependent\b",
    re.I)


def is_meta_issue(text: str) -> bool:
    return bool(_META_ISSUE.search(text))


def apply_frame(inq: Inquiry, out: FrameOutput) -> dict:
    g = inq.graph
    inq.framing = Framing(
        restatement=out.restatement, question_type=out.question_type, scope_in=out.scope_in,
        scope_out=out.scope_out, presuppositions=out.presuppositions, answerhood=out.answerhood,
        standard_override=out.standard_override,
    )
    main = g.add_issue(inq.question, question_type=out.question_type, answerhood=out.answerhood,
                       presuppositions=out.presuppositions)
    g.main_issue_id = main.id
    kept: list[tuple[int, SubIssue]] = []
    dropped: list[str] = []
    for i, s in enumerate(out.sub_issues):
        if is_meta_issue(s.text):
            dropped.append(s.text)
            inq.notes.append(f"frame: dropped sub-issue about the inquiry itself: {s.text}")
        else:
            kept.append((i, s))
    index_to_issue: dict[int, Issue] = {}
    for i, s in kept:
        index_to_issue[i] = g.add_issue(s.text, question_type=s.question_type, answerhood=s.answerhood, parent_id=main.id)
    for i, s in kept:
        iss = index_to_issue[i]
        iss.depends_on = [index_to_issue[j].id for j in s.depends_on if j in index_to_issue and j != i]
    inq.phase = "framed"
    return {"main_issue": main.id, "sub_issues": [x.id for x in index_to_issue.values()],
            "dropped": dropped, "question_type": out.question_type}


def frame(inq: Inquiry, llm: LLM) -> dict:
    out = llm.complete_json(skill_text("frame"), frame_view(inq), FrameOutput)
    return apply_frame(inq, out)


# ---------------------------------------------------------------------------
# Hypothesize
# ---------------------------------------------------------------------------

class ClaimProposal(BaseModel):
    issue_id: str
    text: str
    kind: Literal["substantive", "null", "deflationary"] = "substantive"
    rationale: str = ""


class HypothesizeOutput(BaseModel):
    claims: list[ClaimProposal]
    exclusive_groups: list[list[int]] = Field(
        default_factory=list,
        description="Lists of zero-based indexes into `claims` that are mutually exclusive answers (at most one true). "
                    "Claims in no group are contraries only of their issue's null and deflationary claims.")


def hypothesize_view(inq: Inquiry) -> str:
    return "\n\n".join([_framing_block(inq), _issues_block(inq, with_claims=False)])


def apply_hypothesize(inq: Inquiry, out: HypothesizeOutput) -> dict:
    g = inq.graph
    added: list[str] = []
    dropped: list[str] = []
    index_to_id: dict[int, str] = {}
    for i, p in enumerate(out.claims):
        if g.issue(p.issue_id) is None:
            dropped.append(f"{p.issue_id}: unknown issue")
            continue
        existing = next((c for c in g.claims if c.issue_id == p.issue_id
                         and c.text.strip().lower() == p.text.strip().lower()), None)
        if existing is not None:
            index_to_id[i] = existing.id
            continue
        c = g.add_claim(p.text, issue_id=p.issue_id, kind=p.kind, rationale=p.rationale)
        added.append(c.id)
        index_to_id[i] = c.id
    # every issue gets a null answer to beat, even if the model forgot one
    for iss in g.issues:
        claims = g.claims_for_issue(iss.id)
        if claims and not any(c.kind in ("null", "deflationary") for c in claims):
            c = g.add_claim(f"None of the proposed answers to {iss.id} is established", issue_id=iss.id,
                            kind="null", rationale="added by the harness: every issue needs a null to beat")
            added.append(c.id)
    groups_applied = 0
    if out.exclusive_groups:
        # rivals are only the claims the model says are rivals, within one issue
        for grp in out.exclusive_groups:
            by_issue: dict[str, list[str]] = {}
            for i in grp:
                cid = index_to_id.get(i)
                if cid is not None:
                    by_issue.setdefault(g.claim(cid).issue_id or "", []).append(cid)
            for ids in by_issue.values():
                if len(ids) > 1:
                    g.set_contraries(*ids)
                    groups_applied += 1
        # the null and deflationary answers are rivals of every substantive answer to their issue
        for iss in g.issues:
            claims = g.claims_for_issue(iss.id)
            for nc in (c for c in claims if c.kind in ("null", "deflationary")):
                for sc in (c for c in claims if c.kind == "substantive"):
                    g.set_contraries(nc.id, sc.id)
    else:
        inq.notes.append("hypothesize: no exclusive_groups returned; all claims of an issue treated as contraries")
        for iss in g.issues:
            ids = [c.id for c in g.claims_for_issue(iss.id)]
            if len(ids) > 1:
                g.set_contraries(*ids)
    if inq.framing.standard_override and g.main_issue_id:
        for c in g.claims_for_issue(g.main_issue_id):
            c.proof_standard = inq.framing.standard_override  # type: ignore[assignment]
    inq.phase = "hypothesized"
    return {"claims": added, "dropped": dropped, "exclusive_groups": groups_applied}


def hypothesize(inq: Inquiry, llm: LLM) -> dict:
    out = llm.complete_json(skill_text("hypothesize"), hypothesize_view(inq), HypothesizeOutput)
    return apply_hypothesize(inq, out)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

class TestProposal(BaseModel):
    claim_ids: list[str]
    observation: str
    expected_if: dict[str, str] = Field(default_factory=dict)
    diagnosticity: Literal["high", "medium", "low"] = "medium"
    queries: list[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    tests: list[TestProposal]


def plan_view(inq: Inquiry, extra_queries: Optional[list[str]] = None) -> str:
    ev = inq.evaluation
    parts = [_framing_block(inq), _issues_block(inq, ev)]
    if ev is not None:
        parts.append(_settlers_block(inq, ev))
    parts.append(_tests_block(inq))
    if extra_queries:
        parts.append("# Evidence the critic asked for\n\n" + "\n".join(f"- {q}" for q in extra_queries))
    return "\n\n".join(parts)


def apply_plan(inq: Inquiry, out: PlanOutput) -> dict:
    g = inq.graph
    added: list[str] = []
    dropped: list[str] = []
    for t in out.tests:
        claim_ids = [c for c in t.claim_ids if g.claim(c) is not None]
        queries = [q.strip() for q in t.queries if q.strip()]
        if not claim_ids or not queries:
            dropped.append(f"{t.observation[:60]}: no known claims or no queries")
            continue
        pt = PlannedTest(id=inq.next_test_id(), claim_ids=claim_ids, observation=t.observation,
                         expected_if={k: v for k, v in t.expected_if.items() if k in claim_ids},
                         diagnosticity=t.diagnosticity, queries=queries, round=inq.round)
        inq.tests.append(pt)
        added.append(pt.id)
    return {"tests": added, "dropped": dropped}


def plan(inq: Inquiry, llm: LLM, extra_queries: Optional[list[str]] = None) -> dict:
    out = llm.complete_json(skill_text("plan"), plan_view(inq, extra_queries), PlanOutput)
    return apply_plan(inq, out)


# ---------------------------------------------------------------------------
# Appraise (one source)
# ---------------------------------------------------------------------------

class EvidenceProposal(BaseModel):
    text: str
    kind: EvidenceKind = "tangible"
    quote: str = ""
    location: str = ""
    relevance: Strength = "moderate"
    credibility: Strength = "moderate"
    force: Strength = "moderate"
    credibility_notes: str = ""
    bears_on: dict[str, Literal["for", "against", "neutral"]] = Field(default_factory=dict)


class AppraiseOutput(BaseModel):
    kind: Literal["primary", "secondary", "derivative", "unknown"] = "unknown"
    publisher: str = ""
    date: str = ""
    competence: str = ""
    incentives: str = ""
    derived_from: str = Field(default="", description="URL or source id of the original, when derivative.")
    evidence: list[EvidenceProposal] = Field(default_factory=list)


APPRAISE_WINDOW = 12_000

# named places inside a document that a plan or a critic can ask to be read
LOCATION_RE = re.compile(
    r"(Supplementary\s+(?:Table|Fig(?:ure)?|Data|Information)s?\s*[A-Z]?\d*|Appendix\s+[A-Z0-9]+|Annex\s+[A-Z0-9]+|"
    r"Table\s+[A-Z]?\d+|Fig(?:ure)?\.?\s*[A-Z]?\d+|Section\s+\d+(?:\.\d+)*|pp?\.\s?\d+(?:\s?[-–]\s?\d+)?)",
    re.I)


def locate_requests(inq: Inquiry) -> list[tuple[str, str]]:
    """
    (source id, location) pairs the inquiry has asked for: location patterns in
    planned test observations and in critic requests, resolved to a source by
    an explicit source id, by words of the source's title in the same text, or,
    failing both, to the only primary source in the graph. Already-located
    pairs and locations the source's evidence already covers are skipped.
    """
    g = inq.graph
    texts = [t.observation for t in inq.tests if t.status == "planned"]
    texts += [n[len("critic needs:"):] for n in inq.notes if n.startswith("critic needs:")]
    done = {n[len("located: "):] for n in inq.notes if n.startswith("located: ")}
    primaries = [s for s in g.sources if s.kind == "primary"]
    out: list[tuple[str, str]] = []
    for text in texts:
        locs = {" ".join(m.group(0).split()) for m in LOCATION_RE.finditer(text)}
        if not locs:
            continue
        sid = None
        m = re.search(r"\b(S\d+)\b", text)
        if m and g.source(m.group(1)) is not None:
            sid = m.group(1)
        if sid is None:
            low = text.lower()
            for s in g.sources:
                words = [w for w in re.findall(r"[a-z0-9]{4,}", s.title.lower())]
                if len(words) >= 2 and sum(w in low for w in words) >= max(2, len(words) // 2):
                    sid = s.id
                    break
        if sid is None and len(primaries) == 1:
            sid = primaries[0].id
        if sid is None:
            continue
        for loc in sorted(locs):
            key = f"{sid} {loc}"
            if key in done or (sid, loc) in out:
                continue
            covered = any(e.source_id == sid and loc.lower() in (e.location + " " + e.text).lower() for e in g.evidence)
            if covered:
                continue
            out.append((sid, loc))
    return out


def appraise_view(inq: Inquiry, src: Source, text: str, test: Optional[PlannedTest],
                  part: tuple[int, int] = (1, 1), locate: str = "") -> str:
    parts = [_framing_block(inq), _issues_block(inq, inq.evaluation)]
    if test is not None:
        exp = "\n".join(f"  - if {k}: {v}" for k, v in test.expected_if.items())
        parts.append(f"# Test this source was fetched for\n\n{test.id}: {test.observation}\n{exp}")
    if locate:
        parts.append(f"# Find and extract\n\nThe inquiry asked for: {locate}. If this part of the document contains it, "
                     "extract everything that belongs to it (every figure, with its row and column labels, units and "
                     "notes) as evidence items whose `location` names it. If this part does not contain it, extract "
                     "only what bears on the claims, as usual.")
    parts.append(_sources_block(inq.graph))
    if part != (1, 1):
        already = [e.id for e in inq.graph.evidence if e.source_id == src.id]
        head = (f"# Source to appraise, part {part[0]} of {part[1]}\n\n"
                f"This is a later part of a document already classified as {src.kind}. "
                f"Evidence already extracted from earlier parts: {', '.join(already) or 'none'}. "
                "Extract only what this part adds; keep kind, publisher and date as before.\n\n")
    else:
        head = "# Source to appraise\n\n"
        if len(text) < 1:
            text = "(empty)"
    parts.append(f"{head}{src.id}: {src.title or '(no title)'}\nURL: {src.url}\n\n{text}")
    return "\n\n".join(parts)


def _origin_group(g: ArgumentGraph, src: Source, derived_from: str) -> str:
    """
    Link a derivative source to its original when the graph holds it. If it
    names an origin the graph does not hold, the name is kept and the source
    stays derivative with no derived_from, which evaluate treats as unable to
    corroborate. Returns the source's origin key for the ledger; evidence
    items carry no independence_group of their own, so origins are computed
    from the source (DOI, derivation, title, publisher) at evaluation time.
    """
    key = derived_from.strip()
    if key:
        orig = g.source(key) or next((s for s in g.sources if s.url and s.url == key), None)
        if orig is not None and orig.id != src.id:
            src.derived_from = orig.id
        else:
            src.derived_from_note = key
    return g.origin_key(src)


def apply_appraise(inq: Inquiry, src: Source, out: AppraiseOutput, first: bool = True) -> dict:
    g = inq.graph
    if first:
        src.kind = out.kind
        src.competence = out.competence
        src.incentives = out.incentives
    elif src.kind == "unknown" and out.kind != "unknown":
        # the front matter did not say what the document is; a later part did
        src.kind = out.kind
        src.competence = out.competence or src.competence
        src.incentives = out.incentives or src.incentives
    src.publisher = out.publisher or src.publisher
    src.date = out.date or src.date
    group = _origin_group(g, src, out.derived_from) if first else g.origin_key(src)
    known = {c.id for c in g.claims}
    added: list[str] = []
    for p in out.evidence:
        e = g.add_evidence(
            p.text, kind=p.kind, source_id=src.id, quote=_clip(p.quote, 300), location=p.location,
            credentials=Credentials(relevance=p.relevance, credibility=p.credibility, force=p.force,
                                    credibility_notes=p.credibility_notes),
            bears_on={k: v for k, v in p.bears_on.items() if k in known},
        )
        added.append(e.id)
    return {"source": src.id, "kind": src.kind, "group": group, "evidence": added}


def _chunks(text: str, window: int, overlap: int) -> list[str]:
    if len(text) <= window:
        return [text]
    out, start = [], 0
    while start < len(text):
        out.append(text[start:start + window])
        if start + window >= len(text):
            break
        start += window - overlap
    return out


def appraise(inq: Inquiry, llm: LLM, src: Source, text: str, test: Optional[PlannedTest] = None,
             part: tuple[int, int] = (1, 1), locate: str = "") -> dict:
    out = llm.complete_json(skill_text("appraise"), appraise_view(inq, src, text, test, part, locate), AppraiseOutput)
    # a located re-read must not reclassify a source already appraised
    first = part[0] == 1 and not (locate and any(e.source_id == src.id for e in inq.graph.evidence))
    return apply_appraise(inq, src, out, first=first)


def appraise_full(inq: Inquiry, llm: LLM, src: Source, text: str, test: Optional[PlannedTest] = None,
                  window: int = APPRAISE_WINDOW, overlap: int = 500, max_parts: int = 36,
                  text_complete: bool = True, locate: str = "") -> dict:
    """
    Appraise a source. The first window classifies it; a primary source is
    then read to the end, window by window, so that an attack grounded in
    what the document does not say can be trusted. A source still "unknown"
    after its first window is read on too: the front matter of a long report
    rarely says what it is, and later parts may settle the kind. Secondary
    and derivative sources are sampled.
    `text_complete` is False when the fetcher cut the text; the source is
    then never marked as read in full, whatever was appraised.
    """
    parts = _chunks(text, window, overlap)
    total: dict = {"source": src.id, "evidence": [], "parts": 0, "of": len(parts), "text_complete": text_complete}
    if locate:
        # a targeted read: only the windows that mention the location, all of them
        wanted = [i for i, ch in enumerate(parts) if locate.lower() in ch.lower()]
        indices = wanted or list(range(len(parts)))
    else:
        indices = list(range(len(parts)))
    for n, i in enumerate(indices):
        res = appraise(inq, llm, src, parts[i], test, part=(i + 1, len(parts)), locate=locate)
        total["evidence"].extend(res["evidence"])
        total["parts"] += 1
        if n == 0:
            total["group"] = res["group"]
        if not locate and len(parts) > 1 and src.kind in ("secondary", "derivative"):
            break
        if total["parts"] >= max_parts:
            break
    total["kind"] = src.kind
    if not locate:
        src.read_fully = text_complete and total["parts"] == len(parts)
    return total


# ---------------------------------------------------------------------------
# Argue
# ---------------------------------------------------------------------------

class CQAnswerProposal(BaseModel):
    answer: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    defaulted: bool = False
    outcome: Literal["satisfied", "unsatisfied", "unresolved"] = Field(
        default="satisfied",
        description="What the check established. unsatisfied: the condition does not hold here (the argument then "
                    "does not apply); unresolved: the evidence does not settle it.")


class ArgumentProposal(BaseModel):
    scheme: str
    claim_id: str
    premise_ids: list[str]
    cq_answers: dict[str, CQAnswerProposal] = Field(default_factory=dict)
    note: str = ""


class UnusableProposal(BaseModel):
    evidence_id: str
    reason: str


class ArgueOutput(BaseModel):
    arguments: list[ArgumentProposal] = Field(default_factory=list)
    unusable: list[UnusableProposal] = Field(
        default_factory=list, description="Evidence bearing on these claims that cannot ground any argument, with why.")


def shadowed_by_origin(g: ArgumentGraph, e, claim_ids: set[str]) -> Optional[str]:
    """
    If `e` comes from a derivative source whose original has its own evidence
    bearing on one of `claim_ids`, return the original's source id: the relay
    adds nothing the original does not say better.
    """
    src = g.source(e.source_id) if e.source_id else None
    if src is None or not src.derived_from:
        return None
    mine = set(e.bears_on) & claim_ids
    if not mine:
        return None
    for x in g.evidence:
        if x.source_id == src.derived_from and set(x.bears_on) & mine:
            return src.derived_from
    return None


def issue_evidence(g: ArgumentGraph, issue_id: str, include_unassigned: bool = False) -> tuple[set[str], list[str]]:
    """
    Claim ids of an issue and the evidence ids to argue from: items bearing on
    those claims, minus relays of a source that speaks for itself. A shadowed
    relay is marked unusable so it is neither offered nor counted as orphan.
    """
    claim_ids = {c.id for c in g.claims_for_issue(issue_id)}
    ev_ids = []
    for e in g.evidence:
        if not ((set(e.bears_on) & claim_ids) or (include_unassigned and not e.bears_on)):
            continue
        orig = shadowed_by_origin(g, e, claim_ids)
        if orig is not None:
            e.provenance.setdefault("unusable", f"relay of {orig}, whose own evidence bears on the same claims")
            continue
        ev_ids.append(e.id)
    return claim_ids, ev_ids


def argue_view(inq: Inquiry, issue_id: str) -> str:
    """Argue is called once per issue, with that issue's claims and the evidence bearing on them."""
    g = inq.graph
    ev = inq.evaluation
    iss = g.issue(issue_id)
    claim_ids, ev_ids = issue_evidence(g, issue_id, include_unassigned=(issue_id == g.main_issue_id))
    used = {p for a in g.arguments for p in a.premise_ids}
    orphans = [e for e in ev_ids if e not in used and not g.ev(e).provenance.get("unusable")]
    lines = [f"# Issue under argument\n\n{iss.id}{' (main)' if iss.id == g.main_issue_id else ''} "
             f"[{iss.question_type}]: {iss.text}"]
    if iss.answerhood:
        lines.append(f"complete answer: {iss.answerhood}")
    lines.append("")
    lines.append("Claims (mutually exclusive answers):")
    for c in g.claims_for_issue(issue_id):
        st = f" [{ev.status(c.id)}]" if ev else ""
        lines.append(f"- {c.id} ({c.kind}){st}: {c.text}")
    issue_block = "\n".join(lines)
    orphan_block = ("# Evidence bearing on these claims and not yet in any argument\n\n"
                    + ("\n".join(f"- {e}" for e in orphans) if orphans else "(none)")
                    + "\n\nEvery item above must end up as a premise of an argument below, or in `unusable` with a reason.")
    args_for_issue = [a for a in g.arguments if a.claim_id in claim_ids]
    sub = g.model_copy(update={"arguments": args_for_issue})
    return "\n\n".join([
        _framing_block(inq), issue_block, _sources_block(g), _evidence_block(g, ev_ids),
        orphan_block, _arguments_block(sub, ev), _schemes_block(),
    ])


def apply_argue(inq: Inquiry, out: ArgueOutput, allowed_claims: Optional[set[str]] = None) -> dict:
    g = inq.graph
    added: list[str] = []
    merged: list[str] = []
    dropped: list[str] = []
    still_open: dict[str, list[str]] = {}
    unusable: list[str] = []
    for u in out.unusable:
        e = g.ev(u.evidence_id)
        if e is not None and u.reason.strip():
            e.provenance["unusable"] = u.reason.strip()
            unusable.append(e.id)
    for p in out.arguments:
        if p.scheme not in SCHEMES or p.scheme == "attack":
            dropped.append(f"unknown scheme {p.scheme!r}")
            continue
        if g.claim(p.claim_id) is None:
            dropped.append(f"unknown claim {p.claim_id!r}")
            continue
        if allowed_claims is not None and p.claim_id not in allowed_claims:
            dropped.append(f"{p.claim_id} is not a claim of the issue under argument")
            continue
        premises = [x for x in p.premise_ids if g.ev(x) is not None or g.claim(x) is not None]
        premises = [x for x in premises if x != p.claim_id]
        if not premises:
            dropped.append(f"{p.scheme} → {p.claim_id}: no known premises")
            continue
        existing = next((a for a in g.arguments if not a.is_attack and a.scheme == p.scheme
                         and a.claim_id == p.claim_id and set(a.premise_ids) == set(premises)), None)
        if existing is None:
            a = g.add_argument(p.scheme, premises, p.claim_id, note=p.note, round=inq.round)
            added.append(a.id)
        else:
            a = existing
            merged.append(a.id)
        sch = SCHEMES[p.scheme]
        valid_cq = {q.id for q in sch.critical_questions}
        for qid, ans in p.cq_answers.items():
            if qid not in valid_cq:
                continue
            if sch.cq(qid).kind == "exception":
                continue  # exceptions are the critic's to raise
            ev_ids = [x for x in ans.evidence_ids if g.ev(x) is not None]
            if not ans.answer and not ev_ids:
                continue
            g.answer_cq(a.id, qid, ans.answer, ev_ids, defaulted=ans.defaulted and not ev_ids,
                        outcome="" if ans.defaulted and not ev_ids else ans.outcome)
        open_ = [q.id for q in sch.assumptions() if a.cq[q.id].status == "open"]
        failed = [q.id for q in sch.assumptions() if a.cq[q.id].status == "answered" and a.cq[q.id].outcome == "unsatisfied"]
        if open_ or failed:
            still_open[a.id] = open_ + [f"{q} (unsatisfied)" for q in failed]
    # an item that is a premise somewhere is usable by definition
    in_use = {p for a in g.arguments for p in a.premise_ids}
    for eid in list(unusable):
        if eid in in_use:
            g.ev(eid).provenance.pop("unusable", None)
            unusable.remove(eid)
    return {"arguments": added, "merged": merged, "dropped": dropped, "unusable": unusable,
            "still_inapplicable": still_open}


def argue(inq: Inquiry, llm: LLM) -> dict:
    """One call per issue that has evidence bearing on it; results are merged into one summary."""
    g = inq.graph
    total = {"arguments": [], "merged": [], "dropped": [], "unusable": [], "still_inapplicable": {}, "issues": []}
    for iss in g.issues:
        claim_ids, ev_ids = issue_evidence(g, iss.id, include_unassigned=(iss.id == g.main_issue_id))
        if not claim_ids or not ev_ids:
            continue
        out = llm.complete_json(skill_text("argue"), argue_view(inq, iss.id), ArgueOutput)
        part = apply_argue(inq, out, allowed_claims=claim_ids)
        for k in ("arguments", "merged", "dropped", "unusable"):
            total[k].extend(part[k])
        total["still_inapplicable"].update(part["still_inapplicable"])
        total["issues"].append(iss.id)
    return total


# ---------------------------------------------------------------------------
# Critique
# ---------------------------------------------------------------------------

class AttackProposal(BaseModel):
    target_id: str
    type: AttackType
    premise_ids: list[str] = Field(default_factory=list)
    cq_id: str = ""
    basis: Literal["presence", "absence"] = Field(
        default="presence",
        description="presence: grounded in what a source says. absence: grounded in what a source does not say.")
    note: str = ""


class CritiqueOutput(BaseModel):
    attacks: list[AttackProposal] = Field(default_factory=list)
    needed_evidence: list[str] = Field(default_factory=list)


def _sources_behind(g: ArgumentGraph, target_id: str) -> list[Source]:
    """The sources whose text an attack on `target_id` is about."""
    node = g.node(target_id)
    ev_ids: list[str] = []
    if node is None:
        return []
    if hasattr(node, "credentials"):  # Evidence
        ev_ids = [node.id]
    elif isinstance(node, Argument):
        ev_ids = [p for p in node.premise_ids if g.ev(p) is not None]
    else:  # claim: the evidence behind its supporting arguments
        ev_ids = [p for a in g.arguments_for(target_id) for p in a.premise_ids if g.ev(p) is not None]
    out: list[Source] = []
    for eid in ev_ids:
        e = g.ev(eid)
        s = g.source(e.source_id) if e and e.source_id else None
        if s is not None and s not in out:
            out.append(s)
    return out


def critique_view(inq: Inquiry) -> str:
    g = inq.graph
    ev = inq.evaluation
    return "\n\n".join([
        _framing_block(inq), _issues_block(inq, ev), _sources_block(g), _evidence_block(g, mark_unused=True),
        _arguments_block(g, ev, show_exceptions=True),
    ])


def apply_critique(inq: Inquiry, out: CritiqueOutput) -> dict:
    g = inq.graph
    added: list[str] = []
    dropped: list[str] = []
    absence_unverified: list[str] = []
    needed_extra: list[str] = []
    for p in out.attacks:
        premises = [x for x in p.premise_ids if g.ev(x) is not None or g.claim(x) is not None]
        premises = [x for x in premises if x != p.target_id]
        if not premises:
            dropped.append(f"{p.type} on {p.target_id}: no grounds (bare denial)")
            continue
        if any(a.is_attack and a.attacks.target_id == p.target_id and a.attacks.type == p.type
               and set(a.premise_ids) == set(premises) for a in g.arguments):
            continue
        note = p.note if not p.cq_id else f"[{p.cq_id}] {p.note}"
        if p.basis == "absence":
            # "the source does not report X" is grounded only if the source was read to the end;
            # until then it is a request to read, not an attack
            unread = [s.id for s in _sources_behind(g, p.target_id) if not s.read_fully]
            if unread:
                absence_unverified.append(f"{p.type} on {p.target_id}")
                for sid in unread:
                    needed_extra.append(f"read {sid} fully: {p.note or 'confirm the absence the critic relies on'}")
                continue
        try:
            a = g.add_attack(p.target_id, p.type, premise_ids=premises, origin="critic", note=note, round=inq.round)
        except (KeyError, ValueError) as e:
            dropped.append(f"{p.type} on {p.target_id}: {e}")
            continue
        target = g.node(p.target_id)
        if p.cq_id and isinstance(target, Argument) and p.cq_id in {q.id for q in SCHEMES[target.scheme].critical_questions}:
            a.attacks.raises_cq = p.cq_id
        added.append(a.id)
    needed = [q.strip() for q in out.needed_evidence if q.strip()] + needed_extra
    return {"attacks": added, "dropped": dropped, "absence_unverified": absence_unverified, "needed_evidence": needed}


def critique(inq: Inquiry, llm: LLM) -> dict:
    out = llm.complete_json(skill_text("critique"), critique_view(inq), CritiqueOutput)
    return apply_critique(inq, out)


# ---------------------------------------------------------------------------
# Respond: the proposer answers standing attacks
# ---------------------------------------------------------------------------

class ResponseProposal(BaseModel):
    attack_id: str
    action: Literal["discharge", "counter", "concede"]
    premise_ids: list[str] = Field(default_factory=list, description="Grounds for a counter: evidence or accepted claim ids.")
    cq_answers: dict[str, CQAnswerProposal] = Field(
        default_factory=dict,
        description="discharge: answers, with evidence ids, to the critical questions of the attacked argument that the "
                    "attack raised. counter: answers the counter also supplies. Each answer needs evidence ids.")
    note: str = ""


class RespondOutput(BaseModel):
    responses: list[ResponseProposal] = Field(default_factory=list)


def standing_attacks(inq: Inquiry, ev: Evaluation) -> list[Argument]:
    """Critic or human attacks that are IN and bear on a proposer argument, its evidence, or its claim."""
    g = inq.graph
    out = []
    for a in g.arguments:
        if not a.is_attack or a.origin == "proposer" or ev.labels.get(a.id) != "in":
            continue
        t = a.attacks
        target = g.node(t.target_id)
        if target is None:
            continue
        if isinstance(target, Argument) and target.origin == "proposer":
            out.append(a)
        elif hasattr(target, "credentials") and any(t.target_id in x.premise_ids for x in g.arguments if not x.is_attack):
            out.append(a)
        elif g.claim(t.target_id) is not None:
            out.append(a)
    return out


CONCEDED_MARK = "(conceded by proposer"


def _attack_context_evidence(g: ArgumentGraph, atk: Argument) -> list[str]:
    """
    The evidence most likely to answer an attack: items from the same sources
    as the attacked argument's premises (a report answers questions about its
    own method), items bearing on the attacked claim, and the attack's own
    grounds. The proposer sees these first; the full list follows.
    """
    t = atk.attacks
    target = g.node(t.target_id)
    premise_ids: list[str] = []
    claim_id: Optional[str] = None
    if isinstance(target, Argument):
        premise_ids, claim_id = list(target.premise_ids), target.claim_id
    elif hasattr(target, "credentials"):
        premise_ids = [t.target_id]
        users = [x for x in g.arguments if t.target_id in x.premise_ids and not x.is_attack]
        claim_id = users[0].claim_id if users else None
    else:
        claim_id = t.target_id
        premise_ids = [p for a in g.arguments_for(t.target_id) for p in a.premise_ids]
    sources = {g.ev(p).source_id for p in premise_ids if g.ev(p) is not None and g.ev(p).source_id}
    out: list[str] = []
    for e in g.evidence:
        if e.id in premise_ids or e.id in atk.premise_ids or (e.source_id and e.source_id in sources) \
                or (claim_id and claim_id in e.bears_on):
            out.append(e.id)
    return out


def respond_view(inq: Inquiry, attacks: list[Argument]) -> str:
    g = inq.graph
    ev = inq.evaluation
    new = [a for a in attacks if CONCEDED_MARK not in a.note]
    old = [a for a in attacks if CONCEDED_MARK in a.note]
    lines = ["# Standing attacks on your arguments", ""]
    if old:
        lines.append("Previously conceded, listed for reference; respond to one of these only if evidence gathered "
                     "since now answers it: " + ", ".join(f"{a.id} (on {a.attacks.target_id})" for a in old))
        lines.append("")
    focus: list[str] = []
    for a in new:
        t = a.attacks
        lines.append(f"## {a.id}: {t.type} on {t.target_id} (by {a.origin}, strength {ev.argument_strength.get(a.id, '?')})")
        lines.append(f"grounds: {', '.join(a.premise_ids) or '(reviewer)'}")
        if t.raises_cq:
            lines.append(f"raises critical question: {t.raises_cq} — answering it with evidence discharges this attack")
        lines.append(f"note: {a.note}")
        target = g.node(t.target_id)
        if isinstance(target, Argument):
            sch = SCHEMES[target.scheme]
            lines.append(f"attacked argument {target.id}: {target.scheme} from {', '.join(target.premise_ids)} to {target.claim_id}")
            for q in sch.critical_questions:
                st = target.cq.get(q.id)
                ans = f" — {st.answer}" if st and st.answer else ""
                lines.append(f"  cq {q.id} ({q.kind}) [{st.status if st else 'open'}]: {q.text}{ans}")
        elif hasattr(target, "credentials"):
            users = [x.id for x in g.arguments if t.target_id in x.premise_ids and not x.is_attack]
            lines.append(f"attacked evidence {t.target_id}, used by {', '.join(users) or 'nothing'}")
        else:
            lines.append(f"attacked claim {t.target_id}: {target.text}")
        ctx = _attack_context_evidence(g, a)
        lines.append("evidence to check first for this attack: " + (", ".join(ctx) if ctx else "(none)"))
        focus += [x for x in ctx if x not in focus]
        lines.append("")
    rest = [e.id for e in g.evidence if e.id not in focus]
    return "\n\n".join([_framing_block(inq), _issues_block(inq, ev), "\n".join(lines), _sources_block(g),
                        _evidence_block(g, focus, title="Evidence from the same sources and on the same claims as the attacked arguments"),
                        _evidence_block(g, rest, title="Other evidence")])


def apply_respond(inq: Inquiry, out: RespondOutput) -> dict:
    g = inq.graph
    conceded: list[str] = []
    countered: list[str] = []
    discharged: list[str] = []
    dropped: list[str] = []
    for r in out.responses:
        atk = g.arg(r.attack_id)
        if atk is None or not atk.is_attack:
            dropped.append(f"{r.attack_id}: not an attack")
            continue
        if r.action == "discharge":
            target = g.node(atk.attacks.target_id)
            if not isinstance(target, Argument):
                dropped.append(f"discharge {atk.id}: target is not an argument")
                continue
            valid = {q.id for q in SCHEMES[target.scheme].critical_questions}
            written = []
            for qid, ans in r.cq_answers.items():
                if qid not in valid:
                    continue
                if not ans.evidence_ids or any(g.ev(x) is None for x in ans.evidence_ids):
                    continue  # an answer without evidence in the graph discharges nothing
                g.answer_cq(target.id, qid, ans.answer, list(ans.evidence_ids), outcome=ans.outcome)
                written.append(qid)
            if written:
                discharged.append(atk.id)
                atk.note = (atk.note + f" (discharge attempted by proposer: {', '.join(written)} answered)").strip()
            else:
                dropped.append(f"discharge {atk.id}: no critical question answered with evidence in the graph")
            continue
        if r.action == "concede":
            if CONCEDED_MARK not in atk.note:
                atk.note = (atk.note + f" {CONCEDED_MARK}: {r.note})").strip() if r.note else f"{atk.note} {CONCEDED_MARK})".strip()
                conceded.append(atk.id)
            continue
        premises = [x for x in r.premise_ids if (g.ev(x) is not None or g.claim(x) is not None) and x != atk.id]
        if not premises:
            dropped.append(f"counter to {atk.id}: no grounds")
            continue
        if any(a.is_attack and a.attacks.target_id == atk.id and set(a.premise_ids) == set(premises)
               for a in g.arguments):
            continue
        try:
            c = g.add_attack(atk.id, "undercut", premise_ids=premises, origin="proposer", note=r.note, round=inq.round)
        except (KeyError, ValueError) as e:
            dropped.append(f"counter to {atk.id}: {e}")
            continue
        countered.append(c.id)
        target = g.node(atk.attacks.target_id)
        if isinstance(target, Argument) and r.cq_answers:
            sch = SCHEMES[target.scheme]
            for qid, ans in r.cq_answers.items():
                if qid in {q.id for q in sch.assumptions()}:
                    ev_ids = [x for x in ans.evidence_ids if g.ev(x) is not None]
                    if ans.answer or ev_ids:
                        g.answer_cq(target.id, qid, ans.answer, ev_ids, defaulted=ans.defaulted and not ev_ids,
                                    outcome="" if ans.defaulted and not ev_ids else ans.outcome)
    return {"conceded": conceded, "countered": countered, "discharged": discharged, "dropped": dropped}


def respond(inq: Inquiry, llm: LLM) -> dict:
    ev = inq.evaluation or evaluate_move(inq)
    attacks = standing_attacks(inq, ev)
    new = [a for a in attacks if CONCEDED_MARK not in a.note]
    if not new:
        return {"conceded": [], "countered": [], "discharged": [], "dropped": [], "standing": len(attacks), "new": 0}
    out = llm.complete_json(skill_text("respond"), respond_view(inq, attacks), RespondOutput)
    res = apply_respond(inq, out)
    res["standing"] = len(attacks)
    res["new"] = len(new)
    return res


# ---------------------------------------------------------------------------
# Compute: the arithmetic instrument
# ---------------------------------------------------------------------------

# a number with a unit or sign, excluding bare years
_NUM = re.compile(r"(?<![\d.])\d+(?:[.,]\d+)?\s*(?:%|percent|pp|µg|ug|mg|ppb|ppm|km|m\b|min\b|minutes|hours|per\b|/)", re.I)
_YEAR = re.compile(r"^(?:19|20)\d\d$")


def numeric_evidence(g: ArgumentGraph) -> list:
    out = []
    for e in g.evidence:
        if e.kind == "model_output":
            continue
        if _NUM.search(e.text) or _NUM.search(e.quote):
            out.append(e)
    return out


class VariableBinding(BaseModel):
    value: float
    evidence_id: str
    what: str = Field(default="", description="What this number is, in the source's terms.")


class ComputationProposal(BaseModel):
    name: str
    expression: str = Field(description="Arithmetic over the variable names, e.g. (a - b) / a * 100")
    variables: dict[str, VariableBinding]
    text: str = Field(description="What the result establishes, in our words, without the number.")
    unit: str = ""
    bears_on: dict[str, Literal["for", "against", "neutral"]] = Field(default_factory=dict)
    note: str = ""


class ComputeOutput(BaseModel):
    computations: list[ComputationProposal] = Field(default_factory=list)


def compute_view(inq: Inquiry) -> str:
    g = inq.graph
    nums = [e.id for e in numeric_evidence(g)]
    done = [e for e in g.evidence if e.kind == "model_output"]
    done_block = "# Computations already made\n\n" + ("\n".join(
        f"- {e.id}: {e.text} [{e.provenance.get('expression', '')}]" for e in done) if done else "(none)")
    return "\n\n".join([_framing_block(inq), _issues_block(inq, inq.evaluation),
                        _evidence_block(g, nums, title="Evidence carrying numbers"), done_block])


def apply_compute(inq: Inquiry, out: ComputeOutput) -> dict:
    g = inq.graph
    added: list[str] = []
    dropped: list[str] = []
    known = {c.id for c in g.claims}
    for p in out.computations:
        inputs = []
        for name, b in p.variables.items():
            e = g.ev(b.evidence_id)
            if e is None:
                inputs = None
                dropped.append(f"{p.name}: unknown evidence {b.evidence_id}")
                break
            inputs.append((name, b, e))
        if inputs is None or not inputs:
            if inputs is not None:
                dropped.append(f"{p.name}: no inputs")
            continue
        try:
            result = safe_eval(p.expression, {n: b.value for n, b, _ in inputs})
        except ComputeError as err:
            dropped.append(f"{p.name}: {err}")
            continue
        # the weakest input rules; the arithmetic adds nothing to credibility
        cred = Credentials(
            relevance="moderate",
            credibility=min((e.credentials.credibility for _, _, e in inputs), key=lambda s: STRENGTH_ORDER[s]),
            force=min((e.credentials.force for _, _, e in inputs), key=lambda s: STRENGTH_ORDER[s]),
            credibility_notes=f"computed from {', '.join(e.id for _, _, e in inputs)}",
        )
        first = inputs[0][2]
        shown = f"{result:.4g}{' ' + p.unit if p.unit else ''}"
        # a computation inherits the origin of its inputs; it is never a new origin
        origin = g.evidence_origin(first) or f"source:{first.source_id or first.id}"
        e = g.add_evidence(
            f"{p.text}: {shown}", kind="model_output", quote=p.expression, location="computed",
            credentials=cred, independence_group=origin,
            origin="instrument", bears_on={k: v for k, v in p.bears_on.items() if k in known},
            provenance={
                "instrument": INSTRUMENT_VERSION, "name": p.name, "expression": p.expression,
                "inputs": "; ".join(f"{n}={b.value:g} from {b.evidence_id} ({b.what})" for n, b, _ in inputs),
                "result": repr(result), "round": str(inq.round),
            },
        )
        added.append(e.id)
    return {"computed": added, "dropped": dropped}


def compute(inq: Inquiry, llm: LLM) -> Optional[dict]:
    """Returns None when there is nothing to compute over (fewer than two numeric items)."""
    if len(numeric_evidence(inq.graph)) < 2:
        return None
    out = llm.complete_json(skill_text("compute"), compute_view(inq), ComputeOutput)
    return apply_compute(inq, out)


# ---------------------------------------------------------------------------
# Evaluate, reflect, stop  (code only)
# ---------------------------------------------------------------------------

def evaluate_move(inq: Inquiry) -> Evaluation:
    ev = evaluate(inq.graph)
    inq.evaluation = ev
    return ev


def main_claim_settlers(inq: Inquiry, ev: Evaluation) -> dict[str, list[Settler]]:
    return {c.id: what_would_settle(inq.graph, c.id, ev) for c in inq.main_claims() if ev.status(c.id) != "in"}


def reflect(inq: Inquiry, ev: Evaluation) -> Reflection:
    g = inq.graph
    established = [f"{c.id}: {c.text}" for c in g.claims if ev.status(c.id) == "in"]
    assumed: list[str] = []
    for a in g.arguments:
        for qid, ans in a.cq.items():
            if ans.status == "defaulted":
                assumed.append(f"{a.id}:{qid} defaulted — {ans.answer}")
    for f in ev.flags:
        if f.code == "single_origin":
            assumed.append(f"{f.node_id} rests on one origin")
    lb_ids: list[str] = []
    for c in inq.main_claims():
        for x in load_bearing(g, c.id):
            if x.node_id not in lb_ids:
                lb_ids.append(x.node_id)
    directives: list[str] = []
    for cid, settlers in main_claim_settlers(inq, ev).items():
        for s in settlers[:3]:
            directives.append(f"{cid} {s.kind}: {s.detail}")
    r = Reflection(round=inq.round, established=established, assumed=assumed, load_bearing_node_ids=lb_ids,
                   directive="; ".join(directives) if directives else "main issue has an accepted claim")
    inq.reflections.append(r)
    return r


def stop(inq: Inquiry, ev: Evaluation, rounds_left: int, new_evidence_this_round: int) -> StopAssessment:
    g = inq.graph
    accepted = ev.issues.get(g.main_issue_id, []) if g.main_issue_id else []
    undecided = [c.id for c in inq.main_claims() if ev.status(c.id) == "undecided"]
    settlers = main_claim_settlers(inq, ev)
    addressable = [cid for cid in undecided if settlers.get(cid)]
    if accepted:
        decision, reason = "stop", f"main issue answered by {', '.join(accepted)}"
    elif rounds_left <= 0:
        decision, reason = "stop", "rounds exhausted"
    elif not addressable:
        decision, reason = "stop", "no undecided main claim has anything evidence could settle"
    elif inq.round > 0 and new_evidence_this_round == 0:
        decision, reason = "stop", "the last round found no new evidence; planned tests are unobtainable"
    else:
        decision, reason = "continue", f"{len(addressable)} undecided main claim(s) could still be settled by evidence"
    sa = StopAssessment(round=inq.round, decision=decision, reason=reason, undecided_on_path=undecided,
                        obtainable=[t.id for t in inq.tests if t.status == "planned"])
    inq.stop_assessments.append(sa)
    return sa


# ---------------------------------------------------------------------------
# Conclude
# ---------------------------------------------------------------------------

class JudgementProposal(BaseModel):
    text: str
    confidence: Literal["high", "moderate", "low"] = "low"
    rests_on: str = ""
    claim_ids: list[str] = Field(default_factory=list)


class ConcludeOutput(BaseModel):
    answer: str
    judgements: list[JudgementProposal] = Field(default_factory=list)
    what_would_change_this: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


def conclude_view(inq: Inquiry) -> str:
    g = inq.graph
    ev = inq.evaluation or evaluate_move(inq)
    parts = [_framing_block(inq), _issues_block(inq, ev), _arguments_block(g, ev), _evidence_block(g)]
    lb_lines = ["# Load-bearing nodes for main-issue claims", ""]
    for c in inq.main_claims():
        for x in load_bearing(g, c.id):
            lb_lines.append(f"- {c.id} depends on {x.node_id} ({x.kind}): {x.detail} → would become {x.effect}")
    if len(lb_lines) == 2:
        lb_lines.append("(none)")
    parts.append("\n".join(lb_lines))
    parts.append(_settlers_block(inq, ev))
    if inq.reflections:
        r = inq.reflections[-1]
        parts.append("# Last reflection\n\n" + "\n".join(
            [f"established: {'; '.join(r.established) or 'nothing'}", f"assumed: {'; '.join(r.assumed) or 'nothing'}",
             f"directive: {r.directive}"]))
    ungrounded = [n for n in inq.notes if n.startswith("critic needs:")]
    if ungrounded:
        parts.append("# Critic concerns never grounded\n\n" + "\n".join(f"- {n[len('critic needs:'):].strip()}" for n in ungrounded))
    return "\n\n".join(parts)


# "there is no X" where X is a kind of evidence: the inquiry can only say it did not retrieve one.
# "no detectable effect" and the like are findings, not absence assertions, and are excluded.
_ABSENCE = re.compile(
    r"\b(?:there\s+(?:is|are|was|were)\s+no|does\s+not\s+exist|do\s+not\s+exist|"
    r"no(?!\s+(?:detectable|significant|statistically|measurable|material|net|clear|longer|more|such\s+effect))"
    r"(?:\s+(?:independent|published|external|peer-reviewed|other|separate|official|public|robust|such))*)"
    r"\s+(?:\w+\s+){0,2}?(?:stud(?:y|ies)|analys[ie]s|control(?:\s+group|\s+site|\s+area)?s?|data(?:set)?|"
    r"evaluations?|intervals?|methods?|trials?|replications?|comparisons?)\b",
    re.I)


def absence_assertions(text: str) -> list[str]:
    """Sentences that assert a kind of evidence does not exist."""
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if _ABSENCE.search(sentence):
            out.append(" ".join(sentence.split()))
    return out


def apply_conclude(inq: Inquiry, out: ConcludeOutput) -> dict:
    ev = inq.evaluation or evaluate_move(inq)
    g = inq.graph
    judgements: list[Judgement] = []
    capped: list[str] = []
    for j in out.judgements:
        ids = [c for c in j.claim_ids if g.claim(c) is not None]
        conf = j.confidence
        if not any(ev.status(c) == "in" for c in ids) and conf != "low":
            conf = "low"
            capped.append(j.text[:60])
        judgements.append(Judgement(text=j.text, confidence=conf, rests_on=j.rests_on, claim_ids=ids))
    flags = [f"absence_assertion: {s}" for s in absence_assertions(out.answer)]
    for j in judgements:
        flags += [f"absence_assertion: {s}" for s in absence_assertions(j.text + " " + j.rests_on)]
    inq.conclusion = Conclusion(round=inq.round, answer=out.answer, judgements=judgements,
                                what_would_change_this=out.what_would_change_this, unresolved=out.unresolved,
                                flags=flags)
    inq.phase = "concluded"
    return {"judgements": len(judgements), "capped_to_low": capped, "absence_assertions": len(flags)}


def conclude(inq: Inquiry, llm: LLM) -> dict:
    out = llm.complete_json(skill_text("conclude"), conclude_view(inq), ConcludeOutput, max_tokens=6000)
    return apply_conclude(inq, out)
