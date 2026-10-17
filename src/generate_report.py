from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from common import OUTPUTS, TABLES, setup_logging

LOGGER = setup_logging("report", "report.log")


def read_csv(name: str) -> pd.DataFrame:
    path = TABLES / name
    if not path.exists() or not path.stat().st_size:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def markdown(frame: pd.DataFrame) -> str:
    safe = frame.copy()
    for column in safe.columns:
        if safe[column].dtype == object:
            safe[column] = safe[column].map(lambda value: "" if pd.isna(value) else str(value))
    return safe.to_markdown(index=False, disable_numparse=True)


def fmt(value, digits=3):
    try:
        if pd.isna(value):
            return "NA"
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate manuscript-ready analysis report from actual outputs.")
    parser.add_argument("--allow-quick", action="store_true")
    args = parser.parse_args()
    summary_path = TABLES / "run_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError("run_summary.json not found. Run the analysis first.")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("quick_mode") and not args.allow_quick:
        raise RuntimeError("Quick-mode outputs are for code validation only and cannot generate a publication report.")
    validation_path = TABLES / "validation_report.json"
    if not validation_path.exists():
        raise RuntimeError("validation_report.json not found. Run publication validation before generating a report.")
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if validation.get("status") != "passed":
        raise RuntimeError("Publication validation did not pass; report generation is blocked.")

    quality = read_csv("data_quality_report.csv")
    clusters = read_csv("cluster_selection.csv")
    profiles = read_csv("cluster_profiles.csv")
    coefficients = read_csv("repeated_model_coefficients.csv")
    diagnostics = read_csv("repeated_model_diagnostics.csv")
    performance = read_csv("predictive_performance.csv")
    comparisons = read_csv("predictive_model_comparisons.csv")
    importance = read_csv("feature_importance_summary.csv")
    importance_gate = read_csv("feature_importance_interpretation_gate.csv")
    calibration = read_csv("prediction_calibration.csv")

    lines = [
        "# Adolescents’ Digital Nightlife — Analysis Report",
        "",
        "> This report is generated exclusively from the source files and out-of-fold outputs present in this project. It makes no causal claims.",
        "",
        "## Data integrity and analytic sample",
        "",
        f"- Participants: **{summary.get('participants', 'NA')}**",
        f"- Participant-days: **{summary.get('participant_days', 'NA')}**",
        f"- Non-missing sleep assessments: **{summary.get('sleep_assessments', 'NA')}**",
        f"- Valid primary-analysis days: **{summary.get('valid_primary_days', 'NA')}**",
        f"- Quick validation mode: **{summary.get('quick_mode', False)}**",
        "",
    ]
    if not quality.empty:
        lines += ["### Quality-control metrics", "", markdown(quality), ""]

    lines += ["## Temporal profile discovery", ""]
    if summary.get("cluster_solution_meets_thresholds"):
        lines.append(f"A **{summary.get('selected_k')}‑profile** solution met all prespecified size, silhouette, and stability thresholds.")
        if not profiles.empty:
            lines += ["", markdown(profiles), ""]
    else:
        lines.append("No candidate profile solution met all prespecified acceptance thresholds; no behavioral personas should be reported.")
    if not clusters.empty:
        lines += ["", "### Candidate solutions", "", markdown(clusters), ""]

    lines += ["## Repeated-measures models", ""]
    if diagnostics.empty:
        lines.append("No repeated-measures model was estimable from the available data.")
    else:
        lines += [markdown(diagnostics), ""]
    if not coefficients.empty:
        lines += ["### Coefficients", "", markdown(coefficients), ""]

    lines += [
        "## Participant-grouped predictive validation",
        "",
        "Two performance estimands are reported. `participant_equal` is primary and gives each adolescent equal total weight regardless of valid-day count; `participant_day` is complementary and describes a randomly selected participant-day.",
        "",
    ]
    if performance.empty:
        lines.append("No out-of-fold predictive metrics were generated.")
    else:
        order = {"participant_equal": 0, "participant_day": 1}
        performance = performance.copy()
        performance["_weighting_order"] = performance["evaluation_weighting"].map(order).fillna(99)
        performance = performance.sort_values(["_weighting_order", "feature_set", "model", "metric"]).drop(columns="_weighting_order")
        lines += [markdown(performance), ""]
    if not comparisons.empty:
        lines += ["### Prespecified model comparison", "", markdown(comparisons), ""]
    if not calibration.empty:
        lines += ["### Calibration", "", markdown(calibration), ""]
    if not importance_gate.empty:
        lines += ["### Feature-importance interpretation gate", "", markdown(importance_gate), ""]
    if not importance.empty:
        top = importance.sort_values("importance_mean", ascending=False).groupby(["feature_set", "model"], group_keys=False).head(10)
        lines += ["### Gated outer-fold feature importance", "", markdown(top), ""]
    else:
        lines += [
            "### Feature importance",
            "",
            "No feature-importance interpretation is permitted unless predictive performance exceeds the training-mean comparator under participant-bootstrap uncertainty and is better in every outer fold.",
            "",
        ]

    lines += [
        "## Interpretation constraints",
        "",
        "The analyses are observational and secondary. Associations do not establish that smartphone use caused changes in sleep quality. Reverse directionality, time-varying confounding, measurement differences between platforms, and residual app-classification error remain possible.",
        "",
    ]
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    (OUTPUTS / "ANALYSIS_REPORT.md").write_text("\n".join(lines), encoding="utf-8")

    # A concise manuscript Results scaffold, populated only with actual generated values.
    result = [
        "# Manuscript Results Draft",
        "",
        f"The analytic data contained {summary.get('participant_days', 'NA')} participant-days from {summary.get('participants', 'NA')} adolescents, including {summary.get('sleep_assessments', 'NA')} non-missing morning sleep-quality assessments.",
        "",
    ]
    if summary.get("cluster_solution_meets_thresholds"):
        accepted = clusters[clusters.get("passes_all_thresholds", False) == True] if not clusters.empty else pd.DataFrame()  # noqa: E712
        if not accepted.empty:
            chosen = accepted[accepted["k"] == summary.get("selected_k")].iloc[0]
            result.append(
                f"The prespecified profile analysis retained a {int(chosen['k'])}-profile solution "
                f"(silhouette={fmt(chosen['silhouette'])}; median subsample ARI={fmt(chosen['median_subsample_ari'])}; "
                f"minimum profile fraction={fmt(chosen['minimum_cluster_fraction'])})."
            )
    else:
        result.append("No candidate temporal-profile solution satisfied every prespecified acceptance criterion.")
    if not performance.empty:
        result += [
            "",
            "Out-of-fold prediction was evaluated for two estimands: the primary participant-equal estimand, which gives every adolescent equal total weight, and the complementary participant-day estimand, which gives every held-out day equal weight.",
        ]
        for feature_set, model in [("extended", "elastic_net"), ("baseline_total", "elastic_net"), ("mean_only", "training_mean")]:
            subset = performance[
                (performance["feature_set"] == feature_set)
                & (performance["model"] == model)
                & (performance["metric"] == "mae")
            ]
            if subset.empty:
                continue
            values = {row.evaluation_weighting: row for row in subset.itertuples(index=False)}
            if "participant_equal" in values and "participant_day" in values:
                equal = values["participant_equal"]
                day = values["participant_day"]
                result.append(
                    f"For {feature_set}/{model}, participant-equal MAE was {fmt(equal.estimate)} "
                    f"(95% participant-bootstrap CI {fmt(equal.ci_low)}–{fmt(equal.ci_high)}), whereas "
                    f"participant-day MAE was {fmt(day.estimate)} "
                    f"(95% CI {fmt(day.ci_low)}–{fmt(day.ci_high)})."
                )
    result += [
        "",
        "Repeated-measures coefficient estimates and participant-grouped out-of-fold predictive results are reported in the generated tables. Effect estimates should be interpreted as associations, and predictive comparisons should be based on their participant-bootstrap confidence intervals rather than isolated point estimates.",
        "",
    ]
    (TABLES / "RESULTS_SECTION_DRAFT.md").write_text("\n".join(result), encoding="utf-8")
    LOGGER.info("Generated manuscript-ready report files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
