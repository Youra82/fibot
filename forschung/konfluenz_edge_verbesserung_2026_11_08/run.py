from pathlib import Path
import sys,json,pickle,hashlib,logging
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fibot.analysis.edge_dashboard import read_cache,daily_history
from fibot.analysis.edge_state import uncertainty,frontier_point
from fibot.analysis import analysis_suite as S
from fibot.strategy import confluence_logic as C,trend_filter as F
from engine import VARIANTS,BASE,candidates,isolated,portfolio

TRAIN=pd.Timestamp('2025-01-01',tz='UTC');CUT=pd.Timestamp('2026-05-10',tz='UTC')
OUT=ROOT/'artifacts'/'edge_verbesserung_2026_11_08'


def prepare(args):
    key,cfg,end=args
    logging.disable(logging.WARNING)
    raw=read_cache(ROOT,cfg['market']['symbol'],cfg['market']['timeframe'])
    tf=cfg['market']['timeframe'];delta=pd.Timedelta(tf)
    raw=raw[raw.index+delta<=end]
    df=raw[raw.index>=TRAIN-delta*1200].copy()
    tc=F.settings();daily=daily_history(ROOT,cfg['market']['symbol'],end,raw,tf)
    htf=F.htf_trend(raw,tf,tc);day=F.daily_trend(daily,tc)
    cache_key=(cfg['market']['symbol'],tf,(df.index[0]-delta*F.base_bars_needed(tc)).floor('D'),
               df.index[-1].floor('D'),tuple(sorted(tc.items())))
    C._TREND_CACHE[cache_key]=(htf,day)
    try:prepared=C.precompute_confluence_signals(df,cfg)
    finally:C._TREND_CACHE.pop(cache_key,None)
    allowed=lambda side,t: not tc['enabled'] or F.allowed('long' if side==1 else 'short',t,htf,day)
    results={v:candidates(prepared,cfg,v,allowed) for v in VARIANTS}
    return key,prepared,results


def pool(data,configs,variant,start,end,stress=False):
    rows=[];opens=0
    for key,(frame,variants) in data.items():
        closed,open_rows,_=isolated(variants[variant],frame,configs[key],start,end,60.,stress)
        rows.extend([{**r,'config':key} for r in closed]);opens+=len(open_rows)
    t=pd.DataFrame(rows)
    if t.empty:return t,{'n':0,'open_end':opens}
    t=t.sort_values('known_at',kind='stable')
    u=uncertainty(t.net_r.values,t.known_at,samples=500)
    m=u['point']['metrics'];bycoin=t.groupby('coin').net_r.sum()
    drop=bycoin.nlargest(5).index
    m.update(ci=u['expectancy_ci'],status=u['status'],open_end=opens,
             without_top5_R=float(t[~t.coin.isin(drop)].net_r.mean()))
    return t,m


def paired_ci(base,variant):
    all_t=pd.concat([base.known_at,variant.known_at]);start=all_t.min().floor('D');end=all_t.max().floor('D')
    days=pd.date_range(start,end,freq='D');parts=[]
    for t in (base,variant):
        a=t.assign(day=t.known_at.dt.floor('D')).groupby('day').net_r.agg(['sum','size']).reindex(days,fill_value=0)
        parts.append(a.values)
    groups=[(a,b) for a,b in zip(np.split(parts[0],np.arange(28,len(days),28)),np.split(parts[1],np.arange(28,len(days),28)))]
    rng=np.random.default_rng(20261108);d=[]
    for _ in range(2000):
        chosen=[groups[j] for j in rng.integers(0,len(groups),len(groups))]
        a=np.vstack([x[0] for x in chosen]).sum(axis=0);b=np.vstack([x[1] for x in chosen]).sum(axis=0)
        if a[1]>0 and b[1]>0:d.append(b[0]/b[1]-a[0]/a[1])
    return [float(x) for x in np.quantile(d,[.025,.975])]


