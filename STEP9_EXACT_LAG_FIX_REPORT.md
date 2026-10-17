# Step 9 — Exact Previous-Study-Day Lag Fix

## Blocking issue

The former `sleep_quality_lag1` variable used the previous observed row within each participant. If a participant had a missing study day, a sleep-quality value from two or more days earlier could therefore be mislabeled as a one-day lag.

## Implemented correction

- Removed the ambiguous `sleep_quality_lag1` variable from data preparation and all model specifications.
- Added `sleep_quality_lag1_exact`, which is populated only when the immediately preceding observed record is exactly one numeric study day earlier.
- Observation gaps, nonincreasing days, and adjacent records with missing prior sleep are excluded rather than carried forward.
- Added row-level provenance fields:
  - `sleep_quality_previous_observed_day_gap`
  - `sleep_quality_lag1_exact_status`
- Added audit outputs:
  - `outputs/tables/exact_lag_alignment_audit.csv`
  - `outputs/tables/exact_lag_gap_distribution.csv`
- Renamed the sensitivity model to `sensitivity_exact_previous_day_sleep`.
- Added publication-blocking validation that:
  - rejects the old ambiguous column;
  - rejects any nonmissing lag on a non-one-day gap;
  - independently recomputes and compares every exact lag value;
  - verifies that the sensitivity model requests only `sleep_quality_lag1_exact`.
- Added tests for consecutive days, multi-day gaps, missing prior sleep, unsorted input, and restoration of input row order.

## Official-data engineering validation

The validation run used the five official source files in reduced `--quick` engineering mode. It is not a publication analysis.

- Participants: 155
- Participant-day rows: 3,255
- Rows with a prior observed record: 3,100
- Exact one-study-day transitions: 3,100
- Nonmissing exact previous-day sleep values: 1,733
- Exact adjacent transitions with missing prior sleep: 1,367
- Observation gaps bridged: 0
- Nonincreasing or duplicate day transitions: 0
- Recomputed lag mismatches: 0
- Old `sleep_quality_lag1` column present: no
- Fitted sensitivity model: `sensitivity_exact_previous_day_sleep`
- Sensitivity-model rows: 1,197
- Sensitivity-model participants: 140

The official phone panel contains a numeric row for each of the 21 study days, so its observed day-gap distribution was entirely one day. Missing sleep values still remain missing and are not replaced by older observations. Separate unit tests verify exclusion when whole study-day rows are absent.

## Test results

- Python compilation: passed
- Automated tests: 73/73 passed
- Isolated synthetic smoke test: passed
- Official-data quick engineering validation: passed
- Critical exact-lag validation failures: 0

## Required manuscript wording

The lagged-outcome model is a sensitivity analysis adjusted for sleep quality measured on the immediately preceding study day. It must not be described as using the “previous available” sleep assessment, because observation gaps are never bridged.

## Publication note

The bundled engineering outputs were generated in `--quick` mode only to verify the correction. Final manuscript values must be regenerated with:

```bash
python run_all.py --offline
```
