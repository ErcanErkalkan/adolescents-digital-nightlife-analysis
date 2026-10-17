# Data Modification and Provenance Notice

## Source data

The official CSV files under `data_raw/` are treated as immutable. The distribution builder verifies their hashes against `data_raw/download_manifest.json`. If a hash differs, the package is not permitted to describe that file as an unchanged official source file.

## Derived data

The following transformations may be applied by the pipeline:

- normalization of column names in memory;
- exact, documented variable mapping;
- conversion of usage durations to hours;
- merging by participant and study day;
- validation of bedtime and wake-up fields;
- construction of daytime, pre-bedtime, post-bedtime, and app-category features;
- construction of nighttime exposure and post-bedtime intrusion ratios;
- within-person and between-person decomposition;
- participant-level aggregation for profile analysis;
- exclusion or flagging of invalid, duplicate, or incomplete records according to the analysis plan;
- model fitting, cross-validation, bootstrap uncertainty estimation, and aggregate reporting.

Derived CSV files, statistical tables, figures, and reports are therefore **modified or adapted outputs** based on the CC BY 4.0 dataset. They must retain dataset attribution and this change notice when shared.

## No implied endorsement

The transformations, interpretations, and conclusions are those of the secondary-analysis project. They are not endorsed by the dataset creators, the University of Amsterdam, UvA-AUAS Figshare, or the original article publisher.
