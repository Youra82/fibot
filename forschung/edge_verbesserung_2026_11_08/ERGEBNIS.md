# Konfluenz: Ergebnis der 18 festgelegten Varianten

Entwicklung 01.01.2025–09.05.2026. Vergleich 2026-05-10 00:00:00+00:00 bis 2026-11-08 07:45:00+00:00.
Beide Bereiche wurden bereits fuer Entwicklung oder Config-Auswahl verwendet.
Kein frischer Holdout. Keine Live-Aenderung. Feste heutige 17 Configs; keine
woechentliche historische Portfoliooptimierung. Dadurch Selection Bias.

Auf aelteren Daten ausgewaehlt und vor dem Vergleich eingefroren: **L_S_K**.
Vorab festgelegte Verbesserungskriterien bestanden: **False**.
95%-Blockintervall der gepaarten Erwartungsverbesserung gegen Kontrolle:
[0.0, 0.0]. Die Auswahl wird nach dem Vergleich nicht gewechselt.

Kontrolle: 271 geschlossene Einzeltrades,
0.223 Netto-R je Trade;
gemeinsames Konto 60 → 175.76 USDT.
Kandidat: 271 Einzeltrades, 0.223 Netto-R,
Halbzeiten [0.2974778462813229, 0.13894877517842155], Kostenstress -0.042 Netto-R.
Kandidat gemeinsames Konto 60 → 175.76 USDT,
Kostenstresskonto 72.10 USDT.

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
| L_S_K | 271 | 36.2% | 2.251 | 0.223 | -0.021 bis 0.406 | 175.76 | 33.7% |
| L_S_R15 | 278 | 50.0% | 1.053 | 0.035 | -0.214 bis 0.242 | 106.80 | 37.1% |
| L_S_R20 | 273 | 42.1% | 1.456 | 0.044 | -0.213 bis 0.280 | 97.61 | 39.1% |
| L_S_R30 | 264 | 34.5% | 2.263 | 0.157 | -0.066 bis 0.411 | 158.77 | 31.2% |
| L_A2_K | 266 | 47.4% | 1.694 | 0.299 | 0.122 bis 0.455 | 207.76 | 27.3% |
| L_A2_R15 | 273 | 54.2% | 1.316 | 0.278 | 0.154 bis 0.384 | 204.64 | 24.5% |
| L_A2_R20 | 262 | 45.8% | 1.777 | 0.295 | 0.183 bis 0.425 | 194.26 | 20.3% |
| L_A2_R30 | 244 | 30.7% | 2.699 | 0.148 | -0.122 bis 0.437 | 99.29 | 45.4% |
| C_S_K | 168 | 48.8% | 1.396 | 0.183 | 0.029 bis 0.336 | 89.67 | 24.5% |
| C_S_R15 | 170 | 50.0% | 1.312 | 0.169 | 0.054 bis 0.297 | 88.45 | 14.8% |
| C_S_R20 | 166 | 38.6% | 1.775 | 0.076 | -0.041 bis 0.204 | 64.16 | 27.5% |
| C_S_R30 | 162 | 26.5% | 2.701 | -0.019 | -0.246 bis 0.202 | 45.55 | 44.7% |
| C_A2_K | 168 | 50.6% | 1.195 | 0.118 | -0.039 bis 0.219 | 77.76 | 23.1% |
| C_A2_R15 | 170 | 48.8% | 1.340 | 0.153 | 0.062 bis 0.234 | 86.67 | 16.3% |
| C_A2_R20 | 165 | 37.6% | 1.810 | 0.060 | -0.073 bis 0.166 | 64.24 | 25.9% |
| C_A2_R30 | 160 | 25.6% | 2.744 | -0.043 | -0.324 bis 0.210 | 47.35 | 46.0% |
| L_S_H | 279 | 49.5% | 1.118 | 0.062 | -0.092 bis 0.185 | 115.03 | 23.2% |
| C_S_H | 171 | 62.0% | 0.728 | 0.076 | -0.037 bis 0.207 | 71.11 | 23.8% |

L = Limit; C = nach Beruehrung Schlussbestaetigung, naechstes Open.
S = Strukturstop; A2 = mindestens 2 ATR Abstand, nur erweitern und Groesse
anpassen. K = Strukturziel; H = halbe Strukturzieldistanz; R15/R20/R30 =
1.5/2/3 Preis-R. Detektor mit bisheriger Mindest-CRV-Pruefung bleibt gleich.
Die Unsicherheitswolke wird aus tatsaechlichen Ergebnissen neu berechnet.

Interaktiver Bericht: VERGLEICH.html. Dynamische Detailseiten fuer Kontrolle
und eingefrorenen Kandidaten sind darin verlinkt. Rohtrades, Kontoreplays,
Input-Snapshot, Datenabdeckung und eingefrorene Auswahl liegen daneben.
