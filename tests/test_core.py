from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from inspect_and_prepare import add_exact_previous_day_lag, clean_identifier  # noqa: E402
from common import load_config  # noqa: E402
from run_analysis import balanced_group_fold_ids, gower_numeric_distance, pam  # noqa: E402


def test_missing_participant_ids_never_become_literal_nan():
    result = clean_identifier(pd.Series([None, np.nan, "nan", " P01 ", 12]), load_config())
    assert result.isna().sum() == 3
    assert result.iloc[3] == "P01"
    assert result.iloc[4] == "12"


def test_gower_is_symmetric_bounded_and_no_overlap_is_maximal():
    x = np.array([[1.0, np.nan], [np.nan, 4.0], [1.0, 4.0], [2.0, 5.0]])
    d = gower_numeric_distance(x)
    assert np.allclose(d, d.T)
    assert np.allclose(np.diag(d), 0)
    assert np.all((d >= 0) & (d <= 1))
    assert d[0, 1] == 1.0
    assert d[0, 2] == 0.0


def test_pam_recovers_two_separated_groups():
    x = np.array([[0.0], [0.1], [0.2], [9.8], [9.9], [10.0]])
    d = gower_numeric_distance(x, range_quantiles=(0.0, 1.0))
    result = pam(d, 2, random_state=1, n_init=4)
    first = len(set(result.labels[:3])) == 1
    second = len(set(result.labels[3:])) == 1
    assert first and second and result.labels[0] != result.labels[-1]


def test_balanced_group_folds_have_no_group_leakage():
    groups = pd.Series([f"P{i:02d}" for i in range(20) for _ in range((i % 4) + 1)])
    folds = balanced_group_fold_ids(groups, 5, seed=7)
    frame = pd.DataFrame({"group": groups, "fold": folds})
    assert (frame.groupby("group")["fold"].nunique() == 1).all()
    sizes = frame.groupby("fold").size()
    assert sizes.max() - sizes.min() <= groups.value_counts().max()


def test_exact_previous_day_lag_does_not_bridge_missing_days():
    frame = pd.DataFrame({
        "participant_id": ["P01", "P01", "P01", "P01", "P02", "P02"],
        "day": [1, 2, 4, 5, 1, 3],
        "sleep_quality": [4.0, 5.0, 6.0, np.nan, 3.0, 7.0],
    })
    result, audit, gap_distribution = add_exact_previous_day_lag(frame)
    observed = result["sleep_quality_lag1_exact"].iloc[:4]
    assert pd.isna(observed.iloc[0])
    assert observed.iloc[1] == 4.0
    assert pd.isna(observed.iloc[2])
    assert observed.iloc[3] == 6.0
    assert pd.isna(result.loc[5, "sleep_quality_lag1_exact"])
    assert result.loc[2, "sleep_quality_lag1_exact_status"] == "observation_gap_excluded"
    assert result.loc[5, "sleep_quality_lag1_exact_status"] == "observation_gap_excluded"
    assert int(audit.loc[0, "observation_gap_rows_excluded"]) == 2
    assert int(audit.loc[0, "exact_lag_nonmissing_rows"]) == 2
    assert set(gap_distribution["observed_day_gap"]) == {1.0, 2.0}


def test_exact_previous_day_lag_marks_missing_prior_sleep_without_carrying_older_value():
    frame = pd.DataFrame({
        "participant_id": ["P01", "P01", "P01"],
        "day": [1, 2, 3],
        "sleep_quality": [5.0, np.nan, 7.0],
    })
    result, _, _ = add_exact_previous_day_lag(frame)
    assert result.loc[1, "sleep_quality_lag1_exact"] == 5.0
    assert pd.isna(result.loc[2, "sleep_quality_lag1_exact"])
    assert result.loc[2, "sleep_quality_lag1_exact_status"] == "exact_previous_day_prior_sleep_missing"


def test_exact_previous_day_lag_is_order_invariant_and_restores_input_order():
    frame = pd.DataFrame({
        "participant_id": ["P01", "P01", "P01"],
        "day": [3, 1, 2],
        "sleep_quality": [7.0, 4.0, 5.0],
    }, index=[30, 10, 20])
    result, _, _ = add_exact_previous_day_lag(frame)
    assert result.index.tolist() == [30, 10, 20]
    assert result.loc[30, "sleep_quality_lag1_exact"] == 5.0
    assert pd.isna(result.loc[10, "sleep_quality_lag1_exact"])
    assert result.loc[20, "sleep_quality_lag1_exact"] == 4.0
