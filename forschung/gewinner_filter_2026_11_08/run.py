from pathlib import Path
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
FIB=HERE.parents[1]
SOURCE=FIB/'forschung'/'untersuchung_2026_11_08'/'events.pkl'
CUT=pd.Timestamp('2026-01-01',tz='UTC')
RECENT=pd.Timestamp('2026-10-15',tz='UTC')

def enrich():
    E=pd.read_pickle(SOURCE).sort_values(['ts','coin','cfg']).reset_index(drop=True)
    parts=[]
    for n,((coin,tf),g) in enumerate(E.groupby(['coin','tf']),1):
        path=FIB/'data'/'cache'/f'{coin}-USDT-USDT_{tf}.csv'
        d=pd.read_csv(path);d.index=pd.to_datetime(d.iloc[:,0],utc=True)
        d=d[['high','low','close','volume']].astype(float).sort_index()
        d=d[~d.index.duplicated()]
        h,l,c=d.high,d.low,d.close
        tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
        ema=c.ewm(span=200,adjust=False,min_periods=200).mean()
        gain=c.diff().clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
        loss=(-c.diff()).clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
        up=h.diff();down=-l.diff()
        plus=pd.Series(np.where((up>down)&(up>0),up,0),index=d.index).ewm(alpha=1/14,adjust=False).mean()/atr
        minus=pd.Series(np.where((down>up)&(down>0),down,0),index=d.index).ewm(alpha=1/14,adjust=False).mean()/atr
        adx=(100*(plus-minus).abs()/(plus+minus)).ewm(alpha=1/14,adjust=False).mean()
        feats=pd.DataFrame(dict(atr_pct=100*atr/c,ema_dist=c-ema,ema_slope=ema-ema.shift(10),
             vol_ratio=d.volume/d.volume.rolling(20).mean(),rsi=100-100/(1+gain/loss),adx=adx))
        # Index ist Zeitpunkt, ab dem die Kerze vollstaendig bekannt ist.
        feats.index=feats.index+pd.Timedelta(tf)
        pos=feats.index.searchsorted(pd.DatetimeIndex(g.ts),side='right')-1
        valid=pos>=0
        x=feats.iloc[np.maximum(pos,0)].reset_index(drop=True)
        x.loc[~valid,:]=np.nan
        q=g.reset_index(drop=True).join(x)
        side=np.where(q.dir=='long',1,-1)
        q['ema_ok']=side*q.ema_dist>0
        q['slope_ok']=side*q.ema_slope>0
        q['stop_atr']=q.risk_pct/q.atr_pct
        q['eligible']=np.isfinite(q.ema_dist)&(q.risk_pct>0)&np.isfinite(q.atr_pct)
        q['net_R']=q.R-np.where(q.win,0,.0002/(q.risk_pct/100))
        hours=(pd.to_datetime(q.exit_ts,utc=True)-pd.to_datetime(q.ts,utc=True)).dt.total_seconds()/3600
        q['stress_R']=q.net_R-(.0015+.0001*np.ceil(np.maximum(hours,0)/8))/(q.risk_pct/100)
        parts.append(q)
        if n%50==0:print('features',n,flush=True)
    T=pd.concat(parts,ignore_index=True).sort_values(['ts','coin','cfg']).reset_index(drop=True)
    T.to_pickle(HERE/'features.pkl')
    return T

def masks(T):
    out={'BASE':pd.Series(True,index=T.index),'EMA200':T.ema_ok,'EMA200_SLOPE':T.ema_ok&T.slope_ok}
    for s in (1,1.5,2,2.5):
        out[f'STOP_ATR_{s}']=T.stop_atr>=s
        out[f'EMA_STOP_{s}']=T.ema_ok&(T.stop_atr>=s)
    for rr in (2,3,5):out[f'RR_MAX_{rr}']=T.rr<=rr
    for rr in (3,5):out[f'EMA_RR_{rr}']=T.ema_ok&(T.rr<=rr)
    for s in (1.5,2):out[f'EMA_STOP_{s}_RR3']=T.ema_ok&(T.stop_atr>=s)&(T.rr<=3)
    out['VOL1']=T.vol_ratio>=1
    out['ADX25']=T.adx>=25
    out['RSI40_60']=T.rsi.between(40,60)
    out['EMA_STOP_1.5_VOL1']=T.ema_ok&(T.stop_atr>=1.5)&(T.vol_ratio>=1)
    return {k:(v&T.eligible).values for k,v in out.items()}

def replay(T,mask):
    busy={};keep=[]
    for i in np.flatnonzero(mask):
        r=T.iloc[i]
        if r.coin in busy and r.ts<=busy[r.coin]:continue
        busy[r.coin]=r.exit_ts;keep.append(i)
    return T.iloc[keep].copy()

def stats(t):
    if not len(t):return {'n':0}
    pc=t.groupby('coin').net_R.sum();bad=pc.nlargest(5).index
    return dict(n=len(t),R=float(t.net_R.mean()),sum_R=float(t.net_R.sum()),
          stress_R=float(t.stress_R.mean()),win=float(t.win.mean()),
          without_top5_R=float(t[~t.coin.isin(bad)].net_R.mean()),coins=len(pc))

