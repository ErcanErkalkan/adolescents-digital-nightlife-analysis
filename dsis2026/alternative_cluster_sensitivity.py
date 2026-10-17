"""DSIS 2026 exploratory reviewer-response clustering; NOT preregistered.
Run: python dsis2026/alternative_cluster_sensitivity.py --profiles data_processed/participant_profiles.csv --output dsis2026/results.csv
Requires pandas, numpy, scikit-learn. The CSV must be derived from official Figshare v2 data.
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
 'daytime_use_mean','daytime_use_sd','prebed_use_mean','prebed_use_sd',
 'postbed_use_mean','postbed_use_sd','nighttime_exposure_ratio_mean',
 'nighttime_exposure_ratio_sd','postbed_intrusion_ratio_mean',
 'postbed_intrusion_ratio_sd','social_share_mean','social_share_sd',
 'video_share_mean','video_share_sd'
)

def category(name):
    if name.endswith('_sd'):
        return 'variability'
    if any(token in name for token in ('social_share','game_share','video_share')):
        return 'composition'
    if any(token in name for token in ('nighttime_exposure','postbed_intrusion','prebed','postbed')):
        return 'timing'
    return 'intensity'

def gower(x):
    groups=[category(f) for f in FEATURES]
    kinds=sorted(set(groups))
    weights=np.array([1/(len(kinds)*groups.count(g)) for g in groups])
    rng=np.nanquantile(x,.95,axis=0)-np.nanquantile(x,.05,axis=0)
    full=np.nanmax(x,axis=0)-np.nanmin(x,axis=0)
    rng=np.where(np.isfinite(rng)&(rng>0),rng,full)
    rng=np.where(np.isfinite(rng)&(rng>0),rng,1.)
    d=np.zeros((len(x),len(x)))
    for i in range(len(x)):
        valid=np.isfinite(x[i])[None,:]&np.isfinite(x)
        diff=np.minimum(np.abs(x-x[i])/rng,1.)
        numerator=np.nansum(diff*valid*weights,axis=1)
        denominator=np.sum(valid*weights,axis=1)
        d[i]=np.divide(numerator,denominator,out=np.ones(len(x)),where=denominator>0)
        d[i,i]=0.
    d=(d+d.T)/2
    np.fill_diagonal(d,0.)
    return d

def labels(method,k,d,z):
    if method=='agglomerative_gower':
        try:
            m=AgglomerativeClustering(n_clusters=k,metric='precomputed',linkage='average')
        except TypeError:
            m=AgglomerativeClustering(n_clusters=k,affinity='precomputed',linkage='average')
        return m.fit_predict(d)
    if method=='kmeans_robust':
        return KMeans(n_clusters=k,random_state=42,n_init=20,max_iter=300).fit_predict(z)
    raise ValueError(method)

def evaluate(profiles,output,resamples=200):
    frame=pd.read_csv(profiles)
    if len(frame)!=155 or frame.participant_id.nunique()!=155:
        raise ValueError('Unexpected source cohort; check provenance')
    frame=frame.loc[frame.eligible_for_profiles.astype(bool)].copy()
    if len(frame)!=130:
        raise ValueError('Unexpected eligible sample')
    if any(c not in frame for c in FEATURES):
        raise ValueError('A validated feature is missing')
    for feature in FEATURES:
        count=feature.rsplit('_',1)[0]+'_n'
        if count not in frame:
            raise ValueError('Missing observation count: '+count)
        is_covered=(frame[count]/frame.n_valid_primary_days)>=.7
        frame.loc[~is_covered,feature]=np.nan
    x=frame[list(FEATURES)].to_numpy(dtype=float)
    d=gower(x)
    z=RobustScaler().fit_transform(SimpleImputer(strategy='median').fit_transform(x))
    gen=np.random.default_rng(41017)
    subsets=[np.sort(gen.choice(len(x),size=int(.8*len(x)),replace=False)) for _ in range(resamples)]
    rows=[]
    for method in ('agglomerative_gower','kmeans_robust'):
        for k in range(2,7):
            full=labels(method,k,d,z)
            aris=[adjusted_rand_score(full[idx],labels(method,k,d[np.ix_(idx,idx)],z[idx])) for idx in subsets]
            sil=float(silhouette_score(d,full,metric='precomputed'))
            frac=float(np.bincount(full).min()/len(full))
            med=float(np.median(aris))
            rows.append({'method':method,'k':k,'n':len(full),'n_features':len(FEATURES),
                         'silhouette_gower':sil,'minimum_cluster_fraction':frac,
                         'median_subsample_ari':med,
                         'ari_q10':float(np.quantile(aris,.1)),
                         'ari_q90':float(np.quantile(aris,.9)),
                         'passes_all_original_gates':bool(frac>=.1 and sil>=.25 and med>=.75),
                         'subsample_repetitions':resamples,
                         'analysis_type':'exploratory_posthoc'})
    result=pd.DataFrame(rows)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(output,index=False)
    print(json.dumps({'candidates':len(result),
                      'passed_all_gates':int(result.passes_all_original_gates.sum()),
                      'output':str(output)}))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--profiles',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--resamples',type=int,default=200)
    a=p.parse_args()
    evaluate(a.profiles,a.output,a.resamples)
