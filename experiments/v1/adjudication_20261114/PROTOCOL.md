# Protocol: the decisive test of source adjudication

Written 14 November 2026, before any provider call. No call is made until
Mamadou approves this protocol and the spend. Nothing below is changed after
a held-out result is seen.

## Question

Does the harness arm, on a question that needs several reports weighed
(placement, interest, independence, opposition), reach the right standing
more often than a bare prompt over the same evidence and budget, without
failing to execute? If not, the service continues as a warrant and audit
layer over supplied documents and acquisition is not ported.

## Families

- **Development family**: the twelve cases of increment B4,
  `inquiry/v1/data/adjudication/cases.json` (plant maintenance: six case
  types, a pump and a compressor variant each). Its expectations are in
  `expectations.json` beside it and were fixed on 14 November before any
  call.
- **Held-out family**: the same six case types (corroborated,
  interested_only, opposed_unanswered, opposed_answered, superseded,
  hearsay) in the **energy** sector (post-maintenance commissioning tests of
  substation and generation equipment), twelve cases in two surface variants.
  It is authored only after the code and prompts are frozen (the recorded
  commit below) and before the held-out batch starts; it is committed with
  its expectations before the first held-out call. No code or prompt change
  is made after any held-out result is seen. The scripted instrument is run
  over it once, before the live batch, to check the fixture is well formed;
  that run is a fixture check, not a result.

## Conditions

| | |
|---|---|
| Arms | `ordinary`, `repertoire`, `harness` |
| Mode | `documents` (the manifest is shown; the worker opens what it reads) |
| Proposer | `openai:gpt-5.4-mini-2026-03-17`, effort `low` |
| Critic | `openai:gpt-5.4-2026-03-05`, effort `low` (used by the runtime in the repertoire and harness arms only; the ordinary arm has no review step) |
| Repetitions | three per case and arm: 12 × 3 × 3 = **108 runs per family**, 216 in all |
| Order | the runner's interleaved order, seed 0 |

Models are passed explicitly on the command line; the `.env` defaults are not
used. If Mamadou names other snapshots, this table is edited before the run
and the edit is recorded in the commit.

### Budgets, identical for every arm

| Limit | Value |
|---|---|
| model calls per run | 10 |
| tool calls per run | 8 |
| total tokens per run | 160,000 |
| output tokens per call | 8,192 |
| wall time per run | 180 s |
| consecutive errors | 2 |
| critic calls | 1 |
| **cost cap per run** | **$0.25** (enforced by the runtime from `prices.json`) |
| **cost cap per family batch** | **$15.00** (enforced by the run script: no new run starts once the batch's recorded cost reaches it) |
| **cost cap for the whole test** | **$30.00** |

A run stopped by a limit is an execution failure (below), not a withheld
finding.

## Measures, per arm, per family

For each run the target finding's status is read from the recorded response
(`response.findings[target_claim_id].status`) and compared with the case's
`allowed_target_statuses`.

- **Unwarranted acceptance**: status `established` where the expectation does
  not allow `established` (interested_only, opposed_unanswered, hearsay).
- **Unwarranted withholding**: status other than `established` where the
  expectation is `established` (corroborated, opposed_answered, superseded).
- **Execution failure**: run status `failed`, or stop reason
  `execution_failure` or `resource_limit`. These runs are counted here and
  excluded from the two measures above.
- **Cost and elapsed time per run**: from the recorded usage, priced at the
  rates in `prices.json`; unpriced usage is reported as unknown, never as zero.

A case is **correct** for an arm when the majority of its three repetitions
report a status the expectation allows. Execution failures count as not
correct for the majority.

Reported per arm: the three counts above, the number of correct cases out of
twelve, mean and total cost, mean and total elapsed seconds.

## Pass rule (proposed; to be confirmed or edited before the run)

On the **held-out** family, by majority over the three repetitions per case:

1. the harness arm has fewer unwarranted acceptances than the `ordinary` arm;
2. the harness arm is correct on at least three more cases than the
   `ordinary` arm, net (harness correct cases minus ordinary correct cases ≥ 3);
3. harness execution failures are at most 10 percent of its runs (at most 3
   of 36).

All three must hold. The development family is reported the same way but
decides nothing; it is run first so that an execution fault shows before the
held-out spend.

**If the test fails**: the service continues as a warrant and audit layer
over supplied documents. Acquisition is not ported.

## Cost estimate and proposed cap

From the saved 14 November calls (`experiments/v1/live_20261114/README.md`):
eight documents-mode runs of the harness arm with a critic used 300,740 input
tokens (93,056 cached), 50,281 output tokens, 36 proposer and 7 critic calls,
at an estimated $0.525, so about **$0.066 per harness run**. Those corpora were
larger than this family's (two to three short documents per case), but the
adjudication path adds a second submission for answered opposition, so the
harness estimate is kept at $0.07 per run. The repertoire arm carries the same
critic and prompt weight without the graph loop (about half) and the ordinary
arm is a bare prompt without review (about a quarter).

| Arm | Runs per family | Estimated cost per run | Estimated cost per family |
|---|---:|---:|---:|
| harness | 36 | $0.07 | $2.52 |
| repertoire | 36 | $0.035 | $1.26 |
| ordinary | 36 | $0.02 | $0.72 |
| **total** | **108** | | **$4.50** |

Both families: about **$9**. Proposed caps: **$0.25 per run, $15 per family,
$30 for the whole test**, which is roughly three times the estimate. The
estimate is a calculation from recorded token usage and posted rates, not a
quotation.

Rates in `prices.json` (USD per million tokens, checked 14 November 2026):
GPT-5.4 mini 0.75 input / 0.075 cached input / 4.50 output; GPT-5.4 2.50 /
0.25 / 15.00.

## Procedure after approval

1. Refuse a dirty checkout. Record the frozen commit of the product code and
   prompts in `RESULTS.md`.
2. Author and commit the held-out family and its expectations.
3. Run the development family:
   `python -m inquiry.v1 bench --adapter adjudication --arms ordinary repertoire harness --modes documents --repetitions 3 --model openai:gpt-5.4-mini-2026-03-17 --critic-model openai:gpt-5.4-2026-03-05 --effort low --calls 10 --tool-calls 8 --tokens 160000 --output-tokens 8192 --timeout 180 --prices experiments/v1/adjudication_20261114/prices.json --max-cost-usd 0.25 --out experiments/v1/adjudication_20261114/development`
   with the batch cap enforced by the run script.
4. Run the held-out family the same way into `held_out/`.
5. Never rerun a completed setting or select among alternatives. Save every
   record, journal and assessment.
6. Publish `RESULTS.md` and `results.json` beside this protocol in the style
   of `experiments/v1/live_20261114/README.md`: the measures per arm and
   family, the pass rule applied as written, cost and time, and every case
   where the arms disagree, listed for Mamadou's adjudication. Model review is
   not a substitute for that adjudication.
7. Report the result against the pass rule as written. Expectations and the
   rule are not adjusted after results are seen.

## What this test does not show

One synthetic family per sector, one provider, one model pair. It gives no
model-family robustness result and no human accuracy estimate. A pass says
the harness arm weighed reports better than a bare prompt on these cases
under these budgets; it does not validate the whole repertoire.
