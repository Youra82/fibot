# src/fibot/analysis/analysis_suite.py
# FiBot — Analysen fuer run_analysis.sh (alle Configs bzw. aktives Portfolio).
# Jede Analyse druckt eine Tabelle und schreibt sie zusaetzlich nach artifacts/analysis/.
#
# Aufruf:  python src/fibot/analysis/analysis_suite.py --analysis N [--from ..] [--to ..]
#          [--capital 100] [--scope alle|aktiv] [--no-telegram]

import argparse
import itertools
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fibot.analysis.backtester import run_backtest, load_ohlcv, FEE_PCT  # noqa: E402

CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')
SETTINGS = os.path.join(PROJECT_ROOT, 'settings.json')
OUT_DIR = os.path.join(PROJECT_ROOT, 'artifacts', 'analysis')

_LINES: list = []


def out(s=''):
    print(s)
    _LINES.append(str(s))


# ---------------------------------------------------------------------------
# Daten
# ---------------------------------------------------------------------------

def load_configs(scope: str) -> dict:
    files = sorted(f for f in os.listdir(CONFIGS_DIR) if f.startswith('config_') and f.endswith('.json'))
    cfgs = {f: json.load(open(os.path.join(CONFIGS_DIR, f))) for f in files}
    if scope == 'aktiv':
        act = json.load(open(SETTINGS)).get('live_trading_settings', {}).get('active_strategies', [])
        keep = {(s['symbol'], s['timeframe']) for s in act if s.get('active', True)}
        cfgs = {f: c for f, c in cfgs.items() if (c['market']['symbol'], c['market']['timeframe']) in keep}
    return cfgs


def label(cfg):
    return f"{cfg['market']['symbol'].split('/')[0]} {cfg['market']['timeframe']}"


def trades_frame(result, df) -> pd.DataFrame:
    rows = []
    for t in result.trades:
        if t.result == 'open':
            continue
        risk = abs(t.entry - t.sl)
        if risk <= 0:
            continue
        sgn = 1 if t.direction == 'long' else -1
        r_gross = sgn * (t.exit_price - t.entry) / risk
        fee_r = 2 * FEE_PCT * t.entry / risk
        exit_ts = df.index[min(t.exit_bar, len(df) - 1)]
        rows.append({'ts': pd.Timestamp(t.timestamp), 'exit_ts': exit_ts, 'dir': t.direction,
                     'res': t.result, 'r_gross': r_gross, 'fee_r': fee_r, 'r': r_gross - fee_r,
                     'pnl_pct': t.pnl_pct, 'pnl': t.pnl_usdt, 'entry': t.entry})
    return pd.DataFrame(rows)


def backtest_all(cfgs, start, end, capital, overrides=None):
    res = {}
    for f, cfg in cfgs.items():
        c = json.loads(json.dumps(cfg))
        if overrides:
            c['strategy'].update(overrides)
        sym, tf = c['market']['symbol'], c['market']['timeframe']
        df = load_ohlcv(sym, tf, start, end)
        if df.empty or len(df) < 300:
            continue
        r = run_backtest(df, c, capital, sym, tf, cache_key=(f, start, end))
        res[f] = {'cfg': c, 'result': r, 'trades': trades_frame(r, df), 'df': df}
    return res


def boot_ci(x, n=2000):
    x = np.asarray(x)
    if len(x) < 2:
        return (np.nan, np.nan)
    rng = np.random.default_rng(7)
    m = [rng.choice(x, len(x)).mean() for _ in range(n)]
    return tuple(np.percentile(m, [2.5, 97.5]))


def equity_stats(pnl_pct_seq):
    eq, peak, mdd = 1.0, 1.0, 0.0
    for p in pnl_pct_seq:
        eq *= 1 + p / 100
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
    return (eq - 1) * 100, mdd


# ---------------------------------------------------------------------------
# Analysen
# ---------------------------------------------------------------------------

