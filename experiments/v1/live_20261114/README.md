# V1 live controlled development run

14 November 2026

## Result

**The live harness does not yet satisfy this development packet reliably.** Eight saved cases produced five runtime completions, two partial results and one failure before graph construction. Independent model review rated one result adequate, six partial and one inadequate. Human adjudication remains pending.

The main failures concern model-output admission, evidence acquisition, challenge resolution and result representation. The runs do not establish that the proposed epistemic repertoire succeeds or fails. Those questions require a functioning execution protocol and comparisons that were not run here.

## Method

- Frozen implementation: [`3140e4128cc36d3bfd0a17f681e431cef0a9f7c9`](https://github.com/dioufseck-rgb/inquiry-harness/tree/3140e4128cc36d3bfd0a17f681e431cef0a9f7c9). No product code or prompts changed during the batch.
- Eight settings: all six baseline questions in the fictional hardship packet, plus the missing-details intake variant and the causal variant with an employer record.
- Evidence mode: **documents**. The candidate corpus was known and fixed within each setting; the model chose what to open or search. Actual exposure therefore varied. This was not a fully supplied-evidence experiment.
- Proposer: `openai:gpt-5.4-mini-2026-03-17`; critic: `openai:gpt-5.4-2026-03-05`; both at `low` effort. These are different models from the same provider and family.
- Per-case limits: 10 total model calls, 8 tool calls, 160,000 total tokens, 8,192 output tokens per call, 180 seconds, two consecutive errors, and one critic call.
- A local protocol and categorical expectations were written before the calls. This is a development run, not a publicly preregistered study. Oracle material was separate from the public model input.
- Completed results were never rerun or selected from alternatives. The original scores and artifacts are preserved.

An automatic approval review interrupted the original process after five saved results, treating the packet as private applicant data. The fixture and actual prompts explicitly identify every person, place and record as synthetic. After this was verified, the three unsaved settings were resumed under the same settings. The earlier unsaved attempt at the employer-record case has unknown usage and outcome; it is recorded separately and excluded from saved-run totals. This is eight saved results plus one interrupted, unpersisted attempt, not a claim of exactly eight total attempts.

## Case results

“Complete” below is the runner's execution/completion category, not a judgment of substantive adequacy.

| Setting | Runtime | Substantive finding and remaining problem | Model review | Categorical smoke |
|---|---|---|---|---|
| Applicant's reported loss | Complete | Correct attribution: four-hour shift, 80 credits, 4 April. Does not present the account as independently verified. | Adequate | Pass |
| Local flood occurrence | Complete | Correct bounded event interpretation, but a repaired argument remains under attack; final wording contradicts its recorded standing. | Partial | Fail |
| Individual causation, baseline evidence | Partial | Correctly withholds independent causation, but overstates review coverage; rejected repairs leave the required causal form unresolved. | Partial | Fail |
| Complete intake application | Complete | Correct general policy template, but application acquisition was discarded; the actual next-stage branch was never established. | Partial | Fail |
| Final eligibility | Complete | Correctly finds the record insufficient. The rendered assessment omits the required explanation of the outstanding conditions. Status scoring also has a polarity problem, discussed below. | Partial; core determination adequate | Fail |
| Every worker lost wages | Partial | Correctly declines the universal claim. Unsupported claim form and incorrectly scoped components prevent valid graph completion. | Partial; core determination adequate | Fail |
| Intake application with missing details | Complete | Correctly requests the impact description and event date in the claim text. An unresolved objection survives structural repair, and the proposed action is incomplete. | Partial; policy reading correct | Fail |
| Individual causation, employer trace added | Failed | Employer-document opens were discarded; invalid table requests then ended the run. No graph, critic review or causal finding was produced. | Inadequate | Not checkable |

The categorical result is **one pass, six failures and one uncheckable result**. It is not a substantive accuracy estimate. In particular, the final-eligibility question asks whether the supplied record establishes eligibility. Establishing the proposition *“the supplied record does not establish final eligibility”* is a legitimate negative answer. The scorer expects a differently oriented target and consequently flags its `established` status. That is not a false finding of eligibility. The assessment is still incomplete under its profile because it does not explain all final-stage conditions in the rendered response. No expected scores were changed after observing this issue.

## What the traces establish

### 1. The output parser silently discards substantive operations

**Fourteen of 43 saved worker replies contain multiple complete adjacent JSON objects. Twenty-eight later objects were discarded.** The legacy `extract_json` uses `JSONDecoder.raw_decode` and ignores the returned end position. The runtime acts only on the first object.

In the complete-intake case, this discarded the application open. In the employer-trace case, two correct whole-document employer opens were discarded before the worker attempted invalid table operations. In the universal-scope case, full-document reads were discarded after a search.

The raw strings prove the loss. The adapter did not preserve the underlying SDK response-item boundaries, so these records do not establish whether the adjacent objects came from one text span or several response items. A separate premature fabricated draft in the attribution case was also discarded; after actual source exposure, that case's final answer was correct. It is a raw-output incident, not a final-answer error.

### 2. The critic's output contract is neither clear nor enforced

Seven critic calls were made. Six yielded valid admitted critique envelopes. In the complete-intake case, the critic emitted two source-reference objects followed by a useful critique with three attacks. Only the first source reference was retained. The critic path accepted it without validating the expected observations/attacks envelope, so all three objections were lost.

Critic inputs also advertise the proposer's operation and tool contract alongside the appended critique contract, even though the critic path does not dispatch those tools. This is a directly observed contract inconsistency; its causal contribution to the generated output remains an inference.

Across all complete objects, critics proposed 11 attacks. Eight reached graph records. Final kernel labels were seven `IN` and one `NOT_ADMITTED`. These counts distinguish proposed, recorded and accepted attack structures.

### 3. Repair and challenge resolution do not reliably produce a coherent result

The event and missing-details cases repaired the structural defects identified by the critic, but their objections remained open. In the event case a reply was attempted without the condition link required to discharge the attack. The result simultaneously says “Not established” and “established on the revised graph.”

This calls for validated, revision-aware reply/discharge operations. A revision must not automatically erase every objection: the system needs to record which challenged defect was addressed and check that response.

The baseline causal case also produced malformed JSON at the configured 8,192-output-token ceiling, followed by a rejected edit that changed a condition's meaning under the same ID. Rejected operations are not credited as completed repairs. The exact provider termination reason was not persisted.

### 4. Operational failure must remain distinct from lack of evidence

The employer source contains an operations log, roster row and payroll row as **reading blocks**, with no tables. The worker tried to read their locator names as table IDs. Two unknown-table errors stopped the run. The packet contains the intended causal trace; the harness never exposed it to the proposer. This result cannot be scored as warranted withholding because evidence was insufficient.

Likewise, the universal case has sensible withholding prose but no completed argument in the requested form. A correct label obtained through an unsupported-form guard is not evidence of successful reasoning.

### 5. Replay verifies reproducibility of saved state, not the adequacy of admission

All eight saved ledgers verify. All seven available graph evaluations reproduce; the failed employer case has no graph. **There were zero graph-replay mismatches.** These checks do not reconstruct extraction decisions or recover discarded objects. They therefore coexist with the protocol losses above.

The structural scorer reports seven passes and one failure. Its pass on the no-graph case reflects checks on empty records, not a completed assessment. Completion, graph validity, semantic adequacy and categorical agreement must remain separate measures.

## Cost and latency

Saved calls used **300,740 input tokens**, including **93,056 cached input tokens**, and **50,281 output tokens**. There were **36 proposer calls and seven critic calls**. Summed saved-run elapsed time was **430.86 seconds (7 minutes 11 seconds)**, excluding review, the interruption and restart overhead.

At posted standard rates, the saved calls cost an estimated **$0.525005**, approximately **$0.53**. This is a calculation from recorded token usage, not an invoice. Total session cost is unknown because the interrupted attempt's usage was not saved. The runtime's unpriced `cost_usd` entries are not interpreted as zero-dollar calls.

| Model | Calls | Input tokens | Cached input subset | Output tokens | Estimated USD |
|---|---:|---:|---:|---:|---:|
| GPT-5.4 mini | 36 | 254,384 | 82,304 | 43,442 | 0.330722 |
| GPT-5.4 | 7 | 46,356 | 10,752 | 6,839 | 0.194283 |

Rates per million tokens: mini $0.75 input / $0.075 cached input / $4.50 output; full $2.50 / $0.25 / $15.00. Sources: [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4), checked 14 November 2026.

## Required next changes

1. Enforce one complete, role-specific JSON envelope. Reject trailing objects and malformed envelopes explicitly; retain response-item boundaries and provider completion details. Do not silently choose one object from several.
2. Give the critic its own validated contract and a truthful description of the evidence operations it can request. An invalid critique must not consume the allowance as a successful review.
3. Validate replies and discharges against the attacked revision and condition, and derive the rendered standing and next step from the resulting evaluation.
4. Make evidence manifests distinguish blocks from tables and validate proposed operations before dispatch. Track accessible, requested and actually exposed evidence separately.
5. Repair target/form handling and evaluation scoring: preserve proposition polarity, permit informative unresolved answers to complete an appropriate task, and report unassessed graph checks as unassessed.
6. Add the observed traces as regression cases, then run a newly specified batch. Retain this batch intact. After protocol reliability, compare bare prompt, repertoire-guided workflow and harness on matched evidence and budgets; add independent human adjudication.

This batch covers one synthetic development family. It supplies no model-family robustness result, no baseline comparison, no human accuracy estimate, and no validation of the whole seven-competence repertoire.

## Artifacts

- [Machine-readable summary and reviewed cases](summary.json)
- [Complete frozen run records and audit scripts](inquiry_v1_live_records_20261114.zip)

The archive contains the original protocol, interruption record, eight results, assessments, ledgers, reports, model-review records, mechanical audit, execution scripts, fixture and a SHA-256 manifest. No original result or prespecified score was edited. API credentials are absent. Product code remains the frozen commit above; this results commit changes only experiment artifacts.
