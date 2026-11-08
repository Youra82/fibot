# Kerzen der 407 Kandidaten bis heute nachladen (nur fehlendes Endstueck, backtester.load_ohlcv)
import glob, json, os, sys, logging
from concurrent.futures import ThreadPoolExecutor
FIB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(FIB, 'src')); os.chdir(FIB)
logging.disable(logging.WARNING)
from fibot.analysis.backtester import load_ohlcv
jobs = set()
for f in glob.glob('forschung/konfluenz/search/candidates/*.json'):
    x = json.load(open(f)); jobs.add((x['market']['symbol'], x['market']['timeframe']))
def run(j):
    sym, tf = j
    p = f"data/cache/{sym.replace('/', '-').replace(':', '-')}_{tf}.csv"
    first = open(p).readline() and open(p).readlines()[1][:10]
    try:
        d = load_ohlcv(sym, tf, first, '2026-11-08'); return sym, tf, len(d), str(d.index[-1])
    except Exception as e:
        return sym, tf, -1, str(e)[:80]
with ThreadPoolExecutor(3) as ex:
    for k, r in enumerate(ex.map(run, sorted(jobs))):
        if r[2] < 0 or k % 50 == 0: print(k, r, flush=True)
print('FERTIG')