def a1_is_oos(cfgs, a):
    out('1) In-Sample vs. Out-of-Sample (aus der Optimierung gespeichert)')
    out(f"{'Strategie':<12} {'IS PnL':>8} {'IS DD':>6} {'IS n':>5} | {'OOS PnL':>8} {'OOS DD':>7} {'OOS n':>6} {'OOS WR':>7}")
    for f, c in cfgs.items():
        b = c.get('_backtest', {})
        o = b.get('oos')
        if not o:
            out(f"{label(c):<12} keine OOS-Daten (alte Config)")
            continue
        out(f"{label(c):<12} {b['pnl_pct']:>+7.1f}% {b['max_drawdown']:>5.1f}% {b['total_trades']:>5} | "
            f"{o['pnl_pct']:>+7.1f}% {o['max_drawdown']:>6.1f}% {o['total_trades']:>6} {o['win_rate']:>6.0f}%")


def a2_bootstrap(cfgs, a):
    out('2) Bootstrap-Signifikanz: netto R pro Trade mit 95 %-Bereich')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    allr = []
    out(f"{'Strategie':<12} {'Trades':>6} {'R/Trade':>8} {'95 %-Bereich':>18}  Urteil")
    for f, d in res.items():
        t = d['trades']
        if t.empty:
            continue
        lo, hi = boot_ci(t.r)
        verdict = 'signifikant > 0' if lo > 0 else ('signifikant < 0' if hi < 0 else 'nicht signifikant')
        out(f"{label(d['cfg']):<12} {len(t):>6} {t.r.mean():>+8.3f} [{lo:+.3f}, {hi:+.3f}]  {verdict}")
        allr += list(t.r)
    if allr:
        lo, hi = boot_ci(allr)
        out(f"{'ALLE':<12} {len(allr):>6} {np.mean(allr):>+8.3f} [{lo:+.3f}, {hi:+.3f}]")


def a3_monte_carlo(cfgs, a):
    out('3) Monte Carlo: 5000 Bootstrap-Pfade (Trades mit Zuruecklegen gezogen)')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    seq = pd.concat([d['trades'] for d in res.values() if not d['trades'].empty])
    if seq.empty:
        out('Keine Trades.')
        return
    p = seq.sort_values('ts').pnl_pct.values / max(1, len(res))   # Kapital auf alle Strategien verteilt
    rng = np.random.default_rng(1)
    finals, dds = [], []
    for _ in range(5000):
        f_, d_ = equity_stats(rng.choice(p, len(p), replace=True))
        finals.append(f_)
        dds.append(d_)
    out(f"Trades: {len(p)} | Strategien: {len(res)}")
    for q in (5, 25, 50, 75, 95):
        out(f"  {q:>2}. Perzentil: PnL {np.percentile(finals, q):+8.1f}%   MaxDD {np.percentile(dds, q):6.1f}%")
    out(f"  Wahrscheinlichkeit MaxDD > 30 %: {np.mean(np.array(dds) > 30) * 100:.1f}%")
    out(f"  Wahrscheinlichkeit Verlust:       {np.mean(np.array(finals) < 0) * 100:.1f}%")


def a4_fees(cfgs, a):
    out('4) Gebuehren & Slippage: R pro Trade bei anderen Kosten (Basis 0,06 % je Seite)')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    seq = pd.concat([d['trades'] for d in res.values() if not d['trades'].empty])
    if seq.empty:
        out('Keine Trades.')
        return
    risk_pct = seq.fee_r / (2 * FEE_PCT)          # = entry / risk
    out(f"{'Gebuehr/Seite':>14} {'Slippage':>9} {'R/Trade':>9} {'Summe R':>9}")
    for fee, slip in itertools.product((0.0002, 0.0004, 0.0006, 0.001), (0.0, 0.0005, 0.001)):
        r = seq.r_gross - (2 * fee + slip) * risk_pct
        out(f"{fee * 100:>13.2f}% {slip * 100:>8.2f}% {r.mean():>+9.3f} {r.sum():>+9.1f}")


