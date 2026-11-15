# Source adjudication: the first judgment pattern

Design note for increment B of the premise gate, written before any code.
Version target: 1.0.0a7. The kernel semantics of the seven existing patterns
do not change.

## Why this pattern

The kernel proves record-level claims: that a source reports something, that
a record states something, that a rule applied to admitted antecedents yields
its consequence. The need the premise gate serves lives one step further on:
several reports about one matter, some of them opposed, from sources with
different placement and different interests, and a caller who needs to know
what the matter is. "Was the required inspection completed before the unit
returned to service" is not a question about what the contractor's report
says. It is a question about the inspection, answered by weighing what the
contractor, the inspector, the sensor and the shift note each report.

`source_adjudication` concludes a world assertion from two or more admitted
reports about it. It is the smallest judgment pattern that makes the three
things the gate must get right explicit and checkable: who was placed to know,
who had a stake, and what to do with a report that says the opposite.

## The pattern

| | |
|---|---|
| Name | `source_adjudication` |
| Conclusion form | `assertion` (the same form `document_record` concludes) |
| Premises | At least two admitted `attribution` claims (form `source_reports`), each with its own `attribution` argument resting on located evidence. Code-checked. |
| Required conditions | `positioning`, `interest`, `independence`, `opposition`, `inference_validity`, `applicability` |
| Assumable conditions | None |

The conditions, as the proposer must assess them and the critic may challenge
them:

- **positioning**: each relied-on source was placed to observe or know the
  matter. A clerk relaying what the contractor said was not; an inspector who
  attended was; an automated record of the test sequence was.
- **interest**: each relied-on source's stake in the matter is identified and
  weighed. A contractor paid on completion has a stake in reporting completion;
  that does not exclude the report, but the assessment must say what weight it
  carries and why.
- **independence**: the relied-on reports do not share an origin. The code part
  of this is the existing support-origin count against `profile.min_origins`;
  a source declared `derived_from` another contributes no origin of its own
  because lineage resolves to root origins. The assessed part is whether
  reports that are nominally separate in fact rest on one observation.
- **opposition**: every opposed report in the exposed evidence is identified
  and answered. The code part is that each opposed report is recorded as an
  attack the kernel can see and that the adjudication stands only when each
  such attack is discharged.
- **inference_validity** and **applicability**: as for the other patterns.

### Opposed reports

An opposed report is recorded as an `Attack` of kind `rebut` on the
adjudicated claim, with `support_argument_id` naming the attribution argument
for the opposing report. The attack is founded on that argument's node, so it
is admitted only when the opposing report is itself a located, attributed
record; and it participates in the grounded labelling with everything else.
The adjudication stands only when each such attack has a reply the kernel
admits. The reply machinery is used unchanged: a reply condition with status
`met`, located reply evidence, a reply reason, raised in a later revision than
the attack. That ordering rule means a scripted or live worker answers an
opposed report by submitting the graph with the attack and then submitting
the reply, never both at once.

### What code checks and what a model judges

Code checks, in the kernel, with a diagnostic for each:

1. The argument's pattern is permitted by the profile (existing check, now
   decisive for pattern selection: see `starter_graph` below).
2. The conclusion form is `assertion` (`pattern_claim_form_mismatch`).
3. There are at least two premises, all admitted claims whose form is
   `source_reports`, each supported by at least one valid `attribution`
   argument (`adjudication_requires_attributed_reports`).
4. Premise scopes match the argument scope (existing check).
5. All six required conditions are present, distinct, and `met`; none may be
   assumed (`required_conditions_missing`, `required_conditions_not_distinct`,
   and the ordinary condition checks).
6. The support-origin count of the standing derivation reaches
   `profile.min_origins` (existing finding rule, `minimum_support_origins_not_met`).
7. Each `rebut` on the claim is admitted only with grounds and a founded
   supporting argument; a reply discharges it only from a later revision with
   a met condition and located evidence (existing attack and reply rules).

A model judges the truth of the six condition assessments and whether a
report is in fact opposed. The kernel never reads prose for either.

### `starter_graph`

