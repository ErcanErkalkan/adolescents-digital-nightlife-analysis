# Prediction Performance Estimands

The out-of-fold prediction analysis reports two distinct estimands. They answer different questions and must not be substituted for one another.

## Primary: participant-equal performance

`participant_equal` gives every adolescent the same total contribution, irrespective of how many valid participant-days they provide.

For participant \(i\), with \(n_i\) held-out observations and loss \(L_{it}\):

\[
\operatorname{MAE}_{PE}=\frac{1}{N}\sum_{i=1}^{N}\left(\frac{1}{n_i}\sum_{t=1}^{n_i}|y_{it}-\hat y_{it}|\right),
\]

\[
\operatorname{RMSE}_{PE}=\sqrt{\frac{1}{N}\sum_{i=1}^{N}\left(\frac{1}{n_i}\sum_{t=1}^{n_i}(y_{it}-\hat y_{it})^2\right)}.
\]

Participant-equal \(R^2\) uses observation weights \(1/n_i\), so the total normalized weight is identical for every adolescent. This is the primary manuscript estimand because the scientific target is performance across adolescents rather than performance dominated by adolescents with more valid days.

## Complementary: participant-day performance

`participant_day` gives every held-out participant-day equal weight. It estimates performance for a randomly selected valid participant-day from the analytic sample. Adolescents with more valid days therefore contribute more observations.

## Uncertainty

For both estimands, confidence intervals use participant-cluster bootstrap resampling. Entire adolescents, not isolated days, are sampled with replacement. For `participant_equal`, each sampled adolescent's within-participant losses are averaged before aggregation; repeated bootstrap selection changes participant multiplicity but not the relative weight of days within that adolescent.

## Outputs

- `predictive_performance.csv`: MAE, RMSE and R² with 95% participant-bootstrap intervals for both estimands.
- `predictive_performance_folds.csv`: both estimands in every outer fold.
- `predictive_participant_losses.csv`: participant-specific OOF MAE, MSE and RMSE used to audit participant-equal aggregation.
- `predictive_model_comparisons.csv`: paired model differences for both estimands.
- `predictive_mae_comparison_participant_equal.png`: primary MAE figure.
- `predictive_mae_comparison_participant_day.png`: complementary MAE figure.

## Interpretation rule

A model may not be described simply as having “MAE = x” without naming the estimand. The manuscript should report participant-equal performance first and participant-day performance as complementary. Feature-importance interpretation is gated using participant-equal MAE because that is the primary predictive estimand.