SENS = {'zone_tol_atr': 0.1, 'sl_buf_atr': 0.1, 'min_rr': 0.3, 'min_width_atr': 1.0}


def a5_sensitivity(cfgs, a):
    out('5) Parameter-Sensitivitaet: PnL bei Parameter +- eine Stufe (robust = kleine Aenderung)')
    base = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    out(f"{'Strategie':<12} {'Basis':>8} " + ' '.join(f'{k + "-":>14} {k + "+":>14}' for k in SENS))
    for f, d in base.items():
        cells = []
        for k, step in SENS.items():
            v0 = d['cfg']['strategy'].get(k)
            if v0 is None:
                cells += ['n/a', 'n/a']
                continue
            for sgn in (-1, 1):
                r = backtest_all({f: d['cfg']}, a.date_from, a.date_to, a.capital,
                                 overrides={k: max(0.0, round(v0 + sgn * step, 3))})
                cells.append(f"{r[f]['result'].pnl_pct:+.1f}%" if f in r else 'n/a')
        out(f"{label(d['cfg']):<12} {d['result'].pnl_pct:>+7.1f}% " + ' '.join(f'{c:>14}' for c in cells))


def a6_quarters(cfgs, a):
    out('6) Stabilitaet ueber die Zeit: netto R je Quartal')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    frames = []
    for d in res.values():
        t = d['trades']
        if not t.empty:
            frames.append(t.assign(strat=label(d['cfg'])))
    if not frames:
        out('Keine Trades.')
        return
    t = pd.concat(frames)
    t['q'] = t.ts.dt.tz_localize(None).dt.to_period('Q').astype(str)
    piv = t.pivot_table(index='strat', columns='q', values='r', aggfunc='sum', fill_value=0).round(1)
    out(piv.to_string())
    out(f"\nQuartale im Plus (Summe aller Strategien): {(piv.sum() > 0).sum()} von {piv.shape[1]}")


def a7_long_short(cfgs, a):
    out('7) Long vs. Short')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    out(f"{'Strategie':<12} {'Long n':>7} {'Long R':>8} {'Short n':>8} {'Short R':>8}")
    tot = []
    for d in res.values():
        t = d['trades']
        if t.empty:
            continue
        lo, sh = t[t.dir == 'long'], t[t.dir == 'short']
        out(f"{label(d['cfg']):<12} {len(lo):>7} {lo.r.mean() if len(lo) else 0:>+8.3f} "
            f"{len(sh):>8} {sh.r.mean() if len(sh) else 0:>+8.3f}")
        tot.append(t)
    if tot:
        t = pd.concat(tot)
        for side in ('long', 'short'):
            x = t[t.dir == side].r
            lo_, hi_ = boot_ci(x)
            out(f"ALLE {side:<6} n={len(x):>4}  R/Trade {x.mean():+.3f}  [{lo_:+.3f}, {hi_:+.3f}]")


def _daily(coin, start):
    d = load_ohlcv(f'{coin}/USDT:USDT', '1d', (pd.Timestamp(start) - pd.Timedelta(days=260)).strftime('%Y-%m-%d'),
                   date.today().isoformat())['close']
    return pd.DataFrame({'c': d, 's50': d.rolling(50).mean(), 's100': d.rolling(100).mean(),
                         's200': d.rolling(200).mean()})


