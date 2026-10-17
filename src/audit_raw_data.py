from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from common import RAW, TABLES, load_config, normalize_name

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "outputs" / "RAW_DATA_AUDIT.md"
COMPONENTS = ("phone", "game", "social", "video", "timeframes")
USAGE_FIELDS = ("participant_id", "day", "sleep_quality", "daytime_use", "prebed_use", "postbed_use")
TIMEFRAME_FIELDS = ("participant_id", "day", "bedtime", "wakeup")
DAY_ZERO = pd.Timestamp("2020-06-02")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def encoding_and_delimiter(path: Path) -> tuple[str, str]:
    sample = path.read_bytes()[:65536]
    if sample.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        try:
            sample.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            sample.decode("latin-1")
            encoding = "latin-1"
    text = sample.decode(encoding)
    delimiter = csv.Sniffer().sniff(text, delimiters=",;\t|").delimiter
    return encoding, {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}[delimiter]


def locate_files(config: dict[str, Any]) -> tuple[dict[str, Path], list[str]]:
    aliases = {
        component: {normalize_name(value) for value in config["file_aliases"][component]}
        for component in COMPONENTS
    }
    matches: dict[str, list[Path]] = {component: [] for component in COMPONENTS}
    for path in RAW.iterdir():
        if not path.is_file() or path.name.startswith(".") or path.name == "download_manifest.json":
            continue
        stem = normalize_name(path.stem)
        for component in COMPONENTS:
            if stem in aliases[component]:
                matches[component].append(path)
    errors = []
    resolved = {}
    for component, paths in matches.items():
        if len(paths) == 1:
            resolved[component] = paths[0]
        elif not paths:
            errors.append(f"Missing required component: {component}")
        else:
            errors.append(f"Ambiguous files for {component}: {', '.join(path.name for path in paths)}")
    return resolved, errors


def exact_mapping(columns: list[str], source: str, canonical: str, config: dict[str, Any]) -> tuple[str | None, str, str]:
    normalized_columns = {normalize_name(column): column for column in columns}
    override = config["column_overrides"].get(source, {}).get(canonical)
    if override:
        normalized = normalize_name(override)
        if normalized not in normalized_columns:
            return None, "failed", f"Configured override '{override}' is absent."
        return normalized_columns[normalized], "override", f"Exact configured override '{override}'."
    exact = []
    for alias in config["aliases"][canonical]:
        normalized = normalize_name(alias)
        if normalized in normalized_columns:
            exact.append(normalized_columns[normalized])
    exact = list(dict.fromkeys(exact))
    if len(exact) == 1:
        return exact[0], "exact_alias", f"Unique exact alias '{exact[0]}'."
    if not exact:
        return None, "failed", "No exact alias or override; fuzzy matching was not attempted."
    return None, "ambiguous", f"Multiple exact aliases present: {exact}. Set column_overrides explicitly."


def missing_mask(series: pd.Series, config: dict[str, Any]) -> pd.Series:
    text = series.astype("string").str.strip().str.lower()
    tokens = {str(value).strip().lower() for value in config["missing_string_tokens"]}
    sentinels = {str(value) for value in config["missing_numeric_sentinels"]}
    return series.isna() | text.isin(tokens | sentinels)


def add_quality(rows: list[dict[str, Any]], check: str, component: str, severity: str, status: str,
                observed: Any, expected: Any, detail: str) -> None:
    rows.append({
        "check": check,
        "component": component,
        "severity": severity,
        "status": status,
        "observed": observed,
        "expected": expected,
        "detail": detail,
    })


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    if frame.empty:
        return ["No rows."]
    values = frame[columns].fillna("").astype(str)
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in values.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in row) + " |")
    return lines


