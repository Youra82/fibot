# Daten aller Configs einmal laden (wie der Optimizer: --from oos, Signale vor OOS-Start ausgeblendet)
import json, os, sys, pickle
ROOT = r'C:\Users\matol\Desktop\botprojekte\fibot'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'src')); os.chdir(ROOT)
import logging; logging.disable(logging.WARNING)
import pandas as pd
from fibot.analysis.show_results import load_eval_df

END = '2026-10-28'
data = {}
for f in sorted(os.listdir('src/fibot/strategy/configs')):
    cfg = json.load(open(f'src/fibot/strategy/configs/{f}'))
    sym, tf = cfg['market']['symbol'], cfg['market']['timeframe']
    df, start = load_eval_df(sym, tf, cfg, 'oos', END)
    if df.empty:
        print('leer', f); continue
    df = df[df.index + pd.Timedelta(tf) <= pd.Timestamp.now(tz='UTC')]   # nur geschlossene Kerzen
    data[f] = {'symbol': sym, 'timeframe': tf, 'df': df, 'config': cfg}
pickle.dump(data, open(os.path.join(HERE, 'data.pkl'), 'wb'))
# Auswahltage: Mittwoch 01:00 UTC (= 03:00 VPS-Zeit), ab 08.04.2026
weeks = [str(t) for t in pd.date_range(pd.Timestamp('2026-04-08 01:00', tz='UTC'), pd.Timestamp('2026-10-28 02:00', tz='UTC'), freq='7D')]
json.dump(weeks, open(os.path.join(HERE, 'weeks.json'), 'w'))
print(len(data), 'Configs |', len(weeks), 'Auswahltage', weeks[0], '...', weeks[-1])
print('OOS-Starts:', sorted({d['config']['_backtest']['oos']['start_date'] for d in data.values()}))
