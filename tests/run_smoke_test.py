"""End-to-end validation in a temporary directory using synthetic data only."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SOURCE = Path(__file__).resolve().parents[1]


def generate(raw: Path) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260713)
    phone, timeframes = [], []
    categories = {name: [] for name in ["social", "game", "video"]}
    for pid in range(1, 61):
        profile = pid % 3
        trait = rng.normal(0, .35)
        for day in range(1, 13):
            weekend = day % 7 in (6, 0)
            daytime = max(20, rng.normal([260, 330, 210][profile] + 30 * weekend, 55))
            prebed = max(0, rng.normal([30, 65, 40][profile], 20))
            postbed = max(0, rng.normal([8, 20, 55][profile], 16))
            sleep = np.clip(6.0 + trait - .010 * postbed - .003 * prebed + rng.normal(0, .65), 1, 7)
            if rng.random() < .08:
                sleep = np.nan
            phone.append({"user_id": f"P{pid:03d}", "study_day": day, "sleep_qual": sleep,
                          "daytime_use": daytime / 60, "prebed_use": prebed / 60, "postbed_use": postbed / 60})
            for category in categories:
                if category == "social":
                    shares = ([.35, .60, .30][profile], [.45, .70, .35][profile], [.25, .40, .25][profile])
                elif category == "game":
                    shares = ([.15, .10, .35][profile], [.10, .08, .35][profile], [.10, .10, .55][profile])
                else:
                    shares = ([.20, .12, .18][profile], [.25, .10, .20][profile], [.25, .12, .12][profile])
                jitter = lambda x: max(0, min(.9, rng.normal(x, .05)))
                categories[category].append({
                    "user_id": f"P{pid:03d}", "study_day": day,
                    "daytime_use": daytime * jitter(shares[0]) / 60,
                    "prebed_use": prebed * jitter(shares[1]) / 60,
                    "postbed_use": postbed * jitter(shares[2]) / 60,
                })
            response_date = date(2020, 6, 2) + timedelta(days=day - 1)
            bedtime_date = response_date - timedelta(days=1)
            timeframes.append({
                "user_id": f"P{pid:03d}",
                "date_res": response_date.isoformat(),
                "bt_yes": f"{bedtime_date.isoformat()}T23:00:00Z",
                "wt_today": f"{response_date.isoformat()}T07:00:00Z",
                "sleep_qual": sleep,
            })
    pd.DataFrame(phone).to_csv(raw / "phone.csv", index=False)
    for name, rows in categories.items():
        pd.DataFrame(rows).to_csv(raw / f"{name}.csv", index=False)
    pd.DataFrame(timeframes).to_csv(raw / "timeframes.csv", index=False)


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="adn_smoke_") as temp:
        project = Path(temp) / "project"
        project.mkdir()
        for name in ["src", "analysis_config.json", "run_all.py"]:
            src = SOURCE / name
            shutil.copytree(src, project / name) if src.is_dir() else shutil.copy2(src, project / name)
        config_path = project / "analysis_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["reference_expectations"] = {}
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        generate(project / "data_raw")
        run([sys.executable, "run_all.py", "--offline", "--quick"], project)

        summary = json.loads((project / "outputs/tables/run_summary.json").read_text())
        assert summary["participants"] == 60
        assert summary["participant_days"] == 720
        assert summary["predictive_model_fold_results"] >= 20
        assert "primary_temporal" in set(summary["repeated_models_fitted"])
        selection = pd.read_csv(project / "outputs/tables/cluster_selection.csv")
        assert {"silhouette", "median_subsample_ari", "passes_all_thresholds"} <= set(selection.columns)
        performance = pd.read_csv(project / "outputs/tables/predictive_performance.csv")
        assert {"mean_only", "baseline_total", "temporal", "extended"} <= set(performance["feature_set"])
        assert set(performance["evaluation_weighting"]) == {"participant_day", "participant_equal"}
        for _, group in performance.groupby(["feature_set", "model"]):
            assert set(group["evaluation_weighting"]) == {"participant_day", "participant_equal"}
        assert (project / "outputs/tables/source_file_manifest.csv").exists()
        assert (project / "outputs/tables/analysis_specification_manifest.json").exists()
        assert (project / "outputs/tables/predictive_feature_selection.csv").exists()
        participant_losses = pd.read_csv(project / "outputs/tables/predictive_participant_losses.csv")
        assert not participant_losses.empty
        assert participant_losses.groupby(["feature_set", "model"])["participant_id"].nunique().min() == 60
        assert (project / "outputs/tables/feature_importance_interpretation_gate.csv").exists()
        validation = json.loads((project / "outputs/tables/validation_report.json").read_text())
        assert validation["status"] == "passed"
        assert (project / "outputs/ANALYSIS_REPORT.md").exists()
        print("SMOKE TEST PASSED: all core outputs and validation checks completed in an isolated temporary directory.")


if __name__ == "__main__":
    main()
