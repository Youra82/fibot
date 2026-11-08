"""Offline-Vergleich und dynamische Detailansichten aus eingefrorenen Resultaten."""
from pathlib import Path
import sys,json,html
import numpy as np
import pandas as pd
from plotly.offline import get_plotlyjs

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fibot.analysis.edge_state import uncertainty,market_states
from fibot.analysis.edge_dashboard import write_dashboard,daily_history
from run import paired_ci

OUT=ROOT/'artifacts'/'edge_verbesserung_2026_11_08'

def read_trades(v):
    t=pd.read_csv(OUT/f'{v}_trades.csv')
    for c in ('touch_ts','entry_ts','exit_ts','known_at'):t[c]=pd.to_datetime(t[c],utc=True)
    return t

def records(t,cols):
    return json.loads(t[cols].to_json(orient='records',date_format='iso'))

def main():
    s=json.loads((OUT/'summary.json').read_text());inputs=json.loads((OUT/'inputs.json').read_text())
    base=s['base'];chosen=s['chosen'] or base;data={}
    coverage=json.loads((OUT/'coverage.json').read_text())
    states=market_states(daily_history(ROOT,'BTC/USDT:USDT',pd.Timestamp(s['end'])))
    for v,r in s['results'].items():
        t=read_trades(v);cv=pd.read_csv(OUT/f'{v}_equity.csv')
        # Tagesende plus erster/letzter Messpunkt; voller 15m-Verlauf bleibt als CSV erhalten.
        cv.ts=pd.to_datetime(cv.ts,utc=True)
        shown=pd.concat([cv.iloc[:1],cv.groupby(cv.ts.dt.floor('D')).tail(1),cv.iloc[-1:]]).drop_duplicates('ts').sort_values('ts')
        monthly=t.assign(month=t.known_at.dt.strftime('%Y-%m')).groupby('month').net_r.agg(['mean','size'])
        coins=t.groupby('coin').net_r.agg(['mean','sum','size']).sort_values('sum')
        u=uncertainty(t.net_r.values,t.known_at)
        roll=t.net_r.rolling(50).mean()
        data[v]=dict(result=r,point=u['point'],cloud=u['cloud'],
            equity=records(shown,['ts','equity']),
            rolling=[dict(ts=t.known_at.iloc[i].isoformat(),r=float(roll.iloc[i])) for i in range(49,len(t),3)],
            monthly=[dict(month=k,r=float(x['mean']),n=int(x['size'])) for k,x in monthly.iterrows()],
            coins=[dict(coin=k,r=float(x['mean']),total=float(x['sum']),n=int(x['size'])) for k,x in coins.iterrows()],
            trades=records(t,['coin','tf','direction','entry_ts','known_at','entry','sl','tp','net_r','result']))
        if v in (base,chosen,'L_A2_K'):
            meta=dict(source='Historischer Variantenvergleich '+v+'; gepoolte Einzelrechnungen',configs=len(inputs['configs']),
                config_sha256=s['results'][v].get('input_sha256',json.loads((OUT/'frozen_selection.json').read_text())['input_sha256']),
                as_of=pd.Timestamp(s['end']).isoformat(),start=pd.Timestamp(s['comparison_start']).isoformat(),
                regenerated=pd.Timestamp.now(tz='UTC').isoformat(),
                coverage=[dict(config=k,status='ok',last_close=(pd.Timestamp(x['last'])+pd.Timedelta(inputs['configs'][k]['market']['timeframe'])).isoformat()) for k,x in coverage.items()])
            write_dashboard(t,states,OUT/f'dynamisch_{v}.html',meta)
    exploratory=dict(variant='L_A2_K',paired_improvement_ci=paired_ci(read_trades(base),read_trades('L_A2_K')),
        caveat='Nach Betrachtung des Vergleichs hervorgehoben; kein eingefrorener Sieger. Intervall nicht fuer Mehrfachvergleiche korrigiert.')
    (OUT/'explorativ_2atr.json').write_text(json.dumps(exploratory,indent=2),encoding='utf8')
    payload=json.dumps(dict(summary=s,variants=data,exploratory=exploratory),ensure_ascii=False,allow_nan=False).replace('</','<\\/')
    template=(HERE/'report.html').read_text(encoding='utf8')
    (OUT/'VERGLEICH.html').write_text(template.replace('__PLOTLY__',get_plotlyjs()).replace('__DATA__',payload),encoding='utf8')
    def f(x):return '—' if x is None else f'{x:.3f}'
    rows=[]
    for v,r in s['results'].items():
        q=r['comparison'];a=r['account']
        rows.append(f"| {v} | {q['n']} | {q['win_rate']*100:.1f}% | {f(q['payoff'])} | {f(q['expectancy_r'])} | {f(q['ci'][0])} bis {f(q['ci'][1])} | {a['end_equity']:.2f} | {a['maxdd_pct']:.1f}% |")
    r=s['results'][chosen];q=r['comparison'];b=s['results'][base]
    text=f'''# Konfluenz: Ergebnis der 18 festgelegten Varianten

Entwicklung 01.01.2025–09.05.2026. Vergleich {s['comparison_start']} bis {s['end']}.
Beide Bereiche wurden bereits fuer Entwicklung oder Config-Auswahl verwendet.
Kein frischer Holdout. Keine Live-Aenderung. Feste heutige 17 Configs; keine
woechentliche historische Portfoliooptimierung. Dadurch Selection Bias.

Auf aelteren Daten ausgewaehlt und vor dem Vergleich eingefroren: **{chosen}**.
Vorab festgelegte Verbesserungskriterien bestanden: **{s['criteria_passed']}**.
95%-Blockintervall der gepaarten Erwartungsverbesserung gegen Kontrolle:
{s['paired_improvement_ci']}. Die Auswahl wird nach dem Vergleich nicht gewechselt.

Kontrolle: {b['comparison']['n']} geschlossene Einzeltrades,
{f(b['comparison']['expectancy_r'])} Netto-R je Trade;
gemeinsames Konto 60 → {b['account']['end_equity']:.2f} USDT.
Kandidat: {q['n']} Einzeltrades, {f(q['expectancy_r'])} Netto-R,
Halbzeiten {q['halves_R']}, Kostenstress {f(q['stress_R'])} Netto-R.
Kandidat gemeinsames Konto 60 → {r['account']['end_equity']:.2f} USDT,
Kostenstresskonto {r['stress_account']['end_equity']:.2f} USDT.

Die 2-ATR-Variante L_A2_K faellt erst im Vergleich positiv auf: 266 Trades,
0.299 Netto-R gegen 0.223 bei Kontrolle. Ihr direktes 95%-Intervall fuer
die Verbesserung reicht aber von -0.072 bis +0.224 R und umfasst null.
Sie ist deshalb keine nachgewiesene Verbesserung. Auf den aelteren Daten
lag sie mit 0.136 R unter der Kontrolle mit 0.291 R. Der vermeintlich bessere
Vergleich wird nicht nachtraeglich zur unberuehrten Auswahl umgedeutet.

Die R-Statistik stammt aus je Config isolierten Rechnungen und ist keine
Portfoliorendite. Das gemeinsame Konto begrenzt Positionen auf neun und eine
Position je Coin; 5 USDT Mindestnotional und Marginreservierung. MTM alle
15 Minuten aus letzten bekannten Kerzenschluessen. Endkontostand enthaelt
offene Positionen nach geschaetzten Ausstiegskosten. Keine Tick-, Lot-,
historische Funding- oder Liquidationssimulation. Schlupf- und Kostenstress
sind pauschale Annahmen. Fehlende Bars siehe coverage.json. Die Kontrolle
verwendet dasselbe konservative Kosten-/Gap-Modell wie alle Varianten und
kann deshalb von bisherigen Backtester-Zahlen abweichen.

| Variante | Trades | Gewinnquote | Payoff | Netto-R/Trade | 95%-Intervall R | Konto USDT | Max. DD |
|---|---:|---:|---:|---:|---|---:|---:|
'''+ '\n'.join(rows)+'''

L = Limit; C = nach Beruehrung Schlussbestaetigung, naechstes Open.
S = Strukturstop; A2 = mindestens 2 ATR Abstand, nur erweitern und Groesse
anpassen. K = Strukturziel; H = halbe Strukturzieldistanz; R15/R20/R30 =
1.5/2/3 Preis-R. Detektor mit bisheriger Mindest-CRV-Pruefung bleibt gleich.
Die Unsicherheitswolke wird aus tatsaechlichen Ergebnissen neu berechnet.

Interaktiver Bericht: VERGLEICH.html. Dynamische Detailseiten fuer Kontrolle
und eingefrorenen Kandidaten sind darin verlinkt. Rohtrades, Kontoreplays,
Input-Snapshot, Datenabdeckung und eingefrorene Auswahl liegen daneben.
'''
    (OUT/'ERGEBNIS.md').write_text(text,encoding='utf8')
    print(OUT/'VERGLEICH.html')

if __name__=='__main__':main()
