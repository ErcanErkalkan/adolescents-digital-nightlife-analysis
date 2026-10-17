from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common import detect_dataset_files, load_config  # noqa: E402
from inspect_and_prepare import align_day_key_to_reference, resolve_column, standardize_source  # noqa: E402


USAGE_COLUMNS = [
    "user_id",
    "study_day",
    "daytime_use",
    "prebed_use",
    "postbed_use",
    "sleep_qual",
]


@pytest.mark.parametrize("source", ["phone", "game", "social", "video"])
@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        ("participant_id", "user_id"),
        ("day", "study_day"),
        ("sleep_quality", "sleep_qual"),
        ("daytime_use", "daytime_use"),
        ("prebed_use", "prebed_use"),
        ("postbed_use", "postbed_use"),
    ],
)
def test_usage_schema_exact_mappings(source: str, canonical: str, expected: str) -> None:
    frame = pd.DataFrame(columns=USAGE_COLUMNS)
    resolved, audit = resolve_column(frame, source, canonical, load_config(), required=True)
    assert resolved == expected
    assert audit[0]["method"] == "exact"


@pytest.mark.parametrize(
    ("canonical", "expected", "method"),
    [
        ("participant_id", "user_id", "exact"),
        ("day", "date_res", "override"),
        ("bedtime", "bt_yes", "override"),
        ("wakeup", "wt_today", "override"),
    ],
)
def test_timeframes_schema_exact_mappings(canonical: str, expected: str, method: str) -> None:
    frame = pd.DataFrame(
        columns=[
            "user_id",
            "date_res",
            "weekday",
            "time_res",
            "wt_yes",
            "hbefore_bt_yes",
            "bt_yes",
            "wt_today",
            "sleep_qual",
        ]
    )
    resolved, audit = resolve_column(frame, "timeframes", canonical, load_config(), required=True)
    assert resolved == expected
    assert audit[0]["method"] == method


def test_official_file_stems_resolve_uniquely() -> None:
    if not list((ROOT / "data_raw").glob("*.csv")):
        pytest.skip("Official dataset CSV files are intentionally excluded from code-only distribution")
    resolved = detect_dataset_files(load_config())
    assert set(resolved) == {"phone", "game", "social", "video", "timeframes"}
    assert {key: path.name for key, path in resolved.items()} == {
        "phone": "phone.csv",
        "game": "game.csv",
        "social": "social.csv",
        "video": "video.csv",
        "timeframes": "timeframes.csv",
    }


def test_timeframe_dates_align_to_documented_numeric_study_days() -> None:
    keys, numeric, dates, rule = align_day_key_to_reference(
        pd.Series(["2020-06-02", "2020-06-11"]),
        pd.Series(["n:1", "n:10"], dtype="string"),
        load_config(),
    )
    assert keys.tolist() == ["n:1", "n:10"]
    assert numeric.tolist() == [1.0, 10.0]
    assert dates.dt.strftime("%Y-%m-%d").tolist() == ["2020-06-02", "2020-06-11"]
    assert rule == "date_to_numeric_study_day"


def test_category_sleep_quality_is_audited_but_not_duplicated_into_merge_payload() -> None:
    frame = pd.DataFrame(
        {
            "user_id": [1],
            "study_day": [1],
            "daytime_use": [1.0],
            "prebed_use": [0.1],
            "postbed_use": [0.0],
            "sleep_qual": [5],
        }
    )
    standardized, mappings, _ = standardize_source(frame, "social", load_config(), require_usage=True)
    assert "sleep_quality" not in standardized
    assert {row["canonical"] for row in mappings} >= {"sleep_quality", "participant_id", "day"}
