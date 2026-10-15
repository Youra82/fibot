# Vorregistrierung: Fibo-Kanal-Konfluenz (15.10.2026, vor dem ersten Lauf)

## Hypothese (Mechanismus)
In einem intakten Trendkanal kehrt ein Rücksetzer bevorzugt dort um, wo zwei Unterstützungen zusammenfallen:
- die untere Kanallinie, an der Marktteilnehmer schon mindestens zweimal gekauft haben,
- und die 50–61,8-%-Zone des letzten Impulses.

Eine Limit-Order an diesem Punkt hat einen engen, strukturell begründeten Stop (unter 78,6 % bzw. der Linie) und ein weites Ziel (obere Kanallinie). Shorts werden spiegelbildlich im fallenden Kanal gehandelt.

## Regeln (fest, Lehrbuch-Werte, keine Optimierung, gleich für alle Coins und Timeframes)
- **Pivots:** Hoch/Tief ist ein Extrem über ±5 Kerzen, erst 5 Kerzen später bestätigt (kein Lookahead).
- **Kanal (long):** untere Linie durch 2 bestätigte, steigende Pivot-Tiefs im Fenster der letzten 150 Kerzen. Eine Linie zählt nur, wenn alle folgenden Bedingungen erfüllt sind:
  - mindestens 2 Pivot-Tiefs liegen innerhalb von 0,3 ATR an der Linie,
  - höchstens 3 % der Schlusskurse seit dem ersten Ankerpunkt liegen mehr als 0,5 ATR darunter,
  - kein Pivot-Tief liegt mehr als 0,5 ATR darunter,
  - die Spanne beträgt mindestens 20 Kerzen.

  Unter mehreren gültigen Linien gewinnt die mit den meisten Berührungen, bei Gleichstand die jüngere.
- **Obere Linie:** parallel durch das relativ höchste Pivot-Hoch. Bedingungen: Breite mindestens 3 ATR und höchstens 3 % der Schlusskurse mehr als 0,5 ATR darüber.
- **Impuls:**
  - A ist das letzte Pivot-Tief an der unteren Linie.
  - B ist das höchste bestätigte Pivot-Hoch nach A; es muss höchstens 0,5 ATR unter der oberen Linie liegen.
  - Seit B darf kein Schlusskurs unter 78,6 % liegen.
  - Jedes B wird nur einmal gehandelt.
- **Konfluenz und Order:** Für Kerze i, berechnet aus den Daten bis i−1, wird die untere Linie auf i projiziert. Liegt dieser Wert in der Zone [61,8 % − 0,25 ATR, 50 % + 0,25 ATR] und der letzte Schlusskurs darüber, liegt dort eine Limit-Kauforder. Gefüllt wird, wenn das Tief der Kerze i diesen Preis erreicht; Füllpreis ist der Limitpreis.
- **SL:** min(78,6 %, Linie bei i) − 0,2 ATR.
- **TP:** obere Linie bei i.
- **Order nur bei Chance-Risiko von mindestens 1,5.**
- **Konservative Ausführung:** SL und TP sind fest. Erreicht die Füllkerze den SL, ist es ein Verlust. Ein TP zählt frühestens ab der nächsten Kerze. Berührt eine Kerze SL und TP, zählt es als Verlust.
- **Positionen:** höchstens 1 Position je Coin und Timeframe.
- **Kosten (primär):** 0,06 % Taker je Seite, also 0,12 % Roundtrip. Sekundär wird zusätzlich eine Maker-Variante berichtet: Entry 0,02 %, TP 0,02 %, SL 0,06 %.

## Daten
- **Coins:** AAVE, ADA, AVAX, BNB, BTC, DOGE, ETH, LINK, SOL, XRP (USDT-Perps, Bitget).
- **Primäre Timeframes:** 4h, 6h, 1d. Sekundär: 1h, 2h.
- **Zeitraum:** 2023-04-08 bis 2026-10-15.
- **Aufteilung:** Phase 1 bis 2026-03-31, OOS ab 2026-04-01 (derselbe OOS-Zeitraum, in dem die alten Configs versagt haben).

## Bestehenskriterium (primäre Timeframes, Taker-Kosten)
1. Gesamtzeitraum: netto ≥ +0,10 R pro Trade bei ≥ 300 Trades.
2. OOS ab 2026-04-01: netto > 0 R pro Trade.
3. Robustheit: in mindestens 6 von 10 Coins ist die Summe netto positiv.

Alle drei müssen erfüllt sein. Sonst gilt die Hypothese als nicht bestätigt, und es wird **nicht** an den Parametern nachjustiert.
Liegen es zwar positiv, aber unter 300 Trades, ist das Ergebnis „zu wenig Signale“: erst die Signalmenge klären, dann bewerten.

---

# Nachtrag v2 (15.10.2026, nach der visuellen Stichprobe, vor dem v2-Lauf)

v1 hat nicht bestanden. Die Stichprobe von 10 zufälligen Trades (fester Startwert) zeigt Schwächen in der Kanalerkennung:
- 8 von 10 Kanälen hatten nur 2 Berührungen.
- Die obere Linie wurde praktisch durch B selbst definiert, war also nicht unabhängig bestätigt.
- Einige Einstiege lagen sehr spät nach B.

v2 korrigiert **nur** die Kanaldefinition, gemessen daran, was ein Trader als Kanal zeichnet. Kriterium und Kosten bleiben unverändert. **Dies ist der letzte Anlauf.**

## Änderungen
1. Die obere Linie braucht **mindestens 2 Berührungen** durch Pivot-Hochs (innerhalb von 0,3 ATR). B darf eine davon sein. Die untere Linie braucht weiterhin mindestens 2.
2. **Kein** Schlusskurs seit dem ersten Anker liegt mehr als 0,5 ATR außerhalb einer der beiden Linien (`max_break_frac = 0`).
3. **Frischer Rücksetzer:** Die Fill-Kerze liegt höchstens 2 × (B − A) Kerzen nach B.

## Signalmenge
Liefern die 10 Coins auf 4h/6h/1d weniger als 300 Trades, wird das Universum um diese 10 etablierten Perps erweitert:
LTC, DOT, NEAR, UNI, ATOM, TRX, FIL, BCH, ETC, XLM.

Die Liste ist vorab festgelegt. Bewertet wird dann über alle 20 Coins. Kriterium 3 lautet dann: mindestens 12 von 20 Coins positiv.
