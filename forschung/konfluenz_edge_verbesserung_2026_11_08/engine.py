"""Gemeinsame Forschungs-Ausfuehrung fuer alle Geometrievarianten. Kein Live-Pfad."""
import numpy as np
import pandas as pd

FEE=.0006
SLIP=.0002
VARIANTS=[f'{entry}_{stop}_{target}' for entry in ('L','C') for stop in ('S','A2') for target in ('K','R15','R20','R30')]+['L_S_H','C_S_H']
BASE='L_S_K'


def atr_before(df):
    c=df.close
    tr=pd.concat([df.high-df.low,(df.high-c.shift()).abs(),(df.low-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean().shift(1).values


def find_exit(o,h,l,i,entry,sl,tp,side):
    """Nur Preisverlauf. SL vor TP, TP nicht in Entry-Kerze, konservative Gaps."""
    low=l if side==1 else -h;high=h if side==1 else -l
    stops=np.flatnonzero(low[i:]<=side*sl)
    targets=np.flatnonzero(high[i+1:]>=side*tp)
    a=i+int(stops[0]) if len(stops) else len(o)
    b=i+1+int(targets[0]) if len(targets) else len(o)
    if a==len(o) and b==len(o):return None,None,'open'
    if a<=b:
        norm=min(side*sl,side*o[a])
        xp=side*norm-side*SLIP*abs(norm)
        return a,xp,'sl'
    return b,tp,'tp'


def candidates(df,cfg,variant,trend_allowed=None):
    entry_mode,stop_mode,target=variant.split('_')
    o,h,l,c=[df[k].values for k in ('open','high','low','close')]
    atr=atr_before(df);delta=pd.Timedelta(cfg['market']['timeframe'])
    rows=[]
    for touch in np.flatnonzero(df['_sig_dir'].values):
        side=1 if df['_sig_dir'].iloc[touch]==1 else -1
        ep=float(df['_sig_entry'].iloc[touch]);sl=float(df['_sig_sl'].iloc[touch]);oldtp=float(df['_sig_tp1'].iloc[touch])
        i=touch
        if entry_mode=='C':
            i=None
            for q in range(touch,min(len(c)-1,touch+4)):
                if side==1 and l[q]<=sl or side==-1 and h[q]>=sl:break
                if q>touch and df.index[q]-df.index[q-1]!=delta:break
                if side*(c[q]-ep)>0 and side*(c[q]-o[q])>0:
                    i=q+1;break
            if i is None or df.index[i]-df.index[i-1]!=delta:continue
            if trend_allowed is not None and not trend_allowed(side,df.index[i]):continue
            ep=float(o[i])*(1+side*SLIP)
        if side*(ep-sl)<=0:continue
        if stop_mode=='A2':
            if not np.isfinite(atr[i]) or atr[i]<=0:continue
            sl=side*min(side*sl,side*ep-2*atr[i])
        risk=side*(ep-sl)
        if risk<=0 or min(ep,sl)<=0:continue
        if target=='K':tp=oldtp
        elif target=='H':tp=ep+.5*(oldtp-ep)
        else:tp=ep+side*{'R15':1.5,'R20':2.,'R30':3.}[target]*risk
        if tp<=0 or side*(tp-ep)<=0:continue
        j,xp,res=find_exit(o,h,l,i,ep,sl,tp,side)
        net=None if j is None else (side*(xp-ep)-FEE*(abs(ep)+abs(xp)))/risk
        rows.append(dict(touch_ts=df.index[touch],entry_ts=df.index[i],exit_ts=df.index[j] if j is not None else None,
            known_at=df.index[j]+delta if j is not None else None,entry=ep,sl=sl,tp=tp,exit=xp,
            net_r=net,result=res,side=side,risk=risk,risk_pct=risk/ep,tf=cfg['market']['timeframe']))
    return rows


def outcome(row,end,frame,stress=False):
    """Ergebnis nur bis zur jeweiligen Auswertungsgrenze sichtbar machen."""
    closed=row['known_at'] is not None and row['known_at']<=end
    if closed:
        known=row['known_at'];price=row['exit'];r=row['net_r']
    else:
        delta=pd.Timedelta(row['tf'])
        pos=frame.index.searchsorted(end-delta,side='right')-1
        if pos<0 or frame.index[pos]<row['entry_ts']:
            price=row['entry']
        else:price=float(frame.close.iloc[pos])
        known=end
        r=(row['side']*(price-row['entry'])-FEE*(abs(row['entry'])+abs(price)))/row['risk']
    if stress:
        hours=max(0,(known-row['entry_ts']).total_seconds()/3600)
        r-=(.0015+.0001*np.ceil(hours/8))/row['risk_pct']
    return closed,float(r),known,float(price)


def isolated(rows,frame,cfg,start,end,capital=60.,stress=False):
    equity=capital;busy=None;pending=None;closed=[];opens=[]
    leverage=float(cfg['risk'].get('leverage',3));risk_fraction=float(cfg['risk'].get('risk_per_entry_pct',1))/100
    for row in sorted(rows,key=lambda r:r['entry_ts']):
        if row['entry_ts']<start or row['touch_ts']<start or row['entry_ts']>=end:continue
        if busy is not None and row['entry_ts']<busy:continue
        if pending is not None:
            equity+=pending['pnl'];pending=None
        if equity<=0:break
        notional=min(equity*risk_fraction/row['risk_pct'],equity*leverage)
        if notional<5:continue
        risk_usdt=notional*row['risk_pct']
        done,r,known,price=outcome(row,end,frame,stress)
        record={**row,'net_r':r,'known_at':known,'pnl':risk_usdt*r,'notional':notional,
                'coin':cfg['market']['symbol'].split('/')[0],
                'direction':'long' if row['side']==1 else 'short','gross_r':row['side']*(price-row['entry'])/row['risk']}
        if not done:
            opens.append(record);break
        closed.append(record);pending=record;busy=known
    if pending is not None:equity+=pending['pnl']
    return closed,opens,equity


def mark_price(frame,tf,when,entry_ts,entry):
    p=frame.index.searchsorted(when-pd.Timedelta(tf),side='right')-1
    return float(frame.close.iloc[p]) if p>=0 and frame.index[p]>=entry_ts else entry


def portfolio(all_rows,frames,configs,start,end,capital=60.,stress=False,max_positions=9):
    rows=[]
    for key,items in all_rows.items():
        rows.extend([{**r,'key':key,'coin':configs[key]['market']['symbol'].split('/')[0]} for r in items
                     if start<=r['entry_ts']<end and r['touch_ts']>=start])
    rows.sort(key=lambda r:(r['entry_ts'],r['key']))
    at={}
    for r in rows:at.setdefault(r['entry_ts'],[]).append(r)
    times=set(pd.date_range(start,end,freq='15min'));times.add(end)
    for r in rows:
        if r['known_at'] is not None and r['known_at']<=end:times.add(r['known_at'])
    live={};equity=capital;ledger=[];curve=[]
    for when in sorted(times):
        for coin,pos in list(live.items()):
            row=pos['row']
            if row['known_at'] is not None and row['known_at']<=when:
                _,r,known,price=outcome(row,end,frames[row['key']],stress)
                pnl=pos['risk_usdt']*r;equity+=pnl
                ledger.append(dict(coin=coin,config=row['key'],entry_ts=row['entry_ts'],known_at=known,
                      tf=row['tf'],net_r=r,pnl=pnl,entry=row['entry'],sl=row['sl'],tp=row['tp']))
                del live[coin]
        if equity<=0:curve.append(dict(ts=when,equity=equity));break
        for row in at.get(when,[]):
            if row['coin'] in live or len(live)>=max_positions:continue
            cfg=configs[row['key']];lev=float(cfg['risk'].get('leverage',3));rf=float(cfg['risk'].get('risk_per_entry_pct',1))/100
            free=equity-sum(p['margin'] for p in live.values())
            notional=min(equity*rf/row['risk_pct'],max(0,free)*lev)
            if notional<5:continue
            live[row['coin']]=dict(row=row,notional=notional,risk_usdt=notional*row['risk_pct'],margin=notional/lev)
        mtm=equity
        for pos in live.values():
            row=pos['row'];price=mark_price(frames[row['key']],row['tf'],when,row['entry_ts'],row['entry'])
            r=(row['side']*(price-row['entry'])-FEE*(row['entry']+price))/row['risk']
            if stress:
                hours=max(0,(when-row['entry_ts']).total_seconds()/3600)
                r-=(.0015+.0001*np.ceil(hours/8))/row['risk_pct']
            mtm+=pos['risk_usdt']*r
        curve.append(dict(ts=when,equity=mtm))
    cv=pd.DataFrame(curve)
    peaks=np.maximum.accumulate(np.r_[capital,cv.equity.values])
    dd=1-np.r_[capital,cv.equity.values]/peaks
    summary=dict(end_equity=float(cv.equity.iloc[-1]),realized_equity=float(equity),
       ret_pct=float((cv.equity.iloc[-1]/capital-1)*100),maxdd_pct=float(dd.max()*100),
       closed=len(ledger),open_end=len(live))
    return summary,pd.DataFrame(ledger),cv
