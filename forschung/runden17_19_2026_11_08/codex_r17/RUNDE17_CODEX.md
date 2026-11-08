# Runde 17: Codex-Entwicklung und Freeze

Es wurden genau zehn Filterideen mit jeweils einem festen Satz runder Schwellen untersucht, keine Schwellenraster und keine nachtraeglichen Varianten. Drei Kandidaten werden fuer Claudes gemeinsamen OOS-Test eingefroren. Ein positiver OOS-Ertrag ist damit NICHT nachgewiesen.

## Daten und Trennung

Gelesene Marktdaten: ausschliesslich `events_dev.pkl` und `btc_1d_dev.csv` in diesem Ordner. 42.649 Ereignisse. Das Entwicklungsskript prueft vor der Auswertung, dass jeder Einstieg, jeder Ausstieg und jeder BTC-Zeitstempel strikt vor 10.05.2026 UTC liegt. Kein Zugriff auf gesperrte Forschungspfade, Live-Trades, Boersen oder Netzwerk. Als Laufzeit dient die vorhandene fibot-venv (pandas 3.0.1); der Standardinterpreter kann das pandas-3-Pickle nicht laden.

Suche: Ausstieg vor 01.01.2026. Pruefung: Einstieg ab 01.01.2026 bis Ende der Entwicklungsdatei. Grenzuebergreifende Trades gehoeren nur zur Gesamtansicht. Die Pruefung ist ein Entwicklungs-Holdout, kein unangetasteter OOS-Test: Alle zehn Ideen wurden darauf betrachtet, danach wurden drei ausgewaehlt. Die coinweisen Zusatzteilungen A/B entstehen aus alphabetisch sortierten Coinnamen, abwechselnd zugeteilt; sie sind Robustheitsdiagnostik, keine weitere unabhaengige Testmenge. Keine coin- oder configbezogene Optimierung.

Jede Regel wird mit eligible kombiniert und chronologisch mit stabiler Tie-Reihenfolge replayt. Pro Coin bleibt hoechstens eine Position; Einstieg <= letzter gehaltener Ausstieg wird verworfen. Der Replay erfolgt ueber die ganze Entwicklung, danach werden Teilmengen gebildet: Positionen ueber der Jahresgrenze werden somit respektiert. Coins sind voneinander unabhaengige Positionsslots. Baseline = eligible ohne Filter. Es gibt keine nachtraegliche Filterung einer bereits replayten Baseline.

## Zehn Ideen und mechanische Begruendung

| Idee | Fester Ausdruck | Hypothese |
|---|---|---|
| trend_alignment | trend_ok & ema_ok & slope_ok | Mehrere Trendebenen reduzieren gegenlaeufige Konfluenzsignale. |
| btc_regime | Richtung entspricht vorherigem BTC-Tagesregime | Gemeinsamer Marktfaktor beguenstigt Long ueber SMA200 und Short darunter. |
| btc_regime_local | btc_regime & ema_ok & slope_ok | Globaler und lokaler Trend muessen zusammenpassen. |
| btc_momentum | btc_regime & gerichtete BTC-20-Tage-Rendite > 0 | Momentum bestaetigt das langsame Regime und soll Uebergangsfehler reduzieren. |
| adx_trend | ema_ok & slope_ok & adx >= 25 | Ein etablierter Trend soll zufaellige Kanalberuehrungen aussortieren. |
| volume_confirmation | ema_ok & vol_ratio >= 1 | Ueberdurchschnittliche Beteiligung soll schwache Ausbrueche aussortieren. |
| no_exhaustion | ema_ok & abs(ema_dist) <= 0.03 & 35 <= rsi <= 65 | Keine stark gestreckten oder ueberhitzten Einstiege; ema_dist als relative Distanz interpretiert. |
| structural_stop | 1 <= stop_atr <= 3 & risk_pct >= 1 | Stop ausserhalb normalen ATR-Rauschens, aber ohne extreme Ausdehnung und hohe relative Kosten. |
| cost_buffer | risk_pct >= 1 & rr >= 2 | Begrenzter Gebuehrenanteil in R und ausreichendes Zielpolster. |
| regime_cost_buffer | btc_regime & risk_pct >= 1 | Marktrichtung mit Kostenpuffer verbinden. |

Die Erklaerungen sind Hypothesen, keine aus diesen Daten bewiesenen Kausalmechanismen. Jede Idee verwendet exakt einen Schwellenwertsatz; keine Anpassung nach Sichtung der Ergebnisse.

## Auswahl und Rangfolge

