# src/fibot/strategy/fibot2_logic.py
# fibot 2.0 = Fibo-Kanal-Konfluenz (unveraenderter Detektor plan_both) + Mindest-Stop 2 ATR + Phasentor je Zeitebene.
# Forschung: Runde 17 (08.11.2026), Kandidat P5 -- eingefroren auf Daten < 10.05.2026, OOS 10.05.-08.11.2026:
# alle 407 Configs, eine Position je Coin, Konto 34 USDT / 1 % Risiko: +6,4 %, MaxDD 35,7 %, 429 Trades
# (alte Logik im selben Zeitraum: -99,7 %).
# Diese Datei ist die EINZIGE Rechnung fuer virtuelle Trades, Merkmale und Phasentor -- Live und Backtest rufen sie auf.
# Ereignisse 1:1 wie forschung/untersuchung_2026_11_08/events.py, Merkmale wie forschung/gewinner_filter_2026_11_08/run.py.
from typing import Optional

import numpy as np
import pandas as pd

from fibot.strategy.confluence_logic import plan_both

FEE = 0.0006              # je Seite in R-Rechnung (wie Export)
MAKER_TP_REFUND = 0.0002  # net_R: Verlust-Trades zahlen zusaetzlich (Export-Konvention)
MIN_STOP_ATR = 2.0
GATE_DAYS = 14
GATE_MIN_N = 15
RISK_PER_TRADE = 0.007    # 0,7 % des Kontos bis zum Stop (Entwicklungsjahre MaxDD <= ~35 %)
MAX_NOTIONAL_X = 10.0     # Summe Notional offener Positionen <= 10 x Konto
EXCLUDED_TF = {'5m'}      # Cron 15 min kann 5m nicht kerzengenau bedienen (vor Ergebnissicht festgelegt)


