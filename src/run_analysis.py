from __future__ import annotations

import argparse
import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from joblib import dump
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import ElasticNet
from sklearn.metrics import adjusted_rand_score, mean_absolute_error, mean_squared_error, r2_score, silhouette_score
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

from common import FIGURES, MODELS, PROCESSED, TABLES, ensure_directories, json_dump, load_config, setup_logging

LOGGER = setup_logging("analysis", "analysis.log")

PREREGISTERED_ANALYSIS = {
    "cluster_k_min": 2,
    "cluster_k_max": 6,
    "min_cluster_fraction": 0.10,
    "min_silhouette": 0.25,
    "min_stability_ari": 0.75,
    "stability_subsamples": 200,
    "subsample_fraction": 0.80,
    "gower_range_quantiles": [0.05, 0.95],
    "correlation_prune_threshold": 0.92,
    "random_state": 42,
    "group_cv_splits": 5,
    "inner_cv_splits": 4,
    "bootstrap_repetitions": 1000,
    "min_valid_days_for_profile": 5,
    "profile_missingness_max": 0.30,
    "min_feature_coverage": 0.30,
    "sleep_quality_as_continuous": True,
    "prediction_evaluation_weightings": ["participant_day", "participant_equal"],
    "primary_prediction_weighting": "participant_equal",
}

PREDICTIVE_FEATURE_SETS = {
    "baseline_total": ["total_use"],
    "temporal": ["daytime_use", "prebed_use", "postbed_use"],
    "extended": [
        "daytime_use", "prebed_use", "postbed_use",
        "nighttime_exposure_ratio", "postbed_intrusion_ratio",
        "social_prebed_use", "social_postbed_use",
        "game_prebed_use", "game_postbed_use",
        "video_prebed_use", "video_postbed_use",
        "sleep_window_hours", "bedtime_sin", "bedtime_cos",
    ],
}
RANDOM_FOREST_FEATURE_SET = "extended"
PREDICTION_EVALUATION_WEIGHTINGS = ("participant_day", "participant_equal")
PRIMARY_PREDICTION_WEIGHTING = "participant_equal"


def validate_preregistered_config(config: dict[str, Any]) -> None:
    options = config.get("analysis", {})
    mismatches = {
        key: {"expected": expected, "observed": options.get(key)}
        for key, expected in PREREGISTERED_ANALYSIS.items()
        if options.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"Preregistered analysis settings changed: {json.dumps(mismatches, sort_keys=True)}")


