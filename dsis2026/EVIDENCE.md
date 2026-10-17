# DSIS 2026: Independent reviewer-response evidence (17 October 2026)

## Provenance and limitations
This report is based on the official Figshare v2 source files recovered from the project's earlier research archive, rather than synthetic observations. Each of the five dataset SHA-256 checksums matched the September 2026 reproducibility-package manifest. See DOI `10.21942/uva.26395903.v2`. No individual participant records are posted to GitHub.

The external CHIuXiD decision was a rejection. The provided screenshot shows *part* of Reviewer 1's comments only. Archival documents named Reviewer 1/2/3 are internal review materials and must NOT be misrepresented as the conference's external reports.

## Verified analytical sample
- 155 participants; 3,255 participant-day rows.
- 1,806 complete primary sleep/use days; 1,449 other rows (44.52%). These are excluded **days**, not 1,449 people.
- 130 participants have at least five usable days for profile clustering.
- 14 retained cluster features after coverage and correlation criteria.

## Reproduced prior PAM output (from archived September aggregate evidence)
- Five prespecified candidate values k=2–6 were fitted.
- Silhouettes range from 0.145 to 0.184; median subsample ARI from 0.205 to 0.443; no candidate passes size >=0.10, silhouette >=0.25 and ARI >=0.75 jointly.
- A fresh complete original pipeline run on 17 October 2026 finished successfully with `quick_mode=false` and passed publication validation. The previous five PAM candidates and all reported model metrics reproduced numerically.

## NEW: post-hoc alternative clustering experiment (independently executed)
- Methods: average-linkage agglomerative clustering on robust numeric Gower dissimilarity; k-means on median-imputed robust-scaled features.
- k=2..6 each, 200 same-seed 80% subsamples per k; all silhouettes evaluated on the same Gower dissimilarity for comparison.
- All 10 combinations failed the **joint original three-part gates**. For average linkage k=2: silhouette 0.334977 but minimum cluster fraction 0.007692 and median ARI 0.378609. For k-means k=2: median ARI 0.780450 and minimum cluster fraction 0.461538 but silhouette only 0.147645.
- These are exploratory reviewer-response analyses, not preregistered tests. The negative findings are conditional on this cohort, distance/scale and tested methods.
- Exact aggregate table: `dsis2026/alternative_cluster_sensitivity.csv`. Runnable independent code: `dsis2026/alternative_cluster_sensitivity.py`.

## NEW: data-quality audit and calendar defect repair (isolated working copy)
- Old pipeline: calendar `date` and `is_weekend` missing in all 3,255 prepared rows despite 1,856 aligned `timeframe_date` values.
- Fixed locally by deriving dates from exact matched `timeframe_date` **without** imputing missing dates or changing numeric study-day indexes.
- After correction: 1,856 known dates/weekend flags, of which 399 weekend dates. Primary valid rows remain 1,806.
- 76 Python tests passed after the missing original `data_raw/download_manifest.json` was restored. The source-only historical pipeline was imported into GitHub, including the tested date-alignment fix, and original data are not stored in the repository.

## Independent full-run reconciliation
- 17 October 2026: after isolating stale outputs, executed `python run_all.py --offline` with no quick or partial flags. Mandatory raw audit, preparation, model run, validation, and report generation all completed.
- Publication validation status: PASSED. Expected counts and 5 PAM candidates confirmed.
- Against archived September aggregate outputs, 7 tables were row-count/schema consistent and had exact same numeric values, max delta 0, including full grouped-CV fold performance and mixed-model coefficient outputs.
- Local calendar-date repair did not change the model metrics.

## Additional post-hoc inference audit
- Same 1,806-row (155 participant) sample, Gaussian GEE with AR(1) working correlation: within-person post-bed coefficient **-0.058518**, 95% CI **[-0.131462, 0.014426]**, p = **0.115870**.
- Same sample, proportional-odds ordinal GEE with participant exchangeable working correlation: within-person post-bed log-odds coefficient **-0.073302**, 95% CI **[-0.164584, 0.017980]**, p = **0.115511**. Do not compare ordinal log odds to the linear coefficient in magnitude.
- Matching **1,197 rows (140 participants)** for the exact preceding-day model: **without** the lag covariate, the within-person post-bed coefficient was **-0.029373** (95% CI **[-0.083755, 0.025009]**); **with** lag adjustment on the same 1,197 rows it was **-0.031072** (95% CI **[-0.085806, 0.023661]**). The apparent attenuation from the full 1,806-row primary estimate (-0.054) is largely associated with subset restriction, not isolated lag adjustment. Mechanisms of selection remain uncertain.
- These are observational, exploratory sensitivity analyses, not pre-registered. Full runnable scripts and numerical JSON are present in the `dsis2026/` folder.

## Still required before paper is final
1. **Completed:** Complete tested source-only pipeline migrated to GitHub. Independent public CI and local original-data verification are recorded separately.
2. **Completed locally:** clean-output non-quick run with original raw files; 7 aligned archival-vs-fresh output tables matched on all numeric values (maximum absolute numeric difference 0), covering cluster selections, 34 repeated-model coefficient rows, 30 predictive performance rows, 50 outer-fold rows, pairwise comparisons, sample flow, and quality summary. The full sources are now in GitHub; detailed original-data execution logs remain in the separate local verification report and are not published with participant data.
3. Matched-sample lag, AR(1) and ordinal checks have now been executed **post hoc**. Their results are reported below; mechanisms of selection/attrition and external cohort replication remain unresolved.
4. The 25 bibliographic records have been checked and corrected in the 17 October version (24 DOI entries, one ISBN); see `dsis2026/KAYNAKCA_DOGRULAMA_RAPORU_TR.md`. User reports coauthor approvals complete. Exact CMT author order, licensed similarity screening and formal submission still require verification.
5. No claims about prospective prediction; the original machine-learning setting is post-night reconstruction.

## Canonical manuscript sync
The latest **6-page anonymous IEEEtran manuscript** with corrected bibliography has been placed in the user's Google Drive `05_CONFERENCES/DSIS_2026_ADOLESCENT_SLEEP/01_CURRENT_SUBMISSION`. The verified manuscript PDF SHA-256 is `a540e64d0716344af6805503066e44d146a400f1d4032d07afd786553fdd0e6b`. Do not confuse this with the older DSIS PDF variants. The current manuscript itself is intentionally not pushed to a publicly author-identifying GitHub repo during double-blind review. See `dsis2026/CURRENT_SYNC_20261017.md`.
