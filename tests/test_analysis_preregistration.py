from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common import load_config  # noqa: E402
import run_analysis as run_analysis_module  # noqa: E402
import generate_report as generate_report_module  # noqa: E402
from run_analysis import (  # noqa: E402
    PREDICTIVE_FEATURE_SETS,
    PREREGISTERED_ANALYSIS,
    RANDOM_FOREST_FEATURE_SET,
    apply_within_participant_profile_missingness,
    assert_disjoint_participants,
    bootstrap_prediction_metrics,
    calibration_tables,
    cluster_candidate_passes,
    construct_name,
    construct_weights,
    feature_importance_interpretation_gate,
    fit_one_repeated_model,
    gower_numeric_distance,
    make_elastic_pipeline,
    make_elastic_search,
    metrics_for_both_estimands,
    paired_model_comparisons,
    participant_equal_observation_weights,
    participant_prediction_losses,
    profile_candidate_columns,
    prune_correlated_features,
    repeated_model_specifications,
    select_accepted_cluster_k,
    select_training_features,
    split_indices_from_fold_ids,
    validate_analysis_input,
    validate_oof_predictions,
    validate_preregistered_config,
    weighted_metrics,
)


def test_preregistered_configuration_is_fail_closed() -> None:
    config = load_config()
    validate_preregistered_config(config)
    assert {key: config["analysis"][key] for key in PREREGISTERED_ANALYSIS} == PREREGISTERED_ANALYSIS
    altered = copy.deepcopy(config)
    altered["analysis"]["min_silhouette"] = 0.24
    with pytest.raises(ValueError, match="Preregistered analysis settings changed"):
        validate_preregistered_config(altered)


