"""Frozen causal filters. Inputs may contain OOS rows; no file/network access."""
import numpy as np
import pandas as pd


def btc_features(T, btc_daily):
    b = btc_daily.copy()
    b['day'] = pd.to_datetime(b['timestamp'], utc=True).dt.floor('D')
    b = b.sort_values('day')
    if b.day.duplicated().any():
        raise ValueError('Duplicate BTC days')
    b['sma200'] = b.close.rolling(200, min_periods=200).mean()
    b['ret20'] = b.close.pct_change(20, fill_method=None)
    # Strictly before the entry day, including entries at midnight.
    q = pd.DataFrame({'day': pd.to_datetime(T.ts, utc=True).dt.floor('D'),
                      'order': np.arange(len(T))}).sort_values('day')
    z = pd.merge_asof(q, b[['day', 'close', 'sma200', 'ret20']],
                      on='day', direction='backward', allow_exact_matches=False)
    return z.sort_values('order').reset_index(drop=True)


def masks(T, btc_daily):
    b = btc_features(T, btc_daily)
    long = T.dir.to_numpy() == 'long'
    bull = (b.close > b.sma200).to_numpy()
    known = b.sma200.notna().to_numpy()
    regime = known & (long == bull)
    raw = {
        'structural_stop': T.stop_atr.between(1, 3) & (T.risk_pct >= 1),
        'cost_buffer': (T.risk_pct >= 1) & (T.rr >= 2),
        'regime_cost_buffer': regime & (T.risk_pct >= 1),
    }
    return {k: np.asarray(v, dtype=bool) for k, v in raw.items()}


def replay(T, mask):
    """Stable chronological replay; ties preserve input order, <= is excluded."""
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != (len(T),):
        raise ValueError('Mask length')
    order = np.argsort(pd.to_datetime(T.ts, utc=True).array.asi8, kind='stable')
    busy, keep = {}, []
    for i in order:
        if not mask[i] or not bool(T.iloc[i].eligible):
            continue
        r = T.iloc[i]
        if r.coin in busy and r.ts <= busy[r.coin]:
            continue
        busy[r.coin] = r.exit_ts
        keep.append(i)
    return T.iloc[keep]


def stats(T, n_boot=2000, seed=17020):
    """28-calendar-day block bootstrap, including empty blocks, ratio of sums."""
    if not len(T):
        return {'n': 0, 'net_R': None, 'stress_R': None,
                'without_top5_net_R': None, 'without_top5_n': 0, 'ci95': [None, None]}
    top = T.groupby('coin').net_R.sum().nlargest(5).index
    rest = T[~T.coin.isin(top)]
    days = pd.to_datetime(T.ts, utc=True)
    blocks = ((days - days.min().floor('D')).dt.total_seconds() // (28*86400)).astype(int)
    g = T.assign(block=blocks.to_numpy()).groupby('block').net_R.agg(['sum', 'count'])
    g = g.reindex(range(int(blocks.max())+1), fill_value=0)
    rng = np.random.default_rng(seed)
    ix = rng.integers(0, len(g), size=(n_boot, len(g)))
    sums, counts = g['sum'].to_numpy()[ix].sum(1), g['count'].to_numpy()[ix].sum(1)
    boot = sums[counts > 0] / counts[counts > 0]
    return {'n': len(T), 'net_R': float(T.net_R.mean()),
            'stress_R': float(T.stress_R.mean()),
            'without_top5_net_R': float(rest.net_R.mean()) if len(rest) else None,
            'without_top5_n': len(rest), 'top5': list(top),
            'ci95': np.quantile(boot, [.025, .975]).tolist()}
