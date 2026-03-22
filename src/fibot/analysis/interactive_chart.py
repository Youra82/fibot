# src/fibot/analysis/interactive_chart.py
# FiBot — Interaktiver Candlestick-Chart mit Fibonacci-Trade-Markern
#
# Panels:
#   1. Candlestick + Entry/Exit-Marker + SL/TP-Linien + Equity-Kurve (rechte Achse)
#      Overlay: aktuelle Fibonacci-Levels (Linien) + Struktur-Trendlinien
#   2. Volumen
#   3. RSI(14)  — Entry-Filter (oversold/overbought)
#   4. ATR(14) + ATR-MA — SL-Berechnung + Toleranzzone
#   5. Signal-Score pro Trade (0–10)
#
# Output: HTML-Datei in artifacts/charts/ (öffnet im Browser)

import os
import sys
import json
import logging
from datetime import date

import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from fibot.analysis.backtester import (
    run_backtest, load_ohlcv, auto_days_for_timeframe, BacktestResult
)
from fibot.strategy.fibonacci_logic import (
    find_significant_swings, compute_fib_levels, detect_structure,
    calc_rsi, calc_atr
)

logger = logging.getLogger(__name__)

CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')
CHARTS_DIR  = os.path.join(PROJECT_ROOT, 'artifacts', 'charts')


# ─────────────────────────────────────────────────────────────────────────────
# Pair-Auswahl aus aktuellen Configs
# ─────────────────────────────────────────────────────────────────────────────

def _load_configs() -> list[dict]:
    """Liest alle config_*_fib.json aus dem Configs-Verzeichnis."""
    entries = []
    if not os.path.isdir(CONFIGS_DIR):
        return entries
    for fname in sorted(f for f in os.listdir(CONFIGS_DIR)
                        if f.startswith('config_') and f.endswith('.json')):
        try:
            with open(os.path.join(CONFIGS_DIR, fname)) as f:
                cfg = json.load(f)
            symbol    = cfg.get('market', {}).get('symbol', '')
            timeframe = cfg.get('market', {}).get('timeframe', '')
            if symbol and timeframe:
                entries.append({'filename': fname, 'symbol': symbol, 'timeframe': timeframe})
        except Exception:
            pass
    return entries


def select_pairs() -> list[tuple[str, str]]:
    configs = _load_configs()
    if not configs:
        print("Keine Configs gefunden. Erst run_pipeline.sh ausfuehren.")
        return []

    w = 70
    print("\n" + "=" * w)
    print("  Verfuegbare Pairs  (aus aktuellen Configs)")
    print("=" * w)
    for i, d in enumerate(configs, 1):
        print(f"  {i:2d}) {d['symbol']:<22} {d['timeframe']:<5}")
    print("=" * w)

    print("\n  Einzeln: '1' | Mehrfach: '1,3' oder '1 3'")
    raw = input("  Auswahl: ").strip()
    selected = []
    for token in raw.replace(',', ' ').split():
        try:
            idx = int(token)
            if 1 <= idx <= len(configs):
                d = configs[idx - 1]
                pair = (d['symbol'], d['timeframe'])
                if pair not in selected:
                    selected.append(pair)
        except ValueError:
            pass
    return selected


# ─────────────────────────────────────────────────────────────────────────────
# Indikatoren für Chart-Panels
# ─────────────────────────────────────────────────────────────────────────────

def _compute_panels(df: pd.DataFrame) -> dict:
    """RSI, ATR, ATR-MA für die Indikator-Panels."""
    # RSI
    delta    = df['close'].diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    rsi      = 100 - (100 / (1 + rs))

    # ATR
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low']  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr    = tr.ewm(span=14, min_periods=14).mean()
    atr_ma = atr.rolling(50, min_periods=10).mean().fillna(atr)

    return {'rsi': rsi, 'atr': atr, 'atr_ma': atr_ma}


# ─────────────────────────────────────────────────────────────────────────────
# Chart erstellen
# ─────────────────────────────────────────────────────────────────────────────

