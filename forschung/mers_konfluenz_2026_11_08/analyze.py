"""Zusatzdiagnostik ohne nachtraegliche Parameterwahl."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent

def difference_ci(base,hybrid):
    x=base.groupby(base.entry_ts.dt.floor('D')).R.sum()
    y=hybrid.groupby(hybrid.entry_ts.dt.floor('D')).R.sum()
    start=min(base.entry_ts.min(),hybrid.entry_ts.min()).floor('D')
    end=max(base.entry_ts.max(),hybrid.entry_ts.max()).floor('D')
    idx=pd.date_range(start,end,freq='D')
    d=y.reindex(idx,fill_value=0)-x.reindex(idx,fill_value=0)
    groups=[s.values for _,s in d.groupby(np.arange(len(d))//28)]
    rng=np.random.default_rng(121)
    draws=np.array([np.concatenate([groups[q] for q in rng.integers(0,len(groups),len(groups))]).mean() for _ in range(2000)])
    return dict(mean=float(d.mean()),lo=float(np.quantile(draws,.025)),hi=float(np.quantile(draws,.975)))

def main():
    T=pd.read_csv(HERE/'trades.csv',parse_dates=['entry_ts','exit_ts'])
    manifest=json.loads((HERE/'manifest.json').read_text())
    results=json.loads((HERE/'results.json').read_text())
    T['gross_R']=(T.ret+.0012)/(1-.0006*T.side)/(T.risk_pct/100)
    lines=['# MERS an der Fibo-Kanal-Konfluenz: Ergebnisse','',
       '**Urteil dieses Laufs: keine robust profitable Variante gefunden.** '
       'Auf 1h ist PE ueber die gesamte Historie leicht positiv (+0.038 R/Trade, 430 Trades), '
       'aber 2026 bis 14.10. negativ (-0.242 R/Trade), unter Kostenstress negativ (-0.034 R) '
       'und ohne die fuenf besten Coins negativ (-0.048 R). '
       'Auf 4h sind alle Varianten insgesamt negativ; auch alle sechs lokalen '
       'Stabilitaetsvarianten von PE bleiben insgesamt negativ. '
       'Die Reaktionslogik reduziert teilweise die Verluste, liefert aber keine belastbare '
       'Grundlage fuer eine Live-Umstellung.','',
       'Explorativer historischer Vergleich, kein unabhaengiger Profitabilitaetsnachweis. '
       'Keine Live-Aenderung. Ein R entspricht dem Preisrisiko zwischen Einstieg und Stop; '
       'Gebuehren und Schlupf koennen einen Stopverlust groesser als 1 R machen. '
       'Trade-Mittel sind keine Kontorenditen.','',
       'Alle Varianten verlangen die bestehende strenge Fibo-Kanal-Konfluenz. '
       'L: Limit; C: Rueckeroberung; P: C + nachlassender Gegendruck; E: C + gerichtete Energie; '
       'PE: beides; PEH: zusaetzlich sinkende Histogramm-Entropie.','',
       '## Daten','']
    for tf in ('4h','1h'):
        m=[r for r in manifest if r['tf']==tf]
        lines.append(f'- {tf}: {len(m)} Coins, {sum(r["bars"] for r in m):,} Kerzen, '
                     f'{sum(r["events"] for r in m)} Konfluenzberuehrungen; '
                     f'Historie {min(r["start"] for r in m)} bis {max(r["end"] for r in m)}.')
    lines+=['','Das Universum enthaelt heute vorhandene Coins (Survivorship-Bias). '
            'Die letzten Daten liegen vor dem heutigen Datum. Letzte Zeile je Datei entfernt. '
            'Keine historischen Funding-, Orderbuch- oder Intrabardaten in diesem Test; '
            'Stress ist ein pauschales Szenario, keine Rekonstruktion. '
            'Die Geometrie entspricht DEFAULTS + V2, nicht individuell optimierten Coin-Configs.','',
            '## Gesamtergebnis','',
            '| TF | Variante | Trades | Netto R/Trade | Brutto R/Trade | Stress R/Trade | Gewinner | Ohne Top-5 R | Robust |',
            '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for tf in ('4h','1h'):
        for var in ('L','C','P','E','PE','PEH'):
            t=T[(T.tf==tf)&(T.variant==var)]
            r=results[tf+'_'+var]; s=r['all']
            lines.append(f'| {tf} | {var} | {len(t)} | {s.get("R",np.nan):+.3f} | '
                f'{t.gross_R.mean():+.3f} | {s.get("stress_R",np.nan):+.3f} | '
                f'{s.get("win_pct",np.nan):.1f}% | {s.get("without_top5_R",np.nan):+.3f} | '
                f'{"ja" if r.get("robust") else "nein"} |')
    lines+=['','## Zeit- und Coinpruefungen','',
            '| TF/Variante | vor 2026 R (n) | 2026 bis 14.10. R (n) | ab 15.10. R (n) | Coin A R | Coin B R | Holm p bestanden |',
            '|---|---:|---:|---:|---:|---:|---|']
    for k,r in results.items():
        cells=[]
        for s in ('before2026','2026_before_oct15','recent'):
            cells.append(f'{r[s].get("R",np.nan):+.3f} ({r[s]["n"]})')
        lines.append('| '+k+' | '+' | '.join(cells)+f' | {r["coins_A"].get("R",np.nan):+.3f} | '
                    f'{r["coins_B"].get("R",np.nan):+.3f} | {r.get("holm",False)} |')
    lines+=['','## Guenstigere Maker-Gebuehr fuer den bisherigen Einstieg','',
            'Der Hauptvergleich berechnet allen Entries 6 bp. Fuer L allein entspricht '
            'eine Maker-Entrygebuehr von 2 bp folgender Verbesserung; Exit und Schlupf bleiben gleich:','']
    for tf in ('4h','1h'):
        b=T[(T.tf==tf)&(T.variant=='L')]
        maker=b.R+.0004/(b.risk_pct/100)
        lines.append(f'- {tf}: L mit 2 bp Entrygebuehr {maker.mean():+.3f} R/Trade '
                     f'(statt {b.R.mean():+.3f}).')
    lines+=['','## Verbesserung gegenueber Limit','',
            '28-Tage-Blockbootstrap der Differenz taeglicher Netto-R-Summen, vor 15.10.2026, '
            'inklusive entryfreier Tage. Unterschiedliche Trade-Zahlen gehen damit ein. '
            '95%-Intervalle sind deskriptiv und nicht fuer Mehrfachvergleiche korrigiert. '
            'R-Summen unterstellen gleiche Risikoeinheiten ohne Portfoliokapitalbegrenzung.','',
            '| TF | Hybrid | Differenz R/Tag | 95%-Intervall |','|---|---|---:|---|']
    delta={}
    for tf in ('4h','1h'):
        pre=T[(T.tf==tf)&(T.entry_ts<pd.Timestamp('2026-10-15',tz='UTC'))]
        for var in ('C','P','E','PE','PEH'):
            a=pre[pre.variant=='L'];b=pre[pre.variant==var]
            if len(a)==0 or len(b)==0: continue
            d=difference_ci(a,b);delta[tf+'_'+var]=d
            lines.append(f'| {tf} | {var} | {d["mean"]:+.4f} | [{d["lo"]:+.4f}; {d["hi"]:+.4f}] |')
    sensitivity_path=HERE/'sensitivity_results.json'
    if sensitivity_path.exists():
        sensitivity=json.loads(sensitivity_path.read_text())
        lines+=['','## Lokale Stabilitaet von PE auf 4h','',
            'Vorab separat festgelegte Einzelfaktor-Aenderungen, ohne Auswahl einer besten Einstellung.','',
            '| Aenderung | Trades | Netto R/Trade | Stress R/Trade | Vor 2026 R | Ab 2026 R | Ab 2026 ohne Top-5 R |',
            '|---|---:|---:|---:|---:|---:|---:|']
        for k,v in sensitivity.items():
            a=v['all'];b=v['before2026'];c=v['2026']
            lines.append(f'| {k} | {a["n"]} | {a["R"]:+.3f} | {a["stress_R"]:+.3f} | '
                         f'{b["R"]:+.3f} | {c["R"]:+.3f} | {c["without_top5_R"]:+.3f} |')
    lines+=['','## Ausfuehrung und Grenzen','',
        '- 6 bp Gebuehr je Seite; 2 bp Schlupf auf Market-Entry, Stop und Zeitausstieg. '
        'TP als Limit ohne zusaetzlichen Schlupf. Baseline-Fill konservativ am Limit.',
        '- Struktur-SL/TP unveraendert eingefroren; nach Bestaetigung mindestens 1:1 Preis-CRV. '
        'Vier Kerzen Bestaetigungsfrist, 120 Kerzen maximale Haltedauer.',
        '- SL zuerst bei SL/TP in einer Kerze; kein TP in Eintrittskerze. '
        'Offene Endpositionen und Trades ueber Datenluecken ausgeschlossen.',
        '- Zwoelf automatische Pruefungen fuer Ausfuehrungszeitpunkt, Kosten, Stopvorrang und Gaps, '
        'Spiegelung, Zukunftsinvarianz der Merkmale, Datenluecken, offene Endpositionen, Positionsgrenze '
        'sowie Richtung von Energie und Gegendruck. Zusaetzlich nichtleere ADA-Konfluenzstichprobe '
        'auf Zukunftsinvarianz geprueft.',
        '- Keine Parametersuche. Robuste Freigabe verlangt positive Zeit- und Coinsegmente, '
        'Kostenstress, Ergebnis ohne Top-5 sowie Holm-korrigierte Evidenz ueber zehn Hybridtests.',
        '- Ein fehlgeschlagener Test widerlegt nicht jede moegliche MERS-Definition; '
        'ein einzelner positiver Ausschnitt bestaetigt keine allgemeine Profitabilitaet.','',
        'Reproduktion: `../../.venv/Scripts/python run.py`, danach `../../.venv/Scripts/python analyze.py`. '
        'Details und festgelegte Regeln: PROTOKOLL.md; Rohtrades: trades.csv; Segmente: results.json.']
    (HERE/'ERGEBNIS.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    (HERE/'paired_differences.json').write_text(json.dumps(delta,indent=2),encoding='utf8')
    print('\n'.join(lines))

if __name__=='__main__':main()
