import os, sys, json, pickle
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'strategie_suche_2026_11_08'
sys.path.insert(0, str(OLD))
import harness as H
import konfluenz_k as K

VARS = ('L', 'C', 'P', 'E', 'PE', 'PEH')
WAIT_BARS = 4
PRESSURE_RATIO = 1.0
ENERGY_RATIO = 1.0

def entropy(x):
    counts = np.histogram(x, bins=10)[0]
    p = counts[counts > 0] / len(x)
    return -np.sum(p * np.log(p))

def features(h, l, c):
    a = K._atr(h, l, c, 14)
    z = np.r_[np.nan, np.diff(c)] / a
    neg = np.maximum(-z, 0)
    recent = pd.Series(neg).rolling(2).mean().values
    prior = pd.Series(neg).shift(2).rolling(3).mean().values
    pressure = (prior > 0) & (recent < PRESSURE_RATIO*prior)
    energy = (z > 0) & (z*z > ENERGY_RATIO*pd.Series(z*z).shift(1).rolling(3).mean().values)
    returns = pd.Series(np.r_[np.nan, np.diff(np.log(np.abs(c)))])
    ent = returns.rolling(20).apply(entropy, raw=True)
    return pressure, energy, (ent < ent.shift(3)).values

def candidates(o, h, l, c, events, var, step):
    pressure, energy, ent = features(h, l, c)
    out = []
    for e in events:
        i, sl, tp = e['i'], e['sl'], e['tp']
        if var == 'L':
            u, ep = i, e['limit']
        else:
            u = None
            for q in range(i, min(len(c)-1, i+WAIT_BARS)):
                if l[q] <= sl:
                    break
                if q > i and not np.all(np.diff(step[i:q+2]) == step[1]-step[0]):
                    break
                ok = c[q] > e['limit'] and c[q] > o[q]
                if var in ('P', 'PE', 'PEH'): ok &= pressure[q]
                if var in ('E', 'PE', 'PEH'): ok &= energy[q]
                if var == 'PEH': ok &= ent[q]
                if ok:
                    u = q+1
                    break
            if u is None: continue
            ep = o[u] + H.SLIP*abs(o[u])
        risk = ep-sl
        if risk <= 0 or tp <= ep or (var != 'L' and (tp-ep)/risk < 1): continue
        out.append((u, ep, sl, tp, i))
    return out

def simulate(df, events_by_side, var):
    idx = df.index
    stamp = idx.asi8
    interval = int(pd.Series(np.diff(stamp)).mode().iloc[0])
    arrays = [df[k].values for k in ('open','high','low','close')]
    pending = []
    for side, events in events_by_side.items():
        o,h,l,c = arrays if side == 1 else [-arrays[0],-arrays[2],-arrays[1],-arrays[3]]
        for row in candidates(o,h,l,c,events,var,stamp): pending.append((row[0],side,row))
    pending.sort(key=lambda x:(x[0], x[1]))
    trades, busy = [], -1
    for u,side,(_,ep,sl,tp,touch) in pending:
        if u <= busy: continue
        o,h,l,c = arrays if side == 1 else [-arrays[0],-arrays[2],-arrays[1],-arrays[3]]
        xp, reason = None, None
        for j in range(u, min(len(c), u+120)):
            if l[j] <= sl:
                xp = min(sl,o[j]) if j>u or var!='L' else sl
                xp -= H.SLIP*abs(xp)
                reason='sl'; break
            if j>u and h[j]>=tp:
                xp=tp; reason='tp'; break
        if xp is None:
            j=min(len(c)-1,u+119)
            if u+119>=len(c):
                busy=len(c)-1
                continue
            xp=c[j]-H.SLIP*abs(c[j]); reason='time'
        busy=j
        if j>touch and not np.all(np.diff(stamp[touch:j+1])==interval): continue
        risk=ep-sl
        cost=.0006*(abs(ep)+abs(xp))
        net=xp-ep-cost
        stress_cost=(.0015+.0001*np.ceil((j-u+1)*interval/3.6e12/8))*abs(ep)
        trades.append(dict(entry_ts=idx[u],exit_ts=idx[j],side=side,ret=net/abs(ep),
                           R=net/risk,stress_R=(net-stress_cost)/risk,res=reason,
                           risk_pct=100*risk/abs(ep),bars=j-u+1,touch=touch))
        busy=j
    return trades

