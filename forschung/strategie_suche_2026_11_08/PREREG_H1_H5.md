# Vorregistrierung H1–H5 (Claude + Codex), 08.11.2026 – vor jeder Rechnung dieser Regeln

Quelle der Regeln: VORSCHLAEGE_CODEX.md (Codex), unverändert übernommen, Umsetzung in `h1_h5.py`.
Referenz (Ausbruch-Long „H5 alt“, 04.10.) wurde vorab nachgerechnet (`ref_tests.py`): Tages-t negativ, Endtest −4,5 % → gilt als NICHT robust.

## Daten
geobot-Speicher, 4h, 241 Coins (ohne Stablecoins/Gold), nur heute gelistete Coins (Survivorship). BTC-Tag: stbot+ltbbot+geobot.
Coin-Split fest (Seed 20261108): A 120 / B 121 (`harness.split_coins`).

## Gemeinsame Regeln (alle Hypothesen)
- Nur Long. Signale aus geschlossenen 4h-Kerzen, Einstieg Market zum Open der Folgekerze (+0,02 % Schlupf, 0,06 % Taker).
- G = letzter abgeschlossener BTC-Tagesschluss > Tages-SMA200 (bekannt ab Schluss der Signalkerze).
- ATR20 nach Wilder. SL/TP fest ab Fill. Ausstieg: SL (Stop-Market, Taker + Schlupf; bei Gap zum Open), TP (getriggerter
  Market, Taker), Zeitausstieg nach N Kerzen zum Schluss (Taker + Schlupf). SL und TP in derselben Kerze → SL.
  TP frühestens ab der Kerze nach dem Einstieg.
- Ein Trade je Coin gleichzeitig; nach Ausstieg 6 Kerzen Pause; Signale währenddessen verfallen.
- Funding nicht in den Daten: zusätzlich Szenario 0,01 % je angefangene 8 h Haltedauer.

## Regeln
- **H1 Zweite Welle:** Ereignis b = erster Schluss > SMA20+3·ATR20 (Vorkerze nicht), G_b. b+1..b+3 schließen alle > C_b − A_b und
  ihre Spanne (max H − min L) ≤ 2·A_b. In b+4..b+9 erster Schluss > max(H_b..H_b+3) bei G → Einstieg. A vom Trigger.
  SL −3A, TP +12A, max 60 Kerzen. Ein aktives Setup je Coin.
- **H2 Rücktest des Ausbruchs:** D_b = höchstes Hoch der 20 Kerzen vor b; C_b > D_b, C_b−1 ≤ D_b, G_b. In b+1..b+6 erster Rücktest
  L_t ≤ D_b, L_t ≥ D_b − A_b, C_t > D_b; vorher Tief oder Schluss < D_b − A_b → verworfen. Bei G Einstieg. A am Rücktest.
  SL −3A, TP +9A, max 42 Kerzen.
- **H3 Isolierte Kapitulation:** C_t−1 > SMA50_t−1, G_t, A_pre = ATR20_t−1, D = Minimum der Tiefs t−12..t−1.
  L_t < D, L_t ≤ C_t−1 − 3·A_pre, C_t > D, C_t ≥ L_t + 0,65·(H_t − L_t), V_t ≥ 2·Median(V_t−20..t−1), BTC-4h-Rendite der Kerze > −1 %.
  SL −3·A_pre, TP +4,5·A_pre, max 6 Kerzen.
- **H4 Rückgewinn nach Marktschock:** Marktrendite = gleichgewichtete 4h-Rendite der Coins mit ≥ 200 Kerzen Vorlauf (≥ 100 Coins).
  Schock: ≤ −4 % und G. Coin-Setup bei eigener Rendite ≤ −6 %; P = C_t−1, A_pre. In t+1..t+6 erster Schluss > P (Vorkerze ≤ P) bei G
  → Einstieg. SL −3·A_pre, TP +6·A_pre, max 12 Kerzen.
- **H5 Erster Ausbruch nach Regimewechsel:** BTC schließt Tag d erstmals > SMA200 nach 10 Tagen ≤. Fenster d+1 .. d+20.
  Je Coin nur der erste Wechsel Schluss > SMA20+3·ATR20 im Fenster. SL −3A, TP +12A, max 60 Kerzen.

## Auswertung und Bestehen (je Hypothese, alle Punkte)
Segmente: S = A bis 31.12.2025 | P1 = B bis 14.10.2026 | P2 = A 01.01.–14.10.2026. Ab 15.10. nur berichtet (bereits gesehen).
1. In S, P1 und P2: Mittel der Tages-Mittel > 0.
2. P1: einseitiger p-Wert aus 28-Tage-Block-Bootstrap (2000 Ziehungen) der Tagesmittel; Holm-korrigiert über H1–H5 bei 5 %.
3. P1: ≥ 55 % der Coins mit ≥ 5 Trades positiv; ohne die 5 besten Coins (Netto-P&L) Mittel > 0.
4. P1 mit Kostenstress +0,15 % Roundtrip und Funding-Szenario: Mittel weiterhin > 0.
Kein Nachschieben von Varianten. Besteht eine Hypothese, folgt Kleinkonto-Portfoliosimulation und Vorwärtstest ab 09.11.2026.
