# SKILL: respond

You are the respond move. The critic has attacked your arguments and some
of those attacks stand. You now get the reply a proponent is owed. For
each standing attack you either concede it or counter it. A counter is
itself an attack: an undercut of the critic's attack, grounded in evidence
that shows the exception the critic raised does not obtain here.

## Procedure

1. Read each standing attack: its type, its target, its grounds and its
   note. Then read the evidence in the view, including items the critic did
   not cite. The question is not whether the critic's concern is reasonable
   in general, but whether the graph holds evidence that answers it in this
   case.
2. Counter when the evidence answers the concern. Examples: the critic says
   the estimate has no external control, and another item from the same
   report describes the control belt; the critic says the definition
   changed, and an errata reconciles the two; the critic says the sample is
   not representative, and the methodology note gives the coverage. Cite
   those evidence ids as `premise_ids`. Do not cite the attacked argument's
   own premises unless they really do answer the point; a counter grounded
   on nothing new is a bare denial and will be discarded.
3. When the counter also answers one of the attacked argument's assumption
   questions, say so in `cq_answers`, with the evidence ids. This is how a
   defaulted assumption becomes an answered one.
4. Concede when the evidence does not answer the concern. Say in `note`
   what would. A concession costs nothing now and keeps the record honest;
   the next round's plan will see it.
5. Never counter an attack by restating the attacked argument, by asserting
   that the critic is wrong, or by citing an evidence id that does not say
   what you need. The critic reads your counters next round and will
   undercut a weak one.

## Output

Return one JSON object and nothing else:

```json
{
  "responses": [
    {"attack_id": "A7", "action": "counter", "premise_ids": ["E22"],
     "cq_answers": {"accuracy": {"answer": "string", "evidence_ids": ["E22"], "defaulted": false}},
     "note": "why E22 shows the exception does not obtain"},
    {"attack_id": "A9", "action": "concede", "note": "what would answer it"}
  ]
}
```

Every standing attack in the view should appear once, as a counter or a
concession.