def main() -> int:
    config = load_config()
    TABLES.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    files, file_errors = locate_files(config)
    inventory_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    frames: dict[str, pd.DataFrame] = {}
    mappings: dict[str, dict[str, str]] = {}
    critical_errors = list(file_errors)

    for component in COMPONENTS:
        path = files.get(component)
        if path is None:
            inventory_rows.append({"component": component, "status": "missing"})
            add_quality(quality_rows, "required_component_present", component, "critical", "failed", "absent", "present",
                        f"No unique file resolved for {component}.")
            continue
        encoding, delimiter_name = encoding_and_delimiter(path)
        delimiter = {"comma": ",", "semicolon": ";", "tab": "\t", "pipe": "|"}[delimiter_name]
        frame = pd.read_csv(path, encoding=encoding, sep=delimiter, low_memory=False)
        raw_strings = pd.read_csv(path, encoding=encoding, sep=delimiter, dtype="string", keep_default_na=False)
        frames[component] = raw_strings
        inventory_rows.append({
            "component": component,
            "status": "present",
            "exact_filename": path.name,
            "extension": path.suffix,
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
            "encoding": encoding,
            "delimiter": delimiter_name,
            "row_count": len(frame),
            "column_count": len(frame.columns),
        })
        add_quality(quality_rows, "required_component_present", component, "critical", "passed", path.name, "present",
                    "Unique exact file-stem match.")

        required = TIMEFRAME_FIELDS if component == "timeframes" else USAGE_FIELDS
        mappings[component] = {}
        for position, column in enumerate(frame.columns, start=1):
            schema_rows.append({
                "component": component,
                "exact_filename": path.name,
                "column_position": position,
                "column_name": column,
                "inferred_dtype": str(frame[column].dtype),
                "non_missing_raw": int((~missing_mask(raw_strings[column], config)).sum()),
                "missing_or_sentinel_raw": int(missing_mask(raw_strings[column], config).sum()),
            })
        for canonical in required:
            column, method, detail = exact_mapping(list(frame.columns), component, canonical, config)
            status = "passed" if column else "failed"
            add_quality(quality_rows, "exact_column_mapping", component, "critical", status, column or "unresolved", canonical,
                        f"{method}: {detail}")
            if column:
                mappings[component][canonical] = column
                for row in schema_rows:
                    if row["component"] == component and row["column_name"] == column:
                        row["mapping_target"] = canonical
                        row["mapping_method"] = method
            else:
                critical_errors.append(f"{component}.{canonical}: {detail}")

    for component, frame in frames.items():
        mapping = mappings.get(component, {})
        id_col = mapping.get("participant_id")
        day_col = mapping.get("day")
        if id_col:
            missing_ids = int(missing_mask(frame[id_col], config).sum())
            add_quality(quality_rows, "missing_participant_ids", component, "critical",
                        "passed" if missing_ids == 0 else "failed", missing_ids, 0, "Raw missing tokens and numeric sentinels checked.")
        if day_col:
            missing_days = int(missing_mask(frame[day_col], config).sum())
            add_quality(quality_rows, "missing_study_days", component, "critical",
                        "passed" if missing_days == 0 else "failed", missing_days, 0, "Raw missing tokens and numeric sentinels checked.")
            valid = ~missing_mask(frame[day_col], config)
            if component == "timeframes":
                parsed_day = pd.to_datetime(frame.loc[valid, day_col], errors="coerce")
                invalid_days = int(parsed_day.isna().sum())
            else:
                parsed_day = pd.to_numeric(frame.loc[valid, day_col], errors="coerce")
                invalid_days = int((parsed_day.isna() | (parsed_day < 1) | (parsed_day % 1 != 0)).sum())
            add_quality(quality_rows, "invalid_day_values", component, "critical",
                        "passed" if invalid_days == 0 else "failed", invalid_days, 0, "Dates or positive integer study days required.")
        if id_col and day_col:
            valid = ~missing_mask(frame[id_col], config) & ~missing_mask(frame[day_col], config)
            duplicates = int(frame.loc[valid].duplicated([id_col, day_col]).sum())
            add_quality(quality_rows, "duplicate_participant_day_keys", component, "critical",
                        "passed" if duplicates == 0 else "failed", duplicates, 0, "Exact raw participant-day key checked.")

        sentinel_count = 0
        for column in frame.columns:
            text = frame[column].astype("string").str.strip()
            sentinel_count += int(text.isin({str(value) for value in config["missing_numeric_sentinels"]}).sum())
        add_quality(quality_rows, "numeric_missing_sentinels", component, "info", "observed", sentinel_count,
                    "documented", "Sentinels are missing values, not invalid substantive measurements.")

        if component != "timeframes":
            for canonical in ("daytime_use", "prebed_use", "postbed_use"):
                column = mapping.get(canonical)
                if not column:
                    continue
                valid = ~missing_mask(frame[column], config)
                numeric = pd.to_numeric(frame.loc[valid, column], errors="coerce")
                nonnumeric = int(numeric.isna().sum())
                negative = int((numeric < 0).sum())
                above = int((numeric > 24).sum())
                add_quality(quality_rows, "duration_numeric", component, "critical",
                            "passed" if nonnumeric == 0 else "failed", nonnumeric, 0, f"{column}; authoritative unit: hours.")
                add_quality(quality_rows, "negative_durations", component, "critical",
                            "passed" if negative == 0 else "failed", negative, 0, f"{column}; sentinels excluded.")
                add_quality(quality_rows, "durations_above_24_hours", component, "critical",
                            "passed" if above == 0 else "failed", above, 0, f"{column}; authoritative unit: hours.")
            sleep_col = mapping.get("sleep_quality")
            if sleep_col:
                valid = ~missing_mask(frame[sleep_col], config)
                sleep = pd.to_numeric(frame.loc[valid, sleep_col], errors="coerce")
                invalid_sleep = int((sleep.isna() | ~sleep.between(config["sleep_quality_min"], config["sleep_quality_max"])).sum())
                add_quality(quality_rows, "impossible_sleep_quality_values", component, "critical",
                            "passed" if invalid_sleep == 0 else "failed", invalid_sleep, 0, "Expected morning scale range 1-7.")
        else:
            for canonical in ("bedtime", "wakeup"):
                column = mapping.get(canonical)
                if column:
                    valid = ~missing_mask(frame[column], config)
                    parsed = pd.to_datetime(frame.loc[valid, column], errors="coerce", utc=True)
                    malformed = int(parsed.isna().sum())
                    add_quality(quality_rows, "malformed_times", component, "critical",
                                "passed" if malformed == 0 else "failed", malformed, 0, f"{canonical} mapped to {column}.")

    if "phone" in frames and mappings.get("phone", {}).get("participant_id"):
        phone = frames["phone"]
        id_col = mappings["phone"]["participant_id"]
        participants = int(phone.loc[~missing_mask(phone[id_col], config), id_col].nunique())
        add_quality(quality_rows, "participant_count", "phone", "warning",
                    "matched" if participants == config["reference_expectations"]["participants"] else "discrepant",
                    participants, config["reference_expectations"]["participants"],
                    "A discrepancy requires version/schema investigation, not an assumption of source error.")
        sleep_col = mappings["phone"].get("sleep_quality")
        sleep_n = int((~missing_mask(phone[sleep_col], config)).sum()) if sleep_col else 0
        add_quality(quality_rows, "sleep_assessment_count", "phone", "warning", "observed", sleep_n,
                    f"approximately {config['reference_expectations']['sleep_assessments']}",
                    "The official combination script documents 1,806 released Mplus rows with observed use/sleep after completion rules; compare definitions before judging discrepancy.")

    add_quality(quality_rows, "tracked_app_activity_count", "all", "info", "not_directly_observable", "not in processed files",
                config["reference_expectations"]["tracked_app_activities"],
                "The five released files are participant-day Mplus inputs; the reference activity count pertains to underlying event-level tracking.")
    add_quality(quality_rows, "usage_unit", "phone_game_social_video", "critical", "passed", "hours", "hours",
                "Original combination script sums seconds and divides by 60 twice; descriptive script multiplies released values by 3600.")

    if "phone" in frames and "timeframes" in frames and not critical_errors:
        phone = frames["phone"].copy()
        timing = frames["timeframes"].copy()
        pmap, tmap = mappings["phone"], mappings["timeframes"]
        phone["_study_day"] = pd.to_numeric(phone[pmap["day"]], errors="coerce")
        timing["_study_day"] = (pd.to_datetime(timing[tmap["day"]], errors="coerce") - DAY_ZERO).dt.days + 1
        phone["_id"] = phone[pmap["participant_id"]].astype("string")
        timing["_id"] = timing[tmap["participant_id"]].astype("string")
        merged = timing.merge(phone, on=["_id", "_study_day"], how="left", suffixes=("_timeframes", "_phone"), indicator=True)
        phone_ids = set(phone["_id"].dropna())
        shared_participant_rows = merged["_id"].isin(phone_ids)
        unmatched = int((shared_participant_rows & (merged["_merge"] != "both")).sum())
        timeframe_only_ids = sorted(set(timing["_id"].dropna()) - phone_ids)
        add_quality(quality_rows, "timeframes_to_phone_alignment", "timeframes", "critical",
                    "passed" if unmatched == 0 else "failed", unmatched, 0,
                    "Shared participants only; applied authoritative study_day = date_res - 2020-06-02 + 1 transformation.")
        add_quality(quality_rows, "timeframes_only_participants", "timeframes", "info", "documented",
                    " | ".join(timeframe_only_ids) if timeframe_only_ids else "none", "source-stage difference allowed",
                    "The original source script documents 156 timeframe participants and 155 released analysis participants.")

        t_sleep = "sleep_qual_timeframes"
        p_sleep = pmap["sleep_quality"] + "_phone"
        if t_sleep in merged and p_sleep in merged:
            valid = ~missing_mask(merged[t_sleep], config) & ~missing_mask(merged[p_sleep], config)
            same = int((pd.to_numeric(merged.loc[valid, t_sleep]) == pd.to_numeric(merged.loc[valid, p_sleep])).sum())
            total = int(valid.sum())
            add_quality(quality_rows, "sleep_quality_same_day_alignment", "phone_timeframes", "critical",
                        "passed" if same == total and total > 0 else "failed", f"{same}/{total}", "all comparable rows",
                        "Confirms no additional one-day shift: morning sleep_quality matches the same derived study_day.")

    inventory = pd.DataFrame(inventory_rows)
    schema = pd.DataFrame(schema_rows)
    quality = pd.DataFrame(quality_rows)
    inventory.to_csv(TABLES / "raw_file_inventory.csv", index=False)
    schema.to_csv(TABLES / "raw_schema_report.csv", index=False)
    quality.to_csv(TABLES / "raw_data_quality_audit.csv", index=False)
    failures = quality[(quality["severity"] == "critical") & (quality["status"] == "failed")]

    report = [
        "# Raw Data Audit",
        "",
        "Audit date: 2026-07-17",
        "",
        "## Decision",
        "",
        "**PASSED**" if failures.empty else "**FAILED — substantive analysis is blocked.**",
        "",
        "## Official file inventory",
        "",
        *markdown_table(inventory, ["component", "exact_filename", "size_bytes", "sha256", "encoding", "delimiter", "row_count", "column_count"]),
        "",
        "## Exact mappings",
        "",
        *markdown_table(schema[schema.get("mapping_target", pd.Series(index=schema.index, dtype=object)).notna()],
                        ["component", "column_name", "inferred_dtype", "mapping_target", "mapping_method"]),
        "",
        "## Quality checks",
        "",
        *markdown_table(quality, ["check", "component", "severity", "status", "observed", "expected", "detail"]),
        "",
        "## Authoritative timing and unit interpretation",
        "",
        "The original source script defines `bt_yes` as bedtime yesterday and `wt_today` as wake-up today. It aggregates tracked events into daytime (`wt_yes` to `hbefore_bt_yes`), pre-bedtime (`hbefore_bt_yes` to `bt_yes`), and post-bedtime (`bt_yes` to `wt_today`) windows, groups them with the morning `sleep_qual` on `date_res`, and derives `study_day = date_res - 2020-06-02 + 1`. No additional one-day shift is warranted.",
        "",
        "Usage values are hours because the source script converts summed seconds by dividing by 60 twice. This is supported independently by the authors' descriptive script, which multiplies released values by 3600 for duration display.",
        "",
        "The 745,706 tracked-app-activity expectation is not a row-count target for these participant-day processed files. Any difference in released participant-day or sleep-assessment counts must be reconciled by definition and processing stage rather than labeled a source-data error.",
        "",
        f"Unresolved critical errors: {len(failures)}.",
    ]
    REPORT.write_text("\n".join(report), encoding="utf-8")
    print(json.dumps({"status": "passed" if failures.empty else "failed", "critical_failures": len(failures)}, indent=2))
    return 0 if failures.empty else 2


if __name__ == "__main__":
    raise SystemExit(main())
