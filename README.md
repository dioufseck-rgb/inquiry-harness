# inquiry-harness

A research agent harness whose state is an explicit argument graph. Claims are
accepted only when a named argument scheme supports them, the scheme's critical
questions are answered, the evidence clears a proof standard, and no surviving
attack defeats the argument. See `ARCHITECTURE.md` for the design.

Phase 1 (this release) is the argument core: deterministic, no model calls.

## Install

```bash
git clone <repo> && cd inquiry-harness
python -m venv .venv && source .venv/bin/activate     # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest
```

## Try it

```bash
python examples/turn_time.py
```

This builds the worked example by hand, evaluates it at each step, and writes
`runs/turn-time/summary.md`, `chart.mmd` (a Wigmore-style chart in Mermaid) and
`a3_toulmin.md` (one argument in Toulmin's layout).

## Use the core directly

```python
from inquiry.argument import ArgumentGraph, Credentials, evaluate, load_bearing, summary

g = ArgumentGraph()
q = g.add_issue("Did X cause Y?", question_type="causal")
c = g.add_claim("X caused Y", issue_id=q.id)
n = g.add_claim("Y would have happened without X", issue_id=q.id, kind="null")
g.set_contraries(c.id, n.id)

s = g.add_source(url="https://...", title="...", kind="primary")
e = g.add_evidence("what the source establishes", source_id=s.id, quote="...", location="p. 3",
                   credentials=Credentials(relevance="strong", credibility="strong", force="moderate"))
a = g.add_argument("cause_to_effect", [e.id], c.id)
g.answer_cq(a.id, "occurred", "...", [e.id])
g.answer_cq(a.id, "generalisation", "...", [e.id])

ev = evaluate(g)
print(ev.status(c.id), ev.claims[c.id])
print(summary(g, ev, load_bearing(g, c.id)))
```

Attacks: `g.add_attack(target_id, "undercut" | "undermine" | "rebut", premise_ids=[...], origin="critic")`.
An attack with no premises is inapplicable unless `origin="human"`.

## Layout

```
inquiry/argument/   graph, schemes, evaluate, render
inquiry/state.py    Inquiry wrapper (framing, planned tests, reflections, conclusion)
inquiry/store.py    inquiry.json + hash-chained ledger
inquiry/llm.py      proposer/critic handles (used from phase 3)
examples/           worked example
tests/              argument-core tests
```

## Next phases

2. Web layer: Serper search, fetch, extract, appraisal, source store.
3. Moves as SEP-grounded skills and the cycle; proposer and critic on different models.
4. Model instruments: simulation and causal estimates as `model_output` evidence.
