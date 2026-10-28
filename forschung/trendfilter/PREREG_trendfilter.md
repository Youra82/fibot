# Vorregistrierung: nur in Richtung des übergeordneten Timeframes (fibot Konfluenz)

Festgelegt am 28.10.2026, bevor ein HTF-Merkmal auf irgendeinem Teil der Daten angesehen wurde.
Daten wie PREREG.md: alle gefüllten Orders der 38 Configs einzeln, Ausstieg wie live (SL zuerst, Gebühren).
DISC = vor 01.04.2026, VAL = 01.04.–14.10.2026, HOLD = ab 15.10.2026.

## Mechanismus
Der Einstieg ist ein Rücksetzer an die Kanallinie. Läuft der übergeordnete Trend des Coins in Handelsrichtung,
trägt er den Abprall (Trendfortsetzung); gegen den Trend ist der Rücksetzer eher der Beginn einer Gegenbewegung,
die durch die Linie läuft. Erwartung: höhere Trefferquote UND höherer Ertrag je Trade mit dem Trend.

## Trenddefinition (nur abgeschlossene HTF-Kerzen vor der Füllkerze)
- HTF4: Kerzen des Strategie-Timeframes zu 4er-Kerzen zusammengefasst (15m→1h, 30m→2h, 1h→4h, 2h→8h, 4h→16h, 6h→1d).
  Aufwärts = HTF-Schluss > EMA50 der HTF-Schlusskurse; abwärts = darunter.
- D1: Tageskerze des Coins, Schluss > SMA50 = aufwärts.

## Regeln
- F0   Basis: alle Trades
- H4   nur Trades in Richtung HTF4 (Long nur aufwärts, Short nur abwärts)
- D1   nur Trades in Richtung D1
- H4D1 nur wenn HTF4 und D1 beide in Handelsrichtung

## Auswahl und Erfolgskriterien
1. Auf DISC wird genau EINE Regel gewählt: höchster R je Trade unter den Regeln, die mindestens 35 % der Trades behalten.
2. Bestanden, wenn auf VAL: R je Trade der Regel > R je Trade der Basis mit 90-%-Bootstrap-Intervall der Differenz
   (gefilterte minus Basis) vollständig über 0 UND Trefferquote ≥ Basis + 3 Punkte.
3. Zusätzlich berichtet (kein Kriterium): Summe R, HOLD, und Portfolio-Simulation mit Wochenauswahl.