`starter_graph` currently takes the first pattern whose forms include the
target form; for `assertion` that is always `document_record`. It will take
the first fitting pattern that the profile's `allowed_patterns` permits, in
catalogue order, and fall back to the first fitting pattern when the profile
lists none. A caller selects adjudication by listing it in `allowed_patterns`.
No existing fixture lists `allowed_patterns` that excludes `document_record`,
so the 378-run matrix is unaffected.

## Issuer interest

Source documents gain an optional `issuer_interest` string: the issuer's
declared stake in the matter, supplied by the caller. It is shown in the
manifest and in `search` and `open` results. The kernel does not interpret
it; it is data for the proposer's `interest` assessment and for the critic.

## The fixture family

Setting: plant maintenance. Question: was the required post-overhaul
inspection of a unit completed before the unit returned to service on a given
date. Profile: `min_origins` 2, `allowed_patterns` `["attribution",
"source_adjudication"]`, so a single origin cannot establish the assertion
and the adjudication pattern is selectable.

Sources, with their declared interest:

| Source | Issuer | Placement | Interest |
|---|---|---|---|
| Contractor completion report | contractor, paid on completion | performed the work | paid on completion |
| Independent inspector's log | third-party inspector | attended the inspection | none declared |
| Supervisor's shift note | plant shift supervisor | on shift, did not attend | none declared |
| Automated sensor record | test-rig logger | recorded the test sequence | none |
| Memo derived from the contractor's report | plant office | relays the report | none; `derived_from` the report |
| Clerk's note (hearsay case) | plant office clerk | relays what the contractor said | none |

Six case types, each with two surface variants (a pump and a compressor, with
different identifiers, dates and wording), twelve cases in all:

| Case | Evidence | Expected target status | Expected mechanism |
|---|---|---|---|
| corroborated | inspector's log and sensor record agree the inspection was completed | established | two independent origins, all conditions met |
| interested_only | contractor's report plus its derived memo | not_established | support origins 1 of 2; `independence` left open by an honest proposer |
| opposed_unanswered | contractor's report and sensor record say completed; inspector's log says not completed | not_established or contested | a founded rebut on the claim with no admitted reply |
| opposed_answered | as above, but the inspector's "not completed" entry concerns another unit, shown by located text | established | the rebut is recorded and discharged by a reply condition quoting the other unit, in a later revision |
| superseded | inspector's log v1 says not completed; v2 supersedes it and records completion; sensor record agrees | established | evidence from the superseded version is not admitted for a current claim; the current version and the sensor record are two origins |
| hearsay | a clerk's note relays what the contractor said; the contractor's report | not_established | `positioning` fails for the relay; the proposer leaves it open |

Expectations are held apart from the public requests: `cases.json` holds the
twelve generic requests and nothing else; `expectations.json` holds the
expected statuses and the completion expectations under the keys the
categorical scorer already supports. The separation that `packets.py` and
`FORBIDDEN_PUBLIC_KEYS` enforce applies: an expectation key inside a public
request is rejected before any worker sees it. The loader builds
`ExperimentCase` records for the runner.

A scripted worker for this family, labelled a test instrument, reads the
current sources, builds attribution claims for each report about the unit,
assesses the six conditions from source kind and declared interest, records
a rebut for a report that says the inspection was not completed on the same
unit, and answers it in a second submission when the located text names a
different unit. It reaches the expected status for all twelve cases in the
harness arm. It is plumbing for the kernel checks, not evidence about a
model. The family joins the `bench` command behind `--adapter adjudication`.

## Tests

- Kernel: each case type as a graph, and each code check failing on its own
  (one premise; a premise that is not an attributed report; a missing or
  assumed condition; a rebut without a founded supporter; a reply from the
  same revision; origins below the profile minimum).
- `starter_graph` chooses `source_adjudication` only when the profile permits
  it, and `document_record` otherwise.
- `issuer_interest` validates, appears in the manifest and in `search` and
  `open` results, and is ignored by the kernel.
- The scripted worker reaches the expected status for all twelve cases.
- The 378-run matrix is unchanged.
- Version 1.0.0a7; a validation record under `experiments/v1/`.
