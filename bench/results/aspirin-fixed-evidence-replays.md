# Aspirin question on a fixed evidence packet: four runs, three harness versions

Evidence packet: the five sources retrieved by `runs/bench/health-aspirin-20261110-0209`
(ASPREE mortality and cancer papers via mirrors, the ASPREE disability-free survival paper,
the USPSTF 2022 recommendation page, an AAFP review). Replays used `--evidence-from` so
retrieval was identical; only the harness and model sampling varied. Two rounds each.

| run | harness | accepted on main issue | other accepted | what Revise did | verdict shape |
|---|---|---|---|---|---|
| original (0209) | before Revise | "increases net cardiovascular harm in adults 60+" on ASPREE alone | 4 sub-issue claims | n/a | accepted, overclaimed |
| replay 1 | Revise, no answers_issue | ASPREE bleeding + mortality, scoped to 70+ with target | USPSTF Grade D as separate claim; ACC/AHA relay | 11 narrows, 1 split, 11 withdrawals, 28 checks unsatisfied/unresolved | accepted component, mis-stopped as "answered" |
| replay 2 | + answers_issue | none (70+ finding marked not answering; Grade D undecided under the causal standard) | none | 8 narrows, 7 withdrawals | undecided, under-accepted |
| replay 3 | + record-level standard | none (main framed at preponderance this run; all four main claims undecided) | USPSTF conclusions accepted on the sub-issue about guidelines | 6 narrows, 9 withdrawals, 4 retains | undecided with the recommendation accepted where Frame placed it |

## What this shows

1. Revise does what the methodological review asked: component findings are kept at their
   population and outcome, support relations whose grounds concern a different outcome are
   withdrawn with the reason, recommendation and estimate are separated, and the all-age
   NNT-against-NNH figure is rejected as a 60+ estimate every time.
2. The verdict shape is not stable across runs on identical evidence. The variance is in
   Frame and Hypothesize, not in evaluation: whether the guideline's verdict is a claim on the
   main issue or on a sub-issue decides whether the run reports "answered by the
   recommendation" or "undecided", and the main issue's question type (causal in two runs,
   not in the third) decides the standard the estimate must clear.
3. The original run's accepted answer was wrong in scope and the replays' answers are right
   in scope; none of them is wrong. The remaining question is calibration of where a
   recommendation-level answer lives, which is a Frame/Hypothesize rule, not an evaluation
   rule.

## Next for this question

- Have Hypothesize place a recommendation-level claim on the main issue when the question's
  population and outcome are what the body addressed, so that its acceptance is reported as
  the answer at that level rather than as a sub-issue result.
- Retrieve the ASPREE cardiovascular paper (HR 0.95, 95% CI 0.83–1.08) and the corrected
  JAMA meta-analysis (NNT 241) so the 60+ balance can be argued with intervals; Revise asked
  for both in every replay.
