# Research Agent Harness — Architecture

This note records the design of a harness for answering complex questions. Its distinguishing feature is an explicit model of the arguments it makes. Every claim the harness accepts has a recorded argument behind it, every argument has a named inference pattern with its critical questions answered, every piece of evidence carries credentials and provenance, and every objection is recorded as an attack on a specific node. The final answer is a rendering of that structure, not a summary written over it.

## 1. What a harness is, and what this one decides

A harness is everything around the model that turns a stateless text completion into a system that does a task over time: the state it keeps, the context it shows the model at each step, the actions it allows, the control over what happens next, how outputs are verified, when it stops, and what trace it leaves. This harness makes the following choices.

| Decision | Choice |
|---|---|
| State | A typed argument graph (section 2), plus thin inquiry bookkeeping. No transcript is the state. |
| Context assembly | Each move is shown a typed view of the relevant subgraph, not the history. |
| Action space | Argument operations (assert claim, build argument, answer critical question, attack); web tools (search, fetch, extract); later, model instruments. |
| Control | A fixed macro-cycle; the model chooses within each move. |
| Verification | Three mechanical layers: evidence credentials, argument applicability through critical questions, and acceptance by proof standard under grounded semantics. A critic on a separate model attacks the graph. |
| Termination | Stop when no obtainable evidence could change an undecided node on the path to the main claim. |
| Observability | Hash-chained ledger of moves; Toulmin and Wigmore renderings of the graph. |

## 2. The argument model

Toulmin's layout (claim, grounds, warrant, backing, qualifier, rebuttal) is kept as the display form. It is not the data model, because it cannot represent relations between arguments, has no semantics for which claims stand, and treats grounds as given. Three layers supply what it lacks.

### 2.1 Structure (ASPIC+, Walton)

An argument is a set of premises supporting a claim through a defeasible inference rule that instantiates a named scheme. The scheme library (`inquiry/argument/schemes.py`) holds thirteen substantive schemes: expert opinion, position to know, document record, study result, sign, statistical generalization, cause to effect, correlation to cause, inference to the best explanation, analogy, consequences, definition to classification, and argument from a model or simulation. A fourteenth, `attack`, is the scheme every attack argument instantiates (section 2.2). Study result is distinct from document record: the record states an estimate, but the inference from a study's estimate to the world has to survive the questions methodologists ask, and its critical questions follow the GRADE domains (design, directness, uncertainty, risk of bias, inconsistency, imprecision). Toulmin maps onto this exactly: grounds are the premises, the warrant is the scheme's rule, backing is the record of the scheme's critical questions having been answered, the qualifier is the resulting strength, the rebuttal is the set of known attackers.

Critical questions come in two kinds, following Carneades. An *assumption* must be discharged by the proponent before the argument is applicable; an open assumption makes the argument inert. An *exception* stands unless an opponent raises it with grounds; raising it is an undercutting attack. This distinction is what makes rigor mechanical. An argument does not count because it was made; it counts when the questions its scheme is known to be vulnerable to have been answered or explicitly defaulted, and a defaulted assumption costs one level of strength.

### 2.2 Dialectic (Pollock, Dung)

Attacks have three types. *Undermining* attacks a premise (the evidence is unreliable, or a premise claim is false). *Rebutting* attacks a conclusion (an argument for the contrary). *Undercutting* attacks the inference (the scheme does not apply here). Undercuts and undermines are one-directional and are resolved by grounded semantics over the applicable arguments. Grounded semantics is skeptical and unique: a mutual attack leaves both sides undecided, which is the honest result for a research tool. Rebuttals are resolved at the claim level by proof standard. An attack is itself an argument with a grounds assumption, so a bare denial is inapplicable; a human reviewer's objection is treated as grounded by the reviewer.

### 2.3 Weight (Schum, Carneades)

Evidence carries Schum's three credentials: relevance, credibility (for testimonial evidence, veracity, objectivity and access; for tangible evidence, authenticity and accuracy) and inferential force. The weakest of the three rules, and the weakest premise rules an argument's strength. Evidence also carries an independence group: items tracing to the same origin are counted once, and two independent surviving arguments for a claim corroborate it and raise its effective strength one level.

Claims carry a proof standard: scintilla, preponderance, clear and convincing, or beyond reasonable doubt. The standard defaults from the issue's question type (causal questions default to clear and convincing; the rest to preponderance) and can be overridden per claim or at framing. A claim is *in* when its surviving pro arguments clear its standard and no contrary does; *out* when a contrary is in or only con arguments survive; otherwise *undecided*. Numeric credences may be recorded alongside; evaluation does not use them in v1, but a credence that disagrees with the dialectical status is flagged rather than averaged.

### 2.4 SEP grounding

