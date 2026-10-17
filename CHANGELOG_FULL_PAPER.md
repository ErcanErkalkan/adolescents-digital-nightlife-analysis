# Full Paper Changelog

## 2026-07-17

- Created the pre-modification audit required before full-paper workflow changes.
- Inspected `data_raw/` without modifying source files.
- Recorded that all five required official dataset components are absent.
- Added raw-data audit artifacts that explicitly fail the publication gate and leave data-dependent checks unevaluated.
- Did not run preparation, substantive analysis, or empirical Results generation.
- Downloaded the five official Version 2 Figshare files without modifying their bytes.
- Added exact `timeframes` overrides for `date_res`, `bt_yes`, and `wt_today`; existing usage-file aliases required no overrides.
- Documented authoritative hour units, morning sleep-record timing, and the absence of an additional one-day shift.
- Added a strict raw-only audit utility and 29 exact-mapping/file-role tests.
- Distinguished the documented timeframe-only participant from true shared-participant alignment failures.
- Ran the publication-mode preparation command without `--quick` or `--allow-partial`.
- Fixed redundant category outcome columns that prevented merges under the installed pandas version.
- Implemented the documented `date_res` to numeric `study_day` alignment before timeframe merging.
- Fixed usage units to authoritative hours and retained the full alternative-unit audit.
- Added source-row presence indicators so structural file absence is distinct from measured zero and within-file missingness.
- Added total-use, missingness-semantics, sleep-alignment, and midnight-window audit tables.
- Added and manually verified the CONSORT-like secondary-data flow CSV and Markdown report, including investigation of every loss above 5%.
- Confirmed that no substantive model was run during preparation validation.
- Audited `src/run_analysis.py` against the preregistered plan and secondary-methods draft before changing analysis code; documented residual risks in `RUN_ANALYSIS_PREMODIFICATION_AUDIT.md`.
- Locked preregistered clustering, repeated-model, and prediction settings in the analysis code; added safeguards for within-participant profile completeness, training-fold-only preprocessing and feature screening, fold disjointness, out-of-fold validation, and feature-importance interpretation.
- Corrected report generation so validation precedes manuscript-ready report generation and empty no-cluster CSVs are handled safely.
- Added automated preregistration and leakage tests; the final locked environment passed `.\\.venv\\Scripts\\python.exe -m pytest -q` (56 passed) and `.\\.venv\\Scripts\\python.exe tests\\run_smoke_test.py`.
- Created a locked Python 3.13 environment and installed the full dependency closure from the project lock requirements.
- Ran `python run_all.py --offline` in full publication mode with the official five files, without quick mode or reductions to bootstrap repetitions, stability subsamples, folds, or thresholds.
- Confirmed publication validation passed; confirmed source hashes, participant-grouped outer-fold isolation, required artifact presence, and current-run timestamps; exported `outputs/FULL_ANALYSIS_LOG.txt`, `outputs/ENVIRONMENT_FINAL.txt`, and `outputs/analysis_config_used.json`.
- Read every generated table and figure and created `outputs/RESULTS_INTERPRETATION_AUDIT.md`; no manuscript Results prose was drafted from it.

## Step 8 — Clean portable release packaging

The reproducibility release is now separated from the mutable analysis workspace. Code-only and official-data-inclusive archives contain no stale empirical outputs or fitted models. Manuscript numbers must therefore be regenerated through a validated full run rather than copied from a release snapshot.

## Step 9 — exact lag alignment

- The lagged-outcome sensitivity analysis now uses only exact adjacent study days.
- Nonconsecutive observations and exact-day records with missing prior sleep are excluded transparently and audited.
- Manuscript methods must refer to an exact-previous-day lag, not a previous observed record.

## Step 10 — participant-equal predictive performance

- Prediction performance now reports both random participant-day and equal-participant estimands.
- Participant-equal performance is the primary manuscript estimand; each adolescent receives equal total weight regardless of the number of valid days.
- Point estimates, participant-bootstrap intervals, paired comparisons, fold summaries, and the feature-importance gate use explicit estimand labels.
- Publication validation independently recomputes both estimands from out-of-fold predictions and rejects unequal participant totals.
