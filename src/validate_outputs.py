from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common import PROCESSED, TABLES, detect_dataset_files, json_dump, load_config, missing_dataset_stems, setup_logging

LOGGER = setup_logging("validation", "validation.log")

PREDICTION_EVALUATION_WEIGHTINGS = {"participant_day", "participant_equal"}


def _prediction_metric_weights(participant_ids: pd.Series, weighting: str) -> np.ndarray | None:
    ids = participant_ids.astype("string")
    if weighting == "participant_day":
        return None
    if weighting != "participant_equal":
        raise ValueError(f"Unknown prediction evaluation weighting: {weighting}")
    counts = ids.map(ids.value_counts()).to_numpy(dtype=float)
    if (counts <= 0).any() or not np.isfinite(counts).all():
        raise ValueError("Invalid participant counts while validating participant-equal metrics.")
    return 1.0 / counts


def _weighted_prediction_metrics(observed: pd.Series, predicted: pd.Series, weights: np.ndarray | None) -> dict[str, float]:
    y = pd.to_numeric(observed, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(predicted, errors="coerce").to_numpy(dtype=float)
    w = np.ones(len(y), dtype=float) if weights is None else np.asarray(weights, dtype=float)
    w = w / w.sum()
    error = y - p
    mae = float(np.sum(w * np.abs(error)))
    rmse = float(np.sqrt(np.sum(w * error**2)))
    mean_y = float(np.sum(w * y))
    denominator = float(np.sum(w * (y - mean_y) ** 2))
    r2 = float(1 - np.sum(w * error**2) / denominator) if denominator > 0 else np.nan
    return {"mae": mae, "rmse": rmse, "r2": r2}


def check(name: str, passed: bool, severity: str, detail: str) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "severity": severity, "detail": detail}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate publication-analysis outputs.")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--allow-quick", action="store_true")
    args = parser.parse_args()
    config = load_config()
    rows: list[dict[str, Any]] = []

    missing = missing_dataset_stems(config, detect_dataset_files(config))
    rows.append(check(
        "official_source_files_present",
        not missing or args.allow_partial,
        "critical",
        "Missing: " + ", ".join(missing) if missing else "All expected source files detected.",
    ))

    daily_path = PROCESSED / "daily_analytic.csv"
    profiles_path = PROCESSED / "participant_profiles.csv"
    rows.append(check("daily_analytic_exists", daily_path.exists(), "critical", str(daily_path)))
    rows.append(check("participant_profiles_exists", profiles_path.exists(), "critical", str(profiles_path)))

    if daily_path.exists():
        daily = pd.read_csv(daily_path, dtype={"participant_id": "string"})
        ids = daily.get("participant_id", pd.Series(dtype="string")).astype("string")
        bad_ids = ids.isna() | ids.str.strip().str.lower().isin({"", "nan", "none", "null", "<na>"})
        rows.append(check("no_invalid_participant_ids", not bad_ids.any(), "critical", f"Invalid rows: {int(bad_ids.sum())}"))
        key_cols = [c for c in ("participant_id", "day_key") if c in daily]
        if len(key_cols) < 2 and "day" in daily:
            key_cols = ["participant_id", "day"]
        duplicates = int(daily.duplicated(key_cols).sum()) if len(key_cols) == 2 else -1
        rows.append(check("unique_participant_day", duplicates == 0, "critical", f"Duplicates: {duplicates}"))
        if "sleep_quality" in daily:
            q = pd.to_numeric(daily["sleep_quality"], errors="coerce")
            valid = q.dropna().between(config["sleep_quality_min"], config["sleep_quality_max"]).all()
            rows.append(check("sleep_quality_in_declared_range", bool(valid), "critical", f"Observed range: {q.min()}–{q.max()}"))
        if "total_use" in daily:
            use = pd.to_numeric(daily["total_use"], errors="coerce")
            valid = use.dropna().between(0, config["analysis"]["max_total_use_hours"]).all()
            rows.append(check("total_use_in_valid_range", bool(valid), "critical", f"Observed range: {use.min()}–{use.max()} hours"))
        old_lag_present = "sleep_quality_lag1" in daily.columns
        rows.append(check(
            "ambiguous_previous_observation_lag_removed",
            not old_lag_present,
            "critical",
            "sleep_quality_lag1 is absent; only the exact one-study-day lag is permitted."
            if not old_lag_present else "Ambiguous sleep_quality_lag1 column is still present.",
        ))
        exact_lag_columns = {
            "sleep_quality_lag1_exact",
            "sleep_quality_previous_observed_day_gap",
            "sleep_quality_lag1_exact_status",
        }
        rows.append(check(
            "exact_previous_day_lag_columns_exist",
            exact_lag_columns <= set(daily.columns),
            "critical",
            f"Missing columns: {sorted(exact_lag_columns - set(daily.columns))}",
        ))
        if exact_lag_columns <= set(daily.columns):
            gap = pd.to_numeric(daily["sleep_quality_previous_observed_day_gap"], errors="coerce")
            lag = pd.to_numeric(daily["sleep_quality_lag1_exact"], errors="coerce")
            lag_on_wrong_gap = lag.notna() & ~np.isclose(gap, 1.0, rtol=0.0, atol=1e-9, equal_nan=False)
            rows.append(check(
                "exact_lag_never_bridges_observation_gaps",
                not lag_on_wrong_gap.any(),
                "critical",
                f"Nonmissing lag values on non-one-day gaps: {int(lag_on_wrong_gap.sum())}",
            ))
            ordered = daily.copy()
            ordered["_validation_order"] = np.arange(len(ordered), dtype=int)
            ordered["_numeric_day"] = pd.to_numeric(ordered["day"], errors="coerce")
            ordered = ordered.sort_values(
                ["participant_id", "_numeric_day", "_validation_order"],
                kind="mergesort",
                na_position="last",
            )
            previous_day = ordered.groupby("participant_id", sort=False)["_numeric_day"].shift(1)
            previous_sleep = ordered.groupby("participant_id", sort=False)["sleep_quality"].shift(1)
            expected_gap = ordered["_numeric_day"] - previous_day
            expected_exact = previous_sleep.where(
                np.isclose(expected_gap, 1.0, rtol=0.0, atol=1e-9, equal_nan=False)
            )
            actual_exact = pd.to_numeric(ordered["sleep_quality_lag1_exact"], errors="coerce")
            exact_values_match = np.isclose(
                actual_exact, expected_exact, rtol=0.0, atol=1e-12, equal_nan=True
            )
            rows.append(check(
                "exact_lag_values_match_recomputed_previous_day_sleep",
                bool(exact_values_match.all()),
                "critical",
                f"Mismatching rows: {int((~exact_values_match).sum())}",
            ))

    summary_path = TABLES / "run_summary.json"
    rows.append(check("run_summary_exists", summary_path.exists(), "critical", str(summary_path)))
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        quick_ok = not summary.get("quick_mode", False) or args.allow_quick
        rows.append(check("not_quick_mode_for_publication", quick_ok, "critical", f"quick_mode={summary.get('quick_mode')}"))
        observed_weightings = set(summary.get("prediction_evaluation_weightings", []))
        rows.append(check(
            "run_summary_declares_both_prediction_estimands",
            observed_weightings == PREDICTION_EVALUATION_WEIGHTINGS,
            "critical",
            f"Observed: {sorted(observed_weightings)}",
        ))
        rows.append(check(
            "participant_equal_is_primary_prediction_estimand",
            summary.get("primary_prediction_weighting") == "participant_equal",
            "critical",
            f"primary_prediction_weighting={summary.get('primary_prediction_weighting')}",
        ))

    fold_path = TABLES / "outer_fold_assignments.csv"
    prediction_path = TABLES / "out_of_fold_predictions.csv"
    rows.append(check("outer_fold_assignments_exist", fold_path.exists(), "critical", str(fold_path)))
    rows.append(check("out_of_fold_predictions_exist", prediction_path.exists(), "critical", str(prediction_path)))
    if fold_path.exists():
        folds = pd.read_csv(fold_path, dtype={"participant_id": "string"})
        fold_counts = folds.groupby("participant_id")["outer_fold"].nunique()
        rows.append(check(
            "participant_grouping_prevents_outer_fold_leakage",
            bool((fold_counts <= 1).all()),
            "critical",
            f"Participants assigned to >1 fold: {int((fold_counts > 1).sum())}",
        ))
    if prediction_path.exists():
        predictions = pd.read_csv(prediction_path, dtype={"participant_id": "string"})
        duplicate_predictions = int(predictions.duplicated(["row_index", "feature_set", "model"]).sum())
        rows.append(check("one_oof_prediction_per_row_and_model", duplicate_predictions == 0, "critical", f"Duplicates: {duplicate_predictions}"))
        model_counts = predictions.groupby(["feature_set", "model"])["row_index"].nunique()
        rows.append(check("prediction_models_have_rows", bool((model_counts > 0).all()), "critical", model_counts.to_json()))


        performance_path = TABLES / "predictive_performance.csv"
        fold_performance_path = TABLES / "predictive_performance_folds.csv"
        comparison_path = TABLES / "predictive_model_comparisons.csv"
        participant_loss_path = TABLES / "predictive_participant_losses.csv"
        rows.append(check("predictive_performance_exists", performance_path.exists(), "critical", str(performance_path)))
        rows.append(check("predictive_fold_performance_exists", fold_performance_path.exists(), "critical", str(fold_performance_path)))
        rows.append(check("predictive_model_comparisons_exist", comparison_path.exists(), "critical", str(comparison_path)))
        rows.append(check("predictive_participant_losses_exist", participant_loss_path.exists(), "critical", str(participant_loss_path)))

        if performance_path.exists():
            performance = pd.read_csv(performance_path)
            required_columns = {
                "feature_set", "model", "evaluation_weighting", "metric",
                "estimate", "ci_low", "ci_high", "participants", "observations",
            }
            rows.append(check(
                "predictive_performance_has_dual_estimand_schema",
                required_columns <= set(performance.columns),
                "critical",
                f"Missing columns: {sorted(required_columns - set(performance.columns))}",
            ))
            if required_columns <= set(performance.columns):
                expected_models = predictions[["feature_set", "model"]].drop_duplicates()
                coverage = performance.groupby(["feature_set", "model"])["evaluation_weighting"].agg(
                    lambda values: set(values.astype(str))
                )
                missing_weightings = {
                    f"{feature_set}/{model}": sorted(PREDICTION_EVALUATION_WEIGHTINGS - coverage.get((feature_set, model), set()))
                    for feature_set, model in expected_models.itertuples(index=False, name=None)
                    if coverage.get((feature_set, model), set()) != PREDICTION_EVALUATION_WEIGHTINGS
                }
                rows.append(check(
                    "participant_day_and_participant_equal_metrics_reported_for_every_model",
                    not missing_weightings,
                    "critical",
                    json.dumps(missing_weightings, sort_keys=True) if missing_weightings else "Both estimands present for every model.",
                ))

                mismatches = []
                equal_weight_spread = []
                for (feature_set, model), group in predictions.groupby(["feature_set", "model"]):
                    for weighting in sorted(PREDICTION_EVALUATION_WEIGHTINGS):
                        weights = _prediction_metric_weights(group["participant_id"], weighting)
                        recomputed = _weighted_prediction_metrics(group["observed"], group["predicted"], weights)
                        for metric, expected in recomputed.items():
                            match = performance[
                                (performance["feature_set"] == feature_set)
                                & (performance["model"] == model)
                                & (performance["evaluation_weighting"] == weighting)
                                & (performance["metric"] == metric)
                            ]
                            if len(match) != 1:
                                mismatches.append(f"{feature_set}/{model}/{weighting}/{metric}: rows={len(match)}")
                                continue
                            observed_estimate = float(match.iloc[0]["estimate"])
                            if not np.isclose(observed_estimate, expected, rtol=1e-10, atol=1e-10, equal_nan=True):
                                mismatches.append(
                                    f"{feature_set}/{model}/{weighting}/{metric}: "
                                    f"reported={observed_estimate}, recomputed={expected}"
                                )
                    equal_weights = _prediction_metric_weights(group["participant_id"], "participant_equal")
                    participant_totals = pd.DataFrame({
                        "participant_id": group["participant_id"].astype("string").to_numpy(),
                        "weight": equal_weights,
                    }).groupby("participant_id")["weight"].sum()
                    equal_weight_spread.append(float(participant_totals.max() - participant_totals.min()))
                rows.append(check(
                    "predictive_metric_estimates_recompute_from_oof_predictions",
                    not mismatches,
                    "critical",
                    "; ".join(mismatches[:20]) if mismatches else "All participant-day and participant-equal estimates reproduce.",
                ))
                maximum_spread = max(equal_weight_spread) if equal_weight_spread else np.nan
                rows.append(check(
                    "participant_equal_weights_give_each_adolescent_equal_total_influence",
                    bool(equal_weight_spread and maximum_spread <= 1e-12),
                    "critical",
                    f"Maximum participant total-weight spread across models: {maximum_spread}",
                ))

        if participant_loss_path.exists() and performance_path.exists():
            participant_losses = pd.read_csv(participant_loss_path, dtype={"participant_id": "string"})
            required_loss_columns = {
                "feature_set", "model", "participant_id", "observations",
                "mae", "mse", "rmse", "observed_mean", "predicted_mean",
            }
            rows.append(check(
                "participant_loss_table_has_required_schema",
                required_loss_columns <= set(participant_losses.columns),
                "critical",
                f"Missing columns: {sorted(required_loss_columns - set(participant_losses.columns))}",
            ))
            if required_loss_columns <= set(participant_losses.columns):
                duplicate_loss_rows = int(participant_losses.duplicated(["feature_set", "model", "participant_id"]).sum())
                rows.append(check(
                    "one_participant_loss_row_per_model",
                    duplicate_loss_rows == 0,
                    "critical",
                    f"Duplicates: {duplicate_loss_rows}",
                ))
                aggregate_mismatches = []
                for (feature_set, model), group in participant_losses.groupby(["feature_set", "model"]):
                    expected_mae = float(group["mae"].mean())
                    expected_rmse = float(np.sqrt(group["mse"].mean()))
                    for metric, expected in (("mae", expected_mae), ("rmse", expected_rmse)):
                        match = performance[
                            (performance["feature_set"] == feature_set)
                            & (performance["model"] == model)
                            & (performance["evaluation_weighting"] == "participant_equal")
                            & (performance["metric"] == metric)
                        ]
                        if len(match) != 1 or not np.isclose(float(match.iloc[0]["estimate"]), expected, rtol=1e-10, atol=1e-10):
                            aggregate_mismatches.append(f"{feature_set}/{model}/{metric}")
                rows.append(check(
                    "participant_equal_mae_rmse_match_mean_within_participant_losses",
                    not aggregate_mismatches,
                    "critical",
                    ", ".join(aggregate_mismatches) if aggregate_mismatches else "All participant-equal losses aggregate correctly.",
                ))

        if fold_performance_path.exists():
            fold_performance = pd.read_csv(fold_performance_path)
            required_fold_columns = {"feature_set", "model", "fold", "evaluation_weighting", "mae", "rmse", "r2"}
            rows.append(check(
                "fold_performance_has_dual_estimand_schema",
                required_fold_columns <= set(fold_performance.columns),
                "critical",
                f"Missing columns: {sorted(required_fold_columns - set(fold_performance.columns))}",
            ))
            if required_fold_columns <= set(fold_performance.columns):
                fold_coverage = fold_performance.groupby(["feature_set", "model", "fold"])["evaluation_weighting"].agg(
                    lambda values: set(values.astype(str))
                )
                bad_fold_coverage = {
                    str(key): sorted(PREDICTION_EVALUATION_WEIGHTINGS - values)
                    for key, values in fold_coverage.items()
                    if values != PREDICTION_EVALUATION_WEIGHTINGS
                }
                rows.append(check(
                    "every_outer_fold_reports_both_prediction_estimands",
                    not bad_fold_coverage,
                    "critical",
                    json.dumps(bad_fold_coverage, sort_keys=True) if bad_fold_coverage else "Both estimands present in every outer fold.",
                ))

        if comparison_path.exists():
            comparisons = pd.read_csv(comparison_path)
            comparison_weightings = set(comparisons.get("evaluation_weighting", pd.Series(dtype="string")).astype(str))
            rows.append(check(
                "paired_model_comparisons_report_both_prediction_estimands",
                comparison_weightings == PREDICTION_EVALUATION_WEIGHTINGS,
                "critical",
                f"Observed weightings: {sorted(comparison_weightings)}",
            ))

    manifest_path = TABLES / "source_file_manifest.csv"
    rows.append(check("source_hash_manifest_exists", manifest_path.exists(), "critical", str(manifest_path)))
    if manifest_path.exists():
        manifest = pd.read_csv(manifest_path)
        hashes_ok = "sha256" in manifest and manifest["sha256"].astype(str).str.fullmatch(r"[0-9a-fA-F]{64}").all()
        rows.append(check("source_sha256_values_valid", bool(hashes_ok), "critical", f"Rows: {len(manifest)}"))


    repeated_diag_path = TABLES / "repeated_model_diagnostics.csv"
    if daily_path.exists() and "sleep_quality_lag1_exact" in daily.columns:
        exact_lag_n = int(pd.to_numeric(daily["sleep_quality_lag1_exact"], errors="coerce").notna().sum())
        if exact_lag_n >= 100:
            rows.append(check(
                "repeated_model_diagnostics_exist_for_exact_lag_check",
                repeated_diag_path.exists(),
                "critical",
                str(repeated_diag_path),
            ))
            if repeated_diag_path.exists():
                repeated_diag = pd.read_csv(repeated_diag_path)
                exact_rows = repeated_diag[
                    repeated_diag.get("model", pd.Series(dtype="string")).astype(str)
                    == "sensitivity_exact_previous_day_sleep"
                ]
                requested = " | ".join(exact_rows.get("requested_terms", pd.Series(dtype="string")).astype(str))
                rows.append(check(
                    "lagged_sensitivity_model_uses_only_exact_previous_day_sleep",
                    not exact_rows.empty
                    and "sleep_quality_lag1_exact" in requested
                    and "sleep_quality_lag1 |" not in requested,
                    "critical",
                    requested or "Exact lag sensitivity model missing.",
                ))

    report = pd.DataFrame(rows)
    TABLES.mkdir(parents=True, exist_ok=True)
    report.to_csv(TABLES / "validation_report.csv", index=False)
    failures = report[(~report["passed"]) & (report["severity"] == "critical")]
    json_dump(TABLES / "validation_report.json", {
        "status": "passed" if failures.empty else "failed",
        "critical_failures": failures.to_dict(orient="records"),
        "checks": report.to_dict(orient="records"),
    })
    if failures.empty:
        LOGGER.info("All publication validation checks passed.")
        return 0
    LOGGER.error("Publication validation failed: %s", failures[["check", "detail"]].to_dict(orient="records"))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
