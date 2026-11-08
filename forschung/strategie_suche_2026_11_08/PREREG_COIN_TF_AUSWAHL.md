# Vorregistrierung „Konfluenz funktioniert nur auf bestimmten Coins/Zeitebenen“ (User-These), 08.11.2026, vor der Rechnung

These (User): Die Konfluenz ist nicht allgemeingültig, funktioniert aber auf bestimmten Coin×Zeitebene-Kombinationen.
Handelbar ist das nur, wenn die Kombinationen VORHER erkennbar sind. Test: rollierende Auswahl nach eigener Vergangenheit.

## Regel (fest, keine Optimierung je Coin)
- Signal: K0-Lehrbuch-Konfluenz (DEFAULTS+V2, Limit im Voraus, TP obere Kanallinie, SL Plan) mit Mindest-Stop ≥ 1 ATR und ≥ 1 %
  (Ablehnung sonst), Long + Short, Kosten wie runde3.py. Zeitebenen 2h, 4h, 6h (geobot-Speicher, alle Coins mit Daten).
- Monatlich zum Monatsbeginn M (ab 2023-01 bis 2026-10): je Kombination Mittel-R der Trades mit Ausstieg im Fenster [M−6 Mon., M),
  nur Kombinationen mit ≥ 5 solchen Trades. Auswahl: die 20 mit höchstem Mittel-R, sofern > 0.
- Gehandelt werden in Monat M alle Trades (Einstieg in M) der ausgewählten Kombinationen.

## Bestehen
1. Mittel der Monatsmittel (R/Trade der Auswahl) > 0 über alle Monate.
2. Einseitiger Block-Bootstrap über Monate (3-Monats-Blöcke, 9999 Ziehungen, +1-Korrektur): p ≤ 0,05 für Mittel > 0.
3. Auswahl besser als alle Kombinationen im selben Monat (Mittel der monatlichen Differenz > 0, gleicher Bootstrap p ≤ 0,05).
4. Beide Hälften (2023–24, 2025–26) Mittel > 0.
Zusatz: Ergebnis ab 15.10.2026 berichtet (schon gesehen), Monate mit 0 Auswahl gezählt als 0 Trades (ausgelassen).
