import pickle,json
from concurrent.futures import ProcessPoolExecutor
import run as R

SETTINGS={'wait2':(2,1,1),'wait6':(6,1,1),'pressure075':(4,.75,1),
          'pressure125':(4,1.25,1),'energy075':(4,1,.75),'energy125':(4,1,1.25)}

def job(coin):
    df=R.H._read(str(R.Path(R.H.GEO)/f'{coin}-USDT-USDT_4h.csv')).iloc[:-1]
    with open(R.HERE/'events_cache'/f'{coin}_4h.pkl','rb') as f: ev=pickle.load(f)
    rows=[]
    for label,(wait,pressure,energy) in SETTINGS.items():
        R.WAIT_BARS,R.PRESSURE_RATIO,R.ENERGY_RATIO=wait,pressure,energy
        for t in R.simulate(df,ev,'PE'): rows.append(dict(t,coin=coin,setting=label))
    return rows

def main():
    coins=sorted(p.stem.rsplit('_',1)[0] for p in (R.HERE/'events_cache').glob('*_4h.pkl'))
    assert len(coins)==len(R.H.load_universe('4h')), '4h event generation incomplete'
    rows=[]
    with ProcessPoolExecutor(max_workers=6) as pool:
        for n,part in enumerate(pool.map(job,coins),1):
            rows.extend(part)
            if n%25==0:print(n,len(coins),flush=True)
    t=R.pd.DataFrame(rows);t.to_csv(R.HERE/'sensitivity_trades.csv',index=False)
    result={}
    for label,s in t.groupby('setting'):
        result[label]={'all':R.stats(s),'before2026':R.stats(s[s.entry_ts<R.pd.Timestamp('2026-01-01',tz='UTC')]),
                       '2026':R.stats(s[s.entry_ts>=R.pd.Timestamp('2026-01-01',tz='UTC')])}
    (R.HERE/'sensitivity_results.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    for k,v in result.items():print(k,v,flush=True)

if __name__=='__main__':main()
