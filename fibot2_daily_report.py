# fibot2_daily_report.py -- taeglicher Abgleich fibot 2.0: echte Bitget-Trades vs. Portfolio-Backtest
# (fibot.analysis.fibot2_backtest) auf GENAU den Kerzen, die der Live-Bot benutzt hat (artifacts/fibot2_ohlcv).
# Laeuft aus master_runner (Modus fibot2) im Hintergrund und prueft selbst, ob er faellig ist (einmal taeglich ab send_hour UTC).
#   python fibot2_daily_report.py [--force] [--days 7]
import argparse, json, os, sys
from datetime import datetime, timezone

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'src')); sys.path.insert(0, ROOT)
from fibot.analysis import fibot2_backtest as BT  # noqa: E402
from fibot.strategy import fibot2_logic as F  # noqa: E402

LAST_RUN = os.path.join(ROOT, 'artifacts', 'db', '.last_fibot2_report')
REPORT_DIR = os.path.join(ROOT, 'artifacts', 'db', 'reports')
SEND_HOUR = 8
TOL = pd.Timedelta(minutes=20)


def due():
    now = datetime.now(timezone.utc)
    if now.hour < SEND_HOUR:
        return False
    try:
        return open(LAST_RUN).read().strip() != now.strftime('%Y-%m-%d')
    except FileNotFoundError:
        return True


def match(live, sim):
    """Live-Trade passt zu Backtest-Trade: gleicher Coin, gleiche Richtung, Einstieg in der Fuellkerze (+ Kulanz)."""
    used, pairs = set(), []
    for i, lt in live.iterrows():
        cand = sim[(sim.coin == lt.coin) & (sim.dir == lt.side) & (sim.ts <= lt.entry_time) &
                   (lt.entry_time <= sim.ts + sim.tf.map(pd.Timedelta) + TOL)]
        cand = cand[~cand.index.isin(used)]
        if len(cand):
            j = cand.index[0]; used.add(j); pairs.append((i, j))
    return pairs, used


def run(days, force=False):
    from daily_live_vs_backtest_check import _secrets, fetch_live
    from fibot.utils.telegram import send_message
    if not force and not due():
        return
    acc, tg = _secrets()
    end = pd.Timestamp.now(tz='UTC').floor('15min'); start = end - pd.Timedelta(days=days)
    trades, carry, open_pos, plans, equity = fetch_live(acc, start)
    live = pd.DataFrame(trades)
    if len(live):
        live['coin'] = live.symbol.str.replace('USDT', '', regex=False)
    ev, pl = BT.build(start, end, source='live')
    res, sim, _ = BT.simulate(ev, pl, start, end, equity0=equity or 34.)
    if len(sim):
        sim = sim.reset_index(drop=True)
    pairs, used = match(live, sim) if len(live) and len(sim) else ([], set())
    only_live = live.drop(index=[i for i, _ in pairs]) if len(live) else live
    only_sim = sim.drop(index=list(used)) if len(sim) else sim
    lines = [f'FiBot 2.0 Live vs. Backtest ({start:%d.%m.} - {end:%d.%m.%Y}, {days} Tage)',
             f'Live: {len(live)} Trades, PnL {live.pnl.sum() if len(live) else 0:+.2f} USDT',
             f'Backtest: {len(sim)} Trades, PnL {sim.pnl.sum() if len(sim) else 0:+.2f} USDT (gleiche Kerzen, Konto {equity:.2f})',
             f'Uebereinstimmend: {len(pairs)} | nur live: {len(only_live)} | nur Backtest: {len(only_sim)}']
    for _, r in only_live.head(8).iterrows():
        lines.append(f'  nur live: {r.coin} {r.side} {r.entry_time:%d.%m. %H:%M} PnL {r.pnl:+.2f}')
    for _, r in only_sim.head(8).iterrows():
        lines.append(f'  nur Backtest: {r.coin} {r.tf} {r.dir} {r.ts:%d.%m. %H:%M} {r.net_R:+.2f} R')
    for tf in ('15m', '30m', '1h', '2h', '4h', '6h'):
        g = F.gate_value(ev, tf, end)
        lines.append(f'  Phasentor {tf}: ' + ('offen' if g > 0 else 'zu') + (f' ({g:+.2f} R)' if pd.notna(g) else ' (zu wenig Trades)'))
    text = '\n'.join(lines)
    os.makedirs(REPORT_DIR, exist_ok=True)
    open(os.path.join(REPORT_DIR, f'fibot2_{end:%Y%m%d}.txt'), 'w', encoding='utf-8').write(text)
    send_message(tg.get('bot_token'), tg.get('chat_id'), text)
    os.makedirs(os.path.dirname(LAST_RUN), exist_ok=True)
    open(LAST_RUN, 'w').write(datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    print(text)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--force', action='store_true'); ap.add_argument('--days', type=int, default=7)
    a = ap.parse_args(); run(a.days, a.force)
