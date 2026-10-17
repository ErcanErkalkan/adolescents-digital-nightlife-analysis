"""Exploratory DSIS-2026 reviewer-response clustering check (not preregistered).
Run: python dsis2026/alternative_cluster_sensitivity_standalone.py --profiles data_processed/participant_profiles.csv --output dsis2026/results.csv
Requires: pandas numpy scikit-learn. Does not download or redistribute data.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import silhouette_score, adjusted_rand_score

FEATURES = (
    'daytime_use_mean', 'daytime_use_sd', 'prebed_use_mean', 'prebed_use_sd',
    'postbed_use_mean', 'postbed_use_sd', 'nighttime_exposure_ratio_mean',
    'nighttime_exposure_ratio_sd', 'postbed_intrusion_ratio_mean',
    'postbed_intrusion_ratio_sd', 'social_share_mean', 'social_share_sd',
    'video_share_mean', 'video_share_sd',
)

def category(name):
    if name.endswith('_sd'): return 'variability'
    if 'share' in name: return 'composition' if name.startswith(('social_', 'game_', 'video_')) else 'timing'
    if any(w in name for w in ('prebed', 'postbed', 'exposure', 'intrusion')): return 'timing'
    return 'intensity'

def distance_gower(x):
    groups = [category(c) for c in FEATURES]
    kinds = sorted(set(groups))
    weights = np.array([1/(len(kinds)*groups.count(group)) for group in groups])
    rng = np.nanquantile(x, .95, axis=0) - np.nanquantile(x, .05, axis=0)
    fallback = np.nanmax(x,axis=0) - np.nanmin(x,axis=0)
    rng = np.where(np.isfinite(rng) & (rng > 0), rng, fallback)
    rng = np.where(np.isfinite(rng) & (rng > 0), rng, 1.)
    d = np.zeros((len(x),len(x)))
    for i in range(len(x)):
        valid = np.isfinite(x[i])[None,:] & np.isfinite(x)
        delta = np.minimum(np.abs(x-x[i])/rng, 1.)
        numerator = np.nansum(delta*valid*weights,axis=1)
        denominator = np.sum(valid*weights,axis=1)
        d[i] = np.divide(numerator,denominator,out=np.ones(len(x)),where=denominator>0)
        d[i,i]=0.
    d=(d+d.T)/2
    np.fill_diagonal(d,0.)
    return d

def labels(method,k,d,z):
    if method=='agglomerative_gower':
        try: m=AgglomerativeClustering(n_clusters=k,metric='precomputed',linkage='average')
        except TypeError: m=AgglomerativeClustering(n_clusters=k,affinity='precomputed',linkage='average')
        return m.fit_predict(d)
    if method=='kmeans_robust':
        return KMeans(n_clusters=k,random_state=42,n_init=20,max_iter=300).fit_predict(z)
    raise ValueError(method)

def evaluate(input_file,output_file,repetitions=200):
    frame=pd.read_csv(input_file)
    if len(frame)!=155 or frame['participant_id'].nunique()!=155:
        raise ValueError('Unexpected source cohort: check provenance before interpreting')
    frame=frame.loc[frame['eligible_for_profiles'].astype(bool)].copy()
    if len(frame)!=130: raise ValueError('Unexpected eligible sample')
    if any(c not in frame for c in FEATURES): raise ValueError('Missing validated profile feature')
    # Match primary pipeline's within-participant 70% coverage masking.
    for feature in FEATURES:
        base=feature.rsplit('_',1)[0]
        count=base+'_n'
        if count not in frame.columns:
            raise ValueError('Missing observation-count column: '+count)
        valid=(frame[count] / frame['n_valid_primary_days']) >= .7
        frame.loc[~valid,feature] = np.nan
    x=frame[list(FEATURES)].to_numpy(dtype=float)
    d=distance_gower(x)
    z=RobustScaler().fit_transform(SimpleImputer(strategy='median').fit_transform(x))
    gen=np.random.default_rng(41017)
    subsets=[np.sort(gen.choice(len(x),size=int(.8*len(x)),replace=False)) for _ in range(repetitions)]
    records=[]
    for method in ['agglomerative_gower','kmeans_robust']:
        for k in range(2,7):
            base=labels(method,k,d,z)
            ari=[adjusted_rand_score(base[idx],labels(method,k,d[np.ix_(idx,idx)],z[idx])) for idx in subsets]
            sil=float(silhouette_score(d,base,metric='precomputed'))
            frac=float(np.bincount(base).min()/len(base)); med=float(np.median(ari))
            records.append({'method':method,'k':k,'n':len(base),'features':len(FEATURES),
                'silhouette_gower':sil,'min_cluster_fraction':frac,'median_subsample_ari':med,
                'passes_joint_gate':bool(frac>=.1 and sil>=.25 and med>=.75),
                'subsample_repetitions':repetitions,'analysis_type':'exploratory_posthoc'})
    out=pd.DataFrame(records)
    output_file=Path(output_file);output_file.parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(output_file,index=False)
    print(json.dumps({'evaluated':len(out),'passes':int(out.passes_joint_gate.sum()),
                      'status':'completed_exploratory','csv':str(output_file)}))
    return out

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--profiles',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--resamples',type=int,default=200)
    args=parser.parse_args()
    evaluate(args.profiles,args.output,args.resamples)
