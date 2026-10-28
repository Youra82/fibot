# Jede gefuellte Konfluenz-Order (alle 38 Configs, IS+OOS bis heute) mit Merkmalen zum Order-Zeitpunkt
# (nur Daten bis Kerze i-1) und Verlauf danach (R nach Gebuehren, MFE/MAE in R, Bars bis Ausstieg).
# Aufruf: python features.py <idx> <parts>
import json, os, sys
ROOT = r'C:\Users\matol\Desktop\botprojekte\fibot'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'src')); os.chdir(ROOT)
import logging; logging.disable(logging.WARNING)
import numpy as np, pandas as pd
from fibot.analysis.backtester import load_ohlcv
from fibot.strategy.confluence_logic import plan_both, strategy_params

FEE = 0.0006           # je Seite
TODAY = '2026-10-28'
idx, parts = int(sys.argv[1]), int(sys.argv[2])
CFG = 'src/fibot/strategy/configs'
files = sorted(os.listdir(CFG))[idx::parts]

def daily(sym):
    for st in ('2022-01-01', '2023-06-01', '2024-06-01', '2025-01-01', '2025-06-01', '2025-10-01'):
        d = load_ohlcv(sym, '1d', st, TODAY)
        if not d.empty: break
    c = d.close.astype(float)
    out = pd.DataFrame({'r30': c.pct_change(30) * 100, 'r7': c.pct_change(7) * 100,
                        'above50': (c > c.rolling(50).mean()).astype(float)})
    out.index = out.index + pd.Timedelta(days=1)      # bekannt ab Tagesschluss
    return out
BTC = daily('BTC/USDT:USDT')

def at(series_df, ts):
    pos = series_df.index.searchsorted(ts, side='right') - 1
    return series_df.iloc[pos] if pos >= 0 else None

rows = []
for f in files:
    cfg = json.load(open(f'{CFG}/{f}')); p = strategy_params(cfg)
    sym, tf = cfg['market']['symbol'], cfg['market']['timeframe']
    bt = cfg['_backtest']
    warm = (pd.Timestamp(bt['start_date']) - pd.Timedelta(tf) * (int(p['window']) + 100)).strftime('%Y-%m-%d')
    df = load_ohlcv(sym, tf, warm, TODAY)
    df = df[df.index + pd.Timedelta(tf) <= pd.Timestamp.now(tz='UTC')]
    h, l, c, o = (df[x].values.astype(float) for x in ('high', 'low', 'close', 'open'))
    n = len(df)
    lo, sh = plan_both(df, cfg)
    coin = daily(sym)
    t0 = pd.Timestamp(bt['start_date'], tz='UTC')
    for dname, pl, sgn in (('long', lo, 1), ('short', sh, -1)):
        ch = pl['ch']
        # gespiegelte Reihen fuer Short (Kanal/Pivots liegen im gespiegelten Raum)
        H, L, C = (h, l, c) if sgn == 1 else (-l, -h, -c)
        for i in np.nonzero(pl['fill'][:n])[0]:
            ts = df.index[i]
            if ts < t0: continue
            j = i - 1
            lim, sl, tp = pl['limit'][i], pl['sl'][i], pl['tp'][i]
            A, B = int(pl['A'][i]), int(pl['B'][i])
            atr = ch['atr'][j]
            Lm, SLm, TPm = sgn * lim, sgn * sl, sgn * tp          # im (gespiegelten) Long-Raum
            risk = Lm - SLm
            hi, lo_ = H[B], L[A]; diff = hi - lo_
            # Verlauf nach Fill (Long-Raum): SL zuerst bei Doppeltreffer, Fill-Kerze kann SL treffen
            res, exit_k, mfe, mae = None, None, 0.0, 0.0
            if L[i] <= SLm:
                res, exit_k, mae = 'loss', i, -1.0
                mfe = max(0.0, (H[i] - Lm) / risk)
            else:
                mae = min(0.0, (L[i] - Lm) / risk)
                for k_ in range(i + 1, n):
                    if L[k_] <= SLm:
                        res, exit_k = 'loss', k_; mae = -1.0; break
                    mfe = max(mfe, (H[k_] - Lm) / risk); mae = min(mae, (L[k_] - Lm) / risk)
                    if H[k_] >= TPm:
                        res, exit_k = 'win', k_; break
            if res is None: continue                              # noch offen
            rr = (TPm - Lm) / risk
            fee_r = FEE * 2 * abs(lim) / abs(lim - sl)
            R = (rr if res == 'win' else -1.0) - fee_r
            b = at(BTC, ts); cn = at(coin, ts)
            rows.append({
                'cfg': f[7:-9], 'tf': tf, 'dir': dname, 'ts': ts, 'R': R, 'win': res == 'win',
                'mfe': mfe, 'mae': mae, 'bars': exit_k - i, 'instant': bool(pl['instant'][i]),
                'rr': rr, 'fee_r': fee_r,
                'sl_atr': risk / atr, 'width_atr': ch['width'][j] / atr,
                'slope_atr': ch['slope'][j] / atr * 10,                  # Kanalneigung je 10 Kerzen in ATR (Handelsrichtung)
                'imp_atr': diff / atr, 'imp_bars': B - A, 'age_bars': i - B,
                'age_ratio': (i - B) / max(1, B - A),
                'retr': (hi - Lm) / diff,                                # Ruecksetzer-Tiefe 0..1 (0,5 = halb)
                'dist_atr': (C[j] - Lm) / atr,                           # Kurs ueber dem Limit beim Legen
                'atr_pct': atr / abs(c[j]) * 100,
                'mom3_atr': (C[j] - C[max(0, j - 3)]) / atr,             # Bewegung der letzten 3 Kerzen (Richtung)
                'hour': ts.hour, 'wday': ts.weekday(),
                'btc_r30': None if b is None else sgn * b.r30, 'btc_r7': None if b is None else sgn * b.r7,
                'coin_r30': None if cn is None else sgn * cn.r30, 'coin_r7': None if cn is None else sgn * cn.r7,
                'coin_trend': None if cn is None else (cn.above50 if sgn == 1 else 1 - cn.above50),
            })
    print(f, len(rows), flush=True)
pd.DataFrame(rows).to_csv(os.path.join(HERE, f'events_{idx}.csv'), index=False)
