"""
Worked example from the architecture note: builds the argument graph by hand,
evaluates it at each step, and writes the summary and Wigmore chart.

    python examples/turn_time.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inquiry.argument import ArgumentGraph, Credentials, evaluate, load_bearing, summary, toulmin, wigmore
from inquiry.store import InquiryStore
from inquiry.state import Inquiry

g = ArgumentGraph()
q2 = g.add_issue("Did the 2024 schedule change reduce fleet turn time?", question_type="causal",
                 answerhood="A direction and rough magnitude of change, with the measure held constant across periods.")
c4 = g.add_claim("Turn time fell by about 12% after the change", issue_id=q2.id)
c5 = g.add_claim("Turn time did not change materially", issue_id=q2.id, kind="null")
g.set_contraries(c4.id, c5.id)

s1 = g.add_source(url="https://example.org/regulator-2024", title="Regulator annual report 2024", kind="primary",
                  competence="collects operational returns from every operator")
e7 = g.add_evidence("Table 4: mean turn 118 min in 2023 vs 104 min in 2024, all routes",
                    source_id=s1.id, quote="mean turn time 118 / 104", location="p. 37",
                    credentials=Credentials(relevance="strong", credibility="strong", force="moderate",
                                            credibility_notes="aggregated across routes"))
a3 = g.add_argument("statistical_generalization", [e7.id], c4.id)
g.answer_cq(a3.id, "representative", "covers about 90% of the fleet", [e7.id])
g.answer_cq(a3.id, "size", "full-year operational returns; no sampling", [e7.id])
# 'measurement' left open on purpose

def show(title):
    ev = evaluate(g)
    print(f"\n=== {title} ===")
    print(f"{c4.id}: {ev.status(c4.id)}   {c5.id}: {ev.status(c5.id)}")
    for f in ev.flags:
        print(f"  flag {f.code} {f.node_id}: {f.detail}")

show("after one argument with an open assumption")

g.answer_cq(a3.id, "measurement", "same regulator form both years")
show("after discharging the measurement assumption")

e8 = g.add_evidence("2023 methodology note defines turn as arrival-to-departure; 2024 as arrival-to-ready",
                    source_id=s1.id, location="p. 80", credentials=Credentials(relevance="strong", credibility="strong", force="strong"))
x1 = g.add_attack(a3.id, "undercut", premise_ids=[e8.id], origin="critic",
                  note="the 2023 figure uses a different turn definition")
show("after the critic's undercut")

ev = evaluate(g)
lb = load_bearing(g, c4.id)
out = Path("runs/turn-time")
store = InquiryStore("runs", "turn-time")
inq = Inquiry(id="turn-time", question=q2.text, graph=g, phase="inquiring", round=1)
store.save(inq)
store.append_event("evaluate", inq, {"c4": ev.status(c4.id)})
(out / "summary.md").write_text(summary(g, ev, lb), encoding="utf-8")
(out / "chart.mmd").write_text(wigmore(g, ev), encoding="utf-8")
(out / "a3_toulmin.md").write_text(toulmin(g, a3.id, ev), encoding="utf-8")
print(f"\nwrote {out}/summary.md, chart.mmd, a3_toulmin.md; ledger ok = {store.verify_ledger()}")
print()
print(summary(g, ev, lb))