def a8_regime(cfgs, a):
    out('8) Regime: BTC ueber/unter SMA200 und Wirkung des zerobot-Filters S6')
    out('   S6 = Long nur bei BTC > SMA200; Short nur bei BTC < SMA50 und Coin < SMA100 (letzte geschlossene Tageskerze)')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    btc = _daily('BTC', a.date_from)
    rows = []
    for d in res.values():
        t = d['trades']
        if t.empty:
            continue
        coin = d['cfg']['market']['symbol'].split('/')[0]
        cd = btc if coin == 'BTC' else _daily(coin, a.date_from)
        for r in t.itertuples():
            day = r.ts.floor('1D') - pd.Timedelta(days=1)
            b, c = btc.loc[:day].iloc[-1], cd.loc[:day].iloc[-1]
            up = b.c > b.s200
            s6 = up if r.dir == 'long' else (b.c < b.s50 and c.c < c.s100)
            rows.append({'strat': label(d['cfg']), 'up': up, 's6': s6, 'r': r.r, 'dir': r.dir})
    if not rows:
        out('Keine Trades.')
        return
    t = pd.DataFrame(rows)
    out(f"{'Strategie':<12} {'BTC>SMA200':>14} {'BTC<SMA200':>14} {'ohne Filter':>16} {'mit S6':>16}")
    for s, g in t.groupby('strat'):
        u, dn, f6 = g[g.up], g[~g.up], g[g.s6]
        out(f"{s:<12} {u.r.mean() if len(u) else 0:>+8.3f} ({len(u):>3}) {dn.r.mean() if len(dn) else 0:>+8.3f} ({len(dn):>3}) "
            f"{g.r.sum():>+9.1f}R ({len(g):>3}) {f6.r.sum():>+9.1f}R ({len(f6):>3})")
    for name, x in (('ohne Filter', t), ('mit S6', t[t.s6])):
        lo, hi = boot_ci(x.r)
        out(f"ALLE {name:<12} n={len(x):>4}  R/Trade {x.r.mean():+.3f} [{lo:+.3f}, {hi:+.3f}]  Summe {x.r.sum():+.1f}R")


def a9_correlation(cfgs, a):
    out('9) Korrelation der Wochen-Ergebnisse (niedrig = gute Streuung im Portfolio)')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    weekly = {}
    for d in res.values():
        t = d['trades']
        if not t.empty:
            weekly[label(d['cfg'])] = t.set_index('exit_ts').r.resample('W').sum()
    if len(weekly) < 2:
        out('Zu wenige Strategien mit Trades.')
        return
    w = pd.DataFrame(weekly).fillna(0)
    corr = w.corr().round(2)
    out(corr.to_string())
    off = corr.where(~np.eye(len(corr), dtype=bool)).stack()
    out(f"\nMittlere Korrelation: {off.mean():+.2f} | hoechstes Paar: {off.idxmax()} {off.max():+.2f}")


def a10_kelly(cfgs, a):
    out('10) Kelly-Sizing: optimaler Risikoanteil je Trade (halbes Kelly empfohlen)')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    out(f"{'Strategie':<12} {'Trades':>6} {'WR':>6} {'mittl. Gewinn R':>15} {'Kelly':>7} {'1/2 Kelly':>9} {'aktuell':>8}")
    for d in res.values():
        t = d['trades']
        if len(t) < 10:
            continue
        wins, losses = t[t.r > 0].r, t[t.r <= 0].r
        p = len(wins) / len(t)
        b = wins.mean() / abs(losses.mean()) if len(wins) and len(losses) else 0
        kelly = (p - (1 - p) / b) if b > 0 else -1
        cur = d['cfg']['risk'].get('risk_per_entry_pct', 0)
        out(f"{label(d['cfg']):<12} {len(t):>6} {p * 100:>5.0f}% {wins.mean() if len(wins) else 0:>15.2f} "
            f"{kelly * 100:>6.1f}% {kelly * 50:>8.1f}% {cur:>7.2f}%")


