# Vorregistrierung: Annäherung an die „nur Gewinner“-Kurve (fibot Konfluenz)

Festgelegt am 28.10.2026, nachdem nur die Suchdaten (Fills vor 01.04.2026, DISC, 3 855 Trades) angesehen wurden.
Prüfdaten: VAL = 01.04.–14.10.2026 (1 480 Trades), HOLD = ab 15.10.2026 (84 Trades). Beide noch nicht ausgewertet.

## Befund aus DISC
- Kein Einstiegsmerkmal hebt den Ertrag je Trade; Merkmale mit höherer Trefferquote (kleines CRV, flacher Rücksetzer)
  haben kleinere Gewinner (Tausch, kein Vorteil). Marktlage/BTC/Tageszeit: |rho| < 0,04.
- 41 % der Verlierer lagen vor dem SL mindestens +1R im Plus, 61 % mindestens +0,5R.

## Mechanismus
Der Einstieg sitzt an der unteren Kanallinie, das Ziel an der oberen. Viele Trades reagieren zuerst richtig
(Abprall von der Linie), erreichen die obere Linie aber nicht und fallen durch die untere zurück. Wer nach dem ersten
Abprall Risiko herausnimmt, macht aus einem Teil dieser Verlierer Null- oder Kleingewinne. Preis: Gewinner, die nach
dem Abprall noch einmal bis zum Einstieg zurücksetzen, werden zu früh beendet.

## Regeln (alle wirken erst ab der Kerze NACH der Kerze, deren Hoch die Schwelle erreicht; SL+TP in einer Kerze = SL zuerst)
- E0  Basis (heute live)
- BE05  SL auf Einstand (+ Gebühren) nach +0,5R
- BE10  SL auf Einstand nach +1R
- BE15  SL auf Einstand nach +1,5R
- P10   50 % bei +1R schließen, Rest: SL auf Einstand, Ziel unverändert
- P15   50 % bei +1,5R schließen, Rest: SL auf Einstand, Ziel unverändert
Teilschluss bei Erreichen der Schwelle als Limit (Kurs exakt bei Schwelle), Gebühren je Teil.

## Auswahl und Erfolgskriterien
1. Auf DISC wird genau EINE Regel gewählt: höchste Summe R, unter den Regeln mit Trefferquote (Trades mit R > 0) ≥ Basis + 10 Punkte.
2. Bestanden, wenn auf VAL: Summe R der Regel ≥ Summe R der Basis (Ertrag bleibt mindestens gleich) UND
   Anteil Trades mit R > 0 ≥ Basis + 10 Punkte UND größte Verlustserie (in Trades) kürzer als bei der Basis.
3. HOLD wird nur berichtet (zu wenige Trades für ein Urteil).
4. Danach: Portfolio-Simulation mit Wochenauswahl (wie Replay 08.04.–heute) mit der Regel gegen ohne.
