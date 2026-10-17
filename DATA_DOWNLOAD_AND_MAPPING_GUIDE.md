# Data Download and Column-Mapping Guide

## Official sources

- Dataset record: https://uvaauas.figshare.com/articles/dataset/26395903
- DOI: https://doi.org/10.21942/uva.26395903.v2
- Original analysis materials: https://osf.io/tpj98/
- Original preregistration: https://osf.io/kxw2h/

The Figshare record lists five public files: `phone.csv`, `game.csv`, `social.csv`, `video.csv`, and `timeframes`. The first four are processed Mplus input datasets. `timeframes` contains bedtime and wake-up information used to define daytime, pre-bedtime, and post-bedtime periods.

## Recommended download procedure

First try the validated downloader:

```bash
python src/download_data.py
```

It queries public Figshare metadata, retries transient failures, writes files atomically, verifies available MD5 values, rejects HTML error pages, safely extracts archives, and records SHA-256 hashes. If automated access is blocked:

1. Open the official Figshare record.
2. Select **Download all**.
3. Extract the archive without editing the source files.
4. Copy the five files into `data_raw/`.
5. Run:

```bash
python src/inspect_and_prepare.py
```

6. Inspect these audit files before analysis:

- `outputs/tables/schema_report.csv`
- `outputs/tables/resolved_column_mapping.csv`
- `outputs/tables/invalid_duration_audit.csv`
- `outputs/tables/usage_unit_audit.csv`
- `outputs/tables/merge_audit.csv`
- `outputs/tables/data_quality_report.csv`
- `outputs/tables/source_file_manifest.csv`

## Column-mapping safety rule

The pipeline never guesses short or ambiguous variables through broad substring matching. It first searches exact aliases from `analysis_config.json`, then permits only conservative token matches for longer names. If a variable cannot be resolved safely, execution stops rather than silently selecting a wrong column.

Required canonical fields in `phone.csv`:

- `participant_id`
- `day`
- `sleep_quality`
- `daytime_use`
- `prebed_use`
- `postbed_use`

The category files require `participant_id` and `day`; their three time-window variables are strongly recommended.

## If the CSV files have no header row

Do not assign names by intuition. Download the Mplus syntax from the OSF materials and copy the exact `NAMES ARE` order. Add the names as the header row or adapt `read_csv_flexible()` using the verified order. Save the mapping and Mplus syntax with the analysis archive.

## Unit verification

The preparation script evaluates hours, minutes, and seconds conversion candidates and writes the decision and alternatives to `usage_unit_audit.csv` and `data_quality_report.csv`. Before reporting any result, verify the inferred unit against the original syntax and published descriptives. The published mean total daily use is approximately six hours, so a dramatically different scale is a warning sign, not a result.

## Source-data integrity

- Never overwrite `data_raw/` files.
- Record file sizes and SHA-256 checksums after download.
- Keep all transformations in code.
- Do not publish participant-level data in the manuscript repository.

## Publication gate

After a full non-quick run, execute:

```bash
python src/validate_outputs.py
```

A paper-ready run requires `outputs/tables/validation_report.json` to have status `passed`.
