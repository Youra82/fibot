"""Offline-Diagnose des bestehenden Fibot. Keine Orders, kein Telegram, kein Internet."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from fibot.analysis.edge_state import market_states,attach_states,state_at,frontier_point,uncertainty,rolling_points


def read_cache(root,symbol,tf):
    p=Path(root)/'data'/'cache'/(symbol.replace('/','-').replace(':','-')+f'_{tf}.csv')
    if not p.exists():return pd.DataFrame()
    d=pd.read_csv(p)
    d.index=pd.to_datetime(d.iloc[:,0],utc=True)
    cols=[c for c in ('open','high','low','close','volume') if c in d]
    return d[cols].astype(float).sort_index().loc[lambda x:~x.index.duplicated(keep='last')]


def complete_days(frame,tf):
    """Aus Intraday-Daten nur vollstaendige UTC-Tage bilden."""
    if frame.empty:return pd.DataFrame()
    delta=pd.Timedelta(tf);count=int(pd.Timedelta(days=1)/delta)
    if count*delta!=pd.Timedelta(days=1):raise ValueError('Timeframe teilt UTC-Tag nicht.')
    rows=[]
    for day,g in frame.groupby(frame.index.floor('D')):
        expected=pd.date_range(day,periods=count,freq=delta)
        if len(g)!=count or not g.index.equals(expected):continue
        rows.append(dict(ts=day,open=g.open.iloc[0],high=g.high.max(),low=g.low.min(),close=g.close.iloc[-1]))
    return pd.DataFrame(rows).set_index('ts') if rows else pd.DataFrame()


def daily_history(root,symbol,cutoff,fallback=None,fallback_tf=None):
    primary=read_cache(root,symbol,'1d')
    parts=[primary] if not primary.empty else []
    if fallback is not None and fallback_tf:
        q=complete_days(fallback,fallback_tf)
        if not q.empty:parts.append(q)
    for tf in ('1h','4h'):
        q=read_cache(root,symbol,tf)
        if not q.empty:
            q=complete_days(q,tf)
            if not q.empty:parts.append(q)
    if not parts:return pd.DataFrame()
    d=parts[0]
    for p in parts[1:]:d=d.combine_first(p)
    return d.sort_index().loc[lambda x:x.index+pd.Timedelta(days=1)<=cutoff]


def collect_backtests(cfgs,root,start,cutoff,capital=60.):
    from fibot.analysis import backtester as B,analysis_suite as S
    from fibot.strategy import confluence_logic as C,trend_filter as F
    frames=[];coverage=[]
    for name,cfg in cfgs.items():
        symbol=cfg['market']['symbol'];tf=cfg['market']['timeframe'];delta=pd.Timedelta(tf)
        raw=read_cache(root,symbol,tf)
        if raw.empty:
            coverage.append(dict(config=name,status='missing'));continue
        raw=raw[raw.index+delta<=cutoff]
        if raw.empty or raw.index.max()<start:
            coverage.append(dict(config=name,status='no_period_data'));continue
        # Warmup-Signale rechnen, Konto erst zum gewaehlten Start beginnen.
        warm=start-delta*max(1200,int(cfg.get('strategy',{}).get('window',150))+100)
        df=raw[raw.index>=warm].copy()
        if len(df)<300:
            coverage.append(dict(config=name,status='short_history'));continue
        if C.is_confluence(cfg):
            tc=F.settings();key=None;sentinel=object();previous=sentinel
            if tc['enabled']:
                daily=daily_history(root,symbol,cutoff,raw,tf)
                if daily.empty:
                    coverage.append(dict(config=name,status='missing_daily_trend'));continue
                key=(symbol,tf,(df.index[0]-delta*F.base_bars_needed(tc)).floor('D'),
                     df.index[-1].floor('D'),tuple(sorted(tc.items())))
                previous=C._TREND_CACHE.get(key,sentinel)
                C._TREND_CACHE[key]=(F.htf_trend(raw,tf,tc),F.daily_trend(daily,tc))
            try:prepared=C.precompute_confluence_signals(df,cfg)
            finally:
                if key is not None:
                    if previous is sentinel:C._TREND_CACHE.pop(key,None)
                    else:C._TREND_CACHE[key]=previous
            prepared.loc[prepared.index<start,'_sig_dir']=0
            result=B.run_backtest(prepared,cfg,capital,symbol,tf)
        else:
            coverage.append(dict(config=name,status='unsupported_legacy_fibonacci'));continue
        t=S.trades_frame(result,prepared)
        opened=sum(x.result=='open' for x in result.trades)
        coverage.append(dict(config=name,status='ok',last_close=(df.index[-1]+delta).isoformat(),open_end=opened))
        if t.empty:continue
        t=t[(t.ts>=start)&np.isfinite(t.r_actual)].copy()
        t=t.assign(entry_ts=t.ts,exit_ts=t.exit_ts,known_at=t.exit_ts+delta,net_r=t.r_actual,
                   gross_r=t.r_gross,coin=symbol.split('/')[0],tf=tf,direction=t.dir,config=name)
        frames.append(t[['entry_ts','exit_ts','known_at','net_r','gross_r','coin','tf','direction','config','pnl']])
        print(f'Edge-Dashboard: {symbol} {tf}: {len(t)} geschlossene Trades',flush=True)
    columns=['entry_ts','exit_ts','known_at','net_r','gross_r','coin','tf','direction','config','pnl']
    trades=pd.concat(frames,ignore_index=True).sort_values('known_at',kind='stable') if frames else pd.DataFrame(columns=columns)
    return trades,coverage


def write_dashboard(trades,states,output,metadata):
    from plotly.offline import get_plotlyjs
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    t=attach_states(trades,states)
    cutoff=pd.Timestamp(metadata['as_of'])
    t=t[t.known_at<=cutoff].copy()
    records=[]
    for r in t.itertuples():
        records.append(dict(entry=pd.Timestamp(r.entry_ts).isoformat(),exit=pd.Timestamp(r.exit_ts).isoformat(),
            known=pd.Timestamp(r.known_at).isoformat(),r=float(r.net_r),gross=float(r.gross_r),
            coin=r.coin,tf=r.tf,direction=r.direction,trend=r.trend,volatility=r.volatility,config=r.config))
    market=[]
    available_states=states[states.index<=cutoff] if not states.empty else states
    for when,r in available_states.iterrows():
        market.append(dict(known=when.isoformat(),trend=r.trend,volatility=r.volatility,
                           close=float(r.close),atr_pct=float(r.atr_pct)))
    data=dict(trades=records,market=market,meta=metadata)
    def clean(obj):
        if isinstance(obj,dict):return {k:clean(v) for k,v in obj.items()}
        if isinstance(obj,list):return [clean(v) for v in obj]
        if isinstance(obj,float) and not np.isfinite(obj):return None
        return obj
    data=clean(data)
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False).replace('</','<\\/')
    template=Path(__file__).with_suffix('.html').read_text(encoding='utf8')
    output.write_text(template.replace('__PLOTLY__',get_plotlyjs()).replace('__DATA__',payload),encoding='utf8')
    t.to_csv(output.with_suffix('.csv'),index=False)
    output.with_suffix('.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    return data


def generate(cfgs,start_date,end_date,capital=60.,output=None,root=ROOT):
    if not np.isfinite(capital) or capital<=0:raise ValueError('Positives endliches Startkapital erforderlich.')
    start=pd.Timestamp(start_date,tz='UTC')
    requested=pd.Timestamp(end_date,tz='UTC')+pd.Timedelta(days=1)
    cutoff=min(requested,pd.Timestamp.now(tz='UTC'))
    if start>=cutoff:raise ValueError('Start muss vor dem Ende liegen.')
    trades,coverage=collect_backtests(cfgs,root,start,cutoff,capital)
    btc=daily_history(root,'BTC/USDT:USDT',cutoff)
    states=market_states(btc) if not btc.empty else pd.DataFrame()
    digest=hashlib.sha256(json.dumps(cfgs,sort_keys=True).encode()).hexdigest()
    metadata=dict(as_of=cutoff.isoformat(),start=start.isoformat(),configs=len(cfgs),
        config_sha256=digest,coverage=coverage,capital_per_isolated_backtest=capital,
        source='Historische Einzel-Backtests der aktuell ausgewaehlten Konfluenz-Configs',
        limitations='Keine Live-Trades, kein gemeinsamer Konto-Replay, kein unberuehrter Holdout.',
        regenerated=pd.Timestamp.now(tz='UTC').isoformat())
    codefiles=[Path(__file__).with_name(n) for n in ('edge_dashboard.py','edge_state.py','edge_dashboard.html')]
    codefiles += [Path(__file__).parent.parent/'strategy'/n for n in ('confluence_logic.py','trend_filter.py')]
    codefiles += [Path(__file__).with_name('backtester.py')]
    metadata['logic_sha256']=hashlib.sha256(b''.join(p.read_bytes() for p in codefiles)).hexdigest()
    output=Path(output or Path(root)/'artifacts'/'analysis'/'edge_dashboard.html')
    data=write_dashboard(trades,states,output,metadata)
    print(f'Edge-Dashboard gespeichert: {output} ({len(data["trades"])} Trades)')
    return output,data


def main():
    from fibot.analysis.analysis_suite import load_configs
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--scope',choices=['aktiv','alle'],default='aktiv')
    ap.add_argument('--from',dest='start',default='2026-05-10')
    ap.add_argument('--to',dest='end',default=pd.Timestamp.now(tz='Europe/Berlin').strftime('%Y-%m-%d'))
    ap.add_argument('--capital',type=float,default=60.)
    ap.add_argument('--out')
    a=ap.parse_args();generate(load_configs(a.scope),a.start,a.end,a.capital,a.out)

if __name__=='__main__':main()
