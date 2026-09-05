# fibot/daten/compare_live_vs_backtest.py
# Vergleicht echte Live-Trades (Bitget Order-Fill-History) mit dem Backtest
# der aktuell in settings.json aktiven Configs -- inkl. Wochenkorrelation.
#
# Aufruf (aus dem fibot-Projektordner):
#   .venv/Scripts/python.exe daten/compare_live_vs_backtest.py
#   .venv/Scripts/python.exe daten/compare_live_vs_backtest.py --start 2026-05-01 --end 2026-09-05 --capital 100

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone

import ccxt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from fibot.analysis.backtester import run_backtest, load_ohlcv, FINE_TF_MAP, LazyFineData
from fibot.analysis.optimizer import _fetch_min_contracts

CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')
SETTINGS_PATH = os.path.join(PROJECT_ROOT, 'settings.json')
SECRET_PATH = os.path.join(PROJECT_ROOT, 'secret.json')


def _config_filename(symbol: str, timeframe: str) -> str:
    safe = symbol.replace('/', '').replace(':', '')
    return f"config_{safe}_{timeframe}_fib.json"


def load_active_strategies():
    with open(SETTINGS_PATH) as f:
        settings = json.load(f)
    strategies = settings['live_trading_settings']['active_strategies']
    out = {}
    for s in strategies:
        if not s.get('active', True):
            continue
        symbol, timeframe = s['symbol'], s['timeframe']
        sym_id = symbol.split('/')[0] + 'USDT'  # z.B. "ADAUSDT"
        out[sym_id] = (symbol, timeframe, _config_filename(symbol, timeframe))
    return out


def make_exchange():
    with open(SECRET_PATH) as f:
        secret = json.load(f)
    acc = secret['fibot'][0] if isinstance(secret['fibot'], list) else secret['fibot']
    ex = ccxt.bitget({
        'apiKey': acc['apiKey'],
        'secret': acc['secret'],
        'password': acc['password'],
        'options': {'defaultType': 'swap'},
        'enableRateLimit': True,
    })
    ex.load_markets()
    return ex


def fee_sum(fill):
    total = 0.0
    for fd in fill.get('feeDetail', []) or []:
        try:
            total += float(fd.get('totalFee', 0))
        except (TypeError, ValueError):
            pass
    return total


def fetch_all_fills(ex, start_ms, end_ms):
    """Bitget order/fill-history erlaubt max. 7 Tage pro Request -> in Fenstern abholen."""
    window_ms = 7 * 86400 * 1000
    all_fills = {}
    win_start = start_ms
    while win_start < end_ms:
        win_end = min(win_start + window_ms, end_ms)
        id_less_than = None
        while True:
            params = {
                'productType': 'USDT-FUTURES',
                'startTime': str(win_start),
                'endTime': str(win_end),
                'pageSize': 100,
            }
            if id_less_than:
                params['idLessThan'] = id_less_than
            resp = ex.private_mix_get_v2_mix_order_fill_history(params)
            lst = resp.get('data', {}).get('fillList', []) or []
            if not lst:
                break
            for fl in lst:
                all_fills[fl['tradeId']] = fl
            if len(lst) < 100:
                break
            id_less_than = lst[-1]['tradeId']
            time.sleep(ex.rateLimit / 1000)
        win_start = win_end
        time.sleep(ex.rateLimit / 1000)
    return list(all_fills.values())


def live_closing_trades_by_symbol(fills):
    close_fills = [f for f in fills if f.get('tradeSide') == 'close']
    by_order = defaultdict(lambda: {'profit': 0.0, 'fee': 0.0, 'symbol': None, 'ctime': 0})
    for f in close_fills:
        key = (f['symbol'], f['orderId'])
        t = by_order[key]
        t['profit'] += float(f.get('profit', 0) or 0)
        t['fee'] += fee_sum(f)
        t['symbol'] = f['symbol']
        t['ctime'] = max(t['ctime'], int(f['cTime']))

    by_symbol = defaultdict(list)
    for t in by_order.values():
        by_symbol[t['symbol']].append((t['ctime'], t['profit'] + t['fee']))
    for sym in by_symbol:
        by_symbol[sym].sort(key=lambda x: x[0])
    return by_symbol


def backtest_trades_by_symbol(active, start_date, end_date, capital):
    out = {}
    for sym_id, (symbol, timeframe, fname) in active.items():
        cfg_path = os.path.join(CONFIGS_DIR, fname)
        if not os.path.exists(cfg_path):
            print(f"  [!] Config fehlt: {fname} -- ueberspringe {sym_id}")
            out[sym_id] = []
            continue
        config = json.load(open(cfg_path))
        df = load_ohlcv(symbol, timeframe, start_date, end_date)
        if df.empty:
            out[sym_id] = []
            continue
        fine_tf = FINE_TF_MAP.get(timeframe)
        fine_data = LazyFineData(symbol, fine_tf) if fine_tf else None
        result = run_backtest(df, config, capital, symbol, timeframe,
                               min_contracts=_fetch_min_contracts(symbol), fine_data=fine_data)
        closed = [t for t in result.trades if t.result != 'open']
        out[sym_id] = [(int(t.timestamp.timestamp() * 1000), float(t.pnl_usdt)) for t in closed]
        print(f"  {sym_id:<10} Backtest: {len(closed):>3} Trades  |  PnL {result.pnl_pct:+.2f}%  |  WR {result.win_rate:.1f}%")
    return out