def features_frame(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Wilder-ATR14 in %, EMA200-Abstand -- Index = Zeitpunkt, ab dem die Kerze vollstaendig bekannt ist."""
    h, l, c = df.high, df.low, df.close
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    ema = c.ewm(span=200, adjust=False, min_periods=200).mean()
    f = pd.DataFrame(dict(atr_pct=100 * atr / c, ema_dist=c - ema), index=df.index)
    f.index = f.index + pd.Timedelta(tf)
    return f


def feature_at(f: pd.DataFrame, ts) -> Optional[pd.Series]:
    pos = f.index.searchsorted(pd.DatetimeIndex([ts]), side='right')[0] - 1
    return None if pos < 0 else f.iloc[pos]


def stop_atr(limit: float, sl: float, atr_pct: float) -> float:
    return (abs(limit - sl) / abs(limit) * 100) / atr_pct if atr_pct and np.isfinite(atr_pct) else np.nan


def plan_instances(df: pd.DataFrame, cfg: dict, since=None) -> pd.DataFrame:
    """Jede geplante Limit-Order (Kerze i, Long + Short) mit Fill-Kennzeichen -- fuer den Portfolio-Backtest
    (live blockiert eine liegende Order den Coin fuer diese Kerze, auch wenn sie nicht gefuellt wird).
    Live legt je Kerze hoechstens EINE Order: plan_next_order nimmt Long vor Short."""
    tf = cfg['market']['timeframe']; key = f"{cfg['market']['symbol'].split('/')[0]}USDTUSDT_{tf}"
    n = len(df); lo, sh = plan_both(df, cfg)
    feats = features_frame(df, tf); rows = []
    for i in range(n):
        for dname, pl in (('long', lo), ('short', sh)):
            if not np.isfinite(pl['limit'][i]):
                continue
            ts = df.index[i]
            if since is None or ts >= since:
                x = feature_at(feats, ts)
                atr_pct = float(x.atr_pct) if x is not None else np.nan
                rows.append(dict(cfg=key, tf=tf, ts=ts, dir=dname, limit=pl['limit'][i], sl=pl['sl'][i], tp=pl['tp'][i],
                                 fill=bool(pl['fill'][i]), b_ts=str(df.index[pl['B'][i]]),
                                 stop_atr=stop_atr(pl['limit'][i], pl['sl'][i], atr_pct)))
            break                                    # Long vor Short wie plan_next_order
    return pd.DataFrame(rows)


def virtual_events(df: pd.DataFrame, cfg: dict, since=None) -> pd.DataFrame:
    """Alle gefuellten Konfluenz-Orders (Long + Short) der Config auf df mit Ergebnis (nur abgeschlossene Trades).
    df: abgeschlossene Kerzen (open/high/low/close). since: nur Einstiege ab diesem Zeitpunkt."""
    tf = cfg['market']['timeframe']; coin = cfg['market']['symbol'].split('/')[0]
    n = len(df); h, l = df['high'].values, df['low'].values
    lo, sh = plan_both(df, cfg)
    feats = features_frame(df, tf)
    rows = []
    for dname, pl, sgn in (('long', lo, 1), ('short', sh, -1)):
        H, L = (h, l) if sgn == 1 else (-l, -h)
        for i in np.nonzero(pl['fill'][:n])[0]:
            ts = df.index[i]
            if since is not None and ts < since:
                continue
            lim, sl, tp = pl['limit'][i], pl['sl'][i], pl['tp'][i]
            Lm, SLm, TPm = sgn * lim, sgn * sl, sgn * tp
            res, k = None, i
            if L[i] <= SLm:
                res = 'loss'
            else:
                for k in range(i + 1, n):
                    if L[k] <= SLm:
                        res = 'loss'; break
                    if H[k] >= TPm:
                        res = 'win'; break
            if res is None:
                continue
            risk_pct = abs(lim - sl) / abs(lim) * 100
            R = ((TPm - Lm) / (Lm - SLm) if res == 'win' else -1.0) - FEE * 2 * abs(lim) / abs(lim - sl)
            x = feature_at(feats, ts)
            atr_pct = float(x.atr_pct) if x is not None else np.nan
            ema_dist = float(x.ema_dist) if x is not None else np.nan
            rows.append(dict(cfg=f"{cfg['market']['symbol'].split('/')[0]}USDTUSDT_{tf}", coin=coin, tf=tf, dir=dname,
                             ts=ts, exit_ts=df.index[k], R=R, win=res == 'win', risk_pct=risk_pct, atr_pct=atr_pct,
                             stop_atr=risk_pct / atr_pct if np.isfinite(atr_pct) else np.nan,
                             eligible=bool(np.isfinite(ema_dist) and risk_pct > 0 and np.isfinite(atr_pct)),
                             net_R=R - (0 if res == 'win' else MAKER_TP_REFUND / (risk_pct / 100))))
    return pd.DataFrame(rows)


def gate_value(events: pd.DataFrame, tf: str, now, days: int = GATE_DAYS, min_n: int = GATE_MIN_N) -> float:
    """Phasentor: Mittel net_R aller eligible-Ereignisse der Zeitebene mit Ausstieg in [now - days, now)."""
    if events is None or events.empty:
        return np.nan
    e = events[(events.tf == tf) & events.eligible]
    e = e[(e.exit_ts >= now - pd.Timedelta(days=days)) & (e.exit_ts < now)]
    return float(e.net_R.mean()) if len(e) >= min_n else np.nan


def gate_open(events: pd.DataFrame, tf: str, now) -> bool:
    v = gate_value(events, tf, now)
    return bool(np.isfinite(v) and v > 0)


def entry_allowed(plan: dict, atr_pct: float, gate_is_open: bool) -> Optional[str]:
    """None = erlaubt, sonst Grund."""
    if not gate_is_open:
        return 'Phasentor zu'
    s = stop_atr(plan['limit'], plan['sl'], atr_pct)
    if not np.isfinite(s) or s < MIN_STOP_ATR:
        return f'Stop nur {s:.2f} ATR (< {MIN_STOP_ATR})'
    return None
