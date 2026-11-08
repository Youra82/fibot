# tests/wick_live_parity.py -- Ende-zu-Ende: unveraenderter Live-Zyklus (wick_mtf_live.run_cycle) auf der simulierten
# Boerse gegen den Konto-Backtest (wick_mtf_backtest.simulate) auf denselben Daten.
#   python tests/wick_live_parity.py <DATENWURZEL> 2026-09-20 2026-10-20
import os, sys, tempfile, time
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src')); sys.path.insert(0, os.path.dirname(__file__))
from fibot.strategy import wick_mtf as W, wick_mtf_live as LIVE  # noqa: E402
from fibot.analysis.wick_mtf_backtest import load_root, read_csv, simulate  # noqa: E402
from fake_bitget import FakeBitget  # noqa: E402


def main(root, start, end):
    start, end = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    data, _ = load_root(root, end=end)
    res, cv, bt = simulate(data, start, end)
    frames = {}
    for n in W.UNIVERSE:
        for tf in ('30m', '1h', '2h', '4h', '6h'):
            p = os.path.join(root, f'daten_{tf}', f'{n}-USDT-USDT_{tf}.csv')
            if os.path.exists(p):
                frames[n, tf] = read_csv(p)
    frames['BTC', '1d'] = read_csv(os.path.join(root, 'daten_BTC_1d.csv'))
    fx = FakeBitget(frames)
    LIVE.STATE_FILE = os.path.join(tempfile.mkdtemp(), 'state.json')
    t0 = time.time(); bars = pd.date_range(start, end - pd.Timedelta(minutes=30), freq='30min')
    for k, t in enumerate(bars):
        fx.begin_bar(t)
        LIVE.run_cycle(fx, now=t + pd.Timedelta(seconds=20))
        fx.process_bar(t)
        if k % 200 == 0:
            print(f'{t}  {k}/{len(bars)}  {time.time() - t0:.0f}s  Equity {fx.fetch_equity_usdt():.4f}', flush=True)
    fx.now = end
    live = pd.DataFrame(fx.ledger)
    eq_live = fx.cash + sum(v['margin'] + v['q'] * (frames[s.split('/')[0], '30m'].close.asof(end - pd.Timedelta(minutes=30)) - v['entry'])
                            for s, v in fx.positions.items())
    print(f'\nBacktest: {len(bt)} Exits, Ende {res["end"]:.6f}, offen {res["open_end"]}')
    print(f'Live:     {len(live)} Exits, Ende {eq_live:.6f}, offen {len(fx.positions)}')
    key = lambda d: set(zip(d.coin, pd.to_datetime(d.entry_ts, utc=True), d.res))
    a, b = key(bt) if len(bt) else set(), key(live) if len(live) else set()
    print('nur Backtest:', sorted(a - b)); print('nur Live:', sorted(b - a))
    if len(bt) and len(live):
        m = bt.merge(live, on=['coin', 'entry_ts', 'res'], suffixes=('_bt', '_live'))
        m['d_pnl'] = m.pnl_live - m.pnl_bt
        print(m[['coin', 'entry_ts', 'res', 'entry_bt', 'entry_live', 'exit_bt', 'exit_live', 'pnl_bt', 'pnl_live']].to_string())
        print('max |PnL-Abweichung| je Trade:', m.d_pnl.abs().max())
    return a == b


if __name__ == '__main__':
    ok = main(*sys.argv[1:4])
    print('PARITAET OK' if ok else 'PARITAET VERLETZT'); sys.exit(0 if ok else 1)