def a11_dd_duration(cfgs, a):
    out('11) Drawdown-Dauer: laengste Zeit ohne neues Equity-Hoch')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    out(f"{'Strategie':<12} {'MaxDD':>7} {'laengste Phase':>15} {'aktuell im DD seit':>20}")
    for d in res.values():
        t = d['trades']
        if t.empty:
            continue
        t = t.sort_values('exit_ts')
        eq = (1 + t.pnl_pct / 100).cumprod().values
        peak_ts, longest, peak = t.exit_ts.iloc[0], pd.Timedelta(0), eq[0]
        for e, ts in zip(eq, t.exit_ts):
            if e >= peak:
                peak, peak_ts = e, ts
            longest = max(longest, ts - peak_ts)
        cur = (pd.Timestamp.now(tz='UTC') - peak_ts) if eq[-1] < peak else pd.Timedelta(0)
        out(f"{label(d['cfg']):<12} {d['result'].max_drawdown_pct:>6.1f}% {longest.days:>12} Tage {cur.days:>16} Tage")


def a12_time(cfgs, a):
    out('12) Zeitmuster: netto R nach Wochentag und Tageszeit (UTC) des Fills')
    res = backtest_all(cfgs, a.date_from, a.date_to, a.capital)
    t = pd.concat([d['trades'] for d in res.values() if not d['trades'].empty])
    if t.empty:
        out('Keine Trades.')
        return
    days = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    g = t.groupby(t.ts.dt.dayofweek).r.agg(['size', 'mean', 'sum'])
    out('Wochentag  Trades  R/Trade  Summe')
    for i, r in g.iterrows():
        out(f"{days[i]:<9} {int(r['size']):>7} {r['mean']:>+8.3f} {r['sum']:>+7.1f}")
    g = t.groupby(t.ts.dt.hour // 4 * 4).r.agg(['size', 'mean', 'sum'])
    out('\nUhrzeit    Trades  R/Trade  Summe')
    for h, r in g.iterrows():
        out(f"{h:02d}-{h + 4:02d} Uhr {int(r['size']):>6} {r['mean']:>+8.3f} {r['sum']:>+7.1f}")


ANALYSES = {1: a1_is_oos, 2: a2_bootstrap, 3: a3_monte_carlo, 4: a4_fees, 5: a5_sensitivity,
            6: a6_quarters, 7: a7_long_short, 8: a8_regime, 9: a9_correlation, 10: a10_kelly,
            11: a11_dd_duration, 12: a12_time}


def main():
    ap = argparse.ArgumentParser(description='FiBot Analysen')
    ap.add_argument('--analysis', type=int, required=True, help='1-12, 0 = alle')
    ap.add_argument('--from', dest='date_from', default='2025-01-01')
    ap.add_argument('--to', dest='date_to', default=date.today().isoformat())
    ap.add_argument('--capital', type=float, default=100.0)
    ap.add_argument('--scope', choices=['alle', 'aktiv'], default='aktiv')
    ap.add_argument('--no-telegram', action='store_true')
    a = ap.parse_args()

    cfgs = load_configs(a.scope)
    if not cfgs:
        print('Keine Configs gefunden (Scope: %s). Erst run_pipeline.sh ausfuehren.' % a.scope)
        sys.exit(1)
    out(f"FiBot Analyse | {len(cfgs)} Strategie(n) ({a.scope}) | {a.date_from} bis {a.date_to} | Kapital {a.capital:.0f}")
    out('=' * 78)
    todo = sorted(ANALYSES) if a.analysis == 0 else [a.analysis]
    for n in todo:
        if n not in ANALYSES:
            print(f'Unbekannte Analyse {n}.')
            sys.exit(1)
        ANALYSES[n](cfgs, a)
        out('-' * 78)

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"analyse_{a.analysis}_{date.today().isoformat()}.txt")
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(_LINES))
    print(f'Bericht gespeichert: {path}')

    if not a.no_telegram:
        try:
            from fibot.utils.telegram import send_document
            sec = json.load(open(os.path.join(PROJECT_ROOT, 'secret.json'))).get('telegram', {})
            if sec.get('bot_token') and sec.get('chat_id'):
                send_document(sec['bot_token'], sec['chat_id'], path, caption=f'FiBot Analyse {a.analysis}')
        except Exception as e:
            print(f'Telegram nicht gesendet: {e}')


if __name__ == '__main__':
    main()