def create_chart(symbol: str, timeframe: str, df: pd.DataFrame,
                 result: BacktestResult, config: dict) -> object | None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("plotly nicht installiert. Bitte: pip install plotly")
        return None

    panels = _compute_panels(df)
    rsi    = panels['rsi']
    atr    = panels['atr']
    atr_ma = panels['atr_ma']

    # ── Subplots ─────────────────────────────────────────────────────────────
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        specs=[
            [{'secondary_y': True}],
            [{'secondary_y': False}],
            [{'secondary_y': False}],
            [{'secondary_y': False}],
            [{'secondary_y': False}],
        ],
        vertical_spacing=0.022,
        row_heights=[0.42, 0.10, 0.16, 0.16, 0.16],
        subplot_titles=[
            '',
            'Volumen',
            'RSI (14)  — Entry-Filter',
            'ATR (14)  — SL-Basis & Toleranzzone',
            'Signal Score (0–10)',
        ],
    )

    # ── Aktuelle Fib-Levels + Struktur über dem gesamten Chart ───────────────
    # Berechne für die letzten 100 Kerzen (live-equivalent)
    cfg_s = config.get('strategy', {})
    swings = find_significant_swings(
        df,
        lookback=int(cfg_s.get('swing_lookback', 100)),
        pivot_left=int(cfg_s.get('pivot_left', 5)),
        pivot_right=int(cfg_s.get('pivot_right', 5)),
    )

    FIB_COLORS = {
        '38.2':  ('rgba(255,167,38,0.8)',  'dash'),
        '50.0':  ('rgba(255,255,100,0.9)', 'dash'),
        '61.8':  ('rgba(255,167,38,0.8)',  'dash'),
        '78.6':  ('rgba(239,83,80,0.7)',   'dot'),
        '100.0': ('rgba(38,166,154,0.9)',  'solid'),
        '127.2': ('rgba(100,200,255,0.6)', 'dot'),
        '0.0':   ('rgba(150,150,150,0.5)', 'dot'),
    }

    if swings:
        fibs = compute_fib_levels(swings)
        x0 = df.index[max(0, len(df) - int(cfg_s.get('swing_lookback', 100)))]
        x1 = df.index[-1]
        for name, price in fibs.levels.items():
            if name not in FIB_COLORS:
                continue
            color, dash = FIB_COLORS[name]
            fig.add_shape(
                type='line', x0=x0, x1=x1, y0=price, y1=price,
                line=dict(color=color, width=1, dash=dash),
                row=1, col=1,
            )
            fig.add_annotation(
                x=x1, y=price, text=f"  {name}%",
                showarrow=False,
                font=dict(color=color, size=9),
                xanchor='left',
                row=1, col=1,
            )

        # Struktur-Trendlinien
        struct = detect_structure(
            df,
            lookback=int(cfg_s.get('structure_lookback', 60)),
            pivot_left=int(cfg_s.get('pivot_left', 3)),
            pivot_right=int(cfg_s.get('pivot_right', 3)),
            tolerance_atr_mult=float(cfg_s.get('structure_tolerance_atr_mult', 0.3)),
        )
        if struct.type != 'none':
            n   = struct.n_bars
            cur = float(n - 1)
            # Berechne Linienpunkte für die letzten n_bars
            x_struct = df.index[-n:]
            bars     = np.arange(float(n))
            upper_y  = struct.upper_slope * bars + struct.upper_intercept
            lower_y  = struct.lower_slope * bars + struct.lower_intercept

            struct_color = '#26a69a' if struct.bias == 'bullish' else \
                           '#ef5350' if struct.bias == 'bearish' else '#9e9e9e'

            fig.add_trace(go.Scatter(
                x=x_struct, y=upper_y,
                mode='lines',
                line=dict(color=struct_color, width=1.5, dash='dash'),
                name=f'Resistance ({struct.type})',
                hovertemplate=f'Resistance: %{{y:.4f}}<extra>{struct.type}</extra>',
            ), row=1, col=1, secondary_y=False)

            fig.add_trace(go.Scatter(
                x=x_struct, y=lower_y,
                mode='lines',
                line=dict(color=struct_color, width=1.5, dash='dash'),
                fill='tonexty',
                fillcolor=f'rgba(150,150,150,0.06)',
                name=f'Support ({struct.type})',
                hovertemplate=f'Support: %{{y:.4f}}<extra>{struct.type}</extra>',
            ), row=1, col=1, secondary_y=False)

            # Toleranzzonen als Band
            tol_mult = float(cfg_s.get('structure_tolerance_atr_mult', 0.3))
            last_atr = float(atr.iloc[-1]) if not atr.empty else 0
            tol = tol_mult * last_atr

            fig.add_hrect(
                y0=struct.support_at - tol, y1=struct.support_at + tol,
                fillcolor='rgba(38,166,154,0.08)', line_width=0,
                annotation_text=f'Support-Zone ±{tol:.2f}',
                annotation_position='right',
                annotation_font_size=9,
                row=1, col=1,
            )
            fig.add_hrect(
                y0=struct.resistance_at - tol, y1=struct.resistance_at + tol,
                fillcolor='rgba(239,83,80,0.08)', line_width=0,
                annotation_text=f'Resistance-Zone ±{tol:.2f}',
                annotation_position='right',
                annotation_font_size=9,
                row=1, col=1,
            )

    # ── Panel 1: Candlesticks ────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['open'], high=df['high'],
        low=df['low'],   close=df['close'],
        name='OHLC',
        increasing_line_color='#26a69a',
        decreasing_line_color='#ef5350',
        showlegend=True,
    ), row=1, col=1, secondary_y=False)

    # ── Trade-Marker ─────────────────────────────────────────────────────────
    entry_long_x, entry_long_y, entry_long_txt   = [], [], []
    entry_short_x, entry_short_y, entry_short_txt = [], [], []
    exit_win_x,  exit_win_y  = [], []
    exit_loss_x, exit_loss_y = [], []
    exit_open_x, exit_open_y = [], []

    for t in result.trades:
        entry_ts = t.timestamp
        bar_idx  = t.exit_bar if t.exit_bar else len(df) - 1
        exit_ts  = df.index[min(bar_idx, len(df) - 1)]
        tip = (
            f"Score: {t.score:.1f}/10<br>"
            f"SL: {t.sl:.4f}  TP: {t.tp1:.4f}<br>"
            f"Ergebnis: {t.result.upper()}<br>"
            f"PnL: {t.pnl_usdt:+.2f} USDT"
        )

        if t.direction == 'long':
            entry_long_x.append(entry_ts)
            entry_long_y.append(t.entry)
            entry_long_txt.append(tip)
        else:
            entry_short_x.append(entry_ts)
            entry_short_y.append(t.entry)
            entry_short_txt.append(tip)

        if t.result == 'win':
            exit_win_x.append(exit_ts);  exit_win_y.append(t.exit_price)
        elif t.result == 'loss':
            exit_loss_x.append(exit_ts); exit_loss_y.append(t.exit_price)
        else:
            exit_open_x.append(exit_ts); exit_open_y.append(t.exit_price)

        # SL- und TP-Linien pro Trade
        fig.add_shape(
            type='line', x0=entry_ts, x1=exit_ts,
            y0=t.sl, y1=t.sl,
            line=dict(color='rgba(239,68,68,0.45)', width=1, dash='dot'),
        )
        fig.add_shape(
            type='line', x0=entry_ts, x1=exit_ts,
            y0=t.tp1, y1=t.tp1,
            line=dict(color='rgba(34,197,94,0.45)', width=1, dash='dot'),
        )

    if entry_long_x:
        fig.add_trace(go.Scatter(
            x=entry_long_x, y=entry_long_y, mode='markers',
            marker=dict(color='#26a69a', symbol='triangle-up', size=14,
                        line=dict(width=1, color='#fff')),
            name='Entry Long ▲', text=entry_long_txt,
            hovertemplate='%{text}<extra>Entry Long</extra>',
        ), row=1, col=1, secondary_y=False)

    if entry_short_x:
        fig.add_trace(go.Scatter(
            x=entry_short_x, y=entry_short_y, mode='markers',
            marker=dict(color='#ffa726', symbol='triangle-down', size=14,
                        line=dict(width=1, color='#fff')),
            name='Entry Short ▼', text=entry_short_txt,
            hovertemplate='%{text}<extra>Entry Short</extra>',
        ), row=1, col=1, secondary_y=False)

    if exit_win_x:
        fig.add_trace(go.Scatter(
            x=exit_win_x, y=exit_win_y, mode='markers',
            marker=dict(color='#00bcd4', symbol='circle', size=10,
                        line=dict(width=1, color='#fff')),
            name='Exit TP ✓',
        ), row=1, col=1, secondary_y=False)

    if exit_loss_x:
        fig.add_trace(go.Scatter(
            x=exit_loss_x, y=exit_loss_y, mode='markers',
            marker=dict(color='#ef5350', symbol='x', size=10,
                        line=dict(width=2, color='#ef5350')),
            name='Exit SL ✗',
        ), row=1, col=1, secondary_y=False)

    if exit_open_x:
        fig.add_trace(go.Scatter(
            x=exit_open_x, y=exit_open_y, mode='markers',
            marker=dict(color='#9e9e9e', symbol='square', size=8),
            name='Exit Offen ■',
        ), row=1, col=1, secondary_y=False)

    # ── Equity-Kurve (rechte Y-Achse) ───────────────────────────────────────
    eq_times = [df.index[0]]
    eq_vals  = [result.start_capital]
    equity   = result.start_capital
    for t in sorted(result.trades, key=lambda x: x.timestamp):
        equity += t.pnl_usdt
        eq_times.append(t.timestamp)
        eq_vals.append(equity)

    fig.add_trace(go.Scatter(
        x=eq_times, y=eq_vals,
        name='Equity',
        line=dict(color='#5c9bd6', width=1.5),
        hovertemplate='Equity: %{y:.2f} USDT<extra></extra>',
    ), row=1, col=1, secondary_y=True)

    # ── Panel 2: Volumen ─────────────────────────────────────────────────────
    vol_colors = ['#26a69a' if c >= o else '#ef5350'
                  for c, o in zip(df['close'], df['open'])]
    fig.add_trace(go.Bar(
        x=df.index, y=df['volume'],
        marker_color=vol_colors, opacity=0.65,
        name='Volumen', showlegend=False,
        hovertemplate='Vol: %{y:,.0f}<extra></extra>',
    ), row=2, col=1)

    # ── Panel 3: RSI ─────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df.index, y=rsi,
        mode='lines', line=dict(color='#ce93d8', width=1.5),
        fill='tozeroy', fillcolor='rgba(206,147,216,0.07)',
        name='RSI(14)', showlegend=False,
        hovertemplate='RSI: %{y:.1f}<extra></extra>',
    ), row=3, col=1)

    rsi_oversold  = float(cfg_s.get('rsi_oversold',  45))
    rsi_overbought= float(cfg_s.get('rsi_overbought', 55))
    fig.add_hline(y=rsi_oversold,   line_dash='dot',
                  line_color='rgba(38,166,154,0.6)',  row=3, col=1)
    fig.add_hline(y=rsi_overbought, line_dash='dot',
                  line_color='rgba(239,83,80,0.6)',   row=3, col=1)
    fig.add_hline(y=50, line_dash='dot',
                  line_color='rgba(150,150,150,0.3)', row=3, col=1)

    # RSI bei Entry-Zeitpunkten markieren
    all_entry_ts = entry_long_x + entry_short_x
    if all_entry_ts:
        rsi_at_entry = [float(rsi.asof(ts)) for ts in all_entry_ts]
        clr = ['#26a69a'] * len(entry_long_x) + ['#ffa726'] * len(entry_short_x)
        fig.add_trace(go.Scatter(
            x=all_entry_ts, y=rsi_at_entry, mode='markers',
            marker=dict(symbol='circle-open', size=9, color=clr,
                        line=dict(width=2)),
            showlegend=False,
            hovertemplate='RSI @ Entry: %{y:.1f}<extra></extra>',
        ), row=3, col=1)

    # ── Panel 4: ATR + ATR-MA ────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df.index, y=atr_ma,
        mode='lines', line=dict(color='rgba(255,167,38,0.5)', width=1.2, dash='dot'),
        name='ATR-MA(50)', showlegend=False,
        hovertemplate='ATR-MA: %{y:.4f}<extra></extra>',
    ), row=4, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=atr,
        mode='lines', line=dict(color='#42a5f5', width=1.5),
        fill='tonexty', fillcolor='rgba(66,165,245,0.08)',
        name='ATR(14)', showlegend=False,
        hovertemplate='ATR: %{y:.4f}<extra></extra>',
    ), row=4, col=1)

    # Toleranzzone = atr_mult * ATR als Linie
    tol_mult = float(cfg_s.get('structure_tolerance_atr_mult', 0.3))
    fig.add_trace(go.Scatter(
        x=df.index, y=atr * tol_mult,
        mode='lines', line=dict(color='rgba(255,255,100,0.4)', width=1, dash='dot'),
        name=f'Toleranz (×{tol_mult})', showlegend=False,
        hovertemplate=f'Tol ({tol_mult}×ATR): %{{y:.4f}}<extra></extra>',
    ), row=4, col=1)

    # ── Panel 5: Signal Score ────────────────────────────────────────────────
    if result.trades:
        score_ts  = [t.timestamp for t in result.trades]
        score_vals= [t.score     for t in result.trades]
        score_clr = ['#26a69a' if t.direction == 'long' else '#ffa726'
                     for t in result.trades]
        score_txt = [
            f"Score: {t.score:.1f}/10<br>{t.direction.upper()} | {t.result.upper()}<br>"
            f"PnL: {t.pnl_usdt:+.2f} USDT"
            for t in result.trades
        ]
        fig.add_trace(go.Bar(
            x=score_ts, y=score_vals,
            marker_color=score_clr, opacity=0.75,
            name='Signal Score', showlegend=False,
            text=score_txt,
            hovertemplate='%{text}<extra></extra>',
        ), row=5, col=1)
        # Mindest-Score-Linie
        min_score = float(cfg_s.get('min_signal_score', 4.0))
        fig.add_hline(y=min_score, line_dash='dot',
                      line_color='rgba(255,255,255,0.4)', row=5, col=1)

    # ── Titel & Layout ───────────────────────────────────────────────────────
    pnl_pct  = result.pnl_pct
    sign     = '+' if pnl_pct >= 0 else ''
    struct_label = ''
    if swings:
        struct = detect_structure(df,
                     int(cfg_s.get('structure_lookback', 60)),
                     int(cfg_s.get('pivot_left', 3)),
                     int(cfg_s.get('pivot_right', 3)))
        struct_label = f" | Struktur: {struct.type} ({struct.bias})"

    title = (
        f"{symbol} {timeframe} — FiBot Fibonacci | "
        f"Trades: {result.total_trades}  W:{result.wins} L:{result.losses} | "
        f"WR: {result.win_rate:.1f}% | "
        f"PnL: {sign}{pnl_pct:.1f}% | "
        f"MaxDD: {result.max_drawdown_pct:.1f}%"
        f"{struct_label}"
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=12), x=0.5, xanchor='center'),
        height=1100,
        hovermode='x unified',
        template='plotly_dark',
        dragmode='zoom',
        xaxis_rangeslider_visible=False,
        legend=dict(orientation='h', yanchor='bottom', y=1.01,
                    xanchor='center', x=0.5, font=dict(size=11)),
        margin=dict(l=60, r=80, t=80, b=40),
        barmode='overlay',
        yaxis2=dict(
            title='Equity (USDT)', showgrid=False,
            tickfont=dict(color='#5c9bd6'),
            title_font=dict(color='#5c9bd6'),
        ),
    )

    fig.update_yaxes(title_text='Preis', row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text='Vol',   row=2, col=1)
    fig.update_yaxes(title_text='RSI',   row=3, col=1, range=[0, 100])
    fig.update_yaxes(title_text='ATR',   row=4, col=1)
    fig.update_yaxes(title_text='Score', row=5, col=1, range=[0, 10.5])

    for row in range(1, 6):
        fig.update_xaxes(rangeslider_visible=False, row=row, col=1)

    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run_interactive_chart(secrets: dict):
    print("\n" + "=" * 65)
    print("  INTERAKTIVE CHARTS — FiBot Fibonacci")
    print("=" * 65)

    selected = select_pairs()
    if not selected:
        return

    print()
    start_raw = input("Startdatum (JJJJ-MM-TT) [leer=auto]: ").strip()
    end_raw   = input("Enddatum   (JJJJ-MM-TT) [leer=heute]: ").strip()

    cap_raw = input("Startkapital in USDT [Standard: 1000]: ").strip()
    start_capital = float(cap_raw) if cap_raw.replace('.', '').isdigit() else 1000.0

    tg_raw  = input("Per Telegram senden? (j/n) [Standard: n]: ").strip().lower()
    send_tg = tg_raw in ('j', 'y', 'ja')

    os.makedirs(CHARTS_DIR, exist_ok=True)
    generated = []
    today = date.today().isoformat()

    for symbol, timeframe in selected:
        print(f"\n--- {symbol} ({timeframe}) ---")

        # Zeitraum
        if start_raw:
            sd = start_raw
        else:
            n_days = auto_days_for_timeframe(timeframe)
            sd = (pd.Timestamp(today, tz='UTC') - pd.Timedelta(days=n_days)).strftime('%Y-%m-%d')
        ed = end_raw if end_raw else today

        print(f"  Lade Daten [{sd} → {ed}]...")
        df = load_ohlcv(symbol, timeframe, sd, ed)
        if df.empty:
            print("  Keine Daten — übersprungen.")
            continue
        print(f"  {len(df)} Kerzen")

        # Config laden
        safe     = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
        cfg_path = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs',
                                f"config_{safe}_fib.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                config = json.load(f)
        else:
            config = {
                "market":   {"symbol": symbol, "timeframe": timeframe},
                "strategy": {
                    "swing_lookback": 100, "pivot_left": 5, "pivot_right": 5,
                    "structure_lookback": 60, "fib_entry_min": 0.382, "fib_entry_max": 0.618,
                    "fib_sl_level": 0.786, "fib_tp1_level": 1.0, "fib_tp2_level": 1.272,
                    "proximity_pct": 0.5, "structure_tolerance_atr_mult": 0.3,
                    "rsi_period": 14, "rsi_oversold": 45, "rsi_overbought": 55,
                    "volume_ratio_min": 1.0, "min_rr": 1.5,
                    "atr_period": 14, "atr_sl_multiplier": 1.5,
                    "min_signal_score": 4.0, "candle_limit": 500,
                },
                "risk": {"leverage": 10, "risk_per_entry_pct": 1.0, "margin_mode": "isolated"},
            }

        print("  Führe Backtest durch...")
        result = run_backtest(df, config, start_capital, symbol, timeframe)
        print(f"  {result.total_trades} Trades | WR: {result.win_rate:.1f}% | "
              f"PnL: {result.pnl_pct:+.1f}% | MaxDD: {result.max_drawdown_pct:.1f}%")

        # Datum-Filter auf Chart-Ansicht
        df_chart = df.copy()
        if start_raw:
            df_chart = df_chart[df_chart.index >= pd.Timestamp(start_raw, tz='UTC')]
        if end_raw:
            df_chart = df_chart[df_chart.index <= pd.Timestamp(end_raw + 'T23:59:59', tz='UTC')]

        print("  Erstelle Chart...")
        fig = create_chart(symbol, timeframe, df_chart, result, config)
        if fig is None:
            continue

        out_file = os.path.join(CHARTS_DIR, f"fibot_{safe}.html")
        fig.write_html(out_file)
        print(f"  ✅ Chart gespeichert: {out_file}")
        generated.append((symbol, timeframe, out_file))

    print(f"\n✅ {len(generated)} Chart(s) generiert!")
    for _, _, path in generated:
        print(f"  → {path}")

    # Telegram
    if send_tg and generated:
        tg = secrets.get('telegram', {})
        if tg.get('bot_token') and tg.get('chat_id'):
            from fibot.utils.telegram import send_document
            for sym, tf, path in generated:
                try:
                    send_document(tg['bot_token'], tg['chat_id'], path,
                                  caption=f"FiBot Chart: {sym} {tf}")
                    print(f"  ✅ Telegram gesendet: {sym} {tf}")
                except Exception as e:
                    print(f"  Telegram-Fehler: {e}")
        else:
            print("  Telegram nicht konfiguriert (bot_token/chat_id fehlt).")
