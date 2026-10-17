# Methods Draft for the Empirical CHIuXiD Paper

## Dataset and Study Design

We conduct a secondary analysis of the public *Adolescents’ Digital Nightlife* dataset, which combines continuous smartphone app tracking with repeated morning assessments of sleep quality over a 21-day period. The released package contains processed participant-day datasets for overall smartphone use and for social media, game, and video-player app categories, together with bedtime and wake-up information used to construct daytime, pre-bedtime, and post-bedtime exposure windows. The participant-day is the primary analysis unit. Because observations are nested within adolescents, no analysis treats daily records as independent.

The analysis uses the anonymized public release under the terms stated in the official repository record. Our analysis does not attempt re-identification and does not construct individual risk, addiction, or diagnostic labels. Results are reported only at aggregate level. This secondary analysis is observational; all reported relationships are interpreted as associations rather than causal effects.

## Behavioral Feature Engineering

For participant *i* on day *d*, we represent overall smartphone use by daytime use, use during the hour preceding bedtime, and use after the reported bedtime. Total use is the sum of the three windows. We derive the Nighttime Exposure Ratio as the proportion of total use occurring before or after bedtime:

\[
NER_{id}=\frac{PreBed_{id}+PostBed_{id}}{TotalUse_{id}+\epsilon}.
\]

We derive the Post-Bedtime Intrusion Ratio as the share of nighttime exposure occurring after bedtime:

\[
PBIR_{id}=\frac{PostBed_{id}}{PreBed_{id}+PostBed_{id}+\epsilon}.
\]

Equivalent timeframe variables are constructed for social media, game, and video-player use when present in the released category files. To distinguish day-to-day change from stable differences between adolescents, each repeated predictor is decomposed into a participant mean and a person-mean-centered daily deviation. Sleep quality from the preceding available day is included in sensitivity-adjusted explanatory models when coverage is sufficient.

## Temporal Profile Discovery

Participant-level profiling uses predictor-only summaries: the mean and day-to-day standard deviation of overall use, the three time windows, nighttime ratios, and app-category shares. Sleep quality is excluded from the clustering inputs and retained only for external comparison. Participants must contribute at least five valid days.

Because the features differ in scale and include proportions, we compute numeric Gower dissimilarities. To prevent constructs represented by several correlated variables from dominating the solution, features are grouped into intensity, timing, variability, and composition constructs, with equal total weight assigned to each construct. We fit k-medoids solutions for *k* = 2–6. A solution is considered interpretable only when its smallest profile contains at least 10% of eligible participants, mean silhouette is at least 0.25, and median adjusted Rand index across repeated 80% subsamples is at least 0.75. If no candidate passes all criteria, we report that no stable profile structure was identified and do not force persona labels.

## Explanatory Models

Primary explanatory analyses use random-intercept linear mixed models with sleep quality as the outcome and participant as the grouping factor. Overall smartphone use is represented by within-person and between-person components of daytime, pre-bedtime, and post-bedtime use. A lagged-outcome sensitivity model is estimated separately from the primary model, using prior sleep quality only when it was observed exactly one numeric study day earlier; values are never carried across missing study days. An app-category model evaluates social-media, game, and video-player timing only when the required variables have adequate coverage and is treated as exploratory. Predictors are standardized before estimation. If mixed-model optimization fails or the random-effect covariance is singular, an exchangeable Gaussian generalized estimating equation is used as a transparent fallback while retaining participant-clustered inference.

## Out-of-Sample Prediction

We compare a training-mean comparator and three prespecified feature sets: (1) total daily use only, (2) daytime, pre-bedtime, and post-bedtime use, and (3) temporal variables augmented with nighttime ratios and category-specific use. All evaluation uses grouped outer cross-validation so that every record from a participant remains entirely in either the training or test fold. Elastic-net hyperparameters are selected by grouped inner cross-validation. A fixed random forest fitted only to the extended feature set serves as an exploratory nonlinear benchmark and is not used for confirmatory inference. Performance is summarized for two estimands. The complementary participant-day estimand gives every held-out participant-day equal weight. The primary participant-equal estimand gives every adolescent equal total weight regardless of the number of valid held-out days: absolute and squared losses are first averaged within participant and then aggregated equally across participants; participant-equal RMSE is the square root of the equally averaged participant-specific mean squared losses, and R² uses the corresponding inverse-day-count observation weights. Both estimands are reported with participant-cluster bootstrap 95% confidence intervals and paired bootstrap differences for the extended-versus-total-use comparison. Calibration summaries are reported separately and are not substituted for these performance estimands.

## Robustness and Reporting

The pipeline audits duplicate participant-day keys, impossible negative durations, values exceeding 24 hours in a single window, unit conversion, missingness, and participant coverage. The preparation stage excludes invalid negative or over-24-hour window durations from primary validity flags without altering the immutable source files. A separate exact-previous-day lagged-outcome sensitivity model is reported when coverage permits. Rows separated by observation gaps are excluded from this sensitivity model rather than treated as one-day lags. Cluster findings, explanatory estimates, and predictive performance are reported with uncertainty and are interpreted independently. Behavioral profiles are descriptive summaries rather than fixed psychological types.
