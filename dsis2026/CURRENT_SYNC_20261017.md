# DSIS 2026 — latest synced state (17 October 2026)

## Canonical private submission artifacts on Google Drive
Folder: `05_CONFERENCES/DSIS_2026_ADOLESCENT_SLEEP/01_CURRENT_SUBMISSION/`
- `DSIS2026_Anonymous_Submission_CURRENT.pdf` — **current, 6-page US Letter, IEEEtran, anonymous**
- `DSIS2026_Anonymous_Submission_CURRENT.tex` — matching editable LaTeX
- `cluster_diagnostics.png`, `predictive_mae.png` — matching figures
- `02_REPRODUCIBILITY/` — IEEE template and clean code-only ZIP
- `03_AUDIT_REPORTS/` — validated reference audit and independent reanalysis report

Current PDF SHA-256:
`a540e64d0716344af6805503066e44d146a400f1d4032d07afd786553fdd0e6b`

Drive master ZIP: `DSIS2026_CURRENT_CANONICAL_20261017.zip`
SHA-256: `a82f7a849d57e2a66327dca2d506051634d899483aad94b5669eab2fefdcd85a`

## GitHub public reproducibility scope
The current public repo contains the executable analysis pipeline, tests, post-hoc experiments and aggregate findings. It also contains the 25-reference bibliographic audit, but **does not publish the manuscript PDF/LaTeX itself** during the double-blind review period: a public author's account can compromise reviewer anonymity. The canonical manuscript and source remain in the Drive folder. Original / participant-level CSV files are intentionally omitted.

## Integrity/status
- 25 bibliography entries reviewed and corrected: 24 DOI identifiers and one ISBN (not all claim-to-source relationships checked).
- Historical original-data full run: 76 tests passed; numerical audit of 7 tables matched.
- Public GitHub CI: 71 tests passed; 5 requiring protected external raw files skipped.
- Author approvals: confirmed by user on 2026-10-17; exact CMT name order still needs entry.
- Outstanding: licensed similarity report (required threshold per organizer), final CMT metadata and exclusive submission check, and CMT upload/confirmation.
- No submission, acceptance, or IEEE Xplore listing is claimed.

This page is a **sync record**, not peer-review acceptance or a substitute for empirical reproducibility logs.
