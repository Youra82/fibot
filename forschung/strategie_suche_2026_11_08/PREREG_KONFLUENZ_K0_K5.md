# Vorregistrierung Konfluenz K0–K5 („wie ein Trader“), 08.11.2026 – vor jeder Rechnung dieser Regeln

User-Vorgabe: bei der Fibo-Kanal-Konfluenz bleiben, sie soll funktionieren. Frage: Welche Trader-Gewohnheiten fehlen dem fibot?
Umsetzung: `konfluenz_k.py`, Testumgebung `harness.py` (wie PREREG_H1_H5, Protokoll durch Kalibrierung mit ltbbot-Mechanismus bestätigt).

## Feste Basis (keine Optimierung, gleiche Werte für alle Coins)
Lehrbuch-Konfluenz v2 aus `confluence_logic.py`: DEFAULTS + V2 (pivot_k 5, window 150, touch 0,3 ATR, Bruch 0,5 ATR,
obere Linie ≥ 2 Berührungen, kein Schluss außerhalb, Zone 50–61,8 % ± 0,25 ATR, SL min(78,6 %, Linie) − 0,2 ATR,
TP obere Linie, Chance-Risiko ≥ 1,5, Fill ≤ 2·(B−A) Kerzen nach B). Long und Short (gespiegelt). 4h, 241 Coins.
Jeder Impuls B nur einmal; ein Trade je Coin und Richtung gleichzeitig.
Kosten: Limit-Einstieg Maker 0,02 %; Market-Einstieg Taker 0,06 % + 0,02 % Schlupf; SL Taker + Schlupf (bei Gap Open);
TP getriggerter Market = Taker. SL und TP in derselben Kerze → SL; TP frühestens ab Kerze nach Einstieg. Max. 120 Kerzen, dann Schluss.

## Varianten
- **K0 Basis:** Limit im Voraus wie live (Fill wenn Tief ≤ Limit; Füllkerze erreicht SL → Verlust).
- **K1 Bestätigung statt Limit:** Zone berührt (Tief ≤ Limit, Kerze nicht unter SL), dann in derselben oder einer der 3 Folgekerzen
  erster Schluss > Limit mit grüner Kerze (Schluss > Eröffnung), vorher kein SL-Kontakt → Market-Einstieg Open der nächsten Kerze.
  SL/TP aus dem Plan; Chance-Risiko am Einstiegspreis ≥ 1,0, sonst kein Trade.
- **K2 Volumen:** K0 + mittleres Volumen Impuls (A..B) > mittleres Volumen Rücksetzer (B+1..Kerze vor Order).
- **K3 Kanalqualität:** K0 + untere Linie ≥ 3 Berührungen.
- **K4 Liquide Coins + Gebühren:** K0 + Coin im oberen Drittel nach 30-Tage-Median des Quote-Volumens (close·volume, 4h-Summe
  je Tag, zeitpunktgerecht über alle Coins mit Daten) UND Stop-Abstand ≥ 1 % des Einstiegs.
- **K5 Trader-Kombi:** K1 + K2 + K3 + K4.

## Bestehen (je Variante, wie PREREG_H1_H5)
Segmente S = A bis 2025, P1 = B bis 14.10.2026, P2 = A 2026 bis 14.10.; ab 15.10. nur berichtet.
1. Tagesmittel > 0 in S, P1, P2. 2. P1 28-Tage-Block-Bootstrap p, Holm über K0–K5 bei 5 %.
3. P1: ≥ 55 % Coins (≥ 5 Trades) positiv, ohne Top-5-Coins > 0. 4. P1 mit +0,15 % Roundtrip + Funding 0,01 %/8 h > 0.
Zusatz (nicht Kriterium): R/Trade, Trades/Jahr, Long/Short getrennt. Kein Nachschieben von Varianten nach Blick auf P1/P2.
