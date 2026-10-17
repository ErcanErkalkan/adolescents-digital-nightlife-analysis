# Step 10 — Participant-Equal Prediction Metrics Fix

## Problem

The previous pipeline computed OOF MAE, RMSE and R² over all participant-day rows. Although uncertainty used participant-cluster bootstrap resampling, adolescents with more valid days still contributed more total loss. This estimated performance for a random participant-day, not performance with every adolescent equally represented.

## Resolution

The pipeline now reports two explicitly labeled estimands:

1. `participant_day`: every held-out participant-day has equal weight.
2. `participant_equal`: every adolescent has equal total weight; this is the primary prediction estimand.

For participant-equal MAE, absolute losses are averaged within adolescent and then equally across adolescents. Participant-equal RMSE is the square root of the equal average of participant-specific mean squared losses. Participant-equal R² uses inverse valid-day-count observation weights.

Both estimands are generated for every model, every outer fold, bootstrap interval and paired comparison. The feature-importance gate now uses participant-equal MAE.

## New safeguards

- `predictive_performance.csv` must contain both estimands for every model.
- `predictive_performance_folds.csv` must contain both estimands for every model-fold combination.
- `predictive_participant_losses.csv` provides one audit row per participant and model.
- Validation independently recomputes both estimands from OOF predictions.
- Validation confirms that participant-equal total weights have zero spread across adolescents.
- Validation confirms participant-equal MAE and RMSE equal the aggregation of within-participant losses.
- Paired model comparisons must include both estimands.
- `run_summary.json` must declare `participant_equal` as primary.
- Separate participant-day and participant-equal MAE figures are produced.

## Verification

- Python compilation: passed.
- Automated tests: 76/76 passed.
- Isolated synthetic smoke test: passed.
- Official-data quick engineering run: passed.
- Publication validation in quick engineering mode: passed with zero critical errors.

Quick-mode numerical values are engineering validation outputs and must not be used as final manuscript results. Final manuscript values require `python run_all.py --offline` without `--quick`.