def validate_analysis_input(frame: pd.DataFrame) -> None:
    required = {"participant_id", "day_key", "sleep_quality"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Analysis input is missing required participant-day fields: {missing}")
    ids = frame["participant_id"].astype("string")
    invalid_ids = ids.isna() | ids.str.strip().str.lower().isin({"", "nan", "none", "null", "<na>"})
    if invalid_ids.any():
        raise ValueError(f"Analysis input contains {int(invalid_ids.sum())} invalid participant IDs.")
    duplicates = int(frame.duplicated(["participant_id", "day_key"]).sum())
    if duplicates:
        raise ValueError(f"Analysis input contains {duplicates} duplicate participant-day keys.")


def assert_disjoint_participants(train_groups: pd.Series, test_groups: pd.Series, context: str) -> None:
    overlap = set(train_groups.astype("string").dropna()) & set(test_groups.astype("string").dropna())
    if overlap:
        raise RuntimeError(f"Participant leakage in {context}: {sorted(overlap)[:10]}")


def numeric_descriptives(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in frame.select_dtypes(include=np.number).columns:
        values = frame[column].dropna()
        if values.empty:
            continue
        rows.append({
            "variable": column,
            "n": int(values.size),
            "mean": float(values.mean()),
            "sd": float(values.std()),
            "median": float(values.median()),
            "q1": float(values.quantile(0.25)),
            "q3": float(values.quantile(0.75)),
            "min": float(values.min()),
            "max": float(values.max()),
            "missing_pct": float(100 * frame[column].isna().mean()),
        })
    return pd.DataFrame(rows)


def construct_name(column: str) -> str:
    if column.endswith("_sd"):
        return "variability"
    if any(token in column for token in ("social_share", "game_share", "video_share")):
        return "composition"
    if any(token in column for token in ("nighttime_exposure", "postbed_intrusion", "prebed", "postbed")):
        return "timing"
    return "intensity"


def prune_correlated_features(
    frame: pd.DataFrame,
    columns: list[str],
    threshold: float,
) -> tuple[list[str], pd.DataFrame]:
    retained = list(columns)
    audit = []
    for construct in sorted({construct_name(column) for column in columns}):
        construct_columns = [column for column in retained if construct_name(column) == construct]
        if len(construct_columns) < 2:
            continue
        correlation = frame[construct_columns].corr(method="spearman").abs()
        pairs = []
        for i, first in enumerate(construct_columns):
            for second in construct_columns[i + 1 :]:
                value = correlation.loc[first, second]
                if pd.notna(value) and value >= threshold:
                    pairs.append((float(value), first, second))
        for value, first, second in sorted(pairs, reverse=True):
            if first not in retained or second not in retained:
                continue
            missing_first = frame[first].isna().mean()
            missing_second = frame[second].isna().mean()
            if missing_first > missing_second:
                removed, kept = first, second
            elif missing_second > missing_first:
                removed, kept = second, first
            else:
                # Prefer the mean over the SD only when missingness is identical; otherwise deterministic order.
                if first.endswith("_sd") and not second.endswith("_sd"):
                    removed, kept = first, second
                elif second.endswith("_sd") and not first.endswith("_sd"):
                    removed, kept = second, first
                else:
                    removed, kept = sorted((first, second), reverse=True)
            retained.remove(removed)
            audit.append({
                "construct": construct,
                "removed": removed,
                "kept": kept,
                "absolute_spearman": value,
                "threshold": threshold,
            })
    return retained, pd.DataFrame(audit)


def construct_weights(columns: list[str]) -> np.ndarray:
    groups = [construct_name(column) for column in columns]
    unique = sorted(set(groups))
    weights = np.zeros(len(columns), dtype=float)
    for group in unique:
        positions = [index for index, value in enumerate(groups) if value == group]
        for position in positions:
            weights[position] = 1.0 / (len(unique) * len(positions))
    return weights


def profile_candidate_columns(frame: pd.DataFrame) -> list[str]:
    return [
        column for column in frame.columns
        if column.endswith(("_mean", "_sd"))
        and column not in {"sleep_quality_mean", "sleep_quality_sd"}
    ]


def cluster_candidate_passes(
    minimum_cluster_fraction: float,
    mean_silhouette: float,
    median_subsample_ari: float,
    options: dict[str, Any],
) -> bool:
    return bool(
        minimum_cluster_fraction >= options["min_cluster_fraction"]
        and mean_silhouette >= options["min_silhouette"]
        and median_subsample_ari >= options["min_stability_ari"]
    )


def select_accepted_cluster_k(selection: pd.DataFrame) -> int | None:
    if selection.empty or "passes_all_thresholds" not in selection:
        return None
    accepted = selection[selection["passes_all_thresholds"]]
    if accepted.empty:
        return None
    return int(accepted.sort_values(["silhouette", "median_subsample_ari"], ascending=False).iloc[0]["k"])


def apply_within_participant_profile_missingness(
    profiles: pd.DataFrame,
    columns: list[str],
    maximum_missing_fraction: float,
    denominator_column: str = "n_valid_primary_days",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mask participant-level summaries that lack sufficient within-person coverage.

    The preregistered profiling rule first requires at least five valid primary days.
    Feature coverage must therefore be evaluated against those valid analysis days,
    not against all 21 scheduled grid days. Using ``n_observed_days`` as the
    denominator creates a contradictory rule in which a participant can satisfy the
    five-day eligibility criterion but have every profile feature masked solely
    because sleep outcomes are missing on other scheduled days.

    Counts can exceed the denominator because predictor summaries may be available on
    days without a sleep outcome. Coverage is capped at 1.0 for auditing and the
    participant is retained whenever the feature is observed on at least the required
    fraction of valid primary days.
    """
    output = profiles.copy()
    audit_rows: list[dict[str, Any]] = []
    minimum_coverage = 1.0 - maximum_missing_fraction
    if denominator_column not in output:
        raise KeyError(
            f"Missing denominator column required for preregistered profile coverage: {denominator_column}"
        )
    denominator = pd.to_numeric(output[denominator_column], errors="coerce")
    invalid_denominator = denominator.isna() | (denominator <= 0)
    for column in columns:
        base = column.removesuffix("_mean").removesuffix("_sd")
        count_column = f"{base}_n"
        if count_column not in output:
            raise KeyError(f"Missing profile count column required for preregistered missingness: {count_column}")
        counts = pd.to_numeric(output[count_column], errors="coerce")
        raw_coverage = counts / denominator.replace(0, np.nan)
        coverage = raw_coverage.clip(upper=1.0)
        fails = invalid_denominator | coverage.isna() | (coverage < minimum_coverage)
        originally_observed = output[column].notna()
        output.loc[fails, column] = np.nan
        observed_coverage = coverage[coverage.notna()]
        audit_rows.append({
            "feature": column,
            "count_column": count_column,
            "coverage_denominator": denominator_column,
            "minimum_within_participant_coverage": minimum_coverage,
            "participants_evaluated": int(len(output)),
            "participants_below_coverage": int(fails.sum()),
            "summaries_masked": int((fails & originally_observed).sum()),
            "coverage_median": float(observed_coverage.median()) if not observed_coverage.empty else np.nan,
            "coverage_min": float(observed_coverage.min()) if not observed_coverage.empty else np.nan,
            "coverage_max": float(observed_coverage.max()) if not observed_coverage.empty else np.nan,
        })
    return output, pd.DataFrame(audit_rows)


def gower_numeric_distance(
    values: np.ndarray,
    weights: np.ndarray | None = None,
    range_quantiles: tuple[float, float] = (0.05, 0.95),
) -> np.ndarray:
    """Numeric Gower dissimilarity with missing-value pairwise normalization.

    Pairs sharing no observed feature receive maximal dissimilarity (1.0), never zero.
    A robust quantile range limits domination by isolated outliers; full range is used as
    a fallback for features with an empty or zero robust range.
    """
    values = np.asarray(values, dtype=float)
    if values.ndim != 2:
        raise ValueError("values must be a two-dimensional numeric matrix")
    n, p = values.shape
    if p == 0:
        raise ValueError("At least one feature is required")
    low_q, high_q = range_quantiles
    lower = np.nanquantile(values, low_q, axis=0)
    upper = np.nanquantile(values, high_q, axis=0)
    ranges = upper - lower
    full_ranges = np.nanmax(values, axis=0) - np.nanmin(values, axis=0)
    invalid = ~np.isfinite(ranges) | (ranges <= 0)
    ranges[invalid] = full_ranges[invalid]
    ranges[~np.isfinite(ranges) | (ranges <= 0)] = 1.0
    feature_weights = np.ones(p, dtype=float) if weights is None else np.asarray(weights, dtype=float)
    if feature_weights.shape != (p,) or np.any(feature_weights < 0) or feature_weights.sum() <= 0:
        raise ValueError("weights must be non-negative and match the number of features")

    distance = np.zeros((n, n), dtype=float)
    for index in range(n):
        valid = np.isfinite(values[index])[None, :] & np.isfinite(values)
        difference = np.abs(values - values[index]) / ranges
        difference = np.minimum(difference, 1.0)
        numerator = np.nansum(difference * valid * feature_weights, axis=1)
        denominator = np.sum(valid * feature_weights, axis=1)
        row = np.divide(numerator, denominator, out=np.ones(n), where=denominator > 0)
        row[index] = 0.0
        distance[index] = row
    distance = (distance + distance.T) / 2
    np.fill_diagonal(distance, 0.0)
    return distance


@dataclass
class PAMResult:
    medoid_indices: np.ndarray
    labels: np.ndarray
    inertia: float


def pam(
    distance: np.ndarray,
    k: int,
    random_state: int,
    n_init: int = 16,
    max_iter: int = 150,
) -> PAMResult:
    distance = np.asarray(distance, dtype=float)
    n = distance.shape[0]
    if distance.shape != (n, n):
        raise ValueError("distance must be square")
    if not np.all(np.isfinite(distance)) or np.any(distance < 0):
        raise ValueError("distance must contain finite, non-negative values")
    if not 1 < k < n:
        raise ValueError("k must be between 2 and n-1")

    rng = np.random.default_rng(random_state)
    first = int(np.argmin(distance.sum(axis=1)))
    deterministic = [first]
    while len(deterministic) < k:
        nearest = distance[:, deterministic].min(axis=1)
        nearest[deterministic] = -np.inf
        deterministic.append(int(np.argmax(nearest)))
    starts = [np.asarray(deterministic, dtype=int)]
    starts.extend(rng.choice(n, size=k, replace=False) for _ in range(n_init - 1))

    best: PAMResult | None = None
    for initial in starts:
        medoids = np.asarray(initial, dtype=int).copy()
        for _ in range(max_iter):
            labels = np.argmin(distance[:, medoids], axis=1)
            updated = medoids.copy()
            for cluster in range(k):
                members = np.where(labels == cluster)[0]
                if members.size == 0:
                    available = np.setdiff1d(np.arange(n), updated)
                    nearest = distance[:, updated].min(axis=1)
                    updated[cluster] = int(available[np.argmax(nearest[available])])
                else:
                    within = distance[np.ix_(members, members)].sum(axis=1)
                    updated[cluster] = int(members[np.argmin(within)])
            # Repair any duplicate medoids.
            used: set[int] = set()
            for position, value in enumerate(updated):
                if int(value) in used:
                    available = np.array([item for item in range(n) if item not in used and item not in updated[position + 1 :]])
                    nearest = distance[:, np.array(sorted(used), dtype=int)].min(axis=1) if used else distance.sum(axis=1)
                    updated[position] = int(available[np.argmax(nearest[available])])
                used.add(int(updated[position]))
            updated.sort()
            if np.array_equal(updated, medoids):
                break
            medoids = updated
        labels = np.argmin(distance[:, medoids], axis=1)
        inertia = float(distance[np.arange(n), medoids[labels]].sum())
        candidate = PAMResult(medoid_indices=medoids, labels=labels, inertia=inertia)
        if best is None or candidate.inertia < best.inertia:
            best = candidate
    if best is None:
        raise RuntimeError("PAM failed to produce a solution")
    return best


def bootstrap_mean_interval(values: pd.Series, repetitions: int, seed: int) -> tuple[float, float]:
    data = values.dropna().to_numpy(dtype=float)
    if data.size < 2:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    estimates = [rng.choice(data, size=data.size, replace=True).mean() for _ in range(repetitions)]
    return float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975))


def cluster_profiles(profiles: pd.DataFrame, config: dict[str, Any], quick: bool) -> tuple:
    options = config["analysis"]
    selection_columns = [
        "k", "silhouette", "minimum_cluster_fraction", "median_subsample_ari",
        "ari_q10", "ari_q90", "passes_all_thresholds", "pam_total_dissimilarity",
    ]
    output = profiles.copy()
    output["cluster"] = np.nan
    output["cluster_solution_meets_thresholds"] = False

    eligible = profiles[profiles["eligible_for_profiles"].fillna(False)].copy()
    candidate_columns = profile_candidate_columns(eligible)
    status: dict[str, Any] = {
        "status": "not_estimable",
        "reason": None,
        "eligible_participants": int(len(eligible)),
        "initial_candidate_features": int(len(candidate_columns)),
        "features_after_participant_coverage": 0,
        "features_after_correlation_pruning": 0,
        "candidate_solutions_evaluated": 0,
        "selected_k": None,
        "coverage_denominator": "n_valid_primary_days",
        "minimum_valid_days": int(options["min_valid_days_for_profile"]),
        "minimum_within_participant_feature_coverage": float(1.0 - options["profile_missingness_max"]),
        "minimum_across_participant_feature_coverage": float(1.0 - options["profile_missingness_max"]),
    }

    eligible, missingness_audit = apply_within_participant_profile_missingness(
        eligible,
        candidate_columns,
        options["profile_missingness_max"],
        denominator_column="n_valid_primary_days",
    )
    missingness_audit.to_csv(TABLES / "cluster_within_participant_missingness.csv", index=False)

    minimum_feature_coverage = 1.0 - options["profile_missingness_max"]
    feature_coverage_rows: list[dict[str, Any]] = []
    covered_columns: list[str] = []
    for column in candidate_columns:
        coverage = float(eligible[column].notna().mean()) if len(eligible) else 0.0
        unique_values = int(eligible[column].nunique(dropna=True)) if column in eligible else 0
        retained = bool(coverage >= minimum_feature_coverage and unique_values > 1)
        feature_coverage_rows.append({
            "feature": column,
            "eligible_participants": int(len(eligible)),
            "participants_with_summary": int(eligible[column].notna().sum()) if column in eligible else 0,
            "across_participant_coverage": coverage,
            "minimum_required_coverage": minimum_feature_coverage,
            "unique_non_missing_values": unique_values,
            "retained_before_correlation_pruning": retained,
            "exclusion_reason": "" if retained else (
                "insufficient_across_participant_coverage"
                if coverage < minimum_feature_coverage
                else "constant_or_single_valued"
            ),
        })
        if retained:
            covered_columns.append(column)
    pd.DataFrame(feature_coverage_rows).to_csv(TABLES / "cluster_feature_coverage.csv", index=False)
    status["features_after_participant_coverage"] = int(len(covered_columns))

    columns, prune_audit = prune_correlated_features(
        eligible, covered_columns, options["correlation_prune_threshold"]
    )
    if prune_audit.empty:
        prune_audit = pd.DataFrame(columns=[
            "construct", "removed", "kept", "absolute_spearman", "threshold"
        ])
    prune_audit.to_csv(TABLES / "cluster_feature_pruning.csv", index=False)
    status["features_after_correlation_pruning"] = int(len(columns))
    status["features_used"] = list(columns)

    if len(eligible) < 30 or len(columns) < 3:
        reasons = []
        if len(eligible) < 30:
            reasons.append(f"fewer_than_30_eligible_participants:{len(eligible)}")
        if len(columns) < 3:
            reasons.append(f"fewer_than_3_usable_profile_features:{len(columns)}")
        status["reason"] = ";".join(reasons)
        model_info: dict[str, Any] = {
            "analysis_status": status,
            "columns": columns,
            "eligible_index": eligible.index.to_numpy(),
        }
        empty_profile_columns = ["cluster", "n", *columns]
        empty_profile_columns.extend(
            column for column in ("sleep_quality_mean", "sleep_quality_sd") if column in output
        )
        return (
            pd.DataFrame(columns=selection_columns),
            output,
            pd.DataFrame(columns=empty_profile_columns),
            columns,
            None,
            model_info,
        )

    values = eligible[columns].to_numpy(dtype=float)
    weights = construct_weights(columns)
    distance = gower_numeric_distance(
        values,
        weights,
        tuple(options["gower_range_quantiles"]),
    )
    stability_repetitions = min(8, options["stability_subsamples"]) if quick else options["stability_subsamples"]
    rng = np.random.default_rng(options["random_state"])
    selection_rows = []
    fitted: dict[int, PAMResult] = {}
    max_k = min(options["cluster_k_max"], len(eligible) - 1)
    for k in range(options["cluster_k_min"], max_k + 1):
        fit = pam(
            distance,
            k,
            options["random_state"] + k,
            n_init=3 if quick else 16,
            max_iter=80 if quick else 150,
        )
        labels = fit.labels
        cluster_fraction = pd.Series(labels).value_counts(normalize=True)
        silhouette = float(silhouette_score(distance, labels, metric="precomputed"))
        stability = []
        sample_size = min(len(eligible), max(k * 4, int(options["subsample_fraction"] * len(eligible))))
        for repetition in range(stability_repetitions):
            indices = np.sort(rng.choice(len(eligible), size=sample_size, replace=False))
            subfit = pam(
                distance[np.ix_(indices, indices)],
                k,
                options["random_state"] + 1000 + repetition,
                n_init=2 if quick else 4,
                max_iter=50 if quick else 80,
            )
            stability.append(adjusted_rand_score(labels[indices], subfit.labels))
        stability_array = np.asarray(stability)
        median_ari = float(np.median(stability_array))
        passes = cluster_candidate_passes(
            float(cluster_fraction.min()), silhouette, median_ari, options
        )
        selection_rows.append({
            "k": k,
            "silhouette": silhouette,
            "minimum_cluster_fraction": float(cluster_fraction.min()),
            "median_subsample_ari": median_ari,
            "ari_q10": float(np.quantile(stability_array, 0.10)),
            "ari_q90": float(np.quantile(stability_array, 0.90)),
            "passes_all_thresholds": passes,
            "pam_total_dissimilarity": fit.inertia,
        })
        fitted[k] = fit
    selection = pd.DataFrame(selection_rows, columns=selection_columns)
    status["candidate_solutions_evaluated"] = int(len(selection))

    model_info = {
        "weights": weights,
        "columns": columns,
        "eligible_index": eligible.index.to_numpy(),
        "analysis_status": status,
    }
    selected_k = select_accepted_cluster_k(selection)
    if selected_k is None:
        status["status"] = "evaluated_no_stable_solution"
        status["reason"] = "no_candidate_met_all_preregistered_size_silhouette_and_stability_thresholds"
        empty_profile_columns = ["cluster", "n", *columns]
        empty_profile_columns.extend(
            column for column in ("sleep_quality_mean", "sleep_quality_sd") if column in output
        )
        return selection, output, pd.DataFrame(columns=empty_profile_columns), columns, None, model_info

    fit = fitted[selected_k]
    output.loc[eligible.index, "cluster"] = fit.labels + 1
    output.loc[eligible.index, "cluster_solution_meets_thresholds"] = True
    summary_columns = columns + [column for column in ("sleep_quality_mean", "sleep_quality_sd") if column in output]
    profile_table = output.dropna(subset=["cluster"]).groupby("cluster")[summary_columns].mean().reset_index()
    counts = output.dropna(subset=["cluster"]).groupby("cluster").size().rename("n").reset_index()
    profile_table = counts.merge(profile_table, on="cluster")
    if "sleep_quality_mean" in output:
        intervals = []
        for cluster, group in output.dropna(subset=["cluster"]).groupby("cluster"):
            low, high = bootstrap_mean_interval(
                group["sleep_quality_mean"],
                100 if quick else options["bootstrap_repetitions"],
                options["random_state"] + int(cluster),
            )
            intervals.append({
                "cluster": cluster,
                "sleep_quality_mean_ci_low": low,
                "sleep_quality_mean_ci_high": high,
            })
        profile_table = profile_table.merge(pd.DataFrame(intervals), on="cluster", how="left")
    status["status"] = "stable_solution_identified"
    status["reason"] = "selected_candidate_met_all_preregistered_thresholds"
    status["selected_k"] = int(selected_k)
    model_info.update({"fit": fit, "selected_k": selected_k, "distance": distance})
    return selection, output, profile_table, columns, selected_k, model_info


def fit_one_repeated_model(
    frame: pd.DataFrame,
    model_name: str,
    terms: list[str],
) -> tuple[list[dict[str, Any]], Any | None, dict[str, Any]]:
    required = ["participant_id", "sleep_quality", *terms]
    work = frame[required].dropna().copy()
    diagnostics: dict[str, Any] = {
        "model": model_name,
        "n_rows": len(work),
        "n_participants": int(work["participant_id"].nunique()),
        "requested_terms": " | ".join(terms),
    }
    if diagnostics["n_participants"] < 20 or len(work) < 100:
        diagnostics.update({"status": "not_fitted", "reason": "insufficient_complete_data"})
        return [], None, diagnostics

    standardized = []
    for term in terms:
        values = pd.to_numeric(work[term], errors="coerce")
        standard_deviation = values.std(ddof=0)
        if not np.isfinite(standard_deviation) or standard_deviation <= 1e-12:
            continue
        standardized_name = f"z_{term}"
        work[standardized_name] = (values - values.mean()) / standard_deviation
        standardized.append(standardized_name)
    if len(standardized) < 2:
        diagnostics.update({"status": "not_fitted", "reason": "fewer_than_two_variable_terms"})
        return [], None, diagnostics
    formula = "sleep_quality ~ " + " + ".join(standardized)
    diagnostics["formula"] = formula

    failures = []
    selected_model = None
    model_type = None
    for method in ("lbfgs", "powell"):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            try:
                candidate = smf.mixedlm(formula, work, groups=work["participant_id"]).fit(
                    reml=False, method=method, maxiter=3000, disp=False
                )
                converged = bool(getattr(candidate, "converged", True))
                random_variance = float(np.asarray(candidate.cov_re).ravel()[0]) if np.asarray(candidate.cov_re).size else np.nan
                warning_text = " | ".join(str(item.message) for item in captured)
                if not converged or not np.all(np.isfinite(candidate.params)) or not np.isfinite(random_variance) or random_variance <= 1e-8:
                    failures.append(
                        f"MixedLM {method} rejected: converged={converged}, random_variance={random_variance}, warnings={warning_text}"
                    )
                    continue
                selected_model = candidate
                model_type = f"mixedlm_{method}"
                diagnostics.update({
                    "converged": converged,
                    "random_intercept_variance": random_variance,
                    "warnings": warning_text,
                })
                break
            except Exception as exc:  # noqa: BLE001
                failures.append(f"MixedLM {method}: {exc}")

    if selected_model is None:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            try:
                candidate = smf.gee(
                    formula,
                    groups="participant_id",
                    data=work,
                    cov_struct=sm.cov_struct.Exchangeable(),
                    family=sm.families.Gaussian(),
                ).fit()
                selected_model = candidate
                model_type = "gee_exchangeable_fallback"
                diagnostics["warnings"] = " | ".join(str(item.message) for item in captured)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"GEE: {exc}")

    if selected_model is None:
        diagnostics.update({"status": "failed", "reason": " | ".join(failures)})
        return [], None, diagnostics

    diagnostics.update({
        "status": "fitted",
        "model_type": model_type,
        "fallback_reason": " | ".join(failures) if model_type.startswith("gee") else "",
    })
    confidence = selected_model.conf_int()
    rows = []
    for term, estimate in selected_model.params.items():
        rows.append({
            "model": model_name,
            "model_type": model_type,
            "term": term.removeprefix("z_"),
            "estimate": float(estimate),
            "std_error": float(selected_model.bse.get(term, np.nan)),
            "p_value": float(selected_model.pvalues.get(term, np.nan)),
            "ci_low": float(confidence.loc[term, 0]) if term in confidence.index else np.nan,
            "ci_high": float(confidence.loc[term, 1]) if term in confidence.index else np.nan,
            "n_rows": len(work),
            "n_participants": diagnostics["n_participants"],
            "aic": float(getattr(selected_model, "aic", np.nan)),
            "bic": float(getattr(selected_model, "bic", np.nan)),
        })
    return rows, selected_model, diagnostics


def repeated_model_specifications(frame: pd.DataFrame) -> dict[str, list[str]]:
    available = set(frame.columns)
    primary_terms = [term for term in [
        "daytime_use_within", "daytime_use_between",
        "prebed_use_within", "prebed_use_between",
        "postbed_use_within", "postbed_use_between",
        "day",
    ] if term in available and frame[term].notna().sum() >= 50]
    specifications: dict[str, list[str]] = {"primary_temporal": primary_terms}
    if (
        "sleep_quality_lag1_exact" in available
        and frame["sleep_quality_lag1_exact"].notna().sum() >= 100
    ):
        specifications["sensitivity_exact_previous_day_sleep"] = (
            primary_terms + ["sleep_quality_lag1_exact"]
        )
    app_terms = [term for term in [
        "social_prebed_use_within", "social_prebed_use_between",
        "social_postbed_use_within", "social_postbed_use_between",
        "game_prebed_use_within", "game_prebed_use_between",
        "game_postbed_use_within", "game_postbed_use_between",
        "video_prebed_use_within", "video_prebed_use_between",
        "video_postbed_use_within", "video_postbed_use_between",
        "day",
    ] if term in available and frame[term].notna().sum() >= 50]
    if len(app_terms) >= 4:
        specifications["app_specific_exploratory"] = app_terms
    return specifications


def fit_repeated_models(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    specifications = repeated_model_specifications(frame)

    coefficient_rows = []
    models: dict[str, Any] = {}
    diagnostic_rows = []
    for name, terms in specifications.items():
        rows, model, diagnostics = fit_one_repeated_model(frame, name, terms)
        coefficient_rows.extend(rows)
        diagnostic_rows.append(diagnostics)
        if model is not None:
            models[name] = model
    return pd.DataFrame(coefficient_rows), models, pd.DataFrame(diagnostic_rows)


def balanced_group_fold_ids(groups: pd.Series, n_splits: int, seed: int) -> pd.Series:
    groups = groups.astype("string")
    counts = groups.value_counts().rename_axis("group").reset_index(name="n")
    if len(counts) < n_splits:
        n_splits = len(counts)
    rng = np.random.default_rng(seed)
    counts["tie"] = rng.random(len(counts))
    counts = counts.sort_values(["n", "tie"], ascending=[False, True])
    fold_load = np.zeros(n_splits, dtype=int)
    assignment: dict[str, int] = {}
    for row in counts.itertuples(index=False):
        fold = int(np.argmin(fold_load))
        assignment[str(row.group)] = fold
        fold_load[fold] += int(row.n)
    return groups.map(assignment).astype(int)


def split_indices_from_fold_ids(fold_ids: pd.Series) -> list[tuple[np.ndarray, np.ndarray]]:
    splits = []
    values = fold_ids.to_numpy()
    for fold in sorted(pd.unique(values)):
        test = np.where(values == fold)[0]
        train = np.where(values != fold)[0]
        splits.append((train, test))
    return splits


def weighted_metrics(observed: np.ndarray, predicted: np.ndarray, weights: np.ndarray | None = None) -> dict[str, float]:
    observed = np.asarray(observed, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if observed.shape != predicted.shape:
        raise ValueError("Observed and predicted arrays must have identical shapes.")
    if observed.size == 0:
        return {"mae": np.nan, "rmse": np.nan, "r2": np.nan}
    if weights is None:
        weights = np.ones_like(observed, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if weights.shape != observed.shape:
        raise ValueError("Metric weights must have the same shape as the observations.")
    if not np.isfinite(weights).all() or (weights < 0).any() or float(weights.sum()) <= 0:
        raise ValueError("Metric weights must be finite, nonnegative, and sum to a positive value.")
    weights = weights / weights.sum()
    error = observed - predicted
    mae = float(np.sum(weights * np.abs(error)))
    rmse = float(np.sqrt(np.sum(weights * error**2)))
    mean_observed = float(np.sum(weights * observed))
    denominator = float(np.sum(weights * (observed - mean_observed) ** 2))
    r2 = float(1 - np.sum(weights * error**2) / denominator) if denominator > 0 else np.nan
    return {"mae": mae, "rmse": rmse, "r2": r2}


def participant_equal_observation_weights(participant_ids: pd.Series | np.ndarray) -> np.ndarray:
    """Give every participant equal total weight, irrespective of valid-day count."""
    ids = pd.Series(participant_ids, dtype="string")
    if ids.isna().any():
        raise ValueError("Participant-equal weighting requires nonmissing participant IDs.")
    counts = ids.value_counts(dropna=False)
    row_counts = ids.map(counts).to_numpy(dtype=float)
    if (row_counts <= 0).any() or not np.isfinite(row_counts).all():
        raise ValueError("Invalid participant observation counts for equal weighting.")
    return 1.0 / row_counts


def metric_weights_for_estimand(
    participant_ids: pd.Series | np.ndarray,
    evaluation_weighting: str,
    participant_multiplicity: pd.Series | None = None,
) -> np.ndarray | None:
    ids = pd.Series(participant_ids, dtype="string")
    if evaluation_weighting not in PREDICTION_EVALUATION_WEIGHTINGS:
        raise ValueError(f"Unknown prediction evaluation weighting: {evaluation_weighting}")
    if participant_multiplicity is None:
        multiplicity = np.ones(len(ids), dtype=float)
    else:
        multiplicity = ids.map(participant_multiplicity).fillna(0).to_numpy(dtype=float)
    if evaluation_weighting == "participant_day":
        return multiplicity if participant_multiplicity is not None else None
    equal_weights = participant_equal_observation_weights(ids)
    return equal_weights * multiplicity


def metrics_for_both_estimands(
    observed: np.ndarray,
    predicted: np.ndarray,
    participant_ids: pd.Series | np.ndarray,
) -> dict[str, dict[str, float]]:
    return {
        weighting: weighted_metrics(
            observed,
            predicted,
            metric_weights_for_estimand(participant_ids, weighting),
        )
        for weighting in PREDICTION_EVALUATION_WEIGHTINGS
    }


def fold_performance_rows(
    *,
    feature_set: str,
    model: str,
    fold: int,
    observed: pd.Series | np.ndarray,
    predicted: np.ndarray,
    participant_ids: pd.Series | np.ndarray,
    best_params: str,
) -> list[dict[str, Any]]:
    observed_array = np.asarray(observed, dtype=float)
    predicted_array = np.asarray(predicted, dtype=float)
    ids = pd.Series(participant_ids, dtype="string")
    metrics = metrics_for_both_estimands(observed_array, predicted_array, ids)
    rows = []
    for weighting, values in metrics.items():
        rows.append({
            "feature_set": feature_set,
            "model": model,
            "fold": fold,
            "evaluation_weighting": weighting,
            "estimand": (
                "random_participant_day" if weighting == "participant_day"
                else "equal_total_weight_per_participant"
            ),
            "n_test": len(observed_array),
            "n_test_participants": int(ids.nunique()),
            **values,
            "best_params": best_params,
        })
    return rows


def participant_prediction_losses(predictions: pd.DataFrame) -> pd.DataFrame:
    """Return participant-level OOF losses used by the participant-equal estimand."""
    if predictions.empty:
        return pd.DataFrame(columns=[
            "feature_set", "model", "participant_id", "observations",
            "mae", "mse", "rmse", "observed_mean", "predicted_mean",
        ])
    frame = predictions.copy()
    frame["absolute_error"] = (frame["observed"] - frame["predicted"]).abs()
    frame["squared_error"] = (frame["observed"] - frame["predicted"]) ** 2
    losses = frame.groupby(
        ["feature_set", "model", "participant_id"], as_index=False
    ).agg(
        observations=("row_index", "size"),
        mae=("absolute_error", "mean"),
        mse=("squared_error", "mean"),
        observed_mean=("observed", "mean"),
        predicted_mean=("predicted", "mean"),
    )
    losses["rmse"] = np.sqrt(losses["mse"])
    return losses[[
        "feature_set", "model", "participant_id", "observations",
        "mae", "mse", "rmse", "observed_mean", "predicted_mean",
    ]]


def bootstrap_prediction_metrics(
    predictions: pd.DataFrame,
    repetitions: int,
    seed: int,
) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(seed)
    for (feature_set, model), group in predictions.groupby(["feature_set", "model"]):
        participant_ids = group["participant_id"].astype("string").unique()
        observed = group["observed"].to_numpy(dtype=float)
        predicted = group["predicted"].to_numpy(dtype=float)
        for evaluation_weighting in PREDICTION_EVALUATION_WEIGHTINGS:
            point_weights = metric_weights_for_estimand(
                group["participant_id"], evaluation_weighting
            )
            point = weighted_metrics(observed, predicted, point_weights)
            bootstrap_values = {metric: [] for metric in point}
            for _ in range(repetitions):
                sampled = rng.choice(participant_ids, size=len(participant_ids), replace=True)
                multiplicity = pd.Series(sampled, dtype="string").value_counts()
                weights = metric_weights_for_estimand(
                    group["participant_id"], evaluation_weighting, multiplicity
                )
                metrics = weighted_metrics(observed, predicted, weights)
                for metric, value in metrics.items():
                    bootstrap_values[metric].append(value)
            for metric, value in point.items():
                values = np.asarray(bootstrap_values[metric], dtype=float)
                rows.append({
                    "feature_set": feature_set,
                    "model": model,
                    "evaluation_weighting": evaluation_weighting,
                    "estimand": (
                        "random_participant_day" if evaluation_weighting == "participant_day"
                        else "equal_total_weight_per_participant"
                    ),
                    "metric": metric,
                    "estimate": value,
                    "ci_low": float(np.nanquantile(values, 0.025)),
                    "ci_high": float(np.nanquantile(values, 0.975)),
                    "participants": len(participant_ids),
                    "observations": len(group),
                })
    return pd.DataFrame(rows)


def paired_model_comparisons(
    predictions: pd.DataFrame,
    repetitions: int,
    seed: int,
) -> pd.DataFrame:
    baseline = predictions[(predictions["feature_set"] == "baseline_total") & (predictions["model"] == "elastic_net")]
    extended = predictions[(predictions["feature_set"] == "extended") & (predictions["model"] == "elastic_net")]
    if baseline.empty or extended.empty:
        return pd.DataFrame()
    merged = baseline[["row_index", "participant_id", "observed", "predicted"]].merge(
        extended[["row_index", "predicted"]],
        on="row_index",
        suffixes=("_baseline", "_extended"),
        validate="one_to_one",
    )
    ids = merged["participant_id"].astype("string").unique()
    rng = np.random.default_rng(seed)
    rows = []
    for evaluation_weighting in PREDICTION_EVALUATION_WEIGHTINGS:
        point_weights = metric_weights_for_estimand(
            merged["participant_id"], evaluation_weighting
        )
        point_baseline = weighted_metrics(
            merged["observed"], merged["predicted_baseline"], point_weights
        )
        point_extended = weighted_metrics(
            merged["observed"], merged["predicted_extended"], point_weights
        )
        for metric in ("mae", "rmse", "r2"):
            differences = []
            for _ in range(repetitions):
                sampled = rng.choice(ids, size=len(ids), replace=True)
                multiplicity = pd.Series(sampled, dtype="string").value_counts()
                weights = metric_weights_for_estimand(
                    merged["participant_id"], evaluation_weighting, multiplicity
                )
                base_metric = weighted_metrics(
                    merged["observed"], merged["predicted_baseline"], weights
                )[metric]
                extended_metric = weighted_metrics(
                    merged["observed"], merged["predicted_extended"], weights
                )[metric]
                differences.append(extended_metric - base_metric)
            values = np.asarray(differences, dtype=float)
            rows.append({
                "comparison": "extended_elastic_minus_baseline_total_elastic",
                "evaluation_weighting": evaluation_weighting,
                "estimand": (
                    "random_participant_day" if evaluation_weighting == "participant_day"
                    else "equal_total_weight_per_participant"
                ),
                "metric": metric,
                "difference": point_extended[metric] - point_baseline[metric],
                "ci_low": float(np.nanquantile(values, 0.025)),
                "ci_high": float(np.nanquantile(values, 0.975)),
            })
    return pd.DataFrame(rows)


def feature_importance_interpretation_gate(
    fold_results: pd.DataFrame,
    predictions: pd.DataFrame,
    repetitions: int,
    seed: int,
) -> pd.DataFrame:
    columns = [
        "feature_set", "model", "evaluation_weighting",
        "mae_difference_vs_training_mean", "ci_low", "ci_high",
        "improved_outer_folds", "total_outer_folds", "performance_exceeds_comparator",
        "stable_across_outer_folds", "importance_interpretation_allowed", "gate_rule",
    ]
    if fold_results.empty or predictions.empty:
        return pd.DataFrame(columns=columns)
    evaluation_weighting = PRIMARY_PREDICTION_WEIGHTING
    comparator_predictions = predictions[
        (predictions["feature_set"] == "mean_only") & (predictions["model"] == "training_mean")
    ][["row_index", "participant_id", "observed", "predicted"]].rename(
        columns={"predicted": "predicted_comparator"}
    )
    comparator_folds = fold_results[
        (fold_results["feature_set"] == "mean_only")
        & (fold_results["model"] == "training_mean")
        & (fold_results["evaluation_weighting"] == evaluation_weighting)
    ][["fold", "mae"]].rename(columns={"mae": "comparator_mae"})
    rng = np.random.default_rng(seed)
    rows = []
    candidates = predictions[
        ~((predictions["feature_set"] == "mean_only") & (predictions["model"] == "training_mean"))
    ][["feature_set", "model"]].drop_duplicates()
    for candidate in candidates.itertuples(index=False):
        feature_set, model = candidate.feature_set, candidate.model
        model_predictions = predictions[
            (predictions["feature_set"] == feature_set) & (predictions["model"] == model)
        ][["row_index", "predicted"]].rename(columns={"predicted": "predicted_model"})
        merged = comparator_predictions.merge(model_predictions, on="row_index", how="inner", validate="one_to_one")
        if merged.empty:
            continue
        point_weights = metric_weights_for_estimand(
            merged["participant_id"], evaluation_weighting
        )
        point_model = weighted_metrics(
            merged["observed"], merged["predicted_model"], point_weights
        )["mae"]
        point_comparator = weighted_metrics(
            merged["observed"], merged["predicted_comparator"], point_weights
        )["mae"]
        participant_ids = merged["participant_id"].astype("string").unique()
        differences = []
        for _ in range(repetitions):
            sampled = rng.choice(participant_ids, size=len(participant_ids), replace=True)
            multiplicity = pd.Series(sampled, dtype="string").value_counts()
            weights = metric_weights_for_estimand(
                merged["participant_id"], evaluation_weighting, multiplicity
            )
            model_mae = weighted_metrics(
                merged["observed"], merged["predicted_model"], weights
            )["mae"]
            comparator_mae = weighted_metrics(
                merged["observed"], merged["predicted_comparator"], weights
            )["mae"]
            differences.append(model_mae - comparator_mae)
        difference_values = np.asarray(differences, dtype=float)
        ci_low = float(np.nanquantile(difference_values, 0.025))
        ci_high = float(np.nanquantile(difference_values, 0.975))

        model_folds = fold_results[
            (fold_results["feature_set"] == feature_set)
            & (fold_results["model"] == model)
            & (fold_results["evaluation_weighting"] == evaluation_weighting)
        ][["fold", "mae"]].rename(columns={"mae": "model_mae"})
        fold_comparison = comparator_folds.merge(model_folds, on="fold", how="inner", validate="one_to_one")
        improved_folds = int((fold_comparison["model_mae"] < fold_comparison["comparator_mae"]).sum())
        total_folds = int(len(fold_comparison))
        exceeds = bool(ci_high < 0)
        expected_folds = int(len(comparator_folds))
        stable = bool(total_folds == expected_folds and expected_folds > 0 and improved_folds == total_folds)
        rows.append({
            "feature_set": feature_set,
            "model": model,
            "evaluation_weighting": evaluation_weighting,
            "mae_difference_vs_training_mean": point_model - point_comparator,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "improved_outer_folds": improved_folds,
            "total_outer_folds": total_folds,
            "performance_exceeds_comparator": exceeds,
            "stable_across_outer_folds": stable,
            "importance_interpretation_allowed": bool(exceeds and stable),
            "gate_rule": (
                "participant-equal upper 95% participant-bootstrap MAE-difference bound < 0 "
                "and lower participant-equal MAE in every outer fold"
            ),
        })
    return pd.DataFrame(rows, columns=columns)


def select_training_features(
    training_frame: pd.DataFrame,
    requested: list[str],
    minimum_coverage: float,
) -> tuple[list[str], pd.DataFrame]:
    rows = []
    selected = []
    for column in requested:
        coverage = float(training_frame[column].notna().mean()) if column in training_frame else 0.0
        include = bool(column in training_frame and coverage >= minimum_coverage)
        if include:
            selected.append(column)
        rows.append({
            "feature": column,
            "training_coverage": coverage,
            "minimum_coverage": minimum_coverage,
            "selected": include,
            "selection_scope": "outer_training_rows_only",
        })
    return selected, pd.DataFrame(rows)


def make_elastic_pipeline(random_state: int) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("scaler", RobustScaler()),
        ("model", ElasticNet(max_iter=50000, random_state=random_state)),
    ])


def make_elastic_search(
    inner_splits: list[tuple[np.ndarray, np.ndarray]],
    options: dict[str, Any],
    quick: bool,
) -> GridSearchCV:
    parameter_grid = {
        "model__alpha": [0.01, 0.03, 0.1, 0.3] if quick else [0.003, 0.01, 0.03, 0.1, 0.3, 1.0],
        "model__l1_ratio": [0.1, 0.5, 0.9],
    }
    return GridSearchCV(
        make_elastic_pipeline(options["random_state"]),
        parameter_grid,
        cv=inner_splits,
        scoring="neg_mean_absolute_error",
        n_jobs=1,
        refit=True,
    )


def validate_oof_predictions(predictions: pd.DataFrame) -> None:
    required = {"row_index", "participant_id", "feature_set", "model", "fold", "observed", "predicted"}
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError(f"OOF predictions missing required columns: {missing}")
    duplicates = int(predictions.duplicated(["row_index", "feature_set", "model"]).sum())
    if duplicates:
        raise ValueError(f"OOF predictions contain {duplicates} duplicate row/model predictions.")
    participant_folds = predictions.groupby("participant_id")["fold"].nunique()
    if (participant_folds > 1).any():
        raise ValueError("OOF predictions assign at least one participant to multiple outer folds.")
    numeric = predictions[["observed", "predicted"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("OOF predictions contain non-finite observed or predicted values.")


def grouped_prediction(frame: pd.DataFrame, config: dict[str, Any], quick: bool) -> tuple[pd.DataFrame, ...]:
    options = config["analysis"]
    if "sleep_quality" not in frame:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty, empty, empty
    target = pd.to_numeric(frame["sleep_quality"], errors="coerce")
    valid_target = target.notna() & frame["participant_id"].notna()
    working = frame.loc[valid_target].copy()
    target = target.loc[valid_target]
    groups = working["participant_id"].astype("string")
    outer_n = min(options["group_cv_splits"], groups.nunique())
    if outer_n < 3:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty, empty, empty
    outer_fold_ids = balanced_group_fold_ids(groups, outer_n, options["random_state"])
    fold_audit = working[["participant_id", "day", "day_key"]].copy()
    fold_audit["outer_fold"] = outer_fold_ids.to_numpy()

    result_rows = []
    prediction_rows = []
    importance_rows = []
    feature_selection_rows = []
    for fold, (train_positions, test_positions) in enumerate(split_indices_from_fold_ids(outer_fold_ids), start=1):
        train_index = working.index[train_positions]
        test_index = working.index[test_positions]
        y_train = target.loc[train_index]
        y_test = target.loc[test_index]
        train_groups = groups.loc[train_index]
        test_groups = groups.loc[test_index]
        assert_disjoint_participants(train_groups, test_groups, f"outer fold {fold}")

        # Honest mean-only comparator.
        mean_prediction = np.repeat(float(y_train.mean()), len(y_test))
        result_rows.extend(fold_performance_rows(
            feature_set="mean_only",
            model="training_mean",
            fold=fold,
            observed=y_test,
            predicted=mean_prediction,
            participant_ids=groups.loc[test_index],
            best_params="{}",
        ))
        for index, observed, predicted in zip(test_index, y_test, mean_prediction):
            prediction_rows.append({
                "row_index": int(index), "participant_id": str(working.loc[index, "participant_id"]),
                "feature_set": "mean_only", "model": "training_mean", "fold": fold,
                "observed": float(observed), "predicted": float(predicted),
            })

        for feature_set, requested in PREDICTIVE_FEATURE_SETS.items():
            features, selection_audit = select_training_features(
                working.loc[train_index], requested, options["min_feature_coverage"]
            )
            selection_audit.insert(0, "feature_set", feature_set)
            selection_audit.insert(0, "outer_fold", fold)
            feature_selection_rows.extend(selection_audit.to_dict(orient="records"))
            if not features:
                continue
            x_train = working.loc[train_index, features]
            x_test = working.loc[test_index, features]
            inner_n = min(options["inner_cv_splits"], train_groups.nunique())
            if inner_n < 2:
                continue
            inner_fold_ids = balanced_group_fold_ids(
                train_groups,
                inner_n,
                options["random_state"] + fold * 101,
            )
            inner_splits = split_indices_from_fold_ids(inner_fold_ids)
            for inner_fold, (inner_train, inner_test) in enumerate(inner_splits, start=1):
                assert_disjoint_participants(
                    train_groups.iloc[inner_train],
                    train_groups.iloc[inner_test],
                    f"outer fold {fold}, inner fold {inner_fold}",
                )
            search = make_elastic_search(inner_splits, options, quick)
            search.fit(x_train, y_train)
            predicted = search.predict(x_test)
            result_rows.extend(fold_performance_rows(
                feature_set=feature_set,
                model="elastic_net",
                fold=fold,
                observed=y_test,
                predicted=predicted,
                participant_ids=groups.loc[test_index],
                best_params=json.dumps(search.best_params_),
            ))
            for index, observed, prediction in zip(test_index, y_test, predicted):
                prediction_rows.append({
                    "row_index": int(index), "participant_id": str(working.loc[index, "participant_id"]),
                    "feature_set": feature_set, "model": "elastic_net", "fold": fold,
                    "observed": float(observed), "predicted": float(prediction),
                })
            imputer = search.best_estimator_.named_steps["imputer"]
            transformed_names = imputer.get_feature_names_out(features)
            coefficients = search.best_estimator_.named_steps["model"].coef_
            for name, coefficient in zip(transformed_names, coefficients):
                importance_rows.append({
                    "feature_set": feature_set,
                    "model": "elastic_net",
                    "fold": fold,
                    "feature": str(name),
                    "importance": float(abs(coefficient)),
                    "signed_importance": float(coefficient),
                    "importance_type": "absolute_standardized_coefficient",
                })

            if feature_set == RANDOM_FOREST_FEATURE_SET:
                forest = Pipeline([
                    ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
                    ("model", RandomForestRegressor(
                        n_estimators=80 if quick else 500,
                        max_features="sqrt",
                        min_samples_leaf=8,
                        random_state=options["random_state"] + fold,
                        n_jobs=1,
                    )),
                ])
                forest.fit(x_train, y_train)
                forest_prediction = forest.predict(x_test)
                result_rows.extend(fold_performance_rows(
                    feature_set=feature_set,
                    model="random_forest_fixed",
                    fold=fold,
                    observed=y_test,
                    predicted=forest_prediction,
                    participant_ids=groups.loc[test_index],
                    best_params=json.dumps({
                        "n_estimators": 80 if quick else 500,
                        "max_features": "sqrt",
                        "min_samples_leaf": 8,
                    }),
                ))
                for index, observed, prediction in zip(test_index, y_test, forest_prediction):
                    prediction_rows.append({
                        "row_index": int(index), "participant_id": str(working.loc[index, "participant_id"]),
                        "feature_set": feature_set, "model": "random_forest_fixed", "fold": fold,
                        "observed": float(observed), "predicted": float(prediction),
                    })
                permutation = permutation_importance(
                    forest,
                    x_test,
                    y_test,
                    scoring="neg_mean_absolute_error",
                    n_repeats=5 if quick else 20,
                    random_state=options["random_state"] + fold,
                    n_jobs=1,
                )
                for feature, importance, standard_deviation in zip(
                    features, permutation.importances_mean, permutation.importances_std
                ):
                    importance_rows.append({
                        "feature_set": feature_set,
                        "model": "random_forest_fixed",
                        "fold": fold,
                        "feature": feature,
                        "importance": float(importance),
                        "signed_importance": np.nan,
                        "importance_sd": float(standard_deviation),
                        "importance_type": "test_permutation_mae_improvement",
                    })

    fold_results = pd.DataFrame(result_rows)
    predictions = pd.DataFrame(prediction_rows)
    validate_oof_predictions(predictions)
    importances = pd.DataFrame(importance_rows)
    feature_selection = pd.DataFrame(feature_selection_rows)
    repetitions = min(100, options["bootstrap_repetitions"]) if quick else options["bootstrap_repetitions"]
    metric_intervals = bootstrap_prediction_metrics(
        predictions, repetitions, options["random_state"] + 5000
    ) if not predictions.empty else pd.DataFrame()
    comparisons = paired_model_comparisons(
        predictions, repetitions, options["random_state"] + 7000
    ) if not predictions.empty else pd.DataFrame()
    return fold_results, predictions, metric_intervals, comparisons, importances, fold_audit, feature_selection


def calibration_tables(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries = []
    bins = []
    for (feature_set, model), group in predictions.groupby(["feature_set", "model"]):
        if group["predicted"].nunique() > 1:
            slope, intercept = np.polyfit(group["predicted"], group["observed"], 1)
        else:
            slope, intercept = np.nan, np.nan
        summaries.append({
            "feature_set": feature_set,
            "model": model,
            "calibration_intercept": float(intercept),
            "calibration_slope": float(slope),
            "observed_mean": float(group["observed"].mean()),
            "predicted_mean": float(group["predicted"].mean()),
        })
        try:
            group = group.copy()
            group["prediction_bin"] = pd.qcut(group["predicted"], q=min(10, group["predicted"].nunique()), duplicates="drop")
            binned = group.groupby("prediction_bin", observed=True).agg(
                n=("observed", "size"),
                observed_mean=("observed", "mean"),
                predicted_mean=("predicted", "mean"),
            ).reset_index(drop=True)
            binned.insert(0, "model", model)
            binned.insert(0, "feature_set", feature_set)
            bins.append(binned)
        except ValueError:
            continue
    return pd.DataFrame(summaries), pd.concat(bins, ignore_index=True) if bins else pd.DataFrame()


def make_figures(
    daily: pd.DataFrame,
    clustered: pd.DataFrame,
    profile_columns: list[str],
    predictions: pd.DataFrame,
    metric_intervals: pd.DataFrame,
) -> None:
    for column in [name for name in ("total_use", "daytime_use", "prebed_use", "postbed_use") if name in daily]:
        figure, axis = plt.subplots(figsize=(6.4, 3.9))
        axis.hist(daily[column].dropna(), bins=30)
        axis.set_title(column.replace("_", " ").title())
        axis.set_xlabel("Hours")
        axis.set_ylabel("Participant-days")
        figure.tight_layout()
        figure.savefig(FIGURES / f"distribution_{column}.png", dpi=300, bbox_inches="tight")
        plt.close(figure)

    if profile_columns and "cluster" in clustered and clustered["cluster"].notna().any():
        columns = profile_columns[:10]
        means = clustered.dropna(subset=["cluster"]).groupby("cluster")[columns].mean()
        standardized = (means - means.mean()) / means.std(ddof=0).replace(0, 1)
        figure, axis = plt.subplots(figsize=(9.2, 4.8))
        for cluster, row in standardized.iterrows():
            axis.plot(range(len(columns)), row.to_numpy(), marker="o", label=f"Profile {int(cluster)}")
        axis.axhline(0, linewidth=0.8)
        axis.set_xticks(range(len(columns)))
        axis.set_xticklabels(
            [column.replace("_mean", "").replace("_sd", " variability").replace("_", " ") for column in columns],
            rotation=38,
            ha="right",
        )
        axis.set_ylabel("Standardized profile mean")
        axis.legend()
        figure.tight_layout()
        figure.savefig(FIGURES / "temporal_profiles.png", dpi=300, bbox_inches="tight")
        plt.close(figure)

    extended = predictions[(predictions["feature_set"] == "extended") & (predictions["model"] == "elastic_net")]
    if not extended.empty:
        figure, axis = plt.subplots(figsize=(5.4, 5.4))
        axis.scatter(extended["observed"], extended["predicted"], alpha=0.35)
        low = min(extended["observed"].min(), extended["predicted"].min())
        high = max(extended["observed"].max(), extended["predicted"].max())
        axis.plot([low, high], [low, high], linestyle="--")
        axis.set_xlabel("Observed sleep quality")
        axis.set_ylabel("Out-of-fold predicted sleep quality")
        figure.tight_layout()
        figure.savefig(FIGURES / "observed_vs_predicted.png", dpi=300, bbox_inches="tight")
        plt.close(figure)

    for evaluation_weighting in PREDICTION_EVALUATION_WEIGHTINGS:
        mae = metric_intervals[
            (metric_intervals["metric"] == "mae")
            & (metric_intervals["evaluation_weighting"] == evaluation_weighting)
        ].copy()
        if mae.empty:
            continue
        labels = (mae["feature_set"] + "\n" + mae["model"]).tolist()
        yerr = np.vstack([mae["estimate"] - mae["ci_low"], mae["ci_high"] - mae["estimate"]])
        figure, axis = plt.subplots(figsize=(8.0, 4.2))
        axis.errorbar(range(len(mae)), mae["estimate"], yerr=yerr, fmt="o", capsize=4)
        axis.set_xticks(range(len(mae)))
        axis.set_xticklabels(labels, rotation=30, ha="right")
        label = "Participant-day" if evaluation_weighting == "participant_day" else "Participant-equal"
        axis.set_ylabel(f"{label} OOF MAE (95% participant-bootstrap CI)")
        figure.tight_layout()
        output = FIGURES / f"predictive_mae_comparison_{evaluation_weighting}.png"
        figure.savefig(output, dpi=300, bbox_inches="tight")
        if evaluation_weighting == PRIMARY_PREDICTION_WEIGHTING:
            figure.savefig(FIGURES / "predictive_mae_comparison.png", dpi=300, bbox_inches="tight")
        plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run clustering, repeated-measures, and predictive analyses.")
    parser.add_argument("--quick", action="store_true", help="Use fewer repetitions for code validation.")
    args = parser.parse_args()
    ensure_directories()
    config = load_config()
    validate_preregistered_config(config)
    json_dump(TABLES / "analysis_specification_manifest.json", {
        "status": "locked_before_analysis",
        "preregistered_analysis": PREREGISTERED_ANALYSIS,
        "predictive_feature_sets": PREDICTIVE_FEATURE_SETS,
        "elastic_net_role": "primary_predictive_model",
        "random_forest_role": "prespecified_nonlinear_benchmark_extended_only",
        "random_forest_feature_set": RANDOM_FOREST_FEATURE_SET,
        "prediction_evaluation_weightings": list(PREDICTION_EVALUATION_WEIGHTINGS),
        "primary_prediction_weighting": PRIMARY_PREDICTION_WEIGHTING,
        "feature_importance_gate": (
            "participant-equal upper 95% participant-bootstrap OOF MAE-difference bound versus training mean < 0 "
            "and lower participant-equal MAE in every outer fold"
        ),
        "quick_mode": bool(args.quick),
    })
    daily_path = PROCESSED / "daily_analytic.csv"
    profile_path = PROCESSED / "participant_profiles.csv"
    if not daily_path.exists() or not profile_path.exists():
        raise FileNotFoundError("Prepared data are missing. Run src/inspect_and_prepare.py first.")
    daily = pd.read_csv(daily_path)
    profiles = pd.read_csv(profile_path)
    validate_analysis_input(daily)
    numeric_descriptives(daily).to_csv(TABLES / "descriptive_statistics.csv", index=False)

    selection, clustered, profile_table, profile_columns, selected_k, cluster_model = cluster_profiles(
        profiles, config, args.quick
    )
    selection.to_csv(TABLES / "cluster_selection.csv", index=False)
    clustered.to_csv(PROCESSED / "participant_profiles_with_clusters.csv", index=False)
    profile_table.to_csv(TABLES / "cluster_profiles.csv", index=False)
    cluster_status = (cluster_model or {}).get("analysis_status", {
        "status": "not_estimable",
        "reason": "cluster_model_metadata_missing",
        "selected_k": None,
    })
    json_dump(TABLES / "cluster_analysis_status.json", cluster_status)
    if cluster_model is not None:
        serializable = {key: value for key, value in cluster_model.items() if key != "distance"}
        dump(serializable, MODELS / "pam_gower_model.joblib")

    daily = daily.merge(clustered[["participant_id", "cluster"]], on="participant_id", how="left", validate="many_to_one")
    coefficients, repeated_models, diagnostics = fit_repeated_models(daily)
    coefficients.to_csv(TABLES / "repeated_model_coefficients.csv", index=False)
    diagnostics.to_csv(TABLES / "repeated_model_diagnostics.csv", index=False)
    for name, model in repeated_models.items():
        (TABLES / f"repeated_model_{name}_summary.txt").write_text(str(model.summary()), encoding="utf-8")

    prediction_outputs = grouped_prediction(daily, config, args.quick)
    fold_results, predictions, metric_intervals, comparisons, importances, fold_audit, feature_selection = prediction_outputs
    fold_results.to_csv(TABLES / "predictive_performance_folds.csv", index=False)
    predictions.to_csv(TABLES / "out_of_fold_predictions.csv", index=False)
    participant_losses = participant_prediction_losses(predictions)
    participant_losses.to_csv(TABLES / "predictive_participant_losses.csv", index=False)
    metric_intervals.to_csv(TABLES / "predictive_performance.csv", index=False)
    comparisons.to_csv(TABLES / "predictive_model_comparisons.csv", index=False)
    importances.to_csv(TABLES / "feature_importance_outer_folds.csv", index=False)
    fold_audit.to_csv(TABLES / "outer_fold_assignments.csv", index=False)
    feature_selection.to_csv(TABLES / "predictive_feature_selection.csv", index=False)
    repetitions = min(100, config["analysis"]["bootstrap_repetitions"]) if args.quick else config["analysis"]["bootstrap_repetitions"]
    importance_gate = feature_importance_interpretation_gate(
        fold_results, predictions, repetitions, config["analysis"]["random_state"] + 9000
    )
    importance_gate.to_csv(TABLES / "feature_importance_interpretation_gate.csv", index=False)
    summary_columns = [
        "feature_set", "model", "feature", "importance_type", "importance_mean", "importance_sd", "folds"
    ]
    if not importances.empty:
        raw_importance_summary = importances.groupby(
            ["feature_set", "model", "feature", "importance_type"], as_index=False
        ).agg(
            importance_mean=("importance", "mean"),
            importance_sd=("importance", "std"),
            folds=("fold", "nunique"),
        )
    else:
        raw_importance_summary = pd.DataFrame(columns=summary_columns)
    raw_importance_summary.to_csv(TABLES / "feature_importance_audit_summary.csv", index=False)
    allowed = importance_gate[importance_gate["importance_interpretation_allowed"]][["feature_set", "model"]]
    if not raw_importance_summary.empty and not allowed.empty:
        interpretable_importance = raw_importance_summary.merge(
            allowed, on=["feature_set", "model"], how="inner", validate="many_to_one"
        )
    else:
        interpretable_importance = pd.DataFrame(columns=summary_columns)
    interpretable_importance.to_csv(TABLES / "feature_importance_summary.csv", index=False)

    calibration, calibration_bins = calibration_tables(predictions) if not predictions.empty else (pd.DataFrame(), pd.DataFrame())
    calibration.to_csv(TABLES / "prediction_calibration.csv", index=False)
    calibration_bins.to_csv(TABLES / "prediction_calibration_bins.csv", index=False)
    make_figures(daily, clustered, profile_columns, predictions, metric_intervals)

    summary = {
        "participants": int(daily["participant_id"].nunique()),
        "participant_days": int(len(daily)),
        "valid_primary_days": int(daily["valid_primary_day"].fillna(False).sum()) if "valid_primary_day" in daily else None,
        "sleep_assessments": int(daily["sleep_quality"].notna().sum()),
        "selected_k": int(selected_k) if selected_k is not None else None,
        "cluster_solution_meets_thresholds": selected_k is not None,
        "cluster_analysis_status": cluster_status.get("status"),
        "cluster_analysis_reason": cluster_status.get("reason"),
        "cluster_candidate_solutions_evaluated": cluster_status.get("candidate_solutions_evaluated", 0),
        "repeated_models_fitted": list(repeated_models),
        "predictive_model_fold_results": int(len(fold_results)),
        "prediction_evaluation_weightings": list(PREDICTION_EVALUATION_WEIGHTINGS),
        "primary_prediction_weighting": PRIMARY_PREDICTION_WEIGHTING,
        "quick_mode": bool(args.quick),
        "feature_importance_models_passing_gate": int(importance_gate["importance_interpretation_allowed"].sum()),
    }
    json_dump(TABLES / "run_summary.json", summary)
    LOGGER.info("Analysis completed: %s", json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