def job(arg):
    coin,tf=arg
    df=H._read(os.path.join(H.GEO,f'{coin}-USDT-USDT_{tf}.csv')).iloc[:-1]
    o,h,l,c,v=[df[k].values for k in ('open','high','low','close','volume')]
    cache=HERE/'events_cache'
    cache.mkdir(exist_ok=True)
    path=cache/f'{coin}_{tf}.pkl'
    if path.exists():
        with open(path,'rb') as f: ev=pickle.load(f)
    else:
        ev={1:K.touch_events(o,h,l,c,v),-1:K.touch_events(-o,-l,-h,-c,v)}
        with open(path,'wb') as f: pickle.dump(ev,f)
    rows=[]
    for var in VARS:
        for t in simulate(df,ev,var): rows.append(dict(t,coin=coin,tf=tf,variant=var))
    return rows,dict(coin=coin,tf=tf,bars=len(df),start=str(df.index.min()),end=str(df.index.max()),events=sum(map(len,ev.values())))

def stats(t):
    if len(t)==0: return dict(n=0)
    pc=t.groupby('coin').R.sum()
    return dict(n=len(t),R=float(t.R.mean()),ret_pct=float(t.ret.mean()*100),
                stress_R=float(t.stress_R.mean()),win_pct=float((t.R>0).mean()*100),
                coins=int(len(pc)),positive_coins_pct=float((pc>0).mean()*100),
                without_top5_R=float(t[~t.coin.isin(pc.nlargest(5).index)].R.mean()),
                median_stop_pct=float(t.risk_pct.median()))

def bootstrap(t):
    if len(t)<10: return dict(p=1.,lo=float('nan'),hi=float('nan'))
    d=t.groupby(t.entry_ts.dt.floor('D')).R.sum()
    d=d.reindex(pd.date_range(d.index.min(),d.index.max(),freq='D'),fill_value=0.)
    groups=[x.values for _,x in d.groupby(np.arange(len(d))//28)]
    rng=np.random.default_rng(20261108)
    means=np.array([np.concatenate([groups[q] for q in rng.integers(0,len(groups),len(groups))]).mean() for _ in range(2000)])
    return dict(p=float((1+np.sum(means-d.mean()>=d.mean()))/2001),lo=float(np.quantile(means,.025)),hi=float(np.quantile(means,.975)))

def report(T,manifest):
    results={}
    for tf in ('4h','1h'):
        coins=[m['coin'] for m in manifest if m['tf']==tf]
        A,B=H.split_coins(coins)
        for var in VARS:
            t=T[(T.tf==tf)&(T.variant==var)].copy()
            pre=t[t.entry_ts<pd.Timestamp('2026-10-15',tz='UTC')]
            cuts={'all':t,'before2026':t[t.entry_ts<pd.Timestamp('2026-01-01',tz='UTC')],
                  '2026_before_oct15':pre[pre.entry_ts>=pd.Timestamp('2026-01-01',tz='UTC')],
                  'recent':t[t.entry_ts>=pd.Timestamp('2026-10-15',tz='UTC')],
                  'coins_A':pre[pre.coin.isin(A)],'coins_B':pre[pre.coin.isin(B)],
                  'long':t[t.side==1],'short':t[t.side==-1]}
            r={k:stats(v) for k,v in cuts.items()}
            r['bootstrap']=bootstrap(pre)
            r['years']={str(y):stats(s) for y,s in t.groupby(t.entry_ts.dt.year)}
            results[tf+'_'+var]=r
    ordered=sorted([k for k in results if not k.endswith('_L')],key=lambda k:results[k]['bootstrap']['p'])
    alive=True
    for rank,k in enumerate(ordered):
        r=results[k]; alive=alive and r['bootstrap']['p']<=.05/(len(ordered)-rank)
        r['holm']=bool(alive)
        r['robust']=bool(alive and r['all'].get('n',0)>=100 and
            all(r[s].get('R',-1)>0 for s in ('before2026','2026_before_oct15','coins_A','coins_B')) and
            r['all'].get('stress_R',-1)>0 and r['all'].get('without_top5_R',-1)>0)
    (HERE/'results.json').write_text(json.dumps(results,indent=2,allow_nan=True),encoding='utf8')
    for key,r in results.items(): print(key,json.dumps(r['all']), 'bootstrap',r['bootstrap'],'robust',r.get('robust',False),flush=True)
    T.to_csv(HERE/'trades.csv',index=False)

def main():
    args=[]
    for tf in ('4h','1h'):
        for coin in H.load_universe(tf): args.append((coin,tf))
    rows,manifest=[],[]
    with ProcessPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(job,a):a for a in args}
        for count,f in enumerate(as_completed(futures),1):
            r,m=f.result(); rows.extend(r);manifest.append(m)
            print(f'{count}/{len(args)} {m["tf"]} {m["coin"]} events={m["events"]} trades={len(r)}',flush=True)
    T=pd.DataFrame(rows)
    (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    with open(HERE/'raw.pkl','wb') as f: pickle.dump((T,manifest),f)
    report(T,manifest)

if __name__=='__main__': main()