Nach gemeinsamer Betrachtung wurden Regeln mit mindestens 300 Replay-Trades und positivem mittleren net_R in Suche, Pruefung und beiden Coinhaelften behalten. Die anderen sieben scheitern bereits am negativen net_R der Pruefung. Es wurden keine neuen Ideen nachgeschoben. Rangfolge: cost_buffer, structural_stop, regime_cost_buffer. Kosten- und Konzentrationsrobustheit geben dem ersten Kandidaten Vorrang. Der dritte Kandidat bleibt eine bewusst schwache Regimehypothese; er verbessert die Baseline bis 2025 nicht und verliert in 2026 nach Entfernen seiner Top-5-Coins.

## Ergebnisse aller Ideen

Angaben sind Mittelwerte in R pro gehaltenem Trade, keine Portfolio-Renditen. Die vollstaendigen maschinenlesbaren Werte einschliesslich Top-5-Coins stehen in `development_results.json`.

| Regel | N gesamt | net_R gesamt | Suche N / net_R | 2026 N / net_R | Coin A net_R | Coin B net_R |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 24645 | 0.0943 | 17649 / 0.1609 | 6973 / -0.0759 | 0.1129 | 0.0752 |
| trend_alignment | 10845 | 0.1198 | 7605 / 0.1781 | 3225 / -0.0173 | 0.1626 | 0.0743 |
| btc_regime | 15296 | 0.0187 | 11177 / 0.0762 | 4102 / -0.1351 | -0.0032 | 0.0413 |
| btc_regime_local | 10224 | 0.0445 | 7302 / 0.0990 | 2907 / -0.0881 | 0.0242 | 0.0658 |
| btc_momentum | 9793 | 0.0491 | 7874 / 0.0643 | 1904 / -0.0089 | 0.0286 | 0.0700 |
| adx_trend | 10135 | 0.1062 | 7268 / 0.1539 | 2858 / -0.0174 | 0.1341 | 0.0772 |
| volume_confirmation | 7176 | 0.1201 | 5266 / 0.1826 | 1898 / -0.0493 | 0.1399 | 0.0989 |
| no_exhaustion | 10983 | 0.0496 | 7160 / 0.1123 | 3817 / -0.0702 | 0.0661 | 0.0327 |
| structural_stop | 11610 | 0.1124 | 9305 / 0.1263 | 2288 / 0.0474 | 0.1188 | 0.1061 |
| cost_buffer | 11305 | 0.1557 | 9003 / 0.1721 | 2284 / 0.0799 | 0.1574 | 0.1540 |
| regime_cost_buffer | 8563 | 0.0738 | 6845 / 0.0862 | 1702 / 0.0304 | 0.0569 | 0.0914 |

## Kandidaten: Kosten, Konzentration und Unsicherheit je Teilung

Top-5 = fuenf Coins mit hoechster Summe net_R innerhalb der jeweiligen Teilmenge. Ohne Top-5 wird die bereits gehaltene Handelsliste um diese Coins reduziert (Coin-Slots sind getrennt). Anteil = verbleibende Tradezahl / gesamte Tradezahl. Keine festen Coinausschluesse fuer OOS.

Bootstrap: 2.000 Ziehungen, Seed 17020, nicht ueberlappende Kalenderbloecke zu 28 Tagen ab erstem Einstiegstag der Teilmenge, leere Zwischenbloecke eingeschlossen. Je Ziehung gleich viele Bloecke mit Zuruecklegen; Mittel als Summe R / Tradezahl. Alle Coins eines Zeitblocks bleiben gemeinsam. Perzentilintervall 2,5 bis 97,5 Prozent fuer mittleres net_R. Randbloecke koennen kuerzer sein. Deskriptive Intervalle ohne Selektions- oder Multiplizitaetskorrektur; keine p-Werte fuer OOS.

