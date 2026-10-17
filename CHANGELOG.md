# Changelog

## v3.0.0 — final audited pipeline (2026-07-16)

- Enforced complete five-file acquisition and cryptographic manifests.
- Added retry-safe, atomic, checksum-verified download and safe archive extraction.
- Hardened identifier, schema, day, clock, duration-unit, merge and range validation.
- Corrected missing-pair Gower behavior and added balanced constructs/correlation pruning.
- Added strict profile acceptance and no-forced-persona behavior.
- Added singularity-aware MixedLM plus explicit GEE fallback.
- Separated primary, lagged sensitivity and app-category exploratory models.
- Added participant-grouped nested validation, mean baseline, participant bootstrap CIs, paired comparisons, calibration and outer-fold importance.
- Added automatic manuscript report generation and publication-blocking validation.
- Added unit tests, isolated smoke test, CI, exact environment lock, license, citation, attribution and reproducibility checklist.

## v2.0.0

- Introduced the audited public-dataset pipeline with Gower/PAM, grouped validation, timeframe parsing and manuscript materials.

## 3.2.0 — Step 8 portable clean packaging

- Replaced workspace ZIP packaging with an explicit allowlist.
- Added portability auditing and clean code-only/data-inclusive builders.
- Removed virtual environments, caches, bytecode, generated results, processed participant data, logs, and platform binaries from release archives.
- Added cross-platform bootstrap/run helpers, CI matrix, dependency inventory, and clean-archive tests.

## 3.3.0 — Step 9 exact previous-day lag

- Replaced the ambiguous previous-observed sleep lag with `sleep_quality_lag1_exact`.
- Prohibited carrying sleep quality across missing study days.
- Added row-level lag status, day-gap auditing, publication validation, and gap-focused tests.
- Renamed the lagged sensitivity model to `sensitivity_exact_previous_day_sleep`.

## 3.4.0 — Step 10 dual prediction estimands

- Added complementary participant-day and primary participant-equal OOF MAE, RMSE, and R².
- Equalized each adolescent’s total metric weight irrespective of valid-day count.
- Added participant-cluster bootstrap intervals and paired comparisons for both estimands.
- Added fold-level dual-estimand outputs, recomputation validation, figures, tests, and reporting guidance.
