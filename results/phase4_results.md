# Phase 4 results: multi-step agent, recovery, expert iteration

Test episodes: 174 failing designs (60 unseen targets), 8-step budget; an episode is solved when the simulator says every spec passes. All numbers come from simulating the agent's moves with ngspice. 95% CIs are bootstrap intervals over episodes. "steps / reference path" is the total steps used on solved episodes divided by the total number of inverse lattice moves between their start design and the target they came from (a known solution length; the agent can solve with fewer or more moves).

## 1. All test episodes (no Groq)

| agent | n | success (95% CI) | median steps to success | steps / reference path (solved) | mean final distance | sims / episode | invalid-output rate | recoveries / episode |
|---|---|---|---|---|---|---|---|---|
| random | 174 | 0.282 [0.218, 0.351] | 3.0 | 0.67 | 0.564 | 6.2 | 0.000 | 0.00 |
| random + recovery | 174 | 0.339 [0.270, 0.414] | 4.0 | 0.77 | 0.295 | 6.7 | 0.000 | 1.59 |
| textbook rules | 174 | 0.759 [0.690, 0.822] | 2.5 | 0.53 | 0.077 | 4.0 | 0.000 | 0.00 |
| textbook rules + recovery | 174 | 0.753 [0.690, 0.816] | 2.0 | 0.53 | 0.038 | 3.6 | 0.032 | 0.49 |
| fine-tuned Qwen2.5-0.5B | 174 | 0.782 [0.718, 0.845] | 2.0 | 0.41 | 0.026 | 2.3 | 0.000 | 0.00 |
| fine-tuned + recovery | 174 | 0.902 [0.856, 0.948] | 2.0 | 0.46 | 0.011 | 2.9 | 0.000 | 0.67 |
| after expert iteration + recovery | 174 | 0.943 [0.908, 0.977] | 2.0 | 0.45 | 0.009 | 2.7 | 0.000 | 0.39 |

## 2. Groq subset (30 test episodes the Groq agent finished; every agent re-scored on exactly these)

| agent | n | success (95% CI) | median steps to success | steps / reference path (solved) | mean final distance | sims / episode | invalid-output rate | recoveries / episode |
|---|---|---|---|---|---|---|---|---|
| random | 30 | 0.333 [0.167, 0.500] | 2.5 | 0.58 | 0.480 | 5.9 | 0.000 | 0.00 |
| random + recovery | 30 | 0.367 [0.200, 0.567] | 3.0 | 0.85 | 0.270 | 6.6 | 0.000 | 1.47 |
| textbook rules | 30 | 0.767 [0.600, 0.900] | 2.0 | 0.52 | 0.064 | 4.0 | 0.000 | 0.00 |
| textbook rules + recovery | 30 | 0.767 [0.600, 0.900] | 2.0 | 0.52 | 0.037 | 3.6 | 0.027 | 0.43 |
| qwen3.8-27b | 30 | 0.600 [0.433, 0.767] | 2.5 | 0.52 | 0.057 | 3.1 | 0.048 | 0.00 |
| qwen3.8-27b + recovery | 30 | 0.833 [0.700, 0.967] | 3.0 | 0.64 | 0.034 | 3.9 | 0.008 | 0.80 |
| fine-tuned Qwen2.5-0.5B | 30 | 0.767 [0.600, 0.900] | 2.0 | 0.36 | 0.026 | 2.3 | 0.000 | 0.00 |
| fine-tuned + recovery | 30 | 0.933 [0.833, 1.000] | 2.0 | 0.42 | 0.008 | 2.7 | 0.000 | 0.40 |
| after expert iteration + recovery | 30 | 0.900 [0.767, 1.000] | 2.0 | 0.39 | 0.016 | 2.7 | 0.000 | 0.40 |

(Groq free-tier limits (8,000 tokens/min, 200,000 tokens/day per model) restrict this subset to 30 episodes, so CIs are wide: read it as a pilot, not a ranking.)

## 3. Failure classes and recoveries (counts over all test episodes)

| agent | INVALID_OUTPUT | UNAVAILABLE_ACTION | SIM_FAILURE | LOOP | NO_PROGRESS | BUDGET_EXHAUSTED | reask | fallback_rules | loop_block_reask | sim_rollback | progress_rollback |
|---|---|---|---|---|---|---|---|---|---|---|---|
| random | 0 | 0 | 0 | 82 | 206 | 125 | 0 | 0 | 0 | 0 | 0 |
| random + recovery | 0 | 0 | 0 | 70 | 206 | 115 | 0 | 0 | 70 | 0 | 206 |
| textbook rules | 0 | 0 | 0 | 10 | 54 | 42 | 0 | 0 | 0 | 0 | 0 |
| textbook rules + recovery | 45 | 0 | 0 | 7 | 33 | 19 | 21 | 24 | 7 | 0 | 33 |
| fine-tuned Qwen2.5-0.5B | 0 | 0 | 0 | 194 | 61 | 38 | 0 | 0 | 0 | 0 | 0 |
| fine-tuned + recovery | 0 | 7 | 0 | 82 | 27 | 13 | 0 | 7 | 82 | 0 | 27 |
| after expert iteration + recovery | 0 | 4 | 0 | 47 | 16 | 8 | 0 | 4 | 47 | 0 | 16 |

Counts are events, so one episode can contribute several. BUDGET_EXHAUSTED is once per unsolved episode.

## 4. Recovery ablation (same episodes, recovery off vs on)

| comparison | n | success: no recovery | success: recovery | paired difference (95% CI) |
|---|---|---|---|---|
| random | 174 | 0.282 [0.218, 0.351] | 0.339 [0.270, 0.414] | +0.057 [-0.017, +0.138] |
| textbook rules | 174 | 0.759 [0.690, 0.822] | 0.753 [0.690, 0.816] | -0.006 [-0.017, +0.000] |
| fine-tuned Qwen | 174 | 0.782 [0.718, 0.845] | 0.902 [0.856, 0.948] | +0.121 [+0.075, +0.167] |

## 5. Expert iteration: before vs after (agent with recovery)

| comparison | n | success: before | success: after | paired difference (95% CI) |
|---|---|---|---|---|
| fine-tuned -> after expert iteration | 174 | 0.902 [0.856, 0.948] | 0.943 [0.908, 0.977] | +0.040 [+0.006, +0.075] |

- single-step test eval, Phase 3 fine-tuned (n=375): top-1 0.717 [0.669, 0.763], improvement 0.893, regret 0.042, valid 1.000
- single-step test eval, after expert iteration (n=375): top-1 0.731 [0.683, 0.776], improvement 0.896, regret 0.040, valid 1.000

Expert-iteration data: 1408 rollouts, 1293 solved (91.8%), 3002 candidate improving steps, 1196 exact duplicates of Phase 2 examples dropped, **1579 new examples** added to 2926 (total 4505); dropped steps: {'no_improvement_detour': 295, 'episode_not_solved': 908, 'rules_fallback_step': 14}

## 6. Success rate vs step budget

![success vs budget](figures/phase4_success_vs_budget.png)
