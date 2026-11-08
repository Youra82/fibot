# MERS an der Fibo-Kanal-Konfluenz: Ergebnisse

**Urteil dieses Laufs: keine robust profitable Variante gefunden.** Auf 1h ist PE ueber die gesamte Historie leicht positiv (+0.038 R/Trade, 430 Trades), aber 2026 bis 14.10. negativ (-0.242 R/Trade), unter Kostenstress negativ (-0.034 R) und ohne die fuenf besten Coins negativ (-0.048 R). Auf 4h sind alle Varianten insgesamt negativ; auch alle sechs lokalen Stabilitaetsvarianten von PE bleiben insgesamt negativ. Die Reaktionslogik reduziert teilweise die Verluste, liefert aber keine belastbare Grundlage fuer eine Live-Umstellung.

Explorativer historischer Vergleich, kein unabhaengiger Profitabilitaetsnachweis. Keine Live-Aenderung. Ein R entspricht dem Preisrisiko zwischen Einstieg und Stop; Gebuehren und Schlupf koennen einen Stopverlust groesser als 1 R machen. Trade-Mittel sind keine Kontorenditen.

Alle Varianten verlangen die bestehende strenge Fibo-Kanal-Konfluenz. L: Limit; C: Rueckeroberung; P: C + nachlassender Gegendruck; E: C + gerichtete Energie; PE: beides; PEH: zusaetzlich sinkende Histogramm-Entropie.

## Daten

- 4h: 241 Coins, 1,685,503 Kerzen, 1649 Konfluenzberuehrungen; Historie 2021-10-29 20:00:00+00:00 bis 2026-11-01 08:00:00+00:00.
- 1h: 48 Coins, 1,876,549 Kerzen, 1813 Konfluenzberuehrungen; Historie 2021-10-29 18:00:00+00:00 bis 2026-11-01 18:00:00+00:00.

Das Universum enthaelt heute vorhandene Coins (Survivorship-Bias). Die letzten Daten liegen vor dem heutigen Datum. Letzte Zeile je Datei entfernt. Keine historischen Funding-, Orderbuch- oder Intrabardaten in diesem Test; Stress ist ein pauschales Szenario, keine Rekonstruktion. Die Geometrie entspricht DEFAULTS + V2, nicht individuell optimierten Coin-Configs.

## Gesamtergebnis

| TF | Variante | Trades | Netto R/Trade | Brutto R/Trade | Stress R/Trade | Gewinner | Ohne Top-5 R | Robust |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 4h | L | 1632 | -0.210 | -0.174 | -0.259 | 20.3% | -0.254 | nein |
| 4h | C | 910 | -0.207 | -0.181 | -0.241 | 27.9% | -0.253 | nein |
| 4h | P | 776 | -0.200 | -0.176 | -0.232 | 28.5% | -0.249 | nein |
| 4h | E | 440 | -0.145 | -0.123 | -0.174 | 32.0% | -0.214 | nein |
| 4h | PE | 345 | -0.167 | -0.146 | -0.196 | 31.6% | -0.245 | nein |
| 4h | PEH | 174 | -0.101 | -0.080 | -0.130 | 33.9% | -0.224 | nein |
| 1h | L | 1794 | -0.079 | +0.011 | -0.198 | 25.1% | -0.145 | nein |
| 1h | C | 1060 | -0.076 | -0.016 | -0.157 | 33.8% | -0.135 | nein |
| 1h | P | 932 | -0.075 | -0.016 | -0.153 | 34.3% | -0.131 | nein |
| 1h | E | 543 | +0.013 | +0.067 | -0.060 | 40.0% | -0.062 | nein |
| 1h | PE | 430 | +0.038 | +0.092 | -0.034 | 41.2% | -0.048 | nein |
| 1h | PEH | 197 | -0.013 | +0.041 | -0.084 | 39.1% | -0.141 | nein |

## Zeit- und Coinpruefungen

| TF/Variante | vor 2026 R (n) | 2026 bis 14.10. R (n) | ab 15.10. R (n) | Coin A R | Coin B R | Holm p bestanden |
|---|---:|---:|---:|---:|---:|---|
| 4h_L | -0.209 (1230) | -0.267 (388) | +1.276 (14) | -0.331 | -0.124 | False |
| 4h_C | -0.244 (700) | -0.141 (202) | +1.427 (8) | -0.345 | -0.112 | False |
| 4h_P | -0.250 (605) | -0.084 (166) | +1.960 (5) | -0.348 | -0.094 | False |
| 4h_E | -0.197 (326) | -0.070 (109) | +1.554 (5) | -0.238 | -0.105 | False |
| 4h_PE | -0.260 (262) | +0.054 (79) | +1.557 (4) | -0.343 | -0.065 | False |
| 4h_PEH | -0.275 (126) | +0.245 (44) | +1.557 (4) | -0.328 | +0.007 | False |
| 1h_L | -0.043 (1479) | -0.227 (302) | -0.676 (13) | -0.008 | -0.151 | False |
| 1h_C | -0.042 (874) | -0.223 (178) | -0.578 (8) | +0.017 | -0.180 | False |
| 1h_P | -0.027 (771) | -0.289 (153) | -0.596 (8) | +0.044 | -0.209 | False |
| 1h_E | +0.045 (443) | -0.116 (95) | -0.442 (5) | +0.119 | -0.102 | False |
| 1h_PE | +0.102 (349) | -0.242 (78) | -0.043 (3) | +0.175 | -0.127 | False |
| 1h_PEH | +0.043 (159) | -0.306 (37) | +1.984 (1) | +0.094 | -0.164 | False |

