# Vorregistrierung „Welche Einstellungen machen die 38 bestätigten Configs profitabel?“ (Claude), 08.11.2026, vor der Rechnung

## Einstellungsraum (12, fest)
Ziel ∈ {Kanal oben (live), 1 R, 2 R} × Trendfilter ∈ {aus, an (live: HTF 4×TF EMA50 + Tag SMA50)} × Mindest-Stop ∈ {aus (live), ≥ 1 ATR und ≥ 1 %}.
Signal je Config unverändert (eigene Parameter, plan_both), Limit-Fill wie Backtest, SL zuerst, TP ab Folgekerze, Maker 0,02 % rein,
Taker 0,06 % + 0,02 % Schlupf raus (auf Ausstiegs-Notional), max. 200 Kerzen, ein Trade je Config gleichzeitig.

## Teil 1 – Rückblick (In-Sample, nur berichtet)
Je Einstellung: R/Trade aller 38 Configs mit Einstieg 15.10.–08.11.2026; je Config die beste Einstellung.

## Teil 2 – Walk-Forward (entscheidet)
Monatlich zum Monatsbeginn M von 2024-07 bis 2026-11 (Nov. = bis 08.11.): je Config die Einstellung mit höchster Summe R
der Einstiege in [M−3 Monate, M) bei ≥ 3 Trades; ist diese Summe ≤ 0 → Config in M nicht handeln. Gehandelt: Einstiege in M.
Vergleich: feste Live-Einstellung (Kanal oben, Trend an, Stop aus) für alle Configs.
Bestehen „adaptives Einstellen funktioniert“: (1) Mittel der Monats-R/Trade adaptiv > 0, (2) Mittel der monatlichen Differenz
adaptiv − fest > 0, beide mit Block-Bootstrap über Monate (3-Monats-Blöcke, 9999, +1-Korrektur) p ≤ 0,05,
(3) Zusatzbericht 15.10.–08.11.2026 (adaptiv gewählt mit Daten bis 15.10.).
Hinweis: Die 38 Configs wurden auf 01.04.–14.10.2026 ausgewählt → Monate in diesem Zeitraum sind auswahlverzerrt (positiv); getrennt
berichten: 2024-07..2026-03 (vor OOS-Auswahl), 2026-04..2026-10 (Auswahlzeitraum), ab 15.10. (danach).
