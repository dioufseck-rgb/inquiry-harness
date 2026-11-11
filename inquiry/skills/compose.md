# SKILL: compose

Return JSON with `composed_claims` and `cannot_compose` arrays.
Each composed_claim has text, scope, relation, premise_claim_ids, cq, note.
Scope contains population, comparison, outcome, period, relation, optional
magnitude, narrower_than and parent_scope. The conclusion's outcome must
match the main issue. Copy the shared population, comparison and period
exactly from the accepted components. Record narrowing relative to the
main issue in narrower_than and parent_scope. Do not broaden components.
Only supplied accepted component ids may be premises; at least two are needed.
`cq` contains commensurable and direction, each with answer, evidence_ids
(component claim ids are permitted), outcome (satisfied/unsatisfied/unresolved)
and defaulted=false. Code alone answers same_scope. Do not answer exceptions.
Each cannot_compose has component_ids and a concrete why. Never invent a
missing bridge or treat unlike endpoints as interchangeable event counts.
At most four composed claims. The curriculum supplies the reasoning guidance.