## Guenstigere Maker-Gebuehr fuer den bisherigen Einstieg

Der Hauptvergleich berechnet allen Entries 6 bp. Fuer L allein entspricht eine Maker-Entrygebuehr von 2 bp folgender Verbesserung; Exit und Schlupf bleiben gleich:

- 4h: L mit 2 bp Entrygebuehr -0.198 R/Trade (statt -0.210).
- 1h: L mit 2 bp Entrygebuehr -0.049 R/Trade (statt -0.079).

## Verbesserung gegenueber Limit

28-Tage-Blockbootstrap der Differenz taeglicher Netto-R-Summen, vor 15.10.2026, inklusive entryfreier Tage. Unterschiedliche Trade-Zahlen gehen damit ein. 95%-Intervalle sind deskriptiv und nicht fuer Mehrfachvergleiche korrigiert. R-Summen unterstellen gleiche Risikoeinheiten ohne Portfoliokapitalbegrenzung.

| TF | Hybrid | Differenz R/Tag | 95%-Intervall |
|---|---|---:|---|
| 4h | C | +0.0908 | [+0.0236; +0.1637] |
| 4h | P | +0.1102 | [+0.0407; +0.1877] |
| 4h | E | +0.1626 | [+0.0776; +0.2530] |
| 4h | PE | +0.1670 | [+0.0790; +0.2631] |
| 4h | PEH | +0.1895 | [+0.0911; +0.2935] |
| 1h | C | +0.0313 | [-0.0244; +0.0886] |
| 1h | P | +0.0375 | [-0.0231; +0.1005] |
| 1h | E | +0.0786 | [-0.0019; +0.1606] |
| 1h | PE | +0.0827 | [-0.0030; +0.1667] |
| 1h | PEH | +0.0710 | [-0.0216; +0.1636] |

## Lokale Stabilitaet von PE auf 4h

Vorab separat festgelegte Einzelfaktor-Aenderungen, ohne Auswahl einer besten Einstellung.

| Aenderung | Trades | Netto R/Trade | Stress R/Trade | Vor 2026 R | Ab 2026 R | Ab 2026 ohne Top-5 R |
|---|---:|---:|---:|---:|---:|---:|
| energy075 | 413 | -0.162 | -0.191 | -0.256 | +0.150 | -0.047 |
| energy125 | 300 | -0.158 | -0.187 | -0.248 | +0.125 | -0.068 |
| pressure075 | 310 | -0.155 | -0.184 | -0.262 | +0.185 | -0.032 |
| pressure125 | 364 | -0.142 | -0.171 | -0.215 | +0.085 | -0.106 |
| wait2 | 156 | -0.304 | -0.334 | -0.403 | +0.017 | -0.314 |
| wait6 | 474 | -0.158 | -0.186 | -0.212 | +0.026 | -0.135 |

## Ausfuehrung und Grenzen

- 6 bp Gebuehr je Seite; 2 bp Schlupf auf Market-Entry, Stop und Zeitausstieg. TP als Limit ohne zusaetzlichen Schlupf. Baseline-Fill konservativ am Limit.
- Struktur-SL/TP unveraendert eingefroren; nach Bestaetigung mindestens 1:1 Preis-CRV. Vier Kerzen Bestaetigungsfrist, 120 Kerzen maximale Haltedauer.
- SL zuerst bei SL/TP in einer Kerze; kein TP in Eintrittskerze. Offene Endpositionen und Trades ueber Datenluecken ausgeschlossen.
- Zwoelf automatische Pruefungen fuer Ausfuehrungszeitpunkt, Kosten, Stopvorrang und Gaps, Spiegelung, Zukunftsinvarianz der Merkmale, Datenluecken, offene Endpositionen, Positionsgrenze sowie Richtung von Energie und Gegendruck. Zusaetzlich nichtleere ADA-Konfluenzstichprobe auf Zukunftsinvarianz geprueft.
- Keine Parametersuche. Robuste Freigabe verlangt positive Zeit- und Coinsegmente, Kostenstress, Ergebnis ohne Top-5 sowie Holm-korrigierte Evidenz ueber zehn Hybridtests.
- Ein fehlgeschlagener Test widerlegt nicht jede moegliche MERS-Definition; ein einzelner positiver Ausschnitt bestaetigt keine allgemeine Profitabilitaet.

Reproduktion: `../../.venv/Scripts/python run.py`, danach `../../.venv/Scripts/python analyze.py`. Details und festgelegte Regeln: PROTOKOLL.md; Rohtrades: trades.csv; Segmente: results.json.
