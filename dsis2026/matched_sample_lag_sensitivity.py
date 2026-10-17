"""Post-hoc matched-sample check of sample restriction versus exact prior-day adjustment.
Run from repo root: python dsis2026/matched_sample_lag_sensitivity.py
Requires full original src/ pipeline and official-derived data_processed/daily_analytic.csv.
"""
import json
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from run_analysis import fit_one_repeated_model,repeated_model_specifications  # noqa: E402

def main():
    df=pd.read_csv(ROOT/'data_processed/daily_analytic.csv')
    terms=repeated_model_specifications(df)['primary_temporal']
    matched=df.loc[df.sleep_quality_lag1_exact.notna()].copy()
    no_lag,_,a=fit_one_repeated_model(matched,'matched_unlagged',terms)
    with_lag,_,b=fit_one_repeated_model(matched,'matched_lag_adjusted',terms+['sleep_quality_lag1_exact'])
    if a['status']!='fitted' or b['status']!='fitted' or a['n_rows']!=b['n_rows'] or a['n_participants']!=b['n_participants']:
        raise RuntimeError('Models did not fit matching samples; do not report')
    def pick(rows):
        r=next(r for r in rows if r['term']=='postbed_use_within')
        return {k:r[k] for k in ['estimate','ci_low','ci_high','p_value','n_rows','n_participants']}
    result={'analysis_type':'exploratory_posthoc','n':int(a['n_rows']),'participants':int(a['n_participants']),'matched_unlagged':pick(no_lag),'matched_lag_adjusted':pick(with_lag)}
    target=ROOT/'dsis2026/results/matched_sample_lag_sensitivity.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
if __name__=='__main__':
    main()
