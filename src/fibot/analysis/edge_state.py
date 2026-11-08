"""Kausale BTC-Tagesregime und gemeinsame Unsicherheit von Payoff/Gewinnquote."""
import numpy as np
import pandas as pd
from fibot.analysis.edge_math import edge_metrics, calendar_blocks

MIN_TRADES = 30
BLOCK_DAYS = 28
MIN_BLOCKS = 3


def market_states(daily):
    required={'high','low','close'}
    if not required.issubset(daily):raise ValueError('OHLC-Tagesdaten erforderlich.')
    d=daily.sort_index().copy()
    if not isinstance(d.index,pd.DatetimeIndex) or d.index.tz is None:
        raise ValueError('Zeitzonenbewusster Tagesindex erforderlich.')
    d.index=d.index.tz_convert('UTC')
    if d.index.has_duplicates:raise ValueError('Doppelte Tageskerzen nicht erlaubt.')
    if not (d.index==d.index.floor('D')).all():raise ValueError('Tageskerzen muessen um UTC-Mitternacht beginnen.')
    if not np.isfinite(d[['high','low','close']].values).all() or (d.close<=0).any() or (d.high<d.low).any():
        raise ValueError('Endliche, positive und geordnete OHLC-Daten erforderlich.')
    c=d.close.astype(float)
    tr=pd.concat([d.high-d.low,(d.high-c.shift()).abs(),(d.low-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    ema=c.ewm(span=50,adjust=False,min_periods=50).mean()
    vol=atr/c
    # Schwellen stammen ausschliesslich aus vorherigen Tagen.
    low=vol.shift(1).rolling(252,min_periods=126).quantile(1/3)
    high=vol.shift(1).rolling(252,min_periods=126).quantile(2/3)
    trend=np.where(c>ema+atr,'up',np.where(c<ema-atr,'down','range'))
    trend=np.where(ema.notna()&atr.notna(),trend,'unknown')
    volatility=np.where(vol<low,'low',np.where(vol>high,'high','mid'))
    volatility=np.where(low.notna()&high.notna(),volatility,'unknown')
    out=pd.DataFrame(dict(trend=trend,volatility=volatility,close=c,ema50=ema,atr14=atr,atr_pct=100*vol),index=d.index)
    out.index=out.index.tz_convert('UTC')+pd.Timedelta(days=1)
    out.index.name='known_at'
    return out


def attach_states(trades,states):
    t=trades.copy()
    ts=pd.DatetimeIndex(pd.to_datetime(t.entry_ts,utc=True))
    if states.empty:
        t['trend']='unknown';t['volatility']='unknown';return t
    if not states.index.is_monotonic_increasing:raise ValueError('Zustandsreihe muss sortiert sein.')
    pos=states.index.searchsorted(ts,side='right')-1
    for name in ('trend','volatility'):
        values=states[name].values
        t[name]=np.where(pos>=0,values[np.maximum(pos,0)],'unknown')
    return t


def state_at(states,as_of):
    if states.empty:return None
    pos=states.index.searchsorted(pd.Timestamp(as_of),side='right')-1
    if pos<0:return None
    return {'known_at':states.index[pos].isoformat(),**states.iloc[pos].to_dict()}


def frontier_point(values):
    m=edge_metrics(values)
    nonzero=m['wins']+m['losses']
    # Null-Trades beeinflussen die Erwartung, aber nicht den gezeichneten
    # bedingten Punkt. So bleibt die feste Kurve p=1/(1+b) korrekt.
    return dict(metrics=m,x=m['payoff'],
                y=m['wins']/nonzero if nonzero else None)


def uncertainty(values,known_at,samples=500,seed=20261108):
    if not isinstance(samples,int) or samples<100:raise ValueError('Mindestens 100 Stichproben erforderlich.')
    x=np.asarray(values,dtype=float)
    point=frontier_point(x)
    groups=calendar_blocks(x,known_at,BLOCK_DAYS)
    nonempty=sum(bool(len(g)) for g in groups)
    if len(x)<MIN_TRADES or nonempty<MIN_BLOCKS:
        return dict(status='insufficient',n=len(x),nonempty_blocks=nonempty,
                    point=point,cloud=[],expectancy_ci=None)
    # Derselbe explizite Generator wie im Offline-Browser, damit Zahlen und
    # Evidenzstatus nicht durch unterschiedliche Zufallsalgorithmen abweichen.
    state=seed&0xffffffff
    def random():
        nonlocal state
        state^=(state<<13)&0xffffffff
        state^=state>>17
        state^=(state<<5)&0xffffffff
        state&=0xffffffff
        return state/4294967296
    cloud=[];means=[]
    for _ in range(samples):
        seq=np.concatenate([groups[int(random()*len(groups))] for _ in groups])
        if not len(seq):continue
        m=frontier_point(seq);means.append(m['metrics']['expectancy_r'])
        if m['x'] is not None and m['y'] is not None:cloud.append([m['x'],m['y']])
    lo,hi=np.quantile(means,[.025,.975])
    verdict='positive' if lo>0 else ('negative' if hi<0 else 'unclear')
    return dict(status=verdict,n=len(x),nonempty_blocks=nonempty,point=point,
                cloud=cloud,expectancy_ci=[float(lo),float(hi)])


def rolling_points(trades,window=50,step=5):
    if window<2 or step<1:raise ValueError('Fenster >=2 und Schritt >=1 erforderlich.')
    t=trades.sort_values('known_at',kind='stable')
    ends=list(range(window,len(t)+1,step))
    if len(t)>=window and (not ends or ends[-1]!=len(t)):ends.append(len(t))
    result=[]
    for n in ends:
        q=t.iloc[n-window:n];p=frontier_point(q.net_r.values)
        result.append(dict(known_at=q.known_at.iloc[-1].isoformat(),x=p['x'],y=p['y'],
                           expectation=p['metrics']['expectancy_r'],n=len(q)))
    return result
