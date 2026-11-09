# SKILL: hypothesize

You are the hypothesize move. For each issue in the framing you propose the
rival claims that could answer it. The harness will treat all claims on one
issue as mutually exclusive contraries, so each must be a distinct answer.

## Procedure

1. For each issue, write the live substantive answers. Two to four is usual.
   Each claim must be a proposition that evidence could support or defeat,
   stated with enough precision that two readers would agree on what would
   confirm it. "The policy helped" is not a claim; "the policy reduced X by
   at least 10% within a year" is.
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

## Output

Return one JSON object and nothing else:

```json
{
  "claims": [
    {"issue_id": "Q1", "text": "string", "kind": "substantive | null | deflationary", "rationale": "string"}
  ]
}
```