| Kandidat / Teilung | N | net_R | stress_R | Ohne Top-5 net_R | Ohne Top-5 N (Anteil) | 95%-Blockintervall net_R |
|---|---:|---:|---:|---:|---:|---|
| cost_buffer / all | 11305 | 0.1557 | 0.0580 | 0.1378 | 10507 (92.9%) | [0.0943, 0.2247] |
| cost_buffer / search | 9003 | 0.1721 | 0.0758 | 0.1513 | 8335 (92.6%) | [0.1028, 0.2441] |
| cost_buffer / validation2026 | 2284 | 0.0799 | -0.0223 | 0.0293 | 2140 (93.7%) | [-0.0403, 0.2141] |
| cost_buffer / coin_A | 5571 | 0.1574 | 0.0590 | 0.1246 | 4723 (84.8%) | [0.0836, 0.2358] |
| cost_buffer / coin_B | 5734 | 0.1540 | 0.0570 | 0.1183 | 5031 (87.7%) | [0.0802, 0.2358] |
| structural_stop / all | 11610 | 0.1124 | 0.0215 | 0.0969 | 10889 (93.8%) | [0.0682, 0.1553] |
| structural_stop / search | 9305 | 0.1263 | 0.0374 | 0.1064 | 8651 (93.0%) | [0.0884, 0.1638] |
| structural_stop / validation2026 | 2288 | 0.0474 | -0.0512 | 0.0044 | 2114 (92.4%) | [-0.0664, 0.1621] |
| structural_stop / coin_A | 5795 | 0.1188 | 0.0270 | 0.0941 | 4967 (85.7%) | [0.0617, 0.1759] |
| structural_stop / coin_B | 5815 | 0.1061 | 0.0161 | 0.0775 | 5058 (87.0%) | [0.0541, 0.1579] |
| regime_cost_buffer / all | 8563 | 0.0738 | -0.0171 | 0.0548 | 7904 (92.3%) | [-0.0422, 0.1812] |
| regime_cost_buffer / search | 6845 | 0.0862 | -0.0028 | 0.0623 | 6308 (92.2%) | [-0.0235, 0.1982] |
| regime_cost_buffer / validation2026 | 1702 | 0.0304 | -0.0677 | -0.0121 | 1603 (94.2%) | [-0.2538, 0.2320] |
| regime_cost_buffer / coin_A | 4374 | 0.0569 | -0.0345 | 0.0152 | 3729 (85.3%) | [-0.0743, 0.1845] |
| regime_cost_buffer / coin_B | 4189 | 0.0914 | 0.0010 | 0.0674 | 3658 (87.3%) | [-0.0249, 0.1964] |

## Grenzen und Uebergabe

Alle drei 2026-Intervalle enthalten null; alle drei stress_R-Mittel sind 2026 negativ. Regime-Kostenpuffer ist sogar ueber die ganze Entwicklung unter doppelten Kosten negativ. Damit ist keine der Regeln als robust profitabel bestaetigt. Die Kostenfilter reduzieren den beobachteten Einbruch, garantieren aber weder eine positive neue Marktphase noch einen positiven OOS-Test. Die kurzen 2026-Daten umfassen nur etwa fuenf 28-Tage-Bloecke; Bootstrap-Sicherheit ist begrenzt. Die Suchperiode mischt Auf- und Abwaertsphasen, die Pruefung adressiert speziell den beschriebenen Abwaertsmarkt; es wurde kein zusaetzlicher Regime-Sweep gerechnet. Aus dem Mindestumfang in der Entwicklung folgt keine garantierte OOS-Tradezahl. Kandidaten sind korreliert und selektiert; die Entwicklung enthaelt bereits eine bestehende Configauswahl.

`filter.py:masks` liefert ausschliesslich die drei eingefrorenen Kandidaten und nimmt keine Ergebnismerkmale in die Masken auf. Die Maske enthaelt das Signal, `replay` erzwingt zusaetzlich eligible. BTC-Regime: letzter vorhandener Tagesdatensatz strikt vor dem Einstiegstag, SMA200 aus 200 bis dahin vorhandenen Tageskerzen; fehlende Historie verwirft den Regimekandidaten. Keine aktuelle Tageskerze, keine Zukunftsrendite. Bei Datenluecken wird der letzte vorhandene Tag verwendet. Die API liest selbst keine Dateien und beschraenkt spaetere Aufrufer nicht auf Entwicklungsdaten; nur Claude darf sie im OOS anwenden.

Tests: `python -m unittest discover -s runde17 -p test_filter.py -v`. Geprueft werden Vortagsgrenze auch intraday, Aenderung/Entfernung aller BTC-Kerzen ab Einstiegstag, Umsortierung der BTC-Daten, fehlende Warmup-Historie, Replay mit Gleichzeitigkeit und eligible sowie reproduzierbarer Bootstrap. Alle fuenf Tests bestanden. `develop.py` reproduziert die zehn Originalhypothesen; die sieben verworfenen sind nur dort fuer die Auditierbarkeit enthalten.

`PREREG.sha256` bindet die exakten Bytes von `filter.py` und `KANDIDATEN.json`. Nach Erzeugung dieses Freeze-Manifests endet die Arbeit. Keine OOS-Auswertung, kein Nachjustieren; Claude uebernimmt den einzigen gemeinsamen Test samt Holm-Korrektur fuer diese drei und seine fuenf Kandidaten.
