# inquiry-harness

A research agent harness whose state is an explicit argument graph. Claims are
accepted only when a named argument scheme supports them, the scheme's critical
questions are answered, the evidence clears a proof standard, and no surviving
attack defeats the argument. See `ARCHITECTURE.md` for the design.

Phases 1 to 3 are built: the argument core (deterministic, no model calls),
the web layer, and the cycle of moves driven by a proposer and a critic on
different models. The cycle is tested end to end with fakes, and has run
once against live models (Sonnet 5.5 proposer, Opus 5.5 critic) with fake
search and fetch; every move's JSON contract held. Live search has not been
exercised yet.

## Install

```bash
git clone <repo> && cd inquiry-harness
python -m venv .venv && source .venv/bin/activate     # .venv\Scripts\activate on Windows
pip install -e ".[dev,llm,web]"
pytest
```

`dev` is enough for the tests. `llm` adds the Anthropic SDK; `web` adds
httpx, trafilatura and pypdf for search and fetch.

## Run an inquiry

```bash
cp .env.example .env     # fill in ANTHROPIC_API_KEY and SERPER_API_KEY
python -m inquiry.live "Did the 2024 schedule change reduce fleet turn time?" --rounds 2
```

Round 0 frames the question and proposes rival claims. Each round plans the
discriminating tests, searches and fetches sources, appraises them into
evidence with credentials (primary documents read to the end), computes
over the numbers it found, builds arguments, has the critic attack them,
lets the proposer answer the attacks that stand, evaluates the graph,
reflects, and decides whether another round could change anything. Then it
concludes. Output goes to `runs/<id>/`:
`report.md` (answer, judgements, graph summary, surviving arguments in
Toulmin layout), `chart.mmd` (Wigmore chart in Mermaid), `inquiry.json`
(full state), `ledger.jsonl` (hash-chained record of every move) and
`sources/` (extracted text).

Options: `--rounds N`, `--max-sources N` new sources per round, `--queries N`
per round, `--hits N` per query, `--read-parts N` appraisal windows of about
12k characters per primary document (default 36, enough for a 400k-character
report; other source kinds get one window), `--interactive` to enter
objections after each critique as `<target_id> <undermine|undercut|rebut>
<text>`, `--id NAME` to name the run or resume one that stopped, and
`--evidence-from runs/<id>` to replay the cycle on the sources an earlier run
held, with retrieval fixed, so two versions of the harness can be compared.

Benchmark: `python -m inquiry.bench bench/questions.yaml --split held_in`
runs the question set by split and writes a metrics table to
`bench/results/`.

Models come from `INQUIRY_PROPOSER_MODEL` and `INQUIRY_CRITIC_MODEL`; the
critic should be a different model from the proposer.

## Worked example without models

```bash
python examples/turn_time.py
```

This builds the turn-time example by hand, evaluates it at each step, and writes
`runs/turn-time/summary.md`, `chart.mmd` and `a3_toulmin.md` (one argument in
Toulmin's layout). It ends undecided on purpose: the one argument for a fall
in turn time is undercut by a definition change the critic found.

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
inquiry/argument/   graph, schemes, evaluate (incl. load_bearing, what_would_settle), render
inquiry/skills/     one SKILL.md per model-backed move: frame, hypothesize, plan,
                    appraise, compute, argue, critique, respond, conclude
inquiry/tools/      search (Serper + fake), fetch (httpx/trafilatura/pypdf + fake),
                    compute (restricted arithmetic evaluator)
inquiry/moves.py    views, output contracts and apply steps for every move
inquiry/live.py     the cycle, gather, human review, report, CLI
inquiry/state.py    Inquiry wrapper (framing, planned tests, reflections, conclusion)
inquiry/store.py    inquiry.json + hash-chained ledger + source text
inquiry/llm.py      proposer/critic handles; FakeLLM scripted by skill name
examples/           worked example
tests/              argument-core tests and a full fake-driven cycle
```

## Next

- Run against live models and search; expect JSON-contract mismatches. The
  contracts in `inquiry/moves.py` are the source of truth; adjust the skill
  text to match them, not the reverse.
- Phase 4, model instruments: a `run_model` tool that writes `model_output`
  evidence with provenance and builds a `model_output` argument.