def boot(t):
    d=t.groupby(t.ts.dt.floor('D')).net_R.sum()
    if len(d)<2:return [float('nan')]*2
    d=d.reindex(pd.date_range(d.index.min(),d.index.max(),freq='D'),fill_value=0)
    blocks=[g.values for _,g in d.groupby(np.arange(len(d))//28)]
    rng=np.random.default_rng(20261108)
    means=[np.concatenate([blocks[j] for j in rng.integers(0,len(blocks),len(blocks))]).mean() for _ in range(2000)]
    return [float(x) for x in np.quantile(means,[.025,.975])]

def main():
    T=enrich()
    coins=np.array(sorted(T.coin.unique()));perm=np.random.default_rng(20261108).permutation(coins)
    A=set(perm[:len(perm)//2]);B=set(perm[len(perm)//2:])
    rules=masks(T);results={};replays={}
    for name,mask in rules.items():
        t=replay(T,mask);replays[name]=t
        search=t[t.coin.isin(A)&(t.exit_ts<CUT)]
        checks={
          'B_before2026':t[t.coin.isin(B)&(t.ts<CUT)&(t.exit_ts<CUT)],
          'A_2026':t[t.coin.isin(A)&(t.ts>=CUT)&(t.exit_ts<RECENT)],
          'B_2026':t[t.coin.isin(B)&(t.ts>=CUT)&(t.exit_ts<RECENT)],
          'recent':t[t.ts>=RECENT]}
        results[name]={'search':stats(search),'all':stats(t),'selected38_subset_of_universe_replay':stats(t[t.selected]),
                       **{k:stats(v) for k,v in checks.items()}}
        print(name,results[name]['search'],flush=True)
    candidates=[k for k in results if k!='BASE' and results[k]['search']['n']>=200]
    chosen=max(candidates,key=lambda k:results[k]['search']['R'])
    # Selection frozen before any validation-dependent branching.
    (HERE/'chosen.json').write_text(json.dumps({'rule':chosen,'criterion':'highest training mean net R; >=200 trades'},indent=2))
    t=replays[chosen]
    valid=t[((t.coin.isin(B)&(t.exit_ts<CUT))|((t.ts>=CUT)&(t.exit_ts<RECENT)))]
    ci=boot(valid)
    r=results[chosen]
    passed=all(r[k].get('n',0)>=50 and r[k].get('R',-1)>0 and r[k].get('stress_R',-1)>0 and r[k].get('without_top5_R',-1)>0 for k in ('B_before2026','A_2026','B_2026')) and ci[0]>0
    result=dict(rules=results,chosen=chosen,validation_daily_R_ci=ci,passed=bool(passed),
                eligible=int(T.eligible.sum()),events=len(T),configs=T.cfg.nunique())
    (HERE/'results.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    t.to_csv(HERE/'chosen_trades.csv',index=False)
    lines=['# Suche nach einem trennenden Konfluenzfilter','',
      f'{len(T)} historische Ereignisse, {T.cfg.nunique()} Configs; {int(T.eligible.sum())} mit gueltigen Vorabmerkmalen. '
      'Bereits untersuchte und fuer Parameteroptimierung verwendete Historie. Kein frischer Profitabilitaetsnachweis. '
      'Pro Coin eine Position, alle Timeframes gemeinsam; kein Kontokapitalmodell.','',
      f'Nur aus Trainingsdaten ausgewaehlt: **{chosen}**. Diagnostische Robustheitspruefung: **{"bestanden" if passed else "nicht bestanden"}**. '
      f'95%-Blockbootstrapintervall der taeglichen R-Summen in vereinigten Pruefsegmenten: {ci}.','',
      '| Regel | Suche A vor 2026 R (n) | Pruefung B vor 2026 R (n) | A 2026 R (n) | B 2026 R (n) | Ab 15.10. R (n) |',
      '|---|---:|---:|---:|---:|---:|']
    for name,r in results.items():
        cells=[f'{r[k].get("R",np.nan):+.3f} ({r[k]["n"]})' for k in ('search','B_before2026','A_2026','B_2026','recent')]
        lines.append('| '+name+' | '+' | '.join(cells)+' |')
    lines+=['','## Ausgewaehlter Kandidat im Detail','',json.dumps(results[chosen],indent=2),'',
      '## Grenzen','',
      '- Historische Config-Optimierung und wiederverwendete Daten beschraenken die Aussagekraft aller Segmente.',
      '- Quellexport enthaelt nur geschlossene Ereignisse. Am Datenende noch offene Positionen fehlen; kein vollstaendiger Live-Replay.',
      '- Ereignisfolge des urspruenglichen Detektors bleibt fix. Ein Filter erzeugt keine neuen Impuls-Setups.',
      '- Gebuehren und konservativer Stop-Schlupf enthalten; kein historisches Funding, Orderbuch oder Intrabar-Replay.',
      '- Netto-R statt Trefferquote entscheidet. Eine nachtraeglich auf die sieben Gewinner zugeschnittene Regel ist kein belastbarer Filter.',
      '- Produktionscode und settings.json wurden nicht geaendert.']
    (HERE/'ERGEBNIS.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print('CHOSEN',chosen,'PASSED',passed,'CI',ci,flush=True)

if __name__=='__main__':main()
