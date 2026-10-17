# Adolescents' Digital Nightlife — DSIS 2026 Reanalysis

Research reproducibility repository for the DSIS 2026 manuscript **When Smartphone-Use Profiles Are Unstable: Reliability-Gated Behavioral Modeling of Adolescent Sleep**.

## Evidence status (17 October 2026)
- Data source: Siebers et al., *Adolescents' Digital Nightlife*, Figshare version 2, DOI [10.21942/uva.26395903.v2](https://doi.org/10.21942/uva.26395903.v2).
- Five original CSV SHA-256 values matched the September 2026 reproducibility package.
- Source code package: 76 automated tests passed after supplying the original download manifest.
- Original analyzed cohort: 155 participants, 3,255 participant-days, 1,806 complete primary-analysis days.
- Primary prespecified Gower+PAM results: 5 candidate values of k (2–6), none passed all three gates.
- *New exploratory* reviewer-response checks: Gower + average-linkage agglomeration and robust-scaled k-means, 10 candidate fits and 200 subsamples per candidate; no candidate passed all gates. Detailed tables are in `dsis2026/EVIDENCE.md`.


## Latest canonical submission state (17 October 2026)
- Corrected **25-reference** bibliography: 24 DOI records, 1 original-print ISBN; reports: [bibliographic audit](dsis2026/KAYNAKCA_DOGRULAMA_RAPORU_TR.md), [25-row table](dsis2026/KAYNAKCA_25_KAYIT_DENETIMI.csv).
- The **current anonymized six-page PDF** and matching LaTeX/figures are held in the user's private Google Drive `05_CONFERENCES/DSIS_2026_ADOLESCENT_SLEEP/01_CURRENT_SUBMISSION`; they are **not publicly posted under a named GitHub account** during double-blind review.
- Current canonical PDF SHA-256: `a540e64d0716344af6805503066e44d146a400f1d4032d07afd786553fdd0e6b`.
- See [current synchronization manifest](dsis2026/CURRENT_SYNC_20261017.md).
- Coauthor approval stated complete. Licensed similarity screening, exact CMT author metadata/order, and portal submission remain unverified. **No paper has been submitted by this workflow.**

## Reproduce
The official CSV files are **not included** here. Obtain them from the source DOI, and use the exact version-2 files. The reconstruction code and reports must be verified together before claims are added to a manuscript. The complete historical source-only analytical pipeline has now been imported under `src/`, `tests/`, `run_all.py`, and `analysis_config.json`. The original five Figshare v2 CSVs are deliberately not stored in GitHub. Full empirical reproduction therefore requires downloading the official data and running the pipeline locally.

## Integrity rules
1. No synthetic test data as empirical evidence.
2. No fabricated results or retrospective claims of preregistration for exploratory analyses.
3. Do not force cluster/persona labels when stability gates fail.
4. Treat post-night reconstruction as retrospective, not a deployable pre-bedtime forecast.
5. Do not redistribute participant-level data in the public repository.

**Submission status:** DSIS 2026 manuscript remains under final scientific QA; not yet sent.