def main():
    OUT.mkdir(exist_ok=True)
    cfgs=S.load_configs('aktiv')
    end=pd.Timestamp(json.loads((ROOT/'artifacts'/'kontoverlauf_august_2026'/'summary.json').read_text())['data_end'])
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
             [Path(__file__),HERE/'engine.py',Path(C.__file__),Path(F.__file__)]}
    manifest=dict(configs=cfgs,sources=sources,end=str(end),max_positions=9)
    (OUT/'inputs.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    fingerprint=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    cached=OUT/'prepared.pkl'
    if cached.exists():
        with cached.open('rb') as f:old=pickle.load(f)
        data=old['data'] if old['fingerprint']==fingerprint else None
    else:data=None
    if data is None:
        data={}
        with ProcessPoolExecutor(max_workers=6) as ex:
            fs={ex.submit(prepare,(key,cfg,end)):key for key,cfg in cfgs.items()}
            for i,f in enumerate(as_completed(fs),1):
                key,df,v=f.result();data[key]=(df,v)
                print('prepared',i,'/',len(cfgs),key,flush=True)
        with cached.open('wb') as f:pickle.dump({'fingerprint':fingerprint,'data':data},f)
    coverage={k:dict(first=str(df.index[0]),last=str(df.index[-1]),bars=len(df),
                    missing_intervals=int(((df.index[1:]-df.index[:-1])!=pd.Timedelta(cfgs[k]['market']['timeframe'])).sum()),
                    signal_candidates=len(vs[BASE])) for k,(df,vs) in data.items()}
    (OUT/'coverage.json').write_text(json.dumps(coverage,indent=2),encoding='utf8')
    training={}
    for v in VARIANTS:
        _,m=pool(data,cfgs,v,TRAIN,CUT);training[v]=m
        print('TRAIN',v,m.get('n'),m.get('expectancy_r'),m.get('ci'),flush=True)
    eligible=[v for v,m in training.items() if m['n']>=100 and m.get('ci')]
    chosen=sorted(eligible,key=lambda v:(-training[v]['ci'][0],v))[0] if eligible else None
    frozen={'chosen':chosen,'training':training,'input_sha256':fingerprint,'development_end':str(CUT),
            'criterion':'maximum training lower 95% block interval; n>=100'}
    body=json.dumps(frozen,indent=2,sort_keys=True)
    (OUT/'frozen_selection.json').write_text(body,encoding='utf8')
    (OUT/'frozen_selection.sha256').write_text(hashlib.sha256(body.encode()).hexdigest()+'\n')
    print('FROZEN',chosen,flush=True)
    results={};held_trades={}
    frames={k:v[0] for k,v in data.items()}
    for v in VARIANTS:
        t,m=pool(data,cfgs,v,CUT,end);held_trades[v]=t
        _,stress=pool(data,cfgs,v,CUT,end,True)
        midpoint=CUT+(end-CUT)/2
        halves=[t[t.known_at<midpoint],t[t.known_at>=midpoint]] if len(t) else [t,t]
        m.update(stress_R=stress.get('expectancy_r'),halves_R=[float(x.net_r.mean()) if len(x) else None for x in halves])
        rows={k:x[1][v] for k,x in data.items()}
        account,ledger,curve=portfolio(rows,frames,cfgs,CUT,end)
        stress_account,_,_=portfolio(rows,frames,cfgs,CUT,end,stress=True)
        results[v]=dict(training=training[v],comparison=m,account=account,stress_account=stress_account)
        t.to_csv(OUT/f'{v}_trades.csv',index=False);curve.to_csv(OUT/f'{v}_equity.csv',index=False)
        ledger.to_csv(OUT/f'{v}_account_trades.csv',index=False)
        print('COMPARE',v,m.get('expectancy_r'),'account',account,flush=True)
    diff=paired_ci(held_trades[BASE],held_trades[chosen]) if chosen else None
    r=results[chosen]['comparison'] if chosen else {}
    improved=bool(chosen and chosen!=BASE and r.get('n',0)>=100 and r.get('ci') and r['ci'][0]>0 and
        r['stress_R']>0 and all(x is not None and x>0 for x in r['halves_R']) and diff[0]>0)
    summary=dict(chosen=chosen,base=BASE,comparison_start=str(CUT),end=str(end),results=results,
                 paired_improvement_ci=diff,criteria_passed=improved,
                 caveat='Wiederverwendete historische Daten; kein frischer Holdout. Keine Live-Aenderung.')
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print('DONE',chosen,'criteria_passed',improved,'paired_ci',diff,flush=True)

if __name__=='__main__':main()