def test_participant_day_is_unique_analysis_unit() -> None:
    valid = pd.DataFrame({"participant_id": ["P1", "P1"], "day_key": ["n:1", "n:2"], "sleep_quality": [4, 5]})
    validate_analysis_input(valid)
    duplicated = pd.concat([valid, valid.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate participant-day"):
        validate_analysis_input(duplicated)


def test_sleep_quality_is_never_a_profile_input() -> None:
    frame = pd.DataFrame(columns=["total_use_mean", "total_use_sd", "sleep_quality_mean", "sleep_quality_sd"])
    selected = profile_candidate_columns(frame)
    assert selected == ["total_use_mean", "total_use_sd"]


def test_five_valid_days_and_within_participant_feature_coverage_are_enforced() -> None:
    profiles = pd.DataFrame({
        "participant_id": ["P1", "P2"],
        "n_observed_days": [5, 10],
        "n_valid_primary_days": [5, 4],
        "total_use_n": [3, 10],
        "total_use_mean": [4.0, 5.0],
        "total_use_sd": [1.0, 1.2],
    })
    profiles["eligible_for_profiles"] = profiles["n_valid_primary_days"] >= 5
    eligible = profiles[profiles["eligible_for_profiles"]]
    masked, audit = apply_within_participant_profile_missingness(
        eligible, ["total_use_mean", "total_use_sd"], maximum_missing_fraction=0.30
    )
    assert len(eligible) == 1
    assert masked[["total_use_mean", "total_use_sd"]].isna().all().all()
    assert (audit["minimum_within_participant_coverage"] == 0.70).all()


def test_gower_uses_only_jointly_observed_variables() -> None:
    values = np.array([[0.0, np.nan], [1.0, 0.0], [np.nan, 0.0], [np.nan, np.nan]])
    distance = gower_numeric_distance(values, range_quantiles=(0.0, 1.0))
    assert distance[0, 1] == pytest.approx(1.0)
    assert distance[1, 2] == pytest.approx(0.0)
    assert distance[0, 2] == pytest.approx(1.0)
    assert distance[0, 3] == pytest.approx(1.0)


def test_construct_groups_receive_equal_total_weights() -> None:
    columns = ["total_use_mean", "prebed_use_mean", "total_use_sd", "social_share_mean", "game_share_mean"]
    weights = construct_weights(columns)
    totals = {}
    for column, weight in zip(columns, weights):
        totals[construct_name(column)] = totals.get(construct_name(column), 0.0) + weight
    assert set(totals) == {"intensity", "timing", "variability", "composition"}
    assert all(value == pytest.approx(0.25) for value in totals.values())


def test_cluster_candidate_range_and_all_acceptance_thresholds_are_locked() -> None:
    options = load_config()["analysis"]
    assert list(range(options["cluster_k_min"], options["cluster_k_max"] + 1)) == [2, 3, 4, 5, 6]
    assert options["min_cluster_fraction"] == 0.10
    assert options["min_silhouette"] == 0.25
    assert options["min_stability_ari"] == 0.75
    assert cluster_candidate_passes(0.10, 0.25, 0.75, options)
    assert not cluster_candidate_passes(0.099, 0.30, 0.80, options)
    assert not cluster_candidate_passes(0.20, 0.249, 0.80, options)
    assert not cluster_candidate_passes(0.20, 0.30, 0.749, options)


def test_no_cluster_solution_is_selected_when_no_candidate_passes() -> None:
    selection = pd.DataFrame({
        "k": [2, 3, 4, 5, 6],
        "silhouette": [0.3] * 5,
        "median_subsample_ari": [0.8] * 5,
        "passes_all_thresholds": [False] * 5,
    })
    assert select_accepted_cluster_k(selection) is None


def test_redundant_features_are_pruned_within_construct_without_outcome() -> None:
    frame = pd.DataFrame({
        "total_use_mean": np.arange(20, dtype=float),
        "daytime_use_mean": np.arange(20, dtype=float) * 2,
        "prebed_use_mean": np.linspace(0, 1, 20),
        "sleep_quality_mean": np.linspace(7, 1, 20),
    })
    retained, audit = prune_correlated_features(
        frame, ["total_use_mean", "daytime_use_mean", "prebed_use_mean"], threshold=0.92
    )
    assert len({"total_use_mean", "daytime_use_mean"} & set(retained)) == 1
    assert "prebed_use_mean" in retained
    assert "sleep_quality_mean" not in audit.astype(str).to_string()


def test_explanatory_specifications_have_within_between_and_role_labels() -> None:
    rows = 120
    frame = pd.DataFrame({
        "daytime_use_within": np.arange(rows), "daytime_use_between": np.arange(rows),
        "prebed_use_within": np.arange(rows), "prebed_use_between": np.arange(rows),
        "postbed_use_within": np.arange(rows), "postbed_use_between": np.arange(rows),
        "day": np.tile(np.arange(1, 7), 20), "sleep_quality_lag1_exact": np.arange(rows),
        "social_prebed_use_within": np.arange(rows), "social_prebed_use_between": np.arange(rows),
        "game_prebed_use_within": np.arange(rows), "game_prebed_use_between": np.arange(rows),
    })
    specifications = repeated_model_specifications(frame)
    primary = specifications["primary_temporal"]
    for prefix in ("daytime_use", "prebed_use", "postbed_use"):
        assert f"{prefix}_within" in primary
        assert f"{prefix}_between" in primary
    assert "sensitivity_exact_previous_day_sleep" in specifications
    assert "sleep_quality_lag1_exact" in specifications["sensitivity_exact_previous_day_sleep"]
    assert "sleep_quality_lag1" not in {
        term for terms in specifications.values() for term in terms
    }
    assert "app_specific_exploratory" in specifications


class _FakeRepeatedResult:
    converged = True
    cov_re = np.array([[1.0]])
    aic = 1.0
    bic = 2.0

    def __init__(self) -> None:
        self.params = pd.Series({"Intercept": 4.0, "z_x": 0.1, "z_y": -0.1})
        self.bse = pd.Series({"Intercept": 0.1, "z_x": 0.05, "z_y": 0.05})
        self.pvalues = pd.Series({"Intercept": 0.0, "z_x": 0.1, "z_y": 0.1})

    def conf_int(self) -> pd.DataFrame:
        return pd.DataFrame({0: self.params - 0.2, 1: self.params + 0.2})


def _repeated_fixture() -> pd.DataFrame:
    return pd.DataFrame({
        "participant_id": [f"P{i:02d}" for i in range(20) for _ in range(5)],
        "sleep_quality": np.tile([3.0, 4.0, 5.0, 6.0, 7.0], 20),
        "x": np.arange(100, dtype=float),
        "y": np.sin(np.arange(100, dtype=float)),
    })


def test_primary_repeated_model_uses_participant_random_intercept_before_any_gee(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"mixed": 0, "gee": 0}

    class _Mixed:
        def fit(self, **kwargs):
            return _FakeRepeatedResult()

    def fake_mixedlm(formula, data, groups):
        calls["mixed"] += 1
        assert groups.equals(data["participant_id"])
        return _Mixed()

    def fake_gee(*args, **kwargs):
        calls["gee"] += 1
        raise AssertionError("GEE must not be called after an accepted MixedLM fit")

    monkeypatch.setattr(run_analysis_module.smf, "mixedlm", fake_mixedlm)
    monkeypatch.setattr(run_analysis_module.smf, "gee", fake_gee)
    _, _, diagnostics = fit_one_repeated_model(_repeated_fixture(), "primary_temporal", ["x", "y"])
    assert diagnostics["model_type"] == "mixedlm_lbfgs"
    assert calls == {"mixed": 1, "gee": 0}


def test_gee_is_transparent_fallback_only_after_mixed_model_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"mixed": 0, "gee": 0}

    class _FailingMixed:
        def fit(self, **kwargs):
            raise RuntimeError("planned mixed failure")

    class _GEE:
        def fit(self):
            return _FakeRepeatedResult()

    def fake_mixedlm(*args, **kwargs):
        calls["mixed"] += 1
        return _FailingMixed()

    def fake_gee(*args, **kwargs):
        calls["gee"] += 1
        return _GEE()

    monkeypatch.setattr(run_analysis_module.smf, "mixedlm", fake_mixedlm)
    monkeypatch.setattr(run_analysis_module.smf, "gee", fake_gee)
    _, _, diagnostics = fit_one_repeated_model(_repeated_fixture(), "primary_temporal", ["x", "y"])
    assert calls == {"mixed": 2, "gee": 1}
    assert diagnostics["model_type"] == "gee_exchangeable_fallback"
    assert "planned mixed failure" in diagnostics["fallback_reason"]


def test_predictive_roles_and_feature_sets_are_prespecified() -> None:
    assert PREDICTIVE_FEATURE_SETS["baseline_total"] == ["total_use"]
    assert PREDICTIVE_FEATURE_SETS["temporal"] == ["daytime_use", "prebed_use", "postbed_use"]
    assert "extended" in PREDICTIVE_FEATURE_SETS
    assert RANDOM_FOREST_FEATURE_SET == "extended"
    assert "sleep_quality" not in {feature for features in PREDICTIVE_FEATURE_SETS.values() for feature in features}


def test_prediction_preprocessing_pipeline_contract() -> None:
    pipeline = make_elastic_pipeline(random_state=42)
    assert isinstance(pipeline.named_steps["imputer"], SimpleImputer)
    assert pipeline.named_steps["imputer"].strategy == "median"
    assert pipeline.named_steps["imputer"].add_indicator
    assert isinstance(pipeline.named_steps["scaler"], RobustScaler)
    assert pipeline.named_steps["model"].__class__.__name__ == "ElasticNet"


def test_feature_coverage_selection_uses_training_rows_only() -> None:
    training = pd.DataFrame({"always": [1.0, 2.0, 3.0], "test_only": [np.nan, np.nan, np.nan]})
    selected, audit = select_training_features(training, ["always", "test_only"], minimum_coverage=0.30)
    assert selected == ["always"]
    assert set(audit["selection_scope"]) == {"outer_training_rows_only"}


def test_hyperparameter_selection_is_bound_to_grouped_inner_splits() -> None:
    inner_splits = [(np.array([0, 1]), np.array([2, 3])), (np.array([2, 3]), np.array([0, 1]))]
    search = make_elastic_search(inner_splits, load_config()["analysis"], quick=False)
    assert search.cv is inner_splits
    assert search.scoring == "neg_mean_absolute_error"
    assert search.refit is True
    assert search.param_grid["model__alpha"] == [0.003, 0.01, 0.03, 0.1, 0.3, 1.0]
    assert search.param_grid["model__l1_ratio"] == [0.1, 0.5, 0.9]


def test_group_splits_are_disjoint_and_leakage_assertion_fails_closed() -> None:
    fold_ids = pd.Series([0, 0, 1, 1, 2, 2])
    groups = pd.Series(["A", "A", "B", "B", "C", "C"])
    for train, test in split_indices_from_fold_ids(fold_ids):
        assert_disjoint_participants(groups.iloc[train], groups.iloc[test], "test")
    with pytest.raises(RuntimeError, match="Participant leakage"):
        assert_disjoint_participants(pd.Series(["A", "B"]), pd.Series(["B", "C"]), "test")


def _prediction_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    prediction_rows = []
    fold_rows = []
    for fold, participant in enumerate(["P1", "P2", "P3", "P4", "P5"], start=1):
        observed = float(fold)
        for feature_set, model, predicted in [
            ("mean_only", "training_mean", observed + 2.0),
            ("baseline_total", "elastic_net", observed + 1.0),
            ("extended", "elastic_net", observed),
            ("extended", "random_forest_fixed", observed + 0.5),
        ]:
            prediction_rows.append({
                "row_index": fold, "participant_id": participant, "feature_set": feature_set,
                "model": model, "fold": fold, "observed": observed, "predicted": predicted,
            })
            metrics = weighted_metrics(np.array([observed]), np.array([predicted]))
            for evaluation_weighting in ("participant_day", "participant_equal"):
                fold_rows.append({
                    "feature_set": feature_set, "model": model, "fold": fold,
                    "evaluation_weighting": evaluation_weighting, **metrics
                })
    return pd.DataFrame(fold_rows), pd.DataFrame(prediction_rows)


def test_oof_metrics_and_paired_participant_bootstrap_comparison() -> None:
    _, predictions = _prediction_fixture()
    validate_oof_predictions(predictions)
    intervals = bootstrap_prediction_metrics(predictions, repetitions=50, seed=1)
    assert set(intervals["metric"]) == {"mae", "rmse", "r2"}
    assert set(intervals["evaluation_weighting"]) == {"participant_day", "participant_equal"}
    assert {"estimate", "ci_low", "ci_high", "participants", "observations"} <= set(intervals.columns)
    comparisons = paired_model_comparisons(predictions, repetitions=50, seed=1)
    assert set(comparisons["metric"]) == {"mae", "rmse", "r2"}
    assert set(comparisons["evaluation_weighting"]) == {"participant_day", "participant_equal"}
    assert (comparisons.loc[comparisons["metric"].isin(["mae", "rmse"]), "difference"] < 0).all()
    calibration, bins = calibration_tables(predictions)
    assert {"calibration_intercept", "calibration_slope"} <= set(calibration.columns)
    assert not bins.empty


def test_participant_equal_metrics_do_not_overweight_adolescents_with_more_days() -> None:
    participant_ids = pd.Series(["P_LONG"] * 10 + ["P_SHORT"])
    observed = np.zeros(11, dtype=float)
    predicted = np.array([0.0] * 10 + [10.0])
    metrics = metrics_for_both_estimands(observed, predicted, participant_ids)
    assert metrics["participant_day"]["mae"] == pytest.approx(10.0 / 11.0)
    assert metrics["participant_equal"]["mae"] == pytest.approx(5.0)
    weights = participant_equal_observation_weights(participant_ids)
    totals = pd.DataFrame({"participant_id": participant_ids, "weight": weights}).groupby("participant_id")["weight"].sum()
    assert totals.loc["P_LONG"] == pytest.approx(totals.loc["P_SHORT"])


def test_dual_estimand_bootstrap_point_estimates_match_direct_recalculation() -> None:
    predictions = pd.DataFrame({
        "row_index": range(6),
        "participant_id": ["P1", "P1", "P1", "P1", "P2", "P2"],
        "feature_set": ["baseline_total"] * 6,
        "model": ["elastic_net"] * 6,
        "fold": [1, 1, 1, 1, 2, 2],
        "observed": [1, 2, 3, 4, 5, 6],
        "predicted": [1, 2, 3, 4, 0, 0],
    })
    intervals = bootstrap_prediction_metrics(predictions, repetitions=20, seed=7)
    mae = intervals[intervals["metric"] == "mae"].set_index("evaluation_weighting")["estimate"]
    direct = metrics_for_both_estimands(
        predictions["observed"].to_numpy(),
        predictions["predicted"].to_numpy(),
        predictions["participant_id"],
    )
    assert mae.loc["participant_day"] == pytest.approx(direct["participant_day"]["mae"])
    assert mae.loc["participant_equal"] == pytest.approx(direct["participant_equal"]["mae"])
    assert mae.loc["participant_equal"] > mae.loc["participant_day"]


def test_participant_loss_table_aggregates_to_participant_equal_mae_and_rmse() -> None:
    predictions = pd.DataFrame({
        "row_index": range(5),
        "participant_id": ["P1", "P1", "P1", "P2", "P2"],
        "feature_set": ["extended"] * 5,
        "model": ["elastic_net"] * 5,
        "fold": [1, 1, 1, 2, 2],
        "observed": [1.0, 2.0, 3.0, 4.0, 5.0],
        "predicted": [1.0, 2.0, 3.0, 0.0, 0.0],
    })
    losses = participant_prediction_losses(predictions)
    metrics = metrics_for_both_estimands(
        predictions["observed"].to_numpy(), predictions["predicted"].to_numpy(), predictions["participant_id"]
    )["participant_equal"]
    assert losses["mae"].mean() == pytest.approx(metrics["mae"])
    assert np.sqrt(losses["mse"].mean()) == pytest.approx(metrics["rmse"])
    assert set(losses["participant_id"]) == {"P1", "P2"}


def test_oof_integrity_rejects_duplicate_predictions_and_participant_fold_leakage() -> None:
    _, predictions = _prediction_fixture()
    duplicate = pd.concat([predictions, predictions.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate row/model"):
        validate_oof_predictions(duplicate)
    leaked = predictions.copy()
    leaked.loc[leaked.index[0], "fold"] = 99
    with pytest.raises(ValueError, match="multiple outer folds"):
        validate_oof_predictions(leaked)


def test_report_reader_treats_empty_cluster_table_as_no_cluster_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cluster_selection.csv").write_bytes(b"")
    monkeypatch.setattr(generate_report_module, "TABLES", tmp_path)
    assert generate_report_module.read_csv("cluster_selection.csv").empty


def test_feature_importance_gate_requires_comparator_superiority_and_every_fold_stability() -> None:
    folds, predictions = _prediction_fixture()
    gate = feature_importance_interpretation_gate(folds, predictions, repetitions=100, seed=2)
    extended = gate[(gate["feature_set"] == "extended") & (gate["model"] == "elastic_net")].iloc[0]
    assert bool(extended["performance_exceeds_comparator"])
    assert bool(extended["stable_across_outer_folds"])
    assert bool(extended["importance_interpretation_allowed"])
    folds.loc[
        (folds["feature_set"] == "extended") & (folds["model"] == "elastic_net") & (folds["fold"] == 1),
        "mae",
    ] = 3.0
    unstable = feature_importance_interpretation_gate(folds, predictions, repetitions=50, seed=3)
    row = unstable[(unstable["feature_set"] == "extended") & (unstable["model"] == "elastic_net")].iloc[0]
    assert not bool(row["stable_across_outer_folds"])
    assert not bool(row["importance_interpretation_allowed"])