def to_weekly(trades_ms, start_ms, n_weeks):
    weekly = defaultdict(float)
    week_ms = 7 * 86400 * 1000
    for ts, pnl in trades_ms:
        wk = min((ts - start_ms) // week_ms, n_weeks - 1)
        weekly[wk] += pnl
    return [weekly.get(w, 0.0) for w in range(n_weeks)]


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / (sx * sy)


def main():
    ap = argparse.ArgumentParser(description="FiBot: Live-Trades vs. Backtest + Korrelation")
    ap.add_argument('--start', default='2026-05-01', help="Startdatum YYYY-MM-DD")
    ap.add_argument('--end', default=None, help="Enddatum YYYY-MM-DD (Default: heute)")
    ap.add_argument('--capital', type=float, default=100.0, help="Backtest-Startkapital je Coin (isoliert)")
    args = ap.parse_args()

    start_date = args.start
    end_date = args.end or date.today().isoformat()

    print(f"\n=== FiBot Live vs. Backtest: {start_date} -> {end_date} ===\n")

    active = load_active_strategies()
    print(f"Aktive Strategien laut settings.json: {', '.join(active.keys())}\n")

    print("1/3: Live-Fills von Bitget laden (7-Tage-Fenster)...")
    ex = make_exchange()
    start_ms = ex.parse8601(start_date + 'T00:00:00Z')
    end_ms = ex.parse8601(end_date + 'T23:59:59Z')
    fills = fetch_all_fills(ex, start_ms, end_ms)
    live_by_symbol = live_closing_trades_by_symbol(fills)
    print(f"  {len(fills)} Fills geladen, {sum(len(v) for v in live_by_symbol.values())} geschlossene Positionen insgesamt.\n")

    print("2/3: Backtest je aktivem Coin laufen lassen...")
    bt_by_symbol = backtest_trades_by_symbol(active, start_date, end_date, args.capital)

    print("\n3/3: Korrelation berechnen (wochenweise)...\n")
    n_days = (datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)).days + 1
    n_weeks = max(3, -(-n_days // 7))

    print(f"{'Coin':<10} {'Live Trades':>11} {'BT Trades':>10} {'Trend-r':>9} {'Wochen-r':>9}")
    print("-" * 55)
    combined_live = [0.0] * n_weeks
    combined_bt = [0.0] * n_weeks
    for sym_id in active:
        live_weekly = to_weekly(live_by_symbol.get(sym_id, []), start_ms, n_weeks)
        bt_weekly = to_weekly(bt_by_symbol.get(sym_id, []), start_ms, n_weeks)
        live_cum = [sum(live_weekly[:i + 1]) for i in range(n_weeks)]
        bt_cum = [sum(bt_weekly[:i + 1]) for i in range(n_weeks)]
        r_trend = pearson(live_cum, bt_cum)
        r_week = pearson(live_weekly, bt_weekly)
        for i in range(n_weeks):
            combined_live[i] += live_weekly[i]
            combined_bt[i] += bt_weekly[i]
        n_live = len(live_by_symbol.get(sym_id, []))
        n_bt = len(bt_by_symbol.get(sym_id, []))
        rt_str = f"{r_trend:+.2f}" if r_trend is not None else "n/a"
        rw_str = f"{r_week:+.2f}" if r_week is not None else "n/a"
        print(f"{sym_id:<10} {n_live:>11} {n_bt:>10} {rt_str:>9} {rw_str:>9}")

    combined_live_cum = [sum(combined_live[:i + 1]) for i in range(n_weeks)]
    combined_bt_cum = [sum(combined_bt[:i + 1]) for i in range(n_weeks)]
    r_trend_all = pearson(combined_live_cum, combined_bt_cum)
    r_week_all = pearson(combined_live, combined_bt)

    print("-" * 55)
    print(f"Portfolio-Trendkorrelation (kumuliert):  r = {r_trend_all:+.2f}" if r_trend_all is not None else "n/a")
    print(f"Portfolio-Wochenkorrelation:              r = {r_week_all:+.2f}" if r_week_all is not None else "n/a")
    print(f"\nLive Netto-PnL gesamt (aktive Coins):  {combined_live_cum[-1]:+.2f} USDT")
    print(f"Backtest PnL gesamt (isoliert, {args.capital:.0f} USDT je Coin): {combined_bt_cum[-1]:+.2f} USDT")
    print()


if __name__ == '__main__':
    main()
