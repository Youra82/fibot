# Durchgehender Kontoverlauf mit woechentlich wechselndem Team (Einstiege nur waehrend der Team-Zugehoerigkeit,
# offene Positionen laufen ueber SL/TP aus) + echter Live-Kontoverlauf seit 15.10. + Diagramm.
import json, os, sys, glob, pickle
ROOT = r'C:\Users\matol\Desktop\botprojekte\fibot'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'src')); os.chdir(ROOT)
import logging; logging.disable(logging.WARNING)
import contextlib, io
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from fibot.analysis.portfolio_simulator import run_portfolio_simulation
from fibot.analysis.backtester import FINE_TF_MAP, LazyFineData

CAP = 100.0
data = pickle.load(open(os.path.join(HERE, 'data.pkl'), 'rb'))
weeks = [pd.Timestamp(w) for w in json.load(open(os.path.join(HERE, 'weeks.json')))]
sel = {}
for f in glob.glob(os.path.join(HERE, 'sel_*.json')):
    sel.update({pd.Timestamp(k): v for k, v in json.load(open(f)).items()})
assert len(sel) == len(weeks), f'{len(sel)}/{len(weeks)} Wochen ausgewaehlt'
NOW = pd.Timestamp.now(tz='UTC')

periods = {}
for i, w in enumerate(weeks):
    nxt = weeks[i + 1] if i + 1 < len(weeks) else None
    for f in sel[w]['team']:
        periods.setdefault(f, []).append((w, nxt))
sd = {}
for f, per in periods.items():
    d = data[f]; ftf = FINE_TF_MAP.get(d['timeframe'])
    sd[f] = {**d, 'active_periods': per, 'fine_df': LazyFineData(d['symbol'], ftf) if ftf else None}   # Feindaten: echte Reihenfolge SL/TP
import time as _t
_t0 = _t.time()
with contextlib.redirect_stdout(io.StringIO()):
    r = run_portfolio_simulation(CAP, sd, '', '')
print(f'Simulation fertig ({_t.time() - _t0:.0f}s)', flush=True)
eq = r['equity_curve'].set_index('timestamp').equity
eq.index = pd.to_datetime(eq.index, utc=True)
eq = eq[eq.index >= weeks[0]]
th = pd.DataFrame(r['trade_history']); th['ts'] = pd.to_datetime(th.ts, utc=True)

# Live-Konto aus Bitget-Buchungen
acc = json.load(open('secret.json'))['fibot']; acc = acc[0] if isinstance(acc, list) else acc
from fibot.utils.exchange import Exchange
ex = Exchange(acc); e = ex.exchange
e.timeout = 20000   # max. 20 s je Anfrage
bills, s = [], int(pd.Timestamp('2026-10-14', tz='UTC').timestamp() * 1000)
end_ms = e.milliseconds()
while s < end_ms:
    we, last = min(s + 7 * 86400000, end_ms), None
    for _page in range(50):   # harte Obergrenze statt Endlosschleife
        p = {'productType': 'USDT-FUTURES', 'startTime': str(s), 'endTime': str(we), 'limit': '100'}
        if last: p['idLessThan'] = last
        rr = e.private_mix_get_v2_mix_account_bill(p)['data']; b = rr.get('bills') or []; bills += b
        if len(b) < 100: break
        nxt = rr.get('endId') or b[-1]['billId']
        if nxt == last: break   # gleiche Seite noch einmal -> fertig
        last = nxt
    s = we
print(f'Kontobuchungen geladen: {len(bills)}', flush=True)
B = pd.DataFrame(bills).drop_duplicates('billId')
B['t'] = pd.to_datetime(B.cTime.astype('int64'), unit='ms', utc=True); B = B.sort_values('t')
live = B.set_index('t').balance.astype(float)
live = pd.concat([live, pd.Series([ex.fetch_equity_usdt()], index=[NOW])])
L0 = pd.Timestamp('2026-10-15', tz='UTC')
live = live[live.index >= L0]

# Kennzahlen
def dd(x): return float(((x / x.cummax()) - 1).min() * 100)
sim_l0 = float(eq[eq.index <= L0].iloc[-1])
sim_since = eq[eq.index >= L0]
stats = {
    'sim_end': float(eq.iloc[-1]), 'sim_pnl': float(eq.iloc[-1] / CAP * 100 - 100), 'sim_dd': dd(eq),
    'sim_at_l0': sim_l0, 'sim_pnl_to_l0': sim_l0 / CAP * 100 - 100, 'sim_dd_to_l0': dd(eq[eq.index <= L0]),
    'sim_since_l0': float(sim_since.iloc[-1] / sim_l0 * 100 - 100), 'sim_dd_since_l0': dd(sim_since),
    'live_start': float(live.iloc[0]), 'live_now': float(live.iloc[-1]),
    'live_since_l0': float(live.iloc[-1] / live.iloc[0] * 100 - 100), 'live_dd': dd(live),
    'trades': len(th), 'wr': float((th.pnl > 0).mean() * 100),
    'trades_since_l0': int((th.ts >= L0).sum()), 'wr_since_l0': float((th[th.ts >= L0].pnl > 0).mean() * 100),
    'team_sizes': {str(w.date()): len(sel[w]['team']) for w in weeks},
    'teams': {str(w.date()): [data[f]['symbol'].split('/')[0] + '/' + data[f]['timeframe'] for f in sel[w]['team']] for w in weeks},
}
m = eq.resample('ME').last(); m0 = pd.concat([pd.Series([CAP], index=[weeks[0]]), m])
stats['months'] = {k.strftime('%m/%y'): float(v) for k, v in (m0.pct_change().dropna() * 100).items()}
json.dump(stats, open(os.path.join(HERE, 'stats.json'), 'w'), indent=1)
eq.to_csv(os.path.join(HERE, 'equity_sim.csv'))

