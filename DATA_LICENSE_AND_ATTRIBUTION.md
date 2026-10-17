# Data License, Attribution, and Redistribution Policy

## Scope

This repository contains two legally distinct classes of material:

1. **Software and original documentation** created for this secondary-analysis pipeline. These files are licensed under the MIT License in `LICENSE`.
2. **The Adolescents’ Digital Nightlife dataset and data-derived artifacts**. These are **not** covered by the MIT License. The source dataset is licensed by its creators under **Creative Commons Attribution 4.0 International (CC BY 4.0)**.

The official dataset record is:

- **Title:** Dataset belonging to Siebers et al. (2024), “Adolescents’ digital nightlife: The comparative effects of day- and nighttime smartphone use on sleep quality”
- **Creators:** Teun Siebers, Ine Beyens, Susanne E. Baumgartner, and Patti M. Valkenburg
- **Publisher:** Universiteit van Amsterdam / UvA-AUAS Figshare
- **Version:** 2, posted 29 July 2024
- **Dataset DOI:** `10.21942/uva.26395903.v2`
- **Source:** `https://uvaauas.figshare.com/articles/dataset/26395903`
- **License:** CC BY 4.0 — `https://creativecommons.org/licenses/by/4.0/`
- **Related article DOI:** `10.1177/00936502241276793`

## What CC BY 4.0 permits

CC BY 4.0 permits copying, redistribution, transformation, and reuse, including commercial reuse, provided that appropriate credit is supplied, the license is linked, and modifications are indicated. No additional legal or technological restrictions may be imposed on the CC-licensed material.

## Distribution modes

### Code-only reproducibility package — default

The default public distribution excludes:

- official source CSV files under `data_raw/`;
- participant-level or participant-day derived CSV files under `data_processed/`;
- generated outputs containing row-level or participant-level values.

Recipients obtain the official dataset separately from the source DOI and run the pipeline locally. This is the recommended package for conference supplementary material and public code repositories.

### Data-inclusive archival package

A separate data-inclusive package may be created because the source record is CC BY 4.0. It must include:

- `DATASET_ATTRIBUTION.md`;
- `DATA_CHANGES.md`;
- `LICENSE_SCOPE.md`;
- `LICENSES/CC-BY-4.0-NOTICE.txt`;
- `THIRD_PARTY_NOTICES.md`;
- a machine-readable content manifest identifying source and derived data;
- exact hashes for the official source files.

The five files in `data_raw/` are redistributed unchanged only when their SHA-256 hashes match `data_raw/download_manifest.json`. Any processed table, feature table, model input, aggregate table, figure, or report generated from the source data is identified as modified or adapted material and remains subject to attribution to the source dataset.

## Required attribution

When sharing the official data or a substantial portion of derived data, use the attribution in `DATASET_ATTRIBUTION.md`. Do not imply endorsement by the dataset creators, the University of Amsterdam, or the original article authors.

## Changes made by this project

The pipeline may merge source tables, convert units, derive temporal ratios, construct participant-day and participant-level tables, fit statistical models, and generate aggregate results. These transformations are documented in `DATA_CHANGES.md`. The original files in `data_raw/` must never be overwritten.

## Privacy and ethical notice

The source record is public and anonymized. Nevertheless, users should follow applicable ethical, institutional, privacy, and data-protection requirements. A request not to attempt re-identification is an ethical request and **not an additional license condition**.

This document is a project compliance notice, not legal advice.
