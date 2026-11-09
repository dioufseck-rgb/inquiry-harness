"""
Renderers for the argument graph.

    toulmin(g, argument_id, ev)   one argument in Toulmin's layout
    wigmore(g, ev)                the whole graph as a Mermaid chart, evidence at
                                  the bottom, claims at the top, attacks dashed
    summary(g, ev)                markdown: issues, claim status, open
                                  assumptions, flags
"""

from __future__ import annotations

from .evaluate import Evaluation, LoadBearing
from .graph import ArgumentGraph
from .schemes import SCHEMES

_MARK = {"in": "✓", "out": "✗", "undecided": "?"}


def _short(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Toulmin
# ---------------------------------------------------------------------------

def toulmin(g: ArgumentGraph, argument_id: str, ev: Evaluation | None = None) -> str:
    a = g.arg(argument_id)
    if a is None:
        raise KeyError(argument_id)
    sch = SCHEMES[a.scheme]
    lines = [f"### {a.id} — {sch.title}"]
    if a.is_attack:
        lines.append(f"*{a.attacks.type} attack on {a.attacks.target_id}*")
    target = g.claim(a.claim_id) if a.claim_id else None
    lines.append("")
    lines.append(f"**Claim.** {target.text if target else a.attacks.note or '(attack)'}")
    lines.append("")
    lines.append("**Grounds.**")
    for pid in a.premise_ids:
        n = g.ev(pid) or g.claim(pid)
        quote = f' — "{n.quote}"' if getattr(n, "quote", "") else ""
        lines.append(f"- {pid}: {n.text}{quote}")
    if not a.premise_ids:
        lines.append("- (none)")
    lines.append("")
    lines.append(f"**Warrant.** {sch.description} ({sch.name})")
    lines.append("")
    lines.append("**Backing** (critical questions):")
    for q in sch.critical_questions:
        st = a.cq.get(q.id)
        status = st.status if st else "open"
        ans = f" — {st.answer}" if st and st.answer else ""
        lines.append(f"- [{status}] ({q.kind}) {q.text}{ans}")
    if ev is not None:
        strength = ev.argument_strength.get(a.id, "?")
        label = ev.labels.get(a.id, "inapplicable" if not ev.applicable.get(a.id, True) else "?")
        lines.append("")
        lines.append(f"**Qualifier.** strength {strength}; status {label}")
    rebuttals = g.attacks_on(a.id)
    if a.claim_id:
        rebuttals += g.attacks_on(a.claim_id)
    lines.append("")
    lines.append("**Rebuttal.** " + (", ".join(f"{r.id} ({r.attacks.type})" for r in rebuttals) if rebuttals else "none recorded"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Wigmore chart (Mermaid)
# ---------------------------------------------------------------------------

def wigmore(g: ArgumentGraph, ev: Evaluation | None = None) -> str:
    def mark(node_id: str) -> str:
        if ev is None:
            return ""
        if node_id in ev.claims:
            return f" {_MARK[ev.claims[node_id].status]}"
        if node_id in ev.labels:
            return f" {_MARK[ev.labels[node_id]]}"
        if node_id in ev.applicable and not ev.applicable[node_id]:
            return " ∅"
        return ""

    out = ["flowchart BT"]
    for iss in g.issues:
        out.append(f'    {iss.id}{{{{"{iss.id}: {_short(iss.text)}"}}}}')
    for c in g.claims:
        out.append(f'    {c.id}["{c.id}{mark(c.id)}: {_short(c.text)}"]')
        if c.issue_id:
            out.append(f"    {c.id} -.->|answers| {c.issue_id}")
    for e in g.evidence:
        out.append(f'    {e.id}(["{e.id}: {_short(e.text)}"])')
    for a in g.arguments:
        label = f"{a.id}{mark(a.id)}<br/>{a.scheme}"
        if a.is_attack:
            out.append(f'    {a.id}>"{label}<br/>{a.attacks.type}"]')
        else:
            out.append(f'    {a.id}("{label}")')
        for pid in a.premise_ids:
            out.append(f"    {pid} --> {a.id}")
        if a.claim_id:
            out.append(f"    {a.id} --> {a.claim_id}")
        if a.is_attack:
            out.append(f"    {a.id} -. {a.attacks.type} .-x {a.attacks.target_id}")
    for c in g.claims:
        for o in c.contrary_ids:
            if c.id < o:
                out.append(f"    {c.id} <-. contrary .-> {o}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summary(g: ArgumentGraph, ev: Evaluation, lb: list[LoadBearing] | None = None) -> str:
    lines = ["## Issues", ""]
    for iss in g.issues:
        accepted = ev.issues.get(iss.id, [])
        head = f"**{iss.id}** {iss.text}"
        if iss.id == g.main_issue_id:
            head += " *(main)*"
        lines.append(head)
        for c in g.claims_for_issue(iss.id):
            d = ev.claims[c.id]
            lines.append(
                f"- {_MARK[d.status]} {c.id}: {c.text}  "
                f"[{d.standard}; pro {d.pro_strength} vs con {d.con_strength}"
                f"{'; corroborated' if d.corroborated else ''}]"
            )
        if not accepted:
            lines.append("- no accepted answer yet")
        lines.append("")

    open_assumptions = [(aid, why) for aid, why in ev.inapplicable_reasons.items()]
    lines.append("## Arguments")
    lines.append("")
    for a in g.arguments:
        strength = ev.argument_strength[a.id]
        if not ev.applicable[a.id]:
            status = "inapplicable"
        else:
            status = ev.labels[a.id]
        tgt = a.claim_id if a.claim_id else f"{a.attacks.type} → {a.attacks.target_id}"
        lines.append(f"- {a.id} ({a.scheme}, {strength}) → {tgt}: **{status}**")
    lines.append("")

    if open_assumptions:
        lines.append("## Open assumptions")
        lines.append("")
        for aid, why in open_assumptions:
            lines.append(f"- {aid}: " + "; ".join(why))
        lines.append("")

    if lb:
        lines.append("## Load-bearing nodes")
        lines.append("")
        for x in lb:
            lines.append(f"- {x.node_id} ({x.kind}): {x.detail} → would become {x.effect}")
        lines.append("")

    flags = [f for f in ev.flags if f.code != "inapplicable_argument"]
    if flags:
        lines.append("## Flags")
        lines.append("")
        for f in flags:
            lines.append(f"- `{f.code}` {f.node_id}: {f.detail}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
