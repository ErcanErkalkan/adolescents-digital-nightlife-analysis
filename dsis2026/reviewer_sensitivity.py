"""Independent, exploratory cluster-method robustness and missingness audit for DSIS 2026.

Requires validated source data prepared with the audited original pipeline.
The alternative algorithms and checks are POST-HOC reviewer response, not preregistered.
The module never selects/reports an accepted cluster unless all three gates pass.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import RobustScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from run_analysis import (  # noqa: E402
    apply_within_participant_profile_missingness,
    construct_weights,
    gower_numeric_distance,
    profile_candidate_columns,
    prune_correlated_features,
)


def prepare_profiles(raw: pd.DataFrame, config: dict):
    opts = config['analysis']
    eligible = raw.loc[raw['eligible_for_profiles'].fillna(False)].copy()
    candidate = profile_candidate_columns(eligible)
    eligible, _ = apply_within_participant_profile_missingness(
        eligible, candidate, opts['profile_missingness_max'],
        denominator_column='n_valid_primary_days')
    min_coverage = 1.0 - opts['profile_missingness_max']
    retained = [col for col in candidate if eligible[col].notna().mean() >= min_coverage
                and eligible[col].nunique(dropna=True) > 1]
    features, _ = prune_correlated_features(eligible, retained, opts['correlation_prune_threshold'])
    if len(eligible) < 30 or len(features) < 3:
        raise ValueError(f'Cannot fit sensitivity: n={len(eligible)}, features={features}')
    x = eligible[features].to_numpy(dtype=float)
    d = gower_numeric_distance(x, construct_weights(features), tuple(opts['gower_range_quantiles']))
    z = RobustScaler().fit_transform(SimpleImputer(strategy='median').fit_transform(x))
    assert len(eligible) == len(d) == len(z)
    return eligible, features, d, z


def cluster(method: str, k: int, d: np.ndarray, z: np.ndarray):
    if method == 'agglomerative_gower':
        try:
            model = AgglomerativeClustering(n_clusters=k, metric='precomputed', linkage='average')
        except TypeError:  # older sklearn
            model = AgglomerativeClustering(n_clusters=k, affinity='precomputed', linkage='average')
        return model.fit_predict(d)
    if method == 'kmeans_robust':
        return KMeans(n_clusters=k, random_state=42, n_init=20, max_iter=300).fit_predict(z)
    raise ValueError(method)


def audit_missingness(df: pd.DataFrame) -> dict:
    mask = df['valid_primary_day'].astype(bool)
    chosen = ['sleep_quality','daytime_use','prebed_use','postbed_use','social_share','game_share','video_share', 'timeframes_source_row_present']
    coverage = {}
    for c in chosen:
        if c in df:
            coverage[c] = {'observed': int(df[c].notna().sum()),
                           'missing': int(df[c].isna().sum()),
                           'missing_percent': round(100*df[c].isna().mean(),2)}
    return {'total_participants':int(df.participant_id.nunique()),
            'total_participant_days':int(len(df)),
            'valid_primary_days':int(mask.sum()),
            'nonprimary_days':int((~mask).sum()),
            'eligible_for_models':int(df.loc[mask,'participant_id'].nunique()),
            'missing_by_feature':coverage}


def run(profiles_path: Path, daily_path: Path, config_path: Path, out: Path, n_resamples: int=200):
    out.mkdir(exist_ok=True, parents=True)
    config = json.loads(config_path.read_text())
    profiles = pd.read_csv(profiles_path)
    eligible, features, d, z = prepare_profiles(profiles, config)
    opts = config['analysis']
    n = len(eligible)
    rng = np.random.default_rng(41017)
    sample_sets = [np.sort(rng.choice(n, size=int(0.8*n), replace=False)) for _ in range(n_resamples)]
    results=[]
    for method in ('agglomerative_gower','kmeans_robust'):
        for k in range(2, 7):
            full=cluster(method,k,d,z)
            assert np.unique(full).size == k
            sizes = np.bincount(full)
            sil = float(silhouette_score(d,full,metric='precomputed'))
            aris=[]
            for idx in sample_sets:
                sub=cluster(method,k,d[np.ix_(idx,idx)],z[idx])
                aris.append(float(adjusted_rand_score(full[idx],sub)))
            med=float(np.median(aris)); min_frac=float(sizes.min()/n)
            passed=bool(min_frac>=opts['min_cluster_fraction'] and sil>=opts['min_silhouette'] and med>=opts['min_stability_ari'])
            results.append({'method':method,'k':k,'n':n,'n_features':len(features),'silhouette_gower':sil,
                            'min_cluster_fraction':min_frac,'subsample_median_ari':med,
                            'subsample_ari_q10':float(np.quantile(aris,0.1)),
                            'subsample_ari_q90':float(np.quantile(aris,0.9)),
                            'passes_all_original_gates':passed,'posthoc_sensitivity':True,
                            'subsample_repetitions':n_resamples})
    result=pd.DataFrame(results)
    result.to_csv(out/'alternative_cluster_sensitivity.csv',index=False)
    sample=audit_missingness(pd.read_csv(daily_path))
    (out/'missingness_audit.json').write_text(json.dumps(sample,indent=2),encoding='utf-8')
    stat={'methods_tested':sorted(result.method.unique().tolist()),'n_eligible':n,'features_used':features,
          'passes':int(result['passes_all_original_gates'].sum()),'total_candidates':len(result),
          'posthoc':True,'n_resamples':n_resamples,
          'warning':'Exploratory methods, not in original pre-analysis plan; original prespecified PAM remains primary.'}
    (out/'sensitivity_status.json').write_text(json.dumps(stat,indent=2),encoding='utf-8')
    print(json.dumps(stat,indent=2))
    print(result[['method','k','silhouette_gower','min_cluster_fraction','subsample_median_ari','passes_all_original_gates']].to_string(index=False))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--out',type=Path,default=ROOT/'dsis2026'/'results')
    p.add_argument('--resamples',type=int,default=200)
    a=p.parse_args()
    run(a.root/'data_processed'/'participant_profiles.csv',a.root/'data_processed'/'daily_analytic.csv',a.root/'analysis_config.json',a.out,a.resamples)
