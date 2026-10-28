# src/fibot/strategy/trend_filter.py
# Trendfilter "nur in Richtung des uebergeordneten Trends" (Konfluenz-Strategie).
#
# Ein Signal ist nur erlaubt, wenn BEIDE in Handelsrichtung zeigen:
#   - HTF: Kerzen des Strategie-Timeframes zu htf_mult-fachen Kerzen zusammengefasst
#          (15m->1h, 30m->2h, 1h->4h, 2h->8h ...), Schluss > EMA(htf_ema) = aufwaerts
#   - Tag: Tageskerze des Coins, Schluss > SMA(daily_sma) = aufwaerts
# Gezaehlt werden nur Kerzen, die vor dem Beginn der Fuell-/Orderkerze abgeschlossen waren.
# Unbekannter Trend (zu wenig Historie) = kein Trade.
#
# Vorregistriert und getestet am 28.10.2026 (forschung/trendfilter/): auf dem Pruefzeitraum
# 01.04.-14.10.2026 +0,39 statt +0,25 R je Trade; vor April 2026 wirkte er umgekehrt.
# Live, Backtest, Optimizer, Portfolio-Auswahl und Tagesbericht nutzen nur diese Funktionen.

import json
import os

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
SETTINGS_FILE = os.path.join(PROJECT_ROOT, 'settings.json')

DEFAULTS = {'enabled': True, 'htf_mult': 4, 'htf_ema': 50, 'daily_sma': 50}
HTF_BARS_NEEDED = 200      # HTF-Kerzen Vorlauf, damit die EMA eingeschwungen ist
DAILY_BARS_NEEDED = 120


def settings() -> dict:
    """settings.json -> trend_filter (fehlt der Block: Standard = AN)."""
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            s = json.load(f).get('trend_filter', {})
    except Exception:
        s = {}
    return {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}


def base_bars_needed(cfg: dict | None = None) -> int:
    """Kerzen des Strategie-Timeframes, die fuer den HTF-Trend geladen sein muessen."""
    cfg = cfg or settings()
    return int(cfg['htf_mult']) * HTF_BARS_NEEDED + int(cfg['htf_mult'])


def htf_trend(df: pd.DataFrame, timeframe: str, cfg: dict | None = None) -> pd.Series:
    """1.0 = aufwaerts, 0.0 = abwaerts; Index = Zeitpunkt, ab dem der Wert bekannt ist
    (Schluss der HTF-Kerze). Erste htf_ema Werte (EMA nicht eingeschwungen) fehlen."""
    cfg = cfg or settings()
    htf = pd.Timedelta(timeframe) * int(cfg['htf_mult'])
    closes = df['close'].astype(float).resample(htf, origin='epoch').last().dropna()
    # angebrochene letzte HTF-Kerze verwerfen (nur abgeschlossene zaehlen)
    last_end = df.index[-1] + pd.Timedelta(timeframe)
    closes = closes[closes.index + htf <= last_end]
    up = (closes > closes.ewm(span=int(cfg['htf_ema']), adjust=False).mean()).astype(float)
    up = up.iloc[int(cfg['htf_ema']):]
    up.index = up.index + htf
    return up


def daily_trend(daily: pd.DataFrame, cfg: dict | None = None) -> pd.Series:
    """1.0 = Tagesschluss > SMA, 0.0 = darunter; Index = Tagesschluss (bekannt ab)."""
    cfg = cfg or settings()
    c = daily['close'].astype(float)
    sma = c.rolling(int(cfg['daily_sma'])).mean()
    up = (c > sma).astype(float)[sma.notna()]
    up.index = up.index + pd.Timedelta(days=1)
    return up


def _value_at(series: pd.Series, ts) -> float:
    pos = series.index.searchsorted(ts, side='right') - 1
    return float(series.iloc[pos]) if pos >= 0 else float('nan')


def allowed(direction: str, ts, htf: pd.Series, daily: pd.Series) -> bool:
    """Long nur bei HTF und Tag aufwaerts, Short nur bei beiden abwaerts. Unbekannt -> False."""
    want = 1.0 if direction == 'long' else 0.0
    h, d = _value_at(htf, ts), _value_at(daily, ts)
    return h == want and d == want


def mask_signals(sig_dir: np.ndarray, index: pd.DatetimeIndex, htf: pd.Series, daily: pd.Series) -> np.ndarray:
    """Backtest: _sig_dir (1 = Long, 2 = Short) auf erlaubte Signale reduzieren."""
    out = sig_dir.copy()
    for i in np.nonzero(out)[0]:
        if not allowed('long' if out[i] == 1 else 'short', index[i], htf, daily):
            out[i] = 0
    return out
