"""Exploratory post-hoc AR(1) Gaussian GEE and ordinal GEE.
Run with: python dsis2026/temporal_ordinal_sensitivity.py --daily data_processed/daily_analytic.csv --output dsis2026/results/temporal_ordinal_sensitivity.json
Input must be from the official Figshare v2 data, not synthetic observations.
"""
import argparse
import json
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.genmod.generalized_estimating_equations import OrdinalGEE

TERMS = ('daytime_use_within', 'daytime_use_between', 'prebed_use_within', 'prebed_use_between', 'postbed_use_within', 'postbed_use_between', 'day')

def analyze(source, destination):
    raw = pd.read_csv(source)
    required = ['participant_id', 'day', 'sleep_quality'] + [x for x in TERMS if x != 'day']
    frame = raw[required].dropna().sort_values(['participant_id', 'day']).reset_index(drop=True)
    if len(frame) != 1806 or frame.participant_id.nunique() != 155:
        raise ValueError('Unexpected cohort/sample: verify official source version and filters')
    features = pd.DataFrame(index=frame.index)
    for term in TERMS:
        v = frame[term].astype(float)
        sd = v.std(ddof=0)
        if not np.isfinite(sd) or sd <= 0:
            raise ValueError('Undefined feature scale: ' + term)
        features['z_'+term] = (v-v.mean())/sd
    group = frame.participant_id.to_numpy()
    target = frame.sleep_quality.to_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        ar1 = sm.GEE(target, sm.add_constant(features), groups=group, time=frame[['day']].to_numpy(), cov_struct=sm.cov_struct.Autoregressive(grid=True), family=sm.families.Gaussian()).fit(maxiter=120)
        if not all(float(v).is_integer() for v in target) or np.min(target)<1 or np.max(target)>7:
            raise ValueError('Expected ordinal scores 1 through 7')
        ordinal = OrdinalGEE(target.astype(int), features, groups=group, cov_struct=sm.cov_struct.Exchangeable()).fit(maxiter=150)
    term = 'z_postbed_use_within'
    def record(model):
        conf = model.conf_int().loc[term]
        return {'converged': bool(model.converged), 'estimate': float(model.params.loc[term]), 'se': float(model.bse.loc[term]), 'p': float(model.pvalues.loc[term]), 'ci95': [float(conf.iloc[0]),float(conf.iloc[1])]}
    result = {'analysis_type':'exploratory_posthoc', 'n':len(frame), 'participants':int(frame.participant_id.nunique()), 'postbed_within_ar1_gaussian_gee': record(ar1), 'postbed_within_ordinal_exchangeable_gee':record(ordinal)}
    destination=Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--daily',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(analyze(args.daily,args.output),indent=2))
