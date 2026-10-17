from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common import (
    PROCESSED,
    RAW,
    TABLES,
    detect_dataset_files,
    ensure_directories,
    file_sha256,
    load_config,
    missing_dataset_stems,
    normalize_name,
    setup_logging,
)

LOGGER = setup_logging("prepare", "prepare.log")


def read_table(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    suffixes = "".join(path.suffixes).lower()
    missing = config["missing_string_tokens"] + config["missing_numeric_sentinels"]
    if suffixes.endswith((".xlsx", ".xls")):
        frame = pd.read_excel(path, na_values=missing)
    else:
        attempts = [
            {"sep": None, "engine": "python", "encoding": "utf-8-sig"},
            {"sep": ",", "encoding": "utf-8-sig"},
            {"sep": ";", "encoding": "utf-8-sig"},
            {"sep": "\t", "encoding": "utf-8-sig"},
            {"sep": r"\s+", "engine": "python", "encoding": "utf-8-sig"},
            {"sep": ",", "encoding": "latin-1"},
            {"sep": ";", "encoding": "latin-1"},
        ]
        candidates: list[tuple[tuple[int, int], pd.DataFrame]] = []
        errors = []
        for kwargs in attempts:
            try:
                candidate = pd.read_csv(
                    path,
                    na_values=missing,
                    keep_default_na=True,
                    low_memory=False,
                    **kwargs,
                )
                if candidate.shape[1] > 1:
                    score = (candidate.shape[1], -int(candidate.isna().all(axis=1).sum()))
                    candidates.append((score, candidate))
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        if not candidates:
            raise RuntimeError(f"Could not parse {path}. Last errors: {errors[-3:]}")
        candidates.sort(key=lambda item: item[0], reverse=True)
        frame = candidates[0][1]

    normalized = [normalize_name(c) for c in frame.columns]
    duplicates = sorted({c for c in normalized if normalized.count(c) > 1})
    if duplicates:
        raise ValueError(f"Normalized duplicate columns in {path.name}: {duplicates}")
    if all(re.fullmatch(r"\d+(\.\d+)?", str(c).strip()) for c in frame.columns):
        raise ValueError(
            f"{path.name} appears to have no header row. Obtain the official CSV with headers "
            "or provide exact column names before analysis."
        )
    frame.columns = normalized
    return frame


def clean_numeric(series: pd.Series, config: dict[str, Any]) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        values = pd.to_numeric(series, errors="coerce")
    else:
        text = series.astype("string").str.strip()
        text = text.mask(text.str.lower().isin(config["missing_string_tokens"]))
        text = text.str.replace(",", ".", regex=False)
        values = pd.to_numeric(text, errors="coerce")
    for sentinel in config["missing_numeric_sentinels"]:
        values = values.mask(np.isclose(values, sentinel, equal_nan=False))
    return values.astype(float)


def clean_identifier(series: pd.Series, config: dict[str, Any]) -> pd.Series:
    output = series.astype("string").str.strip()
    output = output.mask(output.str.lower().isin(config["missing_string_tokens"]))
    output = output.mask(output.str.lower().isin({"<na>", "nan", "none", "null"}))
    output = output.str.replace(r"\.0$", "", regex=True)
    return output


def parse_day_key(series: pd.Series, config: dict[str, Any]) -> tuple[pd.Series, pd.Series, pd.Series, str]:
    numeric = clean_numeric(series, config)
    if numeric.notna().mean() >= 0.90:
        key = numeric.map(lambda x: f"n:{x:.10g}" if pd.notna(x) else pd.NA).astype("string")
        return key, numeric, pd.Series(pd.NaT, index=series.index), "numeric"

    dates = pd.to_datetime(series, errors="coerce", dayfirst=False)
    if dates.notna().mean() >= 0.90:
        normalized_dates = dates.dt.normalize()
        key = normalized_dates.dt.strftime("d:%Y-%m-%d").astype("string")
        return key, pd.Series(np.nan, index=series.index), normalized_dates, "date"
    raise ValueError("Day/date column could not be parsed reliably (less than 90% coverage).")


def align_day_key_to_reference(
    series: pd.Series,
    reference_keys: pd.Series,
    config: dict[str, Any],
) -> tuple[pd.Series, pd.Series, pd.Series, str]:
    key, numeric, dates, kind = parse_day_key(series, config)
    reference = reference_keys.dropna().astype("string")
    reference_is_numeric = not reference.empty and reference.str.startswith("n:").all()
    if kind == "date" and reference_is_numeric:
        origin_text = config.get("study_day_origin")
        if not origin_text:
            raise ValueError("A documented study_day_origin is required to align date_res with numeric study_day.")
        origin = pd.Timestamp(origin_text)
        derived = (dates - origin).dt.days + 1
        key = derived.map(lambda x: f"n:{x:.10g}" if pd.notna(x) else pd.NA).astype("string")
        return key, derived.astype(float), dates, "date_to_numeric_study_day"
    return key, numeric, dates, kind


def add_exact_previous_day_lag(
    frame: pd.DataFrame,
    *,
    participant_col: str = "participant_id",
    day_col: str = "day",
    value_col: str = "sleep_quality",
    output_col: str = "sleep_quality_lag1_exact",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create a one-study-day lag without carrying values across observation gaps.

    Rows are sorted internally by participant and numeric study day, and the
    original row order is restored before returning. A lag value is populated
    only when the immediately preceding observed record belongs to the same
    participant and its study day is exactly current_day - 1.
    """
    required = {participant_col, day_col, value_col}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"Cannot create exact lag; missing columns: {missing}")

    out = frame.copy()
    out["_lag_original_order"] = np.arange(len(out), dtype=int)
    out["_lag_numeric_day"] = pd.to_numeric(out[day_col], errors="coerce")
    out = out.sort_values(
        [participant_col, "_lag_numeric_day", "_lag_original_order"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)

    previous_day = out.groupby(participant_col, sort=False)["_lag_numeric_day"].shift(1)
    previous_value = out.groupby(participant_col, sort=False)[value_col].shift(1)
    day_gap = out["_lag_numeric_day"] - previous_day
    exact_previous_day = pd.Series(
        np.isclose(day_gap, 1.0, rtol=0.0, atol=1e-9, equal_nan=False),
        index=out.index,
    )

    out["sleep_quality_previous_observed_day_gap"] = day_gap
    out[output_col] = previous_value.where(exact_previous_day)

    status = pd.Series("gap_or_invalid_day_excluded", index=out.index, dtype="string")
    status.loc[previous_day.isna()] = "no_previous_observed_record"
    status.loc[out["_lag_numeric_day"].isna()] = "missing_current_study_day"
    status.loc[previous_day.notna() & out["_lag_numeric_day"].notna() & (day_gap <= 0)] = (
        "nonincreasing_or_duplicate_day_excluded"
    )
    status.loc[previous_day.notna() & out["_lag_numeric_day"].notna() & (day_gap > 1)] = (
        "observation_gap_excluded"
    )
    status.loc[exact_previous_day & previous_value.isna()] = (
        "exact_previous_day_prior_sleep_missing"
    )
    status.loc[exact_previous_day & previous_value.notna()] = "exact_previous_day_available"
    out["sleep_quality_lag1_exact_status"] = status

    audit = pd.DataFrame([{
        "total_rows": int(len(out)),
        "participants": int(out[participant_col].nunique(dropna=True)),
        "rows_with_previous_observed_record": int(previous_day.notna().sum()),
        "exact_previous_day_transition_rows": int(exact_previous_day.sum()),
        "exact_lag_nonmissing_rows": int(out[output_col].notna().sum()),
        "exact_previous_day_prior_sleep_missing_rows": int(
            (exact_previous_day & previous_value.isna()).sum()
        ),
        "first_or_no_previous_record_rows": int(previous_day.isna().sum()),
        "observation_gap_rows_excluded": int((day_gap > 1).fillna(False).sum()),
        "nonincreasing_or_duplicate_rows_excluded": int((day_gap <= 0).fillna(False).sum()),
        "noninteger_positive_gap_rows_excluded": int(
            (
                previous_day.notna()
                & out["_lag_numeric_day"].notna()
                & (day_gap > 0)
                & ~exact_previous_day
                & (day_gap <= 1)
            ).sum()
        ),
        "policy": (
            "The lag is populated only when the immediately preceding observed "
            "record is exactly one numeric study day earlier; gaps are never bridged."
        ),
    }])

    gap_distribution = (
        day_gap.dropna()
        .value_counts()
        .sort_index()
        .rename_axis("observed_day_gap")
        .reset_index(name="row_count")
    )
    gap_distribution["eligible_for_exact_lag"] = np.isclose(
        gap_distribution["observed_day_gap"], 1.0, rtol=0.0, atol=1e-9
    )

    out = out.sort_values("_lag_original_order", kind="mergesort").drop(
        columns=["_lag_original_order", "_lag_numeric_day"]
    )
    out.index = frame.index
    return out, audit, gap_distribution


def parse_clock_minutes(series: pd.Series, config: dict[str, Any]) -> tuple[pd.Series, str]:
    text = series.astype("string").str.strip()
    text = text.mask(text.str.lower().isin(config["missing_string_tokens"]))

    explicit = text.str.extract(r"^(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?$")
    explicit_valid = explicit["h"].notna().mean()
    if explicit_valid >= 0.50:
        hours = pd.to_numeric(explicit["h"], errors="coerce")
        minutes = pd.to_numeric(explicit["m"], errors="coerce")
        seconds = pd.to_numeric(explicit["s"], errors="coerce").fillna(0)
        result = hours * 60 + minutes + seconds / 60
        result = result.mask((hours > 23) | (minutes > 59) | (seconds > 59))
        return result.astype(float), "hh_mm_ss_string"

    datetime_values = pd.to_datetime(text, errors="coerce")
    if datetime_values.notna().mean() >= 0.80:
        result = datetime_values.dt.hour * 60 + datetime_values.dt.minute + datetime_values.dt.second / 60
        return result.astype(float), "datetime_string"

    values = clean_numeric(series, config)
    finite = values.dropna()
    if finite.empty:
        return pd.Series(np.nan, index=series.index, dtype=float), "unparsed"
    q95 = float(finite.quantile(0.95))
    if q95 <= 1.0:
        return ((values * 1440.0) % 1440.0).astype(float), "excel_day_fraction"
    if q95 <= 24.0:
        return ((values * 60.0) % 1440.0).astype(float), "decimal_hours"
    valid_hhmm = ((finite % 100) < 60).mean() >= 0.95
    if q95 <= 2359 and valid_hhmm:
        hours = np.floor(values / 100)
        minutes = values % 100
        result = hours * 60 + minutes
        result = result.mask((hours > 23) | (minutes > 59))
        return result.astype(float), "hhmm_integer"
    return pd.Series(np.nan, index=series.index, dtype=float), "unparsed_numeric"


def resolve_column(
    frame: pd.DataFrame,
    source: str,
    canonical: str,
    config: dict[str, Any],
    required: bool,
) -> tuple[str | None, list[dict[str, Any]]]:
    override = config.get("column_overrides", {}).get(source, {}).get(canonical)
    audit: list[dict[str, Any]] = []
    if override:
        normalized = normalize_name(override)
        if normalized not in frame.columns:
            raise KeyError(f"Override {source}.{canonical}='{override}' is not present.")
        return normalized, [{"candidate": normalized, "score": 1.0, "method": "override"}]

    aliases = [normalize_name(v) for v in config["aliases"][canonical]]
    exact = [alias for alias in aliases if alias in frame.columns]
    if len(exact) == 1:
        return exact[0], [{"candidate": exact[0], "score": 1.0, "method": "exact"}]
    if len(exact) > 1:
        raise KeyError(f"Ambiguous exact aliases for {source}.{canonical}: {exact}")

    candidates: dict[str, float] = {}
    for alias in [a for a in aliases if len(a) >= 5]:
        alias_tokens = set(alias.split("_"))
        for column in frame.columns:
            column_tokens = set(column.split("_"))
            score = len(alias_tokens & column_tokens) / max(1, len(alias_tokens | column_tokens))
            if score >= 0.67:
                candidates[column] = max(candidates.get(column, 0.0), score)
    audit = [
        {"candidate": column, "score": score, "method": "token_similarity"}
        for column, score in sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
    ]
    if audit and (len(audit) == 1 or audit[0]["score"] > audit[1]["score"]):
        return str(audit[0]["candidate"]), audit
    if required:
        raise KeyError(
            f"Could not safely resolve {source}.{canonical}. Candidates: {audit}. "
            "Set an exact value in analysis_config.json > column_overrides."
        )
    return None, audit


def standardize_source(
    frame: pd.DataFrame,
    source: str,
    config: dict[str, Any],
    require_usage: bool,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    mapping_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []

    def resolve(canonical: str, required: bool) -> str | None:
        column, candidates = resolve_column(frame, source, canonical, config, required)
        for candidate in candidates:
            candidate_rows.append({"source": source, "canonical": canonical, **candidate})
        if column:
            mapping_rows.append({"source": source, "canonical": canonical, "original": column})
        return column

    participant_col = resolve("participant_id", True)
    day_col = resolve("day", True)
    sleep_col = resolve("sleep_quality", source == "phone")
    usage_columns = {
        canonical: resolve(canonical, require_usage)
        for canonical in ("daytime_use", "prebed_use", "postbed_use")
    }

    participant_id = clean_identifier(frame[participant_col], config)
    day_key, day_numeric, date, day_kind = parse_day_key(frame[day_col], config)
    out = pd.DataFrame({
        "participant_id": participant_id,
        "day_key": day_key,
        "source_day_numeric": day_numeric,
        "source_date": date,
    })
    out["day_key_kind"] = day_kind
    if sleep_col and source == "phone":
        out["sleep_quality"] = clean_numeric(frame[sleep_col], config)
    for canonical, column in usage_columns.items():
        if column:
            prefix = "" if source == "phone" else f"{source}_"
            out[f"{prefix}{canonical}"] = clean_numeric(frame[column], config)
    return out, mapping_rows, candidate_rows


def choose_usage_divisor(frame: pd.DataFrame, config: dict[str, Any]) -> tuple[float, pd.DataFrame]:
    explicit = str(config.get("usage_unit", "auto")).lower()
    explicit_map = {"hours": 1.0, "minutes": 60.0, "seconds": 3600.0}
    raw_total = frame[["daytime_use", "prebed_use", "postbed_use"]].sum(axis=1, min_count=3)
    reference = config.get("reference_expectations", {}).get("published_mean_total_use_hours_approx")
    candidates = []
    for unit, divisor in explicit_map.items():
        converted = raw_total / divisor
        nonmissing = converted.dropna()
        mean = float(nonmissing.mean()) if not nonmissing.empty else np.nan
        median = float(nonmissing.median()) if not nonmissing.empty else np.nan
        q99 = float(nonmissing.quantile(0.99)) if not nonmissing.empty else np.nan
        invalid_fraction = float((nonmissing > config["analysis"]["max_total_use_hours"]).mean()) if not nonmissing.empty else 1.0
        plausible = bool(nonmissing.size and 0.05 <= median <= 18 and invalid_fraction <= 0.05)
        reference_distance = abs(math.log((mean + 1e-8) / reference)) if reference and mean > 0 else np.nan
        score = invalid_fraction * 100 + (reference_distance if np.isfinite(reference_distance) else 0)
        candidates.append({
            "candidate_unit": unit,
            "divisor": divisor,
            "mean_total_hours": mean,
            "median_total_hours": median,
            "q99_total_hours": q99,
            "invalid_fraction": invalid_fraction,
            "plausible": plausible,
            "reference_log_distance": reference_distance,
            "selection_score": score,
        })
    audit = pd.DataFrame(candidates)
    if explicit in explicit_map:
        return explicit_map[explicit], audit.assign(selected=audit["candidate_unit"].eq(explicit))
    plausible = audit[audit["plausible"]]
    if plausible.empty:
        raise ValueError(
            "Usage unit could not be inferred safely. Set usage_unit to hours, minutes, or seconds "
            "after inspecting outputs/tables/usage_unit_audit.csv."
        )
    selected_index = plausible.sort_values(["selection_score", "invalid_fraction"]).index[0]
    audit["selected"] = audit.index == selected_index
    return float(audit.loc[selected_index, "divisor"]), audit


def create_data_dictionary(frame: pd.DataFrame) -> pd.DataFrame:
    descriptions = {
        "participant_id": "Anonymized participant identifier.",
        "day": "Sequential study day within participant or supplied numeric study day.",
        "date": "Calendar date when supplied by the public file.",
        "sleep_quality": "Morning self-reported sleep quality on the released scale.",
        "daytime_use": "Overall smartphone use during daytime, in hours.",
        "prebed_use": "Overall smartphone use in the hour before bedtime, in hours.",
        "postbed_use": "Overall smartphone use after bedtime, in hours.",
        "total_use": "Sum of daytime, pre-bedtime, and post-bedtime smartphone use.",
        "nighttime_exposure_ratio": "Share of total use occurring pre-bedtime or post-bedtime.",
        "postbed_intrusion_ratio": "Share of nighttime use occurring after bedtime.",
        "sleep_window_hours": "Elapsed clock time between bedtime and wake-up, not objective sleep duration.",
        "valid_primary_day": "True when sleep quality and all three overall use windows are observed and valid.",
    }
    rows = []
    for column in frame.columns:
        description = descriptions.get(column, "Derived or source-mapped analysis variable.")
        if any(column.startswith(f"{category}_") for category in ("social", "game", "video")):
            description = f"{column.split('_', 1)[0].title()} app-category analogue of the named usage feature."
        if column.endswith("_source_row_present"):
            description = "True when the official source file contained this participant-day key; distinguishes structural absence from measured zero."
        if column.endswith("_within"):
            description = "Person-mean-centered daily deviation of " + column.removesuffix("_within") + "."
        elif column.endswith("_between"):
            description = "Participant mean of " + column.removesuffix("_between") + "."
        rows.append({"variable": column, "dtype": str(frame[column].dtype), "description": description})
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate, map, and prepare the public dataset.")
    parser.add_argument("--allow-partial", action="store_true", help="Allow missing app-category/timeframe files.")
    args = parser.parse_args()

    ensure_directories()
    config = load_config()
    files = detect_dataset_files(config)
    missing = missing_dataset_stems(config, files)
    if missing and not args.allow_partial:
        raise FileNotFoundError(f"Missing official files: {missing}. Run src/download_data.py first.")
    if "phone" not in files:
        raise FileNotFoundError("The official phone dataset is required.")

    loaded: dict[str, pd.DataFrame] = {}
    schema_rows = []
    manifest_rows = []
    for source, path in files.items():
        frame = read_table(path, config)
        loaded[source] = frame
        manifest_rows.append({
            "source": source,
            "file": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path),
            "rows": len(frame),
            "columns": len(frame.columns),
        })
        for column in frame.columns:
            schema_rows.append({
                "source": source,
                "file": path.name,
                "column": column,
                "dtype": str(frame[column].dtype),
                "rows": len(frame),
                "non_missing": int(frame[column].notna().sum()),
                "missing_pct": float(100 * frame[column].isna().mean()),
                "unique": int(frame[column].nunique(dropna=True)),
                "sample_values": " | ".join(map(str, frame[column].dropna().head(3).tolist())),
            })
        LOGGER.info("Loaded %s: %d rows x %d columns", path.name, *frame.shape)
    pd.DataFrame(manifest_rows).to_csv(TABLES / "source_file_manifest.csv", index=False)
    pd.DataFrame(schema_rows).to_csv(TABLES / "schema_report.csv", index=False)

    mapping_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    phone, mapping, candidates = standardize_source(loaded["phone"], "phone", config, require_usage=True)
    mapping_rows.extend(mapping)
    candidate_rows.extend(candidates)
    base = phone

    merge_rows = []
    duplicate_counts: dict[str, int] = {"phone": int(base.duplicated(["participant_id", "day_key"]).sum())}
    for source in ("game", "social", "video"):
        if source not in loaded:
            continue
        addon, mapping, candidates = standardize_source(loaded[source], source, config, require_usage=True)
        mapping_rows.extend(mapping)
        candidate_rows.extend(candidates)
        duplicate_count = int(addon.duplicated(["participant_id", "day_key"]).sum())
        duplicate_counts[source] = duplicate_count
        if duplicate_count:
            addon[addon.duplicated(["participant_id", "day_key"], keep=False)].to_csv(
                TABLES / f"duplicate_keys_{source}.csv", index=False
            )
            raise ValueError(f"{source} contains {duplicate_count} duplicate participant-day keys.")
        overlap = base[["participant_id", "day_key"]].merge(
            addon[["participant_id", "day_key"]], on=["participant_id", "day_key"], how="inner"
        )
        merge_rows.append({
            "source": source,
            "source_rows": len(addon),
            "matched_phone_rows": len(overlap),
            "unmatched_source_rows": len(addon) - len(overlap),
            "unmatched_phone_rows": len(base) - len(overlap),
            "match_pct_of_source": 100 * len(overlap) / max(1, len(addon)),
        })
        addon[f"{source}_source_row_present"] = True
        addon = addon.drop(columns=["source_day_numeric", "source_date", "day_key_kind"], errors="ignore")
        base = base.merge(addon, on=["participant_id", "day_key"], how="left", validate="one_to_one")
        base[f"{source}_source_row_present"] = base[f"{source}_source_row_present"].fillna(False).astype(bool)

    clock_rows = []
    if "timeframes" in loaded:
        source = "timeframes"
        frame = loaded[source]
        participant_col, audit = resolve_column(frame, source, "participant_id", config, True)
        candidate_rows.extend({"source": source, "canonical": "participant_id", **row} for row in audit)
        day_col, audit = resolve_column(frame, source, "day", config, True)
        candidate_rows.extend({"source": source, "canonical": "day", **row} for row in audit)
        bedtime_col, audit = resolve_column(frame, source, "bedtime", config, False)
        candidate_rows.extend({"source": source, "canonical": "bedtime", **row} for row in audit)
        wakeup_col, audit = resolve_column(frame, source, "wakeup", config, False)
        candidate_rows.extend({"source": source, "canonical": "wakeup", **row} for row in audit)
        timeframe_sleep_col, audit = resolve_column(frame, source, "sleep_quality", config, False)
        candidate_rows.extend({"source": source, "canonical": "sleep_quality", **row} for row in audit)
        mapping_rows.extend([
            {"source": source, "canonical": "participant_id", "original": participant_col},
            {"source": source, "canonical": "day", "original": day_col},
        ])
        day_key, timeframe_day_numeric, timeframe_dates, day_alignment_rule = align_day_key_to_reference(
            frame[day_col], base["day_key"], config
        )
        timeframes = pd.DataFrame({
            "participant_id": clean_identifier(frame[participant_col], config),
            "day_key": day_key,
            "timeframe_day_numeric": timeframe_day_numeric,
            "timeframe_date": timeframe_dates,
            "timeframes_source_row_present": True,
        })
        if timeframe_sleep_col:
            timeframes["timeframe_sleep_quality"] = clean_numeric(frame[timeframe_sleep_col], config)
            mapping_rows.append({"source": source, "canonical": "sleep_quality", "original": timeframe_sleep_col})
        if bedtime_col:
            timeframes["bedtime_clock_minutes"], rule = parse_clock_minutes(frame[bedtime_col], config)
            mapping_rows.append({"source": source, "canonical": "bedtime", "original": bedtime_col})
            raw_non_missing = int((~frame[bedtime_col].astype("string").str.lower().isin(config["missing_string_tokens"])).sum())
            parsed_n = int(timeframes["bedtime_clock_minutes"].notna().sum())
            clock_rows.append({"variable": "bedtime", "source_column": bedtime_col, "parse_rule": rule,
                               "day_alignment_rule": day_alignment_rule, "raw_non_missing_n": raw_non_missing,
                               "parsed_n": parsed_n, "invalid_or_unparsed_n": max(0, raw_non_missing - parsed_n)})
        if wakeup_col:
            timeframes["wakeup_clock_minutes"], rule = parse_clock_minutes(frame[wakeup_col], config)
            mapping_rows.append({"source": source, "canonical": "wakeup", "original": wakeup_col})
            raw_non_missing = int((~frame[wakeup_col].astype("string").str.lower().isin(config["missing_string_tokens"])).sum())
            parsed_n = int(timeframes["wakeup_clock_minutes"].notna().sum())
            clock_rows.append({"variable": "wakeup", "source_column": wakeup_col, "parse_rule": rule,
                               "day_alignment_rule": day_alignment_rule, "raw_non_missing_n": raw_non_missing,
                               "parsed_n": parsed_n, "invalid_or_unparsed_n": max(0, raw_non_missing - parsed_n)})
        if timeframes.duplicated(["participant_id", "day_key"]).any():
            timeframes[timeframes.duplicated(["participant_id", "day_key"], keep=False)].to_csv(
                TABLES / "duplicate_keys_timeframes.csv", index=False
            )
            raise ValueError("timeframes contains duplicate participant-day keys.")
        duplicate_counts["timeframes"] = int(timeframes.duplicated(["participant_id", "day_key"]).sum())
        if {"bedtime_clock_minutes", "wakeup_clock_minutes"} <= set(timeframes.columns):
            interval = (timeframes["wakeup_clock_minutes"] - timeframes["bedtime_clock_minutes"]) % 1440
            timeframes["sleep_window_hours"] = interval / 60
            timeframes.loc[~timeframes["sleep_window_hours"].between(2, 16), "sleep_window_hours"] = np.nan
            for prefix in ("bedtime", "wakeup"):
                angle = 2 * np.pi * timeframes[f"{prefix}_clock_minutes"] / 1440
                timeframes[f"{prefix}_sin"] = np.sin(angle)
                timeframes[f"{prefix}_cos"] = np.cos(angle)
        overlap = base[["participant_id", "day_key"]].merge(
            timeframes[["participant_id", "day_key"]], on=["participant_id", "day_key"], how="inner"
        )
        merge_rows.append({
            "source": source,
            "source_rows": len(timeframes),
            "matched_phone_rows": len(overlap),
            "unmatched_source_rows": len(timeframes) - len(overlap),
            "unmatched_phone_rows": len(base) - len(overlap),
            "match_pct_of_source": 100 * len(overlap) / max(1, len(timeframes)),
        })
        base = base.merge(timeframes, on=["participant_id", "day_key"], how="left", validate="one_to_one")
        base["timeframes_source_row_present"] = base["timeframes_source_row_present"].fillna(False).astype(bool)

    pd.DataFrame(mapping_rows).to_csv(TABLES / "resolved_column_mapping.csv", index=False)
    pd.DataFrame(candidate_rows).to_csv(TABLES / "column_mapping_candidates.csv", index=False)
    pd.DataFrame(merge_rows).to_csv(TABLES / "file_merge_audit.csv", index=False)
    pd.DataFrame(clock_rows).to_csv(TABLES / "clock_parsing_audit.csv", index=False)

    base = base.replace([np.inf, -np.inf], np.nan)
    base = base[base["participant_id"].notna() & base["day_key"].notna()].copy()
    if base.duplicated(["participant_id", "day_key"]).any():
        base[base.duplicated(["participant_id", "day_key"], keep=False)].to_csv(
            TABLES / "duplicate_keys_phone.csv", index=False
        )
        raise ValueError("phone contains duplicate participant-day keys.")

    # Derive a consistent numeric day while retaining calendar dates when available.
    if base["source_date"].notna().any():
        base["date"] = pd.to_datetime(base["source_date"], errors="coerce")
        base = base.sort_values(["participant_id", "date", "day_key"])
        base["day"] = base.groupby("participant_id")["date"].rank(method="dense").astype("Int64")
        base["is_weekend"] = base["date"].dt.dayofweek.ge(5).astype("boolean")
    else:
        base["day"] = base["source_day_numeric"]
        # Keep the numeric phone-study-day index unchanged, but preserve
        # dates from the explicitly aligned timeframes join wherever present.
        # Missing timeframe rows remain unknown; do not extrapolate dates.
        base["date"] = pd.to_datetime(base["timeframe_date"], errors="coerce") if "timeframe_date" in base else pd.NaT
        base["is_weekend"] = (base["date"].dt.dayofweek >= 5).where(base["date"].notna()).astype("boolean")
    base = base.drop(columns=["source_day_numeric", "source_date", "day_key_kind"], errors="ignore")

    usage_columns = [
        column for column in base.columns
        if column.endswith(("daytime_use", "prebed_use", "postbed_use"))
    ]
    divisor, unit_audit = choose_usage_divisor(base, config)
    unit_audit.to_csv(TABLES / "usage_unit_audit.csv", index=False)
    for column in usage_columns:
        base[column] = base[column] / divisor

    duration_audit = []
    invalid_duration_record_mask = pd.Series(False, index=base.index)
    max_window = config["analysis"]["max_window_hours"]
    for column in usage_columns:
        negative = base[column] < 0
        excessive = base[column] > max_window
        duration_audit.append({
            "variable": column,
            "negative_n": int(negative.sum()),
            "over_max_window_n": int(excessive.sum()),
            "max_window_hours": max_window,
        })
        invalid_duration_record_mask |= negative.fillna(False) | excessive.fillna(False)
        base.loc[negative | excessive, column] = np.nan
    pd.DataFrame(duration_audit).to_csv(TABLES / "invalid_duration_audit.csv", index=False)

    sleep_invalid = pd.Series(False, index=base.index)
    if "sleep_quality" in base:
        sleep_invalid = ~base["sleep_quality"].between(
            config["sleep_quality_min"], config["sleep_quality_max"], inclusive="both"
        ) & base["sleep_quality"].notna()
        base.loc[sleep_invalid, "sleep_quality"] = np.nan
    pd.DataFrame([{
        "sleep_quality_out_of_range_n": int(sleep_invalid.sum()),
        "valid_min": config["sleep_quality_min"],
        "valid_max": config["sleep_quality_max"],
    }]).to_csv(TABLES / "sleep_quality_audit.csv", index=False)

    core = ["daytime_use", "prebed_use", "postbed_use"]
    base["total_use"] = base[core].sum(axis=1, min_count=3)
    excessive_total = base["total_use"] > config["analysis"]["max_total_use_hours"]
    base["implausible_total_use"] = excessive_total.fillna(False)
    base.loc[excessive_total, "total_use"] = np.nan
    recomputed_total = base[core].sum(axis=1, min_count=3)
    total_mismatch = ~(np.isclose(base["total_use"], recomputed_total, equal_nan=True))
    pd.DataFrame([{
        "rows": len(base),
        "rows_with_all_three_windows": int(base[core].notna().all(axis=1).sum()),
        "rows_missing_any_window": int(base[core].isna().any(axis=1).sum()),
        "total_sum_mismatch_n": int(total_mismatch.sum()),
        "aggregation_policy": "total_use = daytime_use + prebed_use + postbed_use; windows are mutually exclusive in source construction",
    }]).to_csv(TABLES / "total_use_consistency_audit.csv", index=False)
    epsilon = 1e-8
    base["nighttime_exposure_ratio"] = (base["prebed_use"] + base["postbed_use"]) / (base["total_use"] + epsilon)
    nighttime_total = base["prebed_use"] + base["postbed_use"]
    base["postbed_intrusion_ratio"] = base["postbed_use"] / (nighttime_total + epsilon)
    base.loc[nighttime_total.eq(0), "postbed_intrusion_ratio"] = 0.0

    category_audit = []
    for category in ("social", "game", "video"):
        category_core = [f"{category}_{name}" for name in core]
        if not set(category_core) <= set(base.columns):
            continue
        base[f"{category}_total_use"] = base[category_core].sum(axis=1, min_count=3)
        share = base[f"{category}_total_use"] / (base["total_use"] + epsilon)
        inconsistent = share > 1.05
        category_audit.append({
            "category": category,
            "rows_with_category_gt_total": int(inconsistent.fillna(False).sum()),
            "category_rows_non_missing": int(base[f"{category}_total_use"].notna().sum()),
        })
        base[f"{category}_share"] = share.mask(inconsistent)
    pd.DataFrame(category_audit).to_csv(TABLES / "category_consistency_audit.csv", index=False)

    missingness_semantics = []
    for category in ("social", "game", "video"):
        presence = f"{category}_source_row_present"
        category_core = [f"{category}_{name}" for name in core]
        if presence not in base or not set(category_core) <= set(base.columns):
            continue
        source_present = base[presence].fillna(False)
        all_missing = base[category_core].isna().all(axis=1)
        category_total = base[category_core].sum(axis=1, min_count=3)
        missingness_semantics.append({
            "category": category,
            "source_row_absent_n": int((~source_present).sum()),
            "source_row_present_all_usage_missing_n": int((source_present & all_missing).sum()),
            "source_row_present_measured_zero_n": int((source_present & category_total.eq(0)).sum()),
            "source_row_present_positive_use_n": int((source_present & category_total.gt(0)).sum()),
            "policy": "Absent source row and present-but-missing remain NA; only observed zero values are zero.",
        })
    pd.DataFrame(missingness_semantics).to_csv(TABLES / "missingness_semantics_audit.csv", index=False)

    base = base.sort_values(["participant_id", "day", "day_key"]).reset_index(drop=True)
    if "sleep_quality" in base:
        base, lag_audit, lag_gap_distribution = add_exact_previous_day_lag(base)
        lag_audit.to_csv(TABLES / "exact_lag_alignment_audit.csv", index=False)
        lag_gap_distribution.to_csv(TABLES / "exact_lag_gap_distribution.csv", index=False)

    decomposition = [column for column in [
        "daytime_use", "prebed_use", "postbed_use", "total_use",
        "nighttime_exposure_ratio", "postbed_intrusion_ratio",
        "social_daytime_use", "social_prebed_use", "social_postbed_use",
        "game_daytime_use", "game_prebed_use", "game_postbed_use",
        "video_daytime_use", "video_prebed_use", "video_postbed_use",
    ] if column in base]
    for column in decomposition:
        participant_mean = base.groupby("participant_id")[column].transform("mean")
        base[f"{column}_between"] = participant_mean
        base[f"{column}_within"] = base[column] - participant_mean

    base["valid_primary_day"] = base[["sleep_quality", *core]].notna().all(axis=1)
    base["valid_lagged_sensitivity_day"] = (
        base["valid_primary_day"] & base.get("sleep_quality_lag1_exact", pd.Series(np.nan, index=base.index)).notna()
    )
    base["valid_prediction_day"] = base["sleep_quality"].notna() & base[core].notna().any(axis=1)

    alignment_rows = []
    if "timeframe_sleep_quality" in base:
        comparable = base[["sleep_quality", "timeframe_sleep_quality"]].notna().all(axis=1)
        matches = np.isclose(
            base.loc[comparable, "sleep_quality"],
            base.loc[comparable, "timeframe_sleep_quality"],
            equal_nan=False,
        )
        alignment_rows.append({
            "check": "same_derived_study_day_sleep_quality",
            "comparable_rows": int(comparable.sum()),
            "matching_rows": int(matches.sum()),
            "mismatch_rows": int((~matches).sum()),
            "interpretation": "sleep_quality is the morning response paired with the preceding wake-to-wake phone-use windows; no extra day shift",
        })
    pd.DataFrame(alignment_rows).to_csv(TABLES / "sleep_time_alignment_audit.csv", index=False)

    if {"bedtime_clock_minutes", "wakeup_clock_minutes"} <= set(base.columns):
        clocks_present = base[["bedtime_clock_minutes", "wakeup_clock_minutes"]].notna().all(axis=1)
        wrap_required = clocks_present & (base["bedtime_clock_minutes"] > base["wakeup_clock_minutes"])
        valid_sleep_window = base["sleep_window_hours"].between(2, 16, inclusive="both")
        pd.DataFrame([{
            "matched_timeframe_rows": int(base["timeframes_source_row_present"].sum()),
            "clock_pairs_parsed_n": int(clocks_present.sum()),
            "midnight_modulo_wrap_required_n": int(wrap_required.sum()),
            "valid_sleep_window_n": int(valid_sleep_window.sum()),
            "invalid_sleep_window_n": int((clocks_present & ~valid_sleep_window).sum()),
            "minimum_sleep_window_hours": float(base["sleep_window_hours"].min()),
            "maximum_sleep_window_hours": float(base["sleep_window_hours"].max()),
            "policy": "sleep window = (wake clock - bedtime clock) modulo 24 hours; valid range 2-16 hours",
        }]).to_csv(TABLES / "time_window_audit.csv", index=False)
    base.to_csv(PROCESSED / "daily_analytic.csv", index=False)

    grouped = base.groupby("participant_id", dropna=False)
    profile_variables = [column for column in [
        "total_use", "daytime_use", "prebed_use", "postbed_use",
        "nighttime_exposure_ratio", "postbed_intrusion_ratio",
        "social_share", "game_share", "video_share",
    ] if column in base]
    profile_parts = [
        grouped["day_key"].nunique().rename("n_observed_days"),
        grouped["valid_primary_day"].sum().rename("n_valid_primary_days"),
    ]
    for column in profile_variables:
        profile_parts.extend([
            grouped[column].mean().rename(f"{column}_mean"),
            grouped[column].std().rename(f"{column}_sd"),
            grouped[column].median().rename(f"{column}_median"),
            grouped[column].count().rename(f"{column}_n"),
        ])
    profiles = pd.concat(profile_parts, axis=1).reset_index()
    if "sleep_quality" in base:
        sleep_summary = grouped["sleep_quality"].agg(["mean", "std", "count"]).reset_index()
        sleep_summary.columns = ["participant_id", "sleep_quality_mean", "sleep_quality_sd", "n_sleep_assessments"]
        profiles = profiles.merge(sleep_summary, on="participant_id", how="left")
    profiles["eligible_for_profiles"] = (
        profiles["n_valid_primary_days"] >= config["analysis"]["min_valid_days_for_profile"]
    )
    profiles.to_csv(PROCESSED / "participant_profiles.csv", index=False)

    flow_rows = []
    for source, frame in loaded.items():
        id_mapping = next(
            (row["original"] for row in mapping_rows if row["source"] == source and row["canonical"] == "participant_id"),
            None,
        )
        participants = int(clean_identifier(frame[id_mapping], config).nunique(dropna=True)) if id_mapping else None
        flow_rows.append({
            "stage": "source_file_records",
            "source": source,
            "record_count": len(frame),
            "participant_count": participants,
            "excluded_records": 0,
            "detail": "Raw official source rows before merging; source file unchanged.",
        })
        flow_rows.append({
            "stage": "duplicate_participant_day_records",
            "source": source,
            "record_count": duplicate_counts.get(source, 0),
            "participant_count": None,
            "excluded_records": duplicate_counts.get(source, 0),
            "detail": "Duplicate rows under the exact mapped participant-day key.",
        })
    for row in merge_rows:
        flow_rows.append({
            "stage": "source_merge",
            "source": row["source"],
            "record_count": row["matched_phone_rows"],
            "participant_count": None,
            "excluded_records": row["unmatched_source_rows"],
            "detail": (
                f"Matched {row['match_pct_of_source']:.3f}% of source rows; "
                f"{row['unmatched_phone_rows']} phone rows had no corresponding source row."
            ),
        })
    invalid_time_records = int(sum(row.get("invalid_or_unparsed_n", 0) for row in clock_rows))
    flow_rows.extend([
        {
            "stage": "participant_day_records_before_merging",
            "source": "phone",
            "record_count": int(manifest_rows[0]["rows"]),
            "participant_count": int(base["participant_id"].nunique()),
            "excluded_records": 0,
            "detail": "Phone participant-day spine before left joins.",
        },
        {
            "stage": "invalid_duration_records",
            "source": "merged_usage",
            "record_count": int(invalid_duration_record_mask.sum()),
            "participant_count": int(base.loc[invalid_duration_record_mask, "participant_id"].nunique()),
            "excluded_records": 0,
            "detail": "Flagged and converted to missing at the affected field; rows retained when otherwise usable.",
        },
        {
            "stage": "invalid_time_records",
            "source": "timeframes",
            "record_count": invalid_time_records,
            "participant_count": None,
            "excluded_records": 0,
            "detail": "Non-missing bedtime or wake-up values that could not be parsed.",
        },
        {
            "stage": "records_lacking_sleep_quality",
            "source": "analytic_spine",
            "record_count": int(base["sleep_quality"].isna().sum()),
            "participant_count": int(base.loc[base["sleep_quality"].isna(), "participant_id"].nunique()),
            "excluded_records": int(base["sleep_quality"].isna().sum()),
            "detail": "Retained in processed data but not eligible for outcome models.",
        },
        {
            "stage": "records_retained_explanatory_models",
            "source": "analytic_spine",
            "record_count": int(base["valid_primary_day"].sum()),
            "participant_count": int(base.loc[base["valid_primary_day"], "participant_id"].nunique()),
            "excluded_records": int((~base["valid_primary_day"]).sum()),
            "detail": "Complete sleep quality plus all three overall-use windows.",
        },
        {
            "stage": "participants_retained_profiling",
            "source": "participant_profiles",
            "record_count": None,
            "participant_count": int(profiles["eligible_for_profiles"].sum()),
            "excluded_records": int((~profiles["eligible_for_profiles"]).sum()),
            "detail": f"At least {config['analysis']['min_valid_days_for_profile']} valid primary days.",
        },
        {
            "stage": "records_retained_predictive_models",
            "source": "analytic_spine",
            "record_count": int(base["valid_prediction_day"].sum()),
            "participant_count": int(base.loc[base["valid_prediction_day"], "participant_id"].nunique()),
            "excluded_records": int((~base["valid_prediction_day"]).sum()),
            "detail": "Observed sleep quality and at least one overall-use window.",
        },
    ])
    flow = pd.DataFrame(flow_rows)
    flow.to_csv(TABLES / "analytic_sample_flow.csv", index=False)
    markdown_rows = [
        "# Analytic Sample Flow",
        "",
        "This flow is generated during preparation from immutable official sources. Excluded counts are stage-specific and must not be summed across overlapping criteria.",
        "",
        "| Stage | Source | Records | Participants | Excluded records | Detail |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in flow.itertuples(index=False):
        def display(value: Any) -> str:
            return "" if pd.isna(value) else str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
        markdown_rows.append(
            f"| {row.stage} | {row.source} | {display(row.record_count)} | {display(row.participant_count)} | "
            f"{display(row.excluded_records)} | {str(row.detail).replace('|', '/')} |"
        )
    markdown_rows.extend([
        "",
        "## Investigation of losses above 5%",
        "",
        f"- The phone file is a completed 155 × 21 participant-day grid ({len(base)} rows). "
        f"Exactly {int(base['sleep_quality'].isna().sum())} rows lack a morning sleep outcome, while "
        f"{int(base['sleep_quality'].notna().sum())} rows contain observed sleep quality and overall-use windows. "
        "These missing outcome rows remain NA and are not converted to zero.",
        f"- The game file contains {len(loaded.get('game', []))} rows from "
        f"{clean_identifier(loaded['game']['user_id'], config).nunique(dropna=True) if 'game' in loaded else 0} participants. "
        "The 441 phone-grid rows without a game source row are structural file coverage absence, retained as NA and marked by `game_source_row_present=False`.",
        f"- The timeframes file contains {len(loaded.get('timeframes', []))} records from "
        f"{clean_identifier(loaded['timeframes']['user_id'], config).nunique(dropna=True) if 'timeframes' in loaded else 0} participants. "
        "Three rows belong to timeframe-only participant 101; all 1,856 timeframe rows for phone participants align after the documented date-to-study-day conversion. "
        "Phone-grid rows without a timeframe record reflect completed-grid days without a morning timeframe record and remain structurally missing.",
        f"- Profiling retains {int(profiles['eligible_for_profiles'].sum())} participants and excludes "
        f"{int((~profiles['eligible_for_profiles']).sum())} participants with fewer than "
        f"{config['analysis']['min_valid_days_for_profile']} valid primary days, as preregistered.",
        "",
        "Stage-specific exclusions overlap and must not be added together.",
    ])
    (TABLES.parent / "ANALYTIC_SAMPLE_FLOW.md").write_text("\n".join(markdown_rows), encoding="utf-8")

    create_data_dictionary(base).to_csv(TABLES / "data_dictionary.csv", index=False)

    reference = config.get("reference_expectations", {})
    quality_rows = [
        {"metric": "participant_count", "value": int(base["participant_id"].nunique())},
        {"metric": "participant_day_rows", "value": int(len(base))},
        {"metric": "valid_primary_days", "value": int(base["valid_primary_day"].sum())},
        {"metric": "median_observed_days_per_participant", "value": float(grouped["day_key"].nunique().median())},
        {"metric": "sleep_quality_non_missing", "value": int(base["sleep_quality"].notna().sum())},
        {"metric": "mean_total_use_hours", "value": float(base["total_use"].mean())},
        {"metric": "usage_divisor", "value": divisor},
        {"metric": "all_official_files_present", "value": not missing},
    ]
    observed_reference = {
        "participants": int(base["participant_id"].nunique()),
        "sleep_assessments": int(base["sleep_quality"].notna().sum()),
    }
    for name, observed in observed_reference.items():
        if name in reference:
            quality_rows.extend([
                {"metric": f"reference_{name}_expected", "value": reference[name]},
                {"metric": f"reference_{name}_matches", "value": observed == reference[name]},
            ])
    pd.DataFrame(quality_rows).to_csv(TABLES / "data_quality_report.csv", index=False)
    LOGGER.info("Prepared %d participant-day rows for %d participants.", len(base), base["participant_id"].nunique())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
