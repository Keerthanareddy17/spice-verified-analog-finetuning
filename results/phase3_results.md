# Phase 3 results

All numbers are lookups into the simulator-precomputed outcomes of every action (no model is ever re-simulated). 95% CIs are bootstrap intervals over states (2000 resamples).

## 1. Eval subset (150 test examples, stratified by step; the main comparison)

| method | n | valid | top-1 tie-aware (95% CI) | top-1 exact | top-3 | improvement rate (95% CI) | mean regret (95% CI) |
|---|---|---|---|---|---|---|---|
| random | 150 | 1.000 | 0.107 [0.097, 0.118] | 0.073 | 0.230 | 0.401 [0.381, 0.419] | 0.243 [0.204, 0.282] |
| majority action | 150 | 1.000 | 0.313 [0.247, 0.387] | 0.293 | 0.393 | 0.480 [0.400, 0.553] | 0.097 [0.080, 0.115] |
| textbook rules | 150 | 1.000 | 0.400 [0.320, 0.480] | 0.287 | 0.733 | 0.880 [0.827, 0.927] | 0.073 [0.050, 0.102] |
| Groq openai/gpt-oss-120b | 150 | 0.987 | 0.513 [0.433, 0.593] | 0.447 | 0.627 | 0.827 [0.767, 0.887] | 0.103 [0.072, 0.141] |
| Groq qwen/qwen3.8-27b | 150 | 1.000 | 0.333 [0.260, 0.407] | 0.253 | 0.493 | 0.787 [0.720, 0.847] | 0.179 [0.128, 0.233] |

## 2. Full test split (375 examples; no Groq)

| method | n | valid | top-1 tie-aware (95% CI) | top-1 exact | top-3 | improvement rate (95% CI) | mean regret (95% CI) |
|---|---|---|---|---|---|---|---|
| random | 375 | 1.000 | 0.117 [0.109, 0.125] | 0.073 | 0.232 | 0.406 [0.395, 0.417] | 0.232 [0.208, 0.258] |
| majority action | 375 | 1.000 | 0.325 [0.280, 0.373] | 0.304 | 0.389 | 0.464 [0.416, 0.515] | 0.092 [0.081, 0.103] |
| textbook rules | 375 | 1.000 | 0.440 [0.392, 0.488] | 0.261 | 0.768 | 0.904 [0.875, 0.933] | 0.070 [0.055, 0.088] |

## 3. Where does each method win or lose? (eval subset)

**By step index (0 = the first failing design, 1-3 = after greedy moves)** (cells: tie-aware top-1 / improvement rate / mean regret)

| method | 0 (n=69) | 1 (n=46) | 2 (n=24) | 3 (n=11) |
|---|---|---|---|---|
| textbook rules | 0.39 / 0.94 / 0.073 | 0.30 / 0.85 / 0.103 | 0.58 / 0.88 / 0.038 | 0.45 / 0.64 / 0.031 |
| majority action | 0.38 / 0.48 / 0.119 | 0.30 / 0.48 / 0.080 | 0.21 / 0.46 / 0.076 | 0.18 / 0.55 / 0.073 |
| Groq openai/gpt-oss-120b | 0.58 / 0.93 / 0.078 | 0.52 / 0.80 / 0.117 | 0.46 / 0.71 / 0.095 | 0.18 / 0.55 / 0.218 |
| Groq qwen/qwen3.8-27b | 0.30 / 0.84 / 0.150 | 0.33 / 0.76 / 0.166 | 0.46 / 0.79 / 0.189 | 0.27 / 0.55 / 0.390 |

**By largest shortfall of the state** (cells: tie-aware top-1 / improvement rate / mean regret)

| method | gain (n=27) | pm (n=32) | power (n=21) | sat (n=18) | ugf (n=52) |
|---|---|---|---|---|---|
| textbook rules | 0.22 / 1.00 / 0.094 | 0.75 / 0.94 / 0.012 | 0.76 / 0.86 / 0.008 | 0.11 / 0.89 / 0.309 | 0.23 / 0.79 / 0.046 |
| majority action | 0.63 / 0.89 / 0.012 | 0.00 / 0.28 / 0.239 | 0.76 / 0.86 / 0.008 | 0.78 / 1.00 / 0.030 | 0.00 / 0.06 / 0.113 |
| Groq openai/gpt-oss-120b | 0.30 / 0.81 / 0.114 | 0.53 / 0.84 / 0.080 | 0.67 / 0.90 / 0.033 | 0.17 / 0.89 / 0.378 | 0.67 / 0.77 / 0.044 |
| Groq qwen/qwen3.8-27b | 0.22 / 1.00 / 0.094 | 0.56 / 0.84 / 0.089 | 0.62 / 0.86 / 0.030 | 0.00 / 0.72 / 0.705 | 0.25 / 0.63 / 0.156 |
