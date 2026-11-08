"""Mathematische Diagnose von Netto-R; keine Signal- oder Sizing-Freigabe."""
import numpy as np
import pandas as pd


def _values(values):
    x=np.asarray(values,dtype=float)
    if x.ndim!=1 or not len(x) or not np.isfinite(x).all():
        raise ValueError('Mindestens ein endlicher Netto-R-Wert erforderlich; keine NaN/Inf.')
    return x


def edge_metrics(net_r, gross_r=None):
    x=_values(net_r);wins=x[x>0];losses=x[x<0]
    p=len(wins)/len(x);q=len(losses)/len(x)
    w=float(wins.mean()) if len(wins) else None
    l=float(-losses.mean()) if len(losses) else None
    payoff=w/l if w is not None and l is not None else None
    needed=(p+q)*l/(w+l) if payoff is not None else None
    result=dict(n=len(x),wins=len(wins),losses=len(losses),breakeven=int((x==0).sum()),
        win_rate=p,avg_win_r=w,avg_loss_r=l,payoff=payoff,
        break_even_win_rate=needed,expectancy_r=float(x.mean()),
        profit_factor=float(wins.sum()/-losses.sum()) if len(losses) else None,
        win_rate_margin=p-needed if needed is not None else None)
    if gross_r is not None:
        g=_values(gross_r)
        if len(g)!=len(x):raise ValueError('Brutto-/Netto-Reihen muessen gleich lang sein.')
        result.update(gross_expectancy_r=float(g.mean()),mean_cost_r=float((g-x).mean()))
    return result


def growth_metrics(net_r,fraction):
    x=_values(net_r)
    if not np.isfinite(fraction) or fraction<0:raise ValueError('Risikoanteil muss endlich und nichtnegativ sein.')
    factors=1+fraction*x
    if (factors<=0).any():
        return dict(fraction=fraction,insolvent=True,mean_log_growth=None,total_return=None,max_drawdown=None)
    logs=np.log1p(fraction*x)
    eq=np.r_[1.,np.exp(np.cumsum(logs))]
    if not np.isfinite(eq).all():raise ValueError('Wachstum numerisch nicht endlich; Risiko/Zeitraum zu gross.')
    dd=1-eq/np.maximum.accumulate(eq)
    return dict(fraction=fraction,insolvent=False,mean_log_growth=float(logs.mean()),
                total_return=float(eq[-1]-1),max_drawdown=float(dd.max()),
                arithmetic_trade_return=float((fraction*x).mean()))


def empirical_log_optimum(net_r,cap=1.):
    """Maximum der Stichproben-log-Wachstumsrate, KEINE Risikorempfehlung."""
    x=_values(net_r)
    if not np.isfinite(cap) or cap<=0:raise ValueError('Positive endliche Obergrenze erforderlich.')
    if x.mean()<=0:return 0.
    upper=min(cap,(1-1e-10)/-x.min()) if x.min()<0 else cap
    # Ableitung des konkaven Mittelwerts log(1+fR).
    def derivative(f):return np.mean(x/(1+f*x))
    if derivative(upper)>=0:return float(upper)
    lo,hi=0.,upper
    for _ in range(80):
        mid=(lo+hi)/2
        if derivative(mid)>0:lo=mid
        else:hi=mid
    return float((lo+hi)/2)


def recovery_required(drawdown):
    if not np.isfinite(drawdown) or not 0<=drawdown<1:raise ValueError('Drawdown muss in [0,1) liegen.')
    return drawdown/(1-drawdown)


def calendar_blocks(net_r,exit_times,days=28):
    x=_values(net_r);times=pd.DatetimeIndex(pd.to_datetime(exit_times,utc=True,errors='raise'))
    if len(times)!=len(x) or pd.isna(times).any():raise ValueError('Gueltiger Ausstiegszeitpunkt je Trade erforderlich.')
    if not isinstance(days,int) or days<1:raise ValueError('Positive ganze Blocklaenge erforderlich.')
    t=pd.DataFrame({'r':x,'day':times.floor('D')}).sort_values('day')
    # Gemeinsame Kalendertage bleiben beisammen; keine kuenstlichen Null-Trades.
    ids=((t.day-t.day.min()).dt.days//days).values
    return [t.r.values[ids==k] for k in range(int(ids.max())+1)]


def block_bootstrap(net_r,exit_times,fraction,days=28,samples=2000,seed=20261108):
    x=_values(net_r);blocks=calendar_blocks(x,exit_times,days)
    if len(blocks)<3:
        return dict(status='zu wenige Kalenderbloecke',blocks=len(blocks),expectancy_ci=None)
    if not isinstance(samples,int) or samples<100:raise ValueError('Mindestens 100 Stichproben erforderlich.')
    rng=np.random.default_rng(seed);means=[];returns=[];dds=[];insolvent=0
    for _ in range(samples):
        seq=np.concatenate([blocks[i] for i in rng.integers(0,len(blocks),len(blocks))])
        if not len(seq):continue
        means.append(float(seq.mean()));g=growth_metrics(seq,fraction)
        if g['insolvent']:
            insolvent+=1;returns.append(-1.);dds.append(1.)
        else:returns.append(g['total_return']);dds.append(g['max_drawdown'])
    return dict(status='empirisches Kalendertage-Blockmodell',blocks=len(blocks),samples=len(means),
        expectancy_ci=[float(a) for a in np.quantile(means,[.025,.975])],
        return_percentiles=[float(a) for a in np.quantile(returns,[.05,.5,.95])],
        drawdown_percentiles=[float(a) for a in np.quantile(dds,[.05,.5,.95])],
        loss_fraction=float(np.mean(np.array(returns)<0)),
        dd30_fraction=float(np.mean(np.array(dds)>.30)),insolvent_fraction=insolvent/len(means))