The critical questions are Walton's in shape, but the account of what each question probes is drawn from the Stanford Encyclopedia of Philosophy entries named on each scheme, and each scheme records which of the surveyed positions it adopts. Testimony schemes take the anti-reductionist default while still demanding positive grounds for expertise and basis. Causal schemes adopt Woodward's interventionist criterion and order evidence by Pearl's ladder. Inference to the best explanation keeps Lipton's likeliest-versus-loveliest distinction and keeps van Fraassen's bad-lot objection as an exception. Statistical generalization makes the uniformity assumption an explicit, challengeable question rather than a hidden premise. The SEP text is not reproduced; the schemes are operational distillations with the entry as citation.

## 3. The cycle

Frame → Hypothesize → Plan → Gather → Compute → Argue → Critique → Respond → Revise → Evaluate → Reflect → Stop or loop → Conclude.

- **Frame** states the question's presuppositions, what a complete answer would contain, and the issue tree. Each sub-question becomes an issue node. Sub-questions are about the world; robustness, independence and whether a standard is met are computed from the graph, not asked of the sources.
- **Hypothesize** adds rival claims to each issue, including the null and the deflationary answer, and marks them contraries.
- **Plan** names the observations that would discriminate between live claims and the queries that would find them. Queries come from here, not from the question.
- **Gather** searches, fetches, extracts, and records sources and evidence with credentials and provenance; derivative sources join the independence group of the primary they repeat, and a derivative source that cannot name its origin corroborates nothing. A primary document is appraised to its end, window by window; other kinds are sampled. The source records whether it was read in full.
- **Compute** is the arithmetic instrument: the proposer names variables bound to numbers in evidence items and an expression over them; code evaluates it on a restricted syntax tree and writes a `model_output` evidence item whose provenance holds the expression, inputs and result. It is how the harness notices that two estimates are compatible.
- **Argue** builds explicit arguments from evidence to claims, one call per issue, and answers the critical questions it can answer with evidence. Every evidence item bearing on the issue's claims ends up in an argument or is marked unusable with a reason.
- **Critique**, on a separate model, walks every argument's open exceptions and attacks where one can be grounded, attempts a rebuttal of every accepted claim, and probes every evidence item's credentials. Its view holds the arguments and evidence, not the proposer's reasoning. Each attack records whether its grounds are something a source says or something it does not say; an absence counts only if the source was read in full, otherwise the attack's grounds stay open.
- **Respond** gives the proposer the reply a proponent is owed. For each standing attack it discharges, counters, or concedes. An undercut records the critical question it raises; answering that question with evidence discharges the attack with no new node (Carneades: a raised exception is met, not denied). A counter is an undercut of the critic's attack grounded in evidence. Without this move the critic wins by default and procedural uncertainty is indistinguishable from real uncertainty.

- **Revise** turns review findings into changes of state. A critical-question answer records what the check established (satisfied, unsatisfied, unresolved), and an unsatisfied check leaves the argument inapplicable rather than counting as answered. For each material finding the proposer narrows a claim to the population, outcome, horizon or quantity the evidence supports, splits a compound claim into parts with different support, reclassifies an item as context or lead, withdraws a support relation while keeping the evidence, retains the claim with the reason a criticism does not defeat it, or requests a specific retrieval. Revised claims carry a target description; the conclusion is written from live claims only. Computations record each input's population, outcome, comparison, source and location, refuse to combine inputs from different comparisons without a stated harmonisation, and carry "uncertainty not established" unless it can be stated.

Three further rules shape the graph. Rivalry is declared, not assumed: Hypothesize names which claims are mutually exclusive, and only those are contraries, besides the null and deflationary answers which are rivals of every substantive answer. Origins are computed from sources, not items: a source's origin is its DOI, else the origin of what it derives from, else its normalised title, else its publisher, and corroboration requires two accepted arguments whose origins are disjoint. A relay yields to its original: when the original's own evidence bears on a claim, the relay's items are set aside.
- **Evaluate** is pure code: applicability, grounded labelling, proof standards, flags.
- **Reflect** reports what is established and what is assumed. Its core is computable: the load-bearing nodes are those whose removal changes the main claim's status.
- **Stop** asks whether any planned, obtainable evidence could change an undecided node on the path to the main claim. If none can, further search has no value.
- **Conclude** renders the accepted claims as key judgements, each with its confidence and the assumption it rests on, and lists what would change the answer.

Human pushback enters at Reflect and before Conclude as attack nodes tagged `human`.

Each model-backed move is shown a typed view of the subgraph it needs and must return one JSON object matching a contract in `inquiry/moves.py`. The apply step is deterministic and defensive: unknown ids are dropped, duplicate arguments merged, answers to exception questions ignored at Argue, attacks without grounds discarded at Critique, and a judgement that cites no accepted claim capped at low confidence at Conclude. Critique runs on the critic model; everything else on the proposer. Evaluate, Reflect and Stop are code: Reflect combines `load_bearing()` with `what_would_settle()`, which lists for each undecided claim what stands between it and acceptance (no argument, an open assumption, a standing attack, a shortfall against the standard, a missing second origin, a surviving contrary). Stop halts when the main issue has an accepted claim, when no undecided main claim has a settler, when a round found no new evidence, or when rounds are exhausted. The critic's requests for evidence feed the next round's Plan.

