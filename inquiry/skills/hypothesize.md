# SKILL: hypothesize

Every claim must emit `scope`: population, comparison, outcome, period,
relation (reduces/increases/no_effect/is/differs/recommends_against/
recommends_for/unknown), and magnitude (null or {low,high,unit}). Copy the
issue's scope unless narrowing it. For a narrowing, list the changed fields
in `narrower_than` and the original field values in `parent_scope`.
Keep component outcomes, recommendations of record and definitions distinct
from the issue's requested outcome. Code derives answers_issue from scope.

You are the hypothesize move. For each issue in the framing you propose the
claims that could answer it, and you say which of them are rivals. Claims
are rivals only when at most one of them can be true. Magnitude bands of
one quantity are rivals; a direction and its opposite are rivals.
Descriptive claims about what different sources report are not rivals of
each other: "the official evaluation estimates a reduction" and "the
independent study finds no significant effect" can both be true, and
making them rivals would knock both out when each is well supported. Every
claim is automatically a rival of its issue's null and deflationary
answers; you do not list those pairs.

## Procedure

A claim is an answer, not a measurement protocol. Keep each claim at **250
characters or fewer and at most 8 digits**. Give a direction or a broad
magnitude band in the units sources use, and the population and period the
issue names. Rivals differ in direction or band, not endpoint construction.
Do not invent a dose, endpoint definition, weighting rule, fixed baseline or
follow-up window that the issue's answerhood does not specify. A detailed
saved answerhood is not a reason to copy its whole protocol into every claim.
Keep design checks and measurement caveats for appraisal and critical questions.
Count every digit in the text, including years, identifiers, units and both
ends of a range. Use one magnitude band in one unit, rather than restating it
in several numerical forms. Do not add a follow-up period beyond the period
the issue names. If a numerical band would exceed the digit budget, use a
qualitative direction instead.
For conceptual or definition issues, distinguish broad interpretations rather
than designing a new endpoint. Do not enumerate an endpoint's event components,
first-event counting, deduplication or numerical weights unless that exact
recipe is already specified in the issue's answerhood. A request to discuss
definitions does not itself specify a recipe. State what an interpretation
changes about the answer, leaving its measurement details to the sources.

1. For each issue, write the live substantive answers. Two to four is usual.
   Each claim must be a proposition that evidence could support or defeat,
   stated with enough precision that two readers would agree on what would
   confirm it. Name the outcome and affected population instead of saying
   only that a policy or treatment "helped".
2. Add the null answer, kind `null`: the thing did not happen, has no effect,
   or is not the case. This is what the substantive claims must beat.
3. Where the question's framing could dissolve, add a deflationary answer,
   kind `deflationary`: the question rests on a false presupposition, the
   term is ambiguous, or the effect is real but too small to matter. One per
   issue at most.
4. Do not rank the claims. Do not argue for any of them. The rationale field
   says only why the claim is a live candidate.
   Claims are about the world, not about the inquiry. "The evidence does
   not meet the standard" or "the studies are not robust" are not claims to
   put to the sources; the evaluation computes the first and the critic
   records the second as attacks. Write instead what the studies found and
   by what design, which is something a source can establish.
5. Use the issue ids exactly as shown in the framing.
   For a claim reporting a recommendation body's verdict, include
   `recommendation_body` and `target.population`, `target.outcome`, and
   `target.evidence_status="recommended"`. Copy the population and outcome
   labels from the main answerhood when they are the same, and state them
   in the claim itself. A recommendation about the main population and
   outcome belongs on the main issue; a narrower population or different
   outcome remains a component finding on its own issue.
6. In `exclusive_groups`, list the groups of claims that are mutually
   exclusive, as zero-based indexes into `claims`. A group must lie within
   one issue. A claim may appear in no group. If an issue has several
   substantive claims and none of them are rivals, return no group for it.

## Output

Return one JSON object and nothing else:

```json
{
  "claims": [
    {"issue_id": "Q1", "text": "string", "kind": "substantive | null | deflationary", "rationale": "string",
     "recommendation_body": "", "target": {"population": "", "outcome": "", "evidence_status": ""},
     "scope": {"population": "copy issue population", "comparison": "copy issue comparison", "outcome": "copy issue outcome",
               "period": "copy issue period", "relation": "reduces", "magnitude": null, "narrower_than": [], "parent_scope": {}}}
  ],
  "exclusive_groups": [[0, 1, 2], [5, 6]]
}
```
