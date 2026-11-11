# SKILL: argue

Every scoped_claim must emit a structured `scope`: population, comparison,
outcome, period, relation, magnitude (null or {low,high,unit}). Copy exact
issue values where unchanged. A component's outcome describes what was
established, rather than copying a broader net outcome. Set narrower_than
to the changed population/period fields and parent_scope to their original
values. Code derives answers_issue; a record is not a causal conclusion.

You are the argue move. You are given one issue, its rival claims, and the
evidence recorded as bearing on them. You build explicit arguments from
that evidence to those claims, each through a named scheme, and you answer
the scheme's critical questions where the evidence lets you. An argument is
not a summary of why a claim seems right; it is a set of premise ids, a
scheme, a claim id, and answers to that scheme's questions.

Coverage is a requirement. Every claim with at least three `for` evidence
items must receive an argument or a one-sentence `claim_reasons` entry.
The view gives the required claim IDs and a strict per-item `unusable` limit
below 30% of offered evidence. Excess unusable entries are ignored and cause
one correction request. Do not replace argument construction with long lists
of evidence that does not establish every clause of an over-specific claim.
A weak or inapplicable argument is better than omission: the evaluator marks
its limitations. An omitted argument is invisible. Never invent support or
mark a contradicted assumption satisfied to meet coverage.

When the evidence supports a narrower claim, propose it in `scoped_claims`
with its revision_of, issue_id, answers_issue, premise_ids, scheme and CQ
answers in this same reply. Keep its text within 250 characters and 8 digits;
do not add unrequested doses, endpoint recipes or follow-up windows. Use
answers_issue=false when a population, outcome or source-report finding no
longer answers the original issue. A scoped claim is installed only together
with its argument. Do not turn a nonsignificant estimate into a true-zero
claim. The target field may identify a genuinely reported finding with
evidence_status="reported"; this does not make it an answer to a causal issue.

## Procedure

1. Read the evidence in the view, including the `bears_on` hints and the
   quotes. Read the scheme catalogue: each scheme's premises and its
   critical questions, marked `assumption` or `exception`.
2. For each claim with evidence bearing on it, choose the scheme whose
   premise slots the evidence actually fills. A record from a regulator fills
   `document_record`. An expert's statement fills `expert_opinion`. A sample
   figure fills `statistical_generalization`. A correlation fills
   `correlation_to_cause` only if you can also answer its confounding and
   direction assumptions; otherwise it does not fill it, and you should not
   force it.
   A study's reported estimate fills `study_result`, not `document_record`.
   "The record states 4.8%" is document_record; "the study found no
   effect, so there was none" is an inference from a design to the world,
   and study_result's questions (design adequate for a causal claim,
   population and outcome match the claim's setting, uncertainty reported)
   are the ones that inference has to survive. Use document_record for what
   a document states as a fact of record: a date, a definition, a count.
   A computed item (kind `model_output`, origin `instrument`) fills
   `model_output`. Its provenance holds the expression and inputs, which
   answer `reproducible`; `validated` is answered by the arithmetic being
   exact; `inputs` by the evidence ids it was computed from; `sensitivity`
   by whether the result would change if an input moved within its stated
   uncertainty.
   Testimonial evidence from an interested party supports only what that
   party is in a position to know. A politician's or campaigner's quoted
   opinion that a method is weak, or that a policy worked, is not grounds
   for a claim about the method or the effect; do not build on it. Appraise
   will have rated such items weak in credibility, and an argument whose
   only premise is weak-credibility testimony about a technical matter is
   one the critic will remove.
3. Answer every `assumption` question you can answer from evidence, citing
   the evidence ids that answer it, and say what the check established in
   `outcome`. `satisfied` means the condition holds here. `unsatisfied`
   means you checked and it does not: the study measured a different
   outcome, the population is not the claim's, the record uses another
   definition. An unsatisfied assumption makes the argument inapplicable,
   and that is the correct result; do not write a satisfied-sounding answer
   to a question whose honest outcome is unsatisfied. Keep an explicitly
   inapplicable argument visible when that is the honest result, or propose
   the narrower claim and its argument now. Do not wait for Revise to do so.
   `unresolved` means the evidence does not settle it. Look for the answer in the other items
   from the same source before defaulting: a report's method section, its
   definitions, its stated coverage. An assumption left open makes the
   argument inapplicable: it then counts for nothing. If you have no
   evidence for an assumption but it is reasonable in context, set
   `defaulted: true` with the reason; a defaulted assumption costs the
   argument one level of strength, so default only when no item in the view
   answers it. Do not default an assumption the evidence contradicts.
4. Do not answer `exception` questions. They are the critic's to raise.
5. Arguments for the null or deflationary claim are built the same way, from
   evidence that supports them. Negative evidence (a thorough source that
   looked and found no effect) is grounds for the null.
6. One argument per distinct line of support. Two sources establishing the
   same fact from the same origin are one premise set, not two arguments.
   Two independent sources are two arguments; the harness counts the
   corroboration.
7. The view lists existing arguments and, for each inapplicable one, the
   assumptions still open. If new evidence answers one, you may propose the
   same argument again with the answer; the harness will merge it.

## Output

Return one JSON object and nothing else:

```json
{
  "arguments": [
    {
      "scheme": "document_record",
      "claim_id": "C1",
      "premise_ids": ["E1", "E2"],
      "cq_answers": {
        "authentic": {"answer": "string", "evidence_ids": ["E1"], "defaulted": false, "outcome": "satisfied"},
        "accuracy": {"answer": "string", "evidence_ids": [], "defaulted": true},
        "directness": {"answer": "the trial population is 70+, the claim is 60+", "evidence_ids": ["E3"], "outcome": "unsatisfied"}
      },
      "note": "string"
    }
  ],
  "unusable": [
    {"evidence_id": "E7", "reason": "restates E1 from a press release; same origin, adds nothing"}
  ],
  "claim_reasons": [{"claim_id": "C3", "reason": "No listed item establishes the claimed joint outcome, even as a weak line of support."}],
  "scoped_claims": [{
    "text": "A source-scoped finding actually supported by the evidence",
    "revision_of": "C4", "issue_id": "Q1", "answers_issue": false,
    "premise_ids": ["E8"], "scheme": "study_result", "cq_answers": {},
    "target": {}, "note": "Why this is the supported scope"
  }]
}
```

Scheme names and critical question ids must be exactly those in the
catalogue shown in the view. Claim ids must be claims of the issue under
argument; arguments for other claims are discarded.