**Worked example.** `examples/turn_time.py` builds the turn-time case by hand. A regulator's table shows mean turn time falling from 118 to 104 minutes; a statistical-generalization argument for a 12% fall is inapplicable while its measurement assumption is open, becomes applicable once that is answered, and is then undercut by a methodology note showing the two years define "turn" differently. The claim ends undecided, which is the correct result, and the load-bearing list names the undercut as the node that would change it.

## 4. Web layer

Search (Serper), fetch, extract to text, store the text with the source. An appraisal step fills the source's competence and incentives and the evidence credentials, and traces origin for the independence group. Short quotes with location are stored on every evidence item because the critic's credential probes need the passage, not a summary.

## 5. Models as instruments

A simulation run, causal estimate or optimization result enters the graph as `model_output` evidence whose credentials are the model's validation status and whose provenance records version, inputs and seed. It supports claims through the `model_output` scheme, whose critical questions are validation for the regime, sourced inputs, reproducibility and sensitivity. Argue, Critique and Evaluate apply unchanged.

## 6. Build phases

1. **Argument core** (done): graph, schemes, evaluation, renderers, tests. Deterministic; no model calls.
2. **Web layer** (done): Serper search, httpx fetch, trafilatura and pypdf extraction, appraisal skill, source text in the store. Fakes for both tools.
3. **Moves as skills** and the cycle (done, tested with fakes): each move a SKILL.md (SEP-grounded procedure, output contract) plus views, contract and apply step in `moves.py`; proposer and critic on different models; interactive mode with the human as reviewer. Not yet run against live models; expect contract mismatches on the first live runs.
4. **Instruments** (started): the arithmetic instrument is built as the Compute move. The next is a data-fetch tool: questions about what monitors recorded live in ratified data tables (LAQN, AURN and the like), which web prose never settles. Such a tool pulls site-level data and writes tangible evidence with provenance. Simulation and causal-estimate instruments follow the same pattern.

## 7. Repository layout

```
inquiry/
  argument/
    graph.py      issues, claims, evidence with credentials and bears_on, sources, arguments, attacks
    schemes.py    thirteen schemes plus attack, typed critical questions, SEP grounding
    evaluate.py   applicability, grounded labelling, proof standards, flags, load_bearing, what_would_settle
    render.py     Toulmin view, Wigmore chart (Mermaid), markdown summary
  skills/         frame, hypothesize, plan, appraise, compute, argue, critique, respond, conclude (SKILL.md each)
  tools/
    search.py     SerperSearch, FakeSearch
    fetch.py      HttpFetcher, FakeFetcher
    compute.py    restricted arithmetic evaluator for the compute instrument
  moves.py        views, output contracts, apply steps; evaluate, reflect and stop as code
  live.py         Harness: the cycle, gather (targeted reads, supplementary hop), human review, report; CLI
  metrics.py      one line of numbers per run; gold matching and expected shape
  bench.py        runs bench/questions.yaml by split, writes bench/results/<date>.json
bench/questions.yaml    six questions: one regression, three held_in, two held_out
  state.py        Inquiry: framing, planned tests, reflections, stop assessments, evaluation, conclusion
  store.py        inquiry.json, hash-chained ledger.jsonl, sources/
  llm.py          proposer/critic LLM handles; JSON-validated completions; FakeLLM scripted by skill name
examples/turn_time.py   the worked example from section 3
tests/                   argument-core tests; one full cycle on fakes
```

## 8. References

Dung (1995), acceptability of arguments; Pollock (1987), defeasible reasoning and defeaters; Prakken (2010), ASPIC+; Gordon, Prakken and Walton (2007), the Carneades model of argument and burden of proof; Walton, Reed and Macagno (2008), *Argumentation Schemes*; Schum (1994), *The Evidential Foundations of Probabilistic Reasoning*; Anderson, Schum and Twining (2005), *Analysis of Evidence*; Wigmore (1913), the chart method; Chesñevar et al. (2006), the Argument Interchange Format; Woodward (2003), *Making Things Happen*; Pearl (2009), *Causality*; Lipton (2004), *Inference to the Best Explanation*. SEP entries: Argument and Argumentation; Defeasible Reasoning; Informal Logic; Epistemological Problems of Testimony; Evidence; Confirmation; Inductive Logic; The Problem of Induction; Causation and Manipulability; Counterfactual Theories of Causation; Abduction; Analogy and Analogical Reasoning; Models in Science; Computer Simulations in Science; Scientific Objectivity; Decision Theory.