# Diagramm
BG, INK, MUTED, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e6e5e0'
BLUE, ORANGE, RED = '#2a78d6', '#eb6834', '#e34948'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.edgecolor': GRID,
                     'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.labelcolor': MUTED})
fig = plt.figure(figsize=(15, 11)); fig.patch.set_facecolor(BG)
gs = fig.add_gridspec(3, 1, height_ratios=[3.2, 0.9, 2.4], hspace=0.38)
ax, axn, az = [fig.add_subplot(gs[i]) for i in range(3)]
for a in (ax, axn, az):
    a.set_facecolor(BG); a.spines[['top', 'right']].set_visible(False); a.grid(axis='y', color=GRID, lw=0.7)

ax.plot(eq.index, eq.values, color=BLUE, lw=1.6, label='Backtest mit Wochenauswahl (Start 100 USDT)')
ax.set_ylabel('Konto (USDT)'); ax.axhline(CAP, color=MUTED, lw=0.8, ls=':')
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f'{v:,.0f}'.replace(',', '.')))
ax.axvspan(L0, eq.index[-1], color=ORANGE, alpha=0.10, lw=0)
ax.axvline(L0, color=ORANGE, lw=1.2, ls='--')
ax.text(L0, 0.97, ' Live-Start 15.10.\n ab hier ungesehene Daten', transform=ax.get_xaxis_transform(), va='top', fontsize=9, color=INK)
ax.text(0.01, 0.97, f"bis 15.10.: {stats['sim_pnl_to_l0']:+,.0f} %  (MaxDD {stats['sim_dd_to_l0']:.0f} %)\n"
                    f"Configs wurden auf genau diesem Zeitraum ausgewählt → geschönt".replace(',', '.'),
        transform=ax.transAxes, va='top', fontsize=9.5, color=INK)
ax.set_title('fibot: Kontoverlauf seit April 2026 mit wöchentlicher Portfolio-Auswahl (nachgespielt, nur Wissen bis zum Auswahltag)',
             loc='left', fontsize=12.5, color=INK)
ax.legend(loc='lower right', frameon=False, fontsize=9)

ts = pd.Series(stats['team_sizes']); ts.index = pd.to_datetime(ts.index, utc=True)
axn.bar(ts.index, ts.values, width=5, color=BLUE, align='edge')
axn.set_ylabel('Strategien\nim Team'); axn.set_xlim(ax.get_xlim())
for a in (ax, axn):
    a.xaxis.set_major_locator(mdates.MonthLocator()); a.xaxis.set_major_formatter(mdates.DateFormatter('%b %y'))

# Zoom seit 01.10.: Backtest vs. Live, beide in % ab 15.10.
z0 = pd.Timestamp('2026-10-01', tz='UTC')
ez = eq[eq.index >= z0] / sim_l0 * 100 - 100
lz = live / live.iloc[0] * 100 - 100
az.plot(ez.index, ez.values, color=BLUE, lw=1.6, label=f"Backtest mit Wochenauswahl: {stats['sim_since_l0']:+.1f} % seit 15.10.")
az.step(lz.index, lz.values, where='post', color=ORANGE, lw=1.8, label=f"Live-Konto (Bitget): {stats['live_since_l0']:+.1f} % seit 15.10.")
az.axhline(0, color=MUTED, lw=0.8); az.axvline(L0, color=ORANGE, lw=1.2, ls='--')
az.set_ylabel('% ab 15.10.'); az.legend(loc='lower left', frameon=False, fontsize=9.5)
az.set_title('Ausschnitt seit 01.10.: Backtest gegen echtes Live-Konto', loc='left', fontsize=11.5, color=INK)
az.xaxis.set_major_locator(mdates.DayLocator(interval=3)); az.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
fig.text(0.125, 0.04, f"Backtest: alle 38 Konfluenz-Configs, Auswahl jeden Mittwoch 01:00 UTC wie live (je Strategie ab OOS-Start 01.04., "
         f"max. PnL bei MaxDD ≤ 30 %, ein Timeframe je Coin), gemeinsames Kapital, {stats['trades']} Trades.", fontsize=8.5, color=MUTED)
out = os.path.join(HERE, 'fibot_equity_wochenauswahl.png')
fig.savefig(out, dpi=120, bbox_inches='tight', facecolor=BG)
print(json.dumps({k: v for k, v in stats.items() if k not in ('teams',)}, indent=1))
print('Team 21.10. (Replay):', stats['teams'].get('2026-10-21'))
print(out)
