# E1: claim granularity

Gate: **FAIL** for after-v5, both frames and providers, three independent samples per cell.

Raw proposals are scored before the guard or repair acts. Every version uses the same checker, including unrequested protocol details. Native metrics and replies remain unchanged. Values below are means [min, max]. All efforts are medium.

| Version | Frame | Provider:model | Raw length | Raw digits | Raw violations | Final nulls/issues | Cost estimate |
|---|---|---|---:|---:|---:|---:|---:|
| after | aspirin | openai:gpt-6.1-sol | 174.79 [165.07, 180.36] | 1.62 [1.43, 2.00] | 0.33 [0.00, 1.00] | 4.00 [4.00, 4.00]/4 | $0.0674 |
| after | aspirin | anthropic:claude-sonnet-5-5 | 173.11 [169.70, 176.54] | 2.06 [1.83, 2.20] | 0.67 [0.00, 1.00] | 3.00 [3.00, 3.00]/4 | $0.0790 |
| after | ulez | openai:gpt-6.1-sol | 129.04 [127.00, 130.50] | 3.55 [2.19, 5.08] | 0.00 [0.00, 0.00] | 6.00 [6.00, 6.00]/6 | $0.0749 |
| after | ulez | anthropic:claude-sonnet-5-5 | 144.89 [142.88, 146.07] | 2.88 [2.62, 3.07] | 1.33 [1.00, 2.00] | 6.00 [6.00, 6.00]/6 | $0.0847 |
| after-v2 | aspirin | openai:gpt-6.1-sol | 176.04 [169.14, 182.25] | 1.69 [1.50, 2.00] | 0.00 [0.00, 0.00] | 4.00 [4.00, 4.00]/4 | $0.0509 |
| after-v2 | aspirin | anthropic:claude-sonnet-5-5 | 166.18 [163.15, 168.92] | 1.69 [1.69, 1.69] | 1.00 [1.00, 1.00] | 4.00 [4.00, 4.00]/4 | $0.0931 |
| after-v2 | ulez | openai:gpt-6.1-sol | 140.86 [138.15, 143.28] | 4.64 [4.15, 4.92] | 0.00 [0.00, 0.00] | 6.00 [6.00, 6.00]/6 | $0.0819 |
| after-v2 | ulez | anthropic:claude-sonnet-5-5 | 142.69 [135.82, 152.00] | 1.87 [1.29, 2.19] | 0.00 [0.00, 0.00] | 6.00 [6.00, 6.00]/6 | $0.0753 |
| after-v3 | aspirin | openai:gpt-6.1-sol | 170.73 [158.21, 181.20] | 2.00 [2.00, 2.00] | 0.00 [0.00, 0.00] | 4.00 [4.00, 4.00]/4 | $0.0499 |
| after-v3 | aspirin | anthropic:claude-sonnet-5-5 | 161.52 [149.54, 175.92] | 1.45 [1.38, 1.50] | 1.00 [1.00, 1.00] | 4.00 [4.00, 4.00]/4 | $0.0906 |
| after-v3 | ulez | openai:gpt-6.1-sol | 138.56 [135.85, 140.96] | 3.35 [2.04, 4.88] | 0.00 [0.00, 0.00] | 6.00 [6.00, 6.00]/6 | $0.0767 |
| after-v3 | ulez | anthropic:claude-sonnet-5-5 | 140.34 [136.88, 145.21] | 2.16 [1.57, 2.71] | 0.67 [0.00, 1.00] | 6.00 [6.00, 6.00]/6 | $0.0795 |
| after-v4 | aspirin | openai:gpt-6.1-sol | 171.49 [159.67, 178.00] | 2.00 [2.00, 2.00] | 0.00 [0.00, 0.00] | 4.00 [4.00, 4.00]/4 | $0.0554 |
| after-v4 | aspirin | anthropic:claude-sonnet-5-5 | 153.45 [132.23, 173.20] | 1.73 [1.54, 1.85] | 1.00 [1.00, 1.00] | 4.00 [4.00, 4.00]/4 | $0.0730 |
| after-v4 | ulez | openai:gpt-6.1-sol | 141.00 [137.36, 148.24] | 4.62 [4.22, 4.86] | 0.00 [0.00, 0.00] | 6.00 [6.00, 6.00]/6 | $0.0677 |
| after-v4 | ulez | anthropic:claude-sonnet-5-5 | 136.63 [132.71, 141.53] | 2.26 [2.20, 2.29] | 0.00 [0.00, 0.00] | 6.00 [6.00, 6.00]/6 | $0.0619 |
| after-v5 | aspirin | openai:gpt-6.1-sol | 160.80 [148.00, 181.71] | 2.00 [2.00, 2.00] | 0.00 [0.00, 0.00] | 4.00 [4.00, 4.00]/4 | $0.0582 |
| after-v5 | aspirin | anthropic:claude-sonnet-5-5 | 163.45 [162.27, 164.91] | 1.41 [1.27, 1.50] | 0.33 [0.00, 1.00] | 4.00 [4.00, 4.00]/4 | $0.0621 |
| after-v5 | ulez | openai:gpt-6.1-sol | 123.68 [111.61, 136.08] | 3.70 [1.30, 4.96] | 0.00 [0.00, 0.00] | 6.00 [6.00, 6.00]/6 | $0.0681 |
| after-v5 | ulez | anthropic:claude-sonnet-5-5 | 129.98 [127.76, 132.19] | 1.86 [1.81, 1.88] | 0.00 [0.00, 0.00] | 6.00 [6.00, 6.00]/6 | $0.0625 |
| before | aspirin | openai:gpt-6.1-sol | 319.17 [311.82, 332.11] | 7.89 [5.65, 9.25] | 16.33 [15.00, 17.00] | 4.00 [4.00, 4.00]/4 | $0.0836 |
| before | aspirin | anthropic:claude-sonnet-5-5 | 205.05 [195.64, 213.50] | 2.93 [2.79, 3.07] | 5.33 [4.00, 6.00] | 3.67 [3.00, 4.00]/4 | $0.0705 |
| before | ulez | openai:gpt-6.1-sol | 218.47 [199.87, 242.58] | 5.42 [3.73, 8.31] | 12.67 [10.00, 17.00] | 6.00 [6.00, 6.00]/6 | $0.0938 |
| before | ulez | anthropic:claude-sonnet-5-5 | 170.56 [163.53, 177.69] | 2.68 [2.44, 2.89] | 1.67 [1.00, 2.00] | 5.67 [5.00, 6.00]/6 | $0.0881 |

The first H1 candidate (`after`) failed the pre-guard ULEZ test on Sonnet. Later versions improved the numeric budget but Sonnet still proposed endpoint recipes for a conceptual issue. All failed candidates are retained. The final revision normalizes legacy answerhood in the view without changing the saved input graph. It also fixes Frame's recognition of unrequested endpoint-construction instructions. Every revision was run on both providers and both frames. JSON/policy repairs add visible API calls.

The code rejects excessive specificity, returns the reasons once, then drops remaining failures. Actual null answers are retained per issue. Frame sanitation is tested separately; the saved E1 frames are identical before and after, so this experiment isolates Hypothesize.

E2(c) uses the median-length Sol aspirin sample from the final candidate, chosen by raw average length then sample number before observing Argue results. Both Argue providers receive this same guarded claim set. This tests the lineage that originally produced the empty graph. Passing the retained-output guard does not turn the failed raw E1 gate into a pass; E6 remains gated.
