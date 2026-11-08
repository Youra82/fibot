# fibot – Warum ist er nicht produktiv? Untersuchung 08.11.2026 (festgelegt VOR den Rechnungen)

## Ausgangslage (bereits geprüft)
- Konto 58,6 (15.10.) → 33,74 USDT (08.11.), keine Transfers.
- Live = Backtest: 56/59 Live-Trades mit 1m-Daten nachgerechnet, gleiches Ergebnis, gleiche Ausstiegsminute.
- Live-Fehler: Wiedereinstieg im selben Impuls nach Sofort-SL (7 Extra-Trades). Erklärt den Verlust nicht.
- Live seit 15.10.: 6 Gewinner aus 52 Signalen, ohne Vorteil wären 12,7 ± 3 zu erwarten.

## Daten
407 Kandidaten der Konfluenz-Suche (`forschung/konfluenz/search/candidates`, je Coin×Timeframe auf In-Sample
optimiert), davon 38 ausgewählt (= live-Configs). Jede gefüllte Order einzeln, Ausstieg wie live (SL zuerst,
Gebühren 0,06 % je Seite), R nach Gebühren. Ohne Positionssperre. Zeiträume:
IS = Optimierungszeitraum der Config bis 31.03.2026 | OOS = 01.04.–14.10.2026 | HOLD = ab 15.10.2026.
Trendfilter wird je Trade mitgeschrieben (Auswahl lief ohne Filter → Hauptauswertung ohne Filter, Filter zusätzlich).

## Fragen und Regeln
**F1 Hat die Methode einen Vorteil?** Mittleres OOS-R/Trade über ALLE 407 Kandidaten (Mittel der Config-Mittel,
t über Configs). Vorteil nur bei > 0 mit t ≥ 2.

**F2 Sagt Vergangenheit die Zukunft voraus?** Spearman-Rho über die Kandidaten: IS-R → OOS-R und OOS-R → HOLD-R
(nur Configs mit ≥ 3 Trades im Zielzeitraum). Vorhersagekraft nur bei Rho > 0 mit p < 0,05.
Zusätzlich: 38 ausgewählte vs. 369 übrige im HOLD (R/Trade, Bootstrap über Configs).

**F3 Zeitverlauf:** monatliches R/Trade der 38 und aller 407. Gibt es einen Bruch am 15.10. oder fällt der Ertrag
schon vorher? Ist OOS-Ertrag der 38 von wenigen Monaten getragen?

**F4 Generalisierung:** präregistrierter Test `forschung/generalisierung` (Regeln dort, unverändert) laufen lassen.

**F5 Marktphase:** Ist die Lage seit 15.10. ungewöhnlich (BTC 30-Tage-Rendite, Volatilität)? R/Trade aller 407 in
IS+OOS je BTC-Phase. Wenn die Strategie in dieser Phase schon immer verlor → Phase; sonst nicht.

## Gesamturteil
„fibot hat einen echten Vorteil, Verlust ist Pech/Phase“ nur wenn F1 bestanden UND (F2 IS→OOS ODER OOS→HOLD
bestanden) UND F4 bestanden. Sonst: Der Backtest-Ertrag kam aus der Auswahl, nicht aus der Strategie.
Keine Änderung am Bot ohne Freigabe des Users.

## Ergebnis (08.11.2026, nach den Rechnungen)
- F1 NICHT bestanden: alle 407 Kandidaten im OOS −0,149 R/Trade (Config-Mittel, t −3,9), gepoolt −0,29 R; vor Gebühren ±0,00 R.
  Nur die 38 ausgewählten +0,42 R (Auswahl auf genau diesem Zeitraum). Bester mechanischer Filter (Stop ≥ 2 %, Trend) OOS +0,02 R (t 0,5).
- F2: IS→OOS ρ +0,13 (p 0,007), OOS→HOLD ρ +0,28 (p<0,001), getragen v. a. von 5m/1h (schlecht bleibt schlecht).
  HOLD 38 ausgewählt −0,29 vs. 369 übrige −0,30 R (Intervall breit). Gute Configs bleiben nicht gut.
- F3: alle Kandidaten ab April 2026 jeden Monat negativ; die 38 im OOS jeden Monat positiv (Auswahl), Okt −0,01, Nov −0,58.
- F5: seit 15.10. sehr ruhiger Markt (BTC-Vola 29 %, nur 11 % der Tage seit 2024 ruhiger); erklärt den Einbruch nicht allein.
- Gesamturteil nach Regel: Backtest-Ertrag kam aus der Auswahl, nicht aus der Strategie (F1 durchgefallen).
- Verlustzerlegung (mit Codex abgestimmt, ERGEBNIS_CODEX.md): 52 reguläre Konfluenz-Trades −31,2 USDT netto
  (davon Gebühren −3,6, Stop-Abweichung −1,9), 7 Doppel-Einstiege +2,8 (Glück WAL), Alt/Test −0,5, alte BTC/XRP +4,0,
  gesamt −24,9 USDT (Gebühren gesamt −5,3). Funding ~0.
- Team-Los: von 122 Backtest-Fills der 38 seit 15.10. live 50 genommen (−0,74 R), 72 nicht (+0,42 R, ohne 4 Ausreißer −0,28 R);
  nicht genommene Coins hatten live keine Orders = nicht im Wochenteam.
