from pathlib import Path
import numpy as np
import pandas as pd

VARIANTEN = ['impuls_382', 'impuls_618']
COLS = ['coin','tf','dir','ts','exit_ts','ret','stress_ret']

def simulate(df, coin, variante):
    """Timestamps are bar OPEN times. Orders depend exclusively on previous bars."""
    if variante not in VARIANTEN:
        raise ValueError(variante)
    d = df.copy()
    d['timestamp'] = pd.to_datetime(d.timestamp, utc=True)
    if not d.timestamp.is_monotonic_increasing or d.timestamp.duplicated().any():
        raise ValueError('Unsorted or duplicate timestamps')
    o,h,l,c = [d[k].to_numpy(float) for k in ['open','high','low','close']]
    ts = d.timestamp.to_numpy()
    prev = d.close.shift(1)
    tr = pd.concat([d.high-d.low,(d.high-prev).abs(),(d.low-prev).abs()],axis=1).max(axis=1)
    atr = tr.rolling(14,min_periods=14).mean().to_numpy()
    hi = d.high.shift(1).rolling(20).max().to_numpy()
    lo = d.low.shift(1).rolling(20).min().to_numpy()
    f = .382 if variante == 'impuls_382' else .618
    rows=[]
    pos=None
    pending=None
    for i in range(21,len(d)):
        # Missing candles invalidate pending orders. Positions survive gaps, with gap stops.
        contiguous = pd.Timestamp(ts[i])-pd.Timestamp(ts[i-1]) == pd.Timedelta(hours=4)
        if not contiguous:
            pending=None
        if pos is None and pending is not None:
            side,entry,stop,target,a,expiry = pending
            if i > expiry:
                pending=None
            elif l[i] <= entry <= h[i]:
                pos=(side,entry,stop,target,i)
                pending=None
        if pos is not None:
            side,entry,stop,target,j=pos
            out=None
            maker=False
            if side==1:
                if l[i]<=stop: out=min(stop,o[i])
                elif h[i]>=target: out=target; maker=True
            else:
                if h[i]>=stop: out=max(stop,o[i])
                elif l[i]<=target: out=target; maker=True
            if out is None and i-j>=18:
                out=c[i]
            if out is not None:
                # Entry maker .02%; exit maker .02% or taker .06% + .02% slippage.
                end=pd.Timestamp(ts[i]) + pd.Timedelta(hours=4)
                start=pd.Timestamp(ts[j])
                funding=.01*(end-start).total_seconds()/(8*3600)
                cost=.02+(.02 if maker else .08)+funding
                gross=100*side*(out/entry-1)
                rows.append([coin,'4h','long' if side==1 else 'short',start,end,gross-cost,gross-2*cost])
                pos=None
            # Do not generate another order while position existed in this bar.
            continue
        if pending is not None:
            continue
        if not np.isfinite(atr[i]) or atr[i]<=0:
            continue
        # Large directional body, close outside prior 20-bar range, near bar extreme.
        side=1 if c[i]>hi[i] else (-1 if c[i]<lo[i] else 0)
        if side==0 or side*(c[i]-o[i])<1.5*atr[i] or h[i]-l[i]>4*atr[i]:
            continue
        if (h[i]-c[i] if side==1 else c[i]-l[i])>.25*(h[i]-l[i]):
            continue
        anchor=l[i] if side==1 else h[i]
        extreme=h[i] if side==1 else l[i]
        entry=extreme-side*f*(h[i]-l[i])
        stop=entry-side*max(atr[i],side*(entry-anchor)+.25*atr[i])
        target=extreme+side*.618*(h[i]-l[i])
        pending=(side,entry,stop,target,atr[i],i+3)
    # Open positions are deliberately not liquidated at the input boundary.
    return pd.DataFrame(rows,columns=COLS)

def trades(root: str, variante: str) -> pd.DataFrame:
    if variante not in VARIANTEN:
        raise ValueError(variante)
    results=[]
    for path in sorted((Path(root)/'4h').glob('*_4h.csv')):
        results.append(simulate(pd.read_csv(path),path.name[:-7],variante))
    return pd.concat(results,ignore_index=True) if results else pd.DataFrame(columns=COLS)
