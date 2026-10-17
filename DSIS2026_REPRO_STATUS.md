# DSIS 2026 source release status (17 October 2026)

This is a clean software-only reproduction source archive reconstructed from the archived September 2026 CHIuXiD code evidence and verified against the original Figshare-v2 data. The new post-hoc analyses are under dsis2026/. No source or derived participant-level dataset is distributed.

Full offline pipeline (on verified official data) completed with quick mode false. Independent table comparison yielded identical numeric outputs for 7 validated aggregate tables. Source preprocessing calendar alignment was corrected without altering any principal numerical model result.

To run on official data, supply the five CSV inputs from DOI 10.21942/uva.26395903.v2 under data_raw and run python run_all.py --offline. Some data-inclusive packaging tests are deliberately skipped if official source files are absent. Publish aggregate results only; do not commit official participant-level data.

The GitHub repository currently includes reviewer-response source and aggregate evidence. Upload this source tree to complete the main historical pipeline migration.

Additional post-hoc Gaussian AR(1) GEE and ordinal GEE scripts/results are available under `dsis2026/temporal_ordinal_sensitivity.py` (requires official prepared data); both post-bed CI values include 0. The data-containing rerun had 76/76 tests passing; data-free source-only package had 71 tests passing and 5 data-required tests skipped.

New matched-sample post-hoc lag check (`dsis2026/matched_sample_lag_sensitivity.py`): on the same 1,197 records from 140 participants, unlagged within-postbed estimate -0.0294 (95% CI -0.0838 to 0.0250) vs lag-adjusted -0.0311 (95% CI -0.0858 to 0.0237). This reveals that apparent full-to-lag model attenuation is substantially associated with sample restriction.
