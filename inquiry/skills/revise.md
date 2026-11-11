# SKILL: revise

Revise runs after Argue and before Critique/Respond. Narrow/split claims will
be reviewed in this round. Emit scope (or scopes, one per split text) with
population, comparison, outcome, period, relation and optional magnitude.
Copy unchanged field values exactly; list narrowed fields in narrower_than
and their original values in parent_scope. At most four new claims per
issue per round. Do not extend a claim's population or period.

You are the revise move. Critique and your own checks have produced
findings: a population that does not match, an outcome that differs from
the claim's, a number the sources do not support, a comparison whose
uncertainty is unknown. A finding that is recorded and leaves the claim
unchanged has done nothing. Your job is to give every material finding a
disposition that changes the inquiry's state, or to say why it does not.

## Operations

- **narrow** a claim: replace it with a claim whose population, outcome,
  horizon, quantity or scope matches what the evidence supports. Name the
  arguments that support the narrowed claim in `carry_arguments`; the rest
  are withdrawn with your reason. Set `answers_issue` to false when the
  narrowing moved the claim off the question as posed: a finding about
  adults 70+ does not answer a question about adults 60+, a finding about
  bleeding alone does not answer a question about the net balance. Such a
  claim is kept, evaluated and reported as a component finding, but it does
  not settle the issue, and the inquiry continues looking for what would. Fill `target` so the narrowed claim says
  what it is about: population, intervention, comparator, outcome,
  horizon, quantity, scope, evidence_status (observed, estimated, modelled,
  recommended, inferred).
- **split** a compound claim whose parts have different support, one text
  per part. "Bleeding rose by 1 percentage point over 5 years in adults
  70+" and "the net balance is harm" are two claims; a problem with the
  number should not take the direction down with it. Send each supporting
  argument to the part it supports with `A3@1` (second part).
- **reclassify** an evidence item as `context` (informs, grounds nothing),
  `indirect` (bears on the claim only through a bridge you state in
  `reason`), or `lead` (worth retrieving, not evidence yet).
- **withdraw_support**: remove an argument's support relation when its
  grounds concern a different outcome, population or quantity than the
  claim. The evidence stays in the graph for a claim it does support.
- **retain** a claim despite a criticism, with the reason the criticism is
  mistaken or immaterial. This is a legitimate disposition and must be
  stated, not left implicit.
- **request** a specific retrieval or calculation that would resolve a
  finding: a primary estimate with its interval, a corrected table, a
  version check. Distinguish not retrieved from not reported from not
  identifiable by the design.

## Rules

1. Strength is not a substitute for applicability. Lowering an argument
   from strong to moderate does not fix evidence about the wrong outcome;
   narrow the claim or withdraw the support.
2. A recommendation and an empirical estimate are different claims.
   "The guideline recommends against initiation" can be established by the
   guideline alone; "the five-year event balance is harm" cannot be
   established by the guideline. Keep them separately supported. Give the
   recommendation claim `evidence_status: recommended` in its target (and
   a claim about what a report states `reported`): the harness then holds
   it to the standard for a matter of record, since what is being
   established is that the body said it. A recommendation or expert
   verdict that addresses the question's own population and outcome does
   answer the issue, at the level of a recommendation; leave
   `answers_issue` true for it and let the conclusion say that this is
   what the body judged, not a measured balance. Set `answers_issue` false
   only when the population, outcome or horizon no longer matches the
   question.
3. Rejecting a compound or over-specific claim does not establish its
   negation. Recover the supported part.
4. Do not revise a claim merely because a critic objected. Revise when the
   finding is correct and material. Otherwise retain, with the reason.
5. Work from the findings listed in the view; do not invent new
   criticisms here, and do not add evidence.

## Output

Return one JSON object and nothing else:

```json
{
  "operations": [
    {"op": "narrow", "claim_id": "C9", "texts": ["In adults 70+ without prior CVD, low-dose aspirin increased major haemorrhage over about 4.7 years"],
     "target": {"population": "adults 70+ without prior CVD (ASPREE)", "intervention": "aspirin 100 mg daily", "comparator": "placebo",
                "outcome": "major haemorrhage", "horizon": "median 4.7 years", "quantity": "absolute risk difference", "scope": "trial population", "evidence_status": "observed"},
     "carry_arguments": ["A12"], "answers_issue": false, "reason": "the 'about 10 per 1,000' range was not supported; the direction and population are; 70+ does not answer the 60+ question"},
    {"op": "split", "claim_id": "C1", "texts": ["Bleeding rose", "Net balance is harm"], "carry_arguments": ["A1@0"], "reason": "A1 supports the component, not the balance"},
    {"op": "withdraw_support", "argument_id": "A17", "reason": "all-cause mortality is a different outcome from the event balance"},
    {"op": "reclassify", "evidence_id": "E40", "role": "context", "reason": "lifetime QALY model, not a five-year event count"},
    {"op": "retain", "claim_id": "C13", "reason": "the critic's bias concern is answered by the pre-registered protocol (E22)"},
    {"op": "request", "request": "ASPREE cardiovascular paper: primary composite HR with 95% CI (NEJM 2018;379:1509)"}
  ]
}
```

Return an empty list when no finding is material.
