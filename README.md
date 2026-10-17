# Adolescents' Digital Nightlife — DSIS 2026 Reanalysis

Research reproducibility repository for the DSIS 2026 manuscript **When Smartphone-Use Profiles Are Unstable: Reliability-Gated Behavioral Modeling of Adolescent Sleep**.

## Evidence status (17 October 2026)
- Data source: Siebers et al., *Adolescents' Digital Nightlife*, Figshare version 2, DOI [10.21942/uva.26395903.v2](https://doi.org/10.21942/uva.26395903.v2).
- Five original CSV SHA-256 values matched the September 2026 reproducibility package.
- Source code package: 76 automated tests passed after supplying the original download manifest.
- Original analyzed cohort: 155 participants, 3,255 participant-days, 1,806 complete primary-analysis days.
- Primary prespecified Gower+PAM results: 5 candidate values of k (2–6), none passed all three gates.
- *New exploratory* reviewer-response checks: Gower + average-linkage agglomeration and robust-scaled k-means, 10 candidate fits and 200 subsamples per candidate; no candidate passed all gates. Detailed tables are in `dsis2026/EVIDENCE.md`.

## Reproduce
The official CSV files are **not included** here. Obtain them from the source DOI, and use the exact version-2 files. The reconstruction code and reports must be verified together before claims are added to a manuscript. The original pipeline is being migrated from verified local archival sources; this repository does not yet contain the complete historical analysis pipeline.

## Integrity rules
1. No synthetic test data as empirical evidence.
2. No fabricated results or retrospective claims of preregistration for exploratory analyses.
3. Do not force cluster/persona labels when stability gates fail.
4. Treat post-night reconstruction as retrospective, not a deployable pre-bedtime forecast.
5. Do not redistribute participant-level data in the public repository.

**Submission status:** DSIS 2026 manuscript remains under final scientific QA; not yet sent.
