"""Data-free integrity checks for DSIS 2026 public aggregate evidence.

This verifies internal consistency only. It is NOT a substitute for rerunning
the full empirical pipeline against Figshare version 2.
"""
from pathlib import Path
import json
import math
import pandas as pd

HERE = Path(__file__).resolve().parent

def main():
    p = HERE / "alternative_cluster_sensitivity.csv"
    table = pd.read_csv(p)
    required = {"method", "k", "n", "features", "silhouette_gower",
                "min_cluster_fraction", "median_subsample_ari", "passes_joint_gate",
                "subsample_repetitions", "analysis_type"}
    assert required == set(table.columns), "Aggregate schema differs from runnable script"
    assert len(table) == 10 and table[["method", "k"]].drop_duplicates().shape[0] == 10
    assert set(table.method) == {"agglomerative_gower", "kmeans_robust"}
    for method in set(table.method):
        assert set(table.loc[table.method == method, "k"]) == set(range(2, 7))
    assert (table.n == 130).all() and (table.features == 14).all()
    assert (table.subsample_repetitions == 200).all()
    assert (table.analysis_type == "exploratory_posthoc").all()
    assert not table.passes_joint_gate.astype(bool).any()
    assert table.silhouette_gower.between(-1, 1).all()
    assert table.min_cluster_fraction.between(0, 1).all()
    assert table.median_subsample_ari.between(-1, 1).all()
    for name in ("temporal_ordinal_sensitivity", "matched_sample_lag_sensitivity"):
        blob = json.loads((HERE / (name + ".json")).read_text())
        assert blob["analysis_type"] == "exploratory_posthoc"
        assert blob["n"] in (1197, 1806)
    # File paths are checked, not the contents of participants' records;
    # the data must NOT be checked into this public repository.
    repo = HERE.parent
    for forbidden in (repo / "data_raw", repo / "data_processed"):
        if forbidden.exists():
            assert not any(x.is_file() and x.suffix.lower() in {".csv", ".parquet", ".xlsx", ".json"}
                           for x in forbidden.rglob("*")), "Participant-level data in public repository"
    print("PASS: aggregate public evidence integrity (NOT an empirical reproduction).")

if __name__ == "__main__":
    main()
