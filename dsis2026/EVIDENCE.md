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
- Reproduction of the *full original fitting* still requires a new complete end-to-end run; archived outputs and identical source hashes alone are not a substitute.

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
- 76 Python tests passed after the missing original `data_raw/download_manifest.json` was restored. Source-code patch awaits migration to GitHub alongside the complete legacy baseline.

## Still required before paper is final
1. Migrate complete tested original pipeline to this GitHub repository, not only the reviewer-response script.
2. Perform a fresh full **non-quick** run with run-specific outputs and fresh hash checks, verify archived claims (mixed models, outer-fold predictions), and compare results before editing numerical tables.
3. Run sensitivity on lag/ordinal outcomes and serial correlation, or explicitly acknowledge the limitations without implying tests were done.
4. Confirm article author order, exact DSIS submission rules, anonymization, bibliography, and coauthor approval.
5. No claims about prospective prediction; the original machine-learning setting is post-night reconstruction.
