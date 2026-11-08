# Präregistrierung: Gesamtpaket Fibo-Wick-Konfluenz mit ≥ 1 Trade/Tag, OOS = letzte 26 Wochen

Stand 08.11.2026, geschrieben VOR jeder Rechnung auf dem OOS-Fenster.

## Ziel (vom User)
Gesamtpaket im ungesehenen OOS 10.05.2026 – 08.11.2026: Rendite > 10 %, im Schnitt ≥ 1 Trade/Tag (≥ 182 Fills),
Konto-MaxDD ≤ 30 % (Portfolio-Grenze des Users).

## Daten
160 Coins mit 30m-, 1h-, 2h-, 4h- und 6h-Daten (Bitget-Historie, heute gelistet). Ein Coin handelt ab seinem ersten Kurs.
Stufe 1 (Auswahl) liest nur Kerzen < 10.05.2026, Konto 10.05.2024 – 09.05.2026, Start 34 USDT.
Stufe 2 (OOS) erst nach SHA256-Freeze von auswahl.json: Konto 10.05.2026 – Datenende, Start 34 USDT, Vorhistorie nur Warmup.

## Engine
Unverändert fibot.analysis.wick_mtf_backtest.simulate (Parität zu Codex R14 bestätigt): 30m-Raster, L3, 12 Slots,
Risiko 7,5 %/Order, 45 % gesamt, 1 Position je Coin, Stop max(10 %, ATR, 1 %), TP = aktuelle Mitte ab Folgekerze,
Zeitausstieg 59 Kerzen, V2-Pause, Kosten Maker 0,02 % / Taker 0,06 % / Slippage 0,02 % / Funding 0,01 % je 8 h.

## Varianten (7, keine weiteren)
| ID | Zeitebenen | Tiefen % | Regel | MTF | BTC50 |
|---|---|---|---|---|---|
| V0 | 1h 2h 4h | 7 11 | R25 | ja | ja | (Kontrolle = Live-Einstellung)
| V1 | 30m 1h 2h 4h 6h | 5 7 11 | R25 | ja | ja |
| V2 | 30m 1h 2h 4h 6h | 5 7 11 | R25 | ja | nein |
| V3 | 30m 1h 2h 4h 6h | 5 7 11 | FIB | ja | ja |
| V4 | 30m 1h 2h 4h 6h | 5 7 11 | FIB | ja | nein |
| V5 | 30m 1h 2h 4h 6h | 5 7 11 | FIB | nein | ja |
| V6 | 30m 1h 2h 4h 6h | 5 7 11 | FIB | nein | nein |
BTC > SMA200 (Regime) gilt immer. FIB = nur Fib-Marke, R25 = Fib + runde Zahl. MTF = zusätzliche Fib-Marke von 2h/4h/6h über der eigenen Zeitebene.

## Auswahl (nur Stufe 1)
Zulässig: Konto-MaxDD ≤ 30 %, ≥ 1 Fill/Tag im Training, Rendite > 0. Höchste CAGR gewinnt (Gleichstand: kleinerer DD, ID).
Ist keine Variante zulässig: höchste Fills/Tag unter DD ≤ 30 % und CAGR > 10 %. Ist auch die leer: Abbruch ohne OOS.
Genau EINE Variante geht ins OOS.

## Bestanden (OOS)
Rendite > 10 % UND MaxDD ≤ 30 % UND ≥ 182 Fills. Daneben berichtet: Ergebnis je Kalendermonat, Anteil Gewinner, Exits.

## Grenzen
Survivorship (nur heute gelistete Coins), konstantes Funding, keine Lot-Mindestmengen, MaxDD auf 30m-Schlusskursen.
Die Familie (Wick-Rückkehr) ist durch frühere Forschung bekannt; das OOS-Fenster wurde für V0 auf 54 Coins bereits einmal gerechnet (+23 %).
