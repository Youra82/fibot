# Trendfilter und Ausstiegsregeln (28.10.2026)

Frage: Wie kommt der fibot näher an die Kurve „nur Gewinner-Trades“?
Daten: jede gefüllte Order aller 38 Konfluenz-Configs einzeln (ohne Positionssperre), Ausstieg wie live
(SL zuerst, Gebühren 0,06 % je Seite).

| Teil | Zeitraum | Trades |
|---|---|---|
| DISC (Suche) | bis 31.03.2026 | 3 855 |
| VAL (Prüfung) | 01.04.–14.10.2026 | 1 480 |
| HOLD (ungesehen, live) | ab 15.10.2026 | 84 |

## 1. Einstiegsmerkmale (`features.py`, `discover.py`)

Kein Merkmal hebt den Ertrag je Trade. Höhere Trefferquote (kleines Chance-Risiko, flacher Rücksetzer) gibt es nur
gegen kleinere Gewinner. BTC-Lage, Coin-Lage und Tageszeit: Rangkorrelation unter 0,04.

## 2. Ausstiegsregeln (`PREREG_ausstiegsregeln.md`, `exits.py`): nicht bestanden

Einstand nach +0,5/1/1,5R und Teilschluss 50 % bei +1/1,5R. In der Prüfung hob der gewählte Teilschluss die
Trefferquote von 32 auf 46 %, senkte den Ertrag aber von +374R auf +116R (Bootstrap −258R, 90 % [−346, −172]).
45 % der Gewinner setzen vorher mindestens 0,5R zurück; jede Risikoreduktion schneidet sie ab.

## 3. Trendfilter (`PREREG_trendfilter.md`, `htf.py`): formal bestanden, eingebaut

Regel: nur Trades in Richtung des übergeordneten Trends. Der HTF-Trend wird aus 4-fachen Kerzen des
Strategie-Timeframes bestimmt (Schluss > EMA50), der Tagestrend aus der Tageskerze des Coins (Schluss > SMA50).
Beide müssen in Handelsrichtung zeigen.

| | DISC R/Trade | VAL R/Trade | VAL Trefferquote | HOLD R/Trade |
|---|---|---|---|---|
| alle Trades | +0,26 | +0,25 | 32,4 % | −0,08 |
| mit Filter | +0,23 | **+0,39** (90 % [+0,02, +0,26] über Basis) | 35,8 % | −0,19 |

Portfolio-Nachbildung mit Wochenauswahl seit 08.04.2026 (`prepare_htf.py`, `replay_*.py`):
100 USDT → 436 USDT mit Filter, 138 USDT ohne. Seit 15.10. −14 % statt −26 %.

**Vorbehalt:** In DISC war der Filter schlechter als ohne; Trades gegen den Trend waren dort sogar am besten
(+0,34R). Der Vorsprung im Portfolio kommt zu einem großen Teil aus dem Juni 2026. Live beobachten.

Live, Backtest, Optimizer, Portfolio-Auswahl und Tagesbericht nutzen dieselben Funktionen in
`src/fibot/strategy/trend_filter.py`; Schalter: `settings.json` → `trend_filter.enabled`.
Die Skripte stammen aus dem Analyseordner und erwarten dort ihre Zwischendateien (`events_*.csv`, `data.pkl`).
