# Auftrag 20 (Runde 17): Filter fuer die fibot-Kanal-Konfluenz, der im ungesehenen OOS positiv ist

Du arbeitest mit Claude zusammen. Aufteilung:
- **Du (Codex):** kreativer Teil. Entwirf HOECHSTENS 10 Filterregeln, jede aus einem Marktmechanismus begruendet
  (warum sollte gerade dieser Filter Verlierer-Setups aussortieren?), waehle auf den Entwicklungsdaten aus, friere ein.
- **Claude:** verwahrt die OOS-Daten (Trades ab 10.05.2026) unter Verschluss und rechnet den einzigen OOS-Test fuer alle
  eingefrorenen Kandidaten (deine + Claudes eigene 5) gemeinsam, mit Holm-Korrektur.

## Daten (nur diese verwenden)
- `runde17/events_dev.pkl`: 42 649 geschlossene Trades des bestehenden fibot-Konfluenz-Detektors (407 Configs = Coin x TF),
  Einstieg 08.04.2023 - 09.05.2026, alle Ausstiege vor 10.05.2026. Spalten: cfg, coin, tf, dir (long/short), ts (Einstieg),
  exit_ts, R (brutto), win, rr (Ziel/Risiko), risk_pct (Stopabstand %), trend_ok (bestehender HTF-/Tagestrendfilter),
  atr_pct, ema_dist, ema_slope (EMA200), vol_ratio (Vol/20er), rsi, adx, ema_ok (EMA200 in Handelsrichtung), slope_ok,
  stop_atr (Stop in ATR14), eligible, net_R (nach Gebuehren, Zielgroesse), stress_R (doppelte Kosten).
  Alle Merkmale sind bei Orderaufgabe bekannt.
- `runde17/btc_1d_dev.csv`: BTC-Tageskerzen bis 09.05.2026 (fuer Marktregime-Merkmale; nur Tage VOR dem Einstiegstag verwenden).
- NICHT lesen: irgendetwas unter C:\Users\matol\Desktop\botprojekte\fibot\forschung\gewinner_filter_2026_11_08 oder
  artifacts\live_trades_* (enthalten Ergebnisse nach dem 10.05.2026). Keine Boersen-/Netzwerkzugriffe.

## Bewertung (fest, wie bisher)
- Nur `eligible == True`. Pro Coin hoechstens eine Position: Trades eines Coins, deren Einstieg vor dem Ausstieg des zuletzt
  behaltenen Trades desselben Coins liegt, entfallen (Replay in Zeitreihenfolge, wie `replay()` unten).
- Zielgroesse: mittleres net_R je Trade; zusaetzlich stress_R, Anteil ohne Top-5-Coins, Zahl Trades, 28-Tage-Blockbootstrap.
  ```python
  def replay(T, mask):
      busy = {}; keep = []
      for i in np.flatnonzero(mask):
          r = T.iloc[i]
          if r.coin in busy and r.ts <= busy[r.coin]: continue
          busy[r.coin] = r.exit_ts; keep.append(i)
      return T.iloc[keep]
  ```
- Mindestumfang je Regel: >= 300 Trades in der Entwicklung, damit im OOS (~6 Monate) genug Trades bleiben.

## Entwicklung (dein Spielraum, aber dokumentiert)
Teile die Entwicklungsdaten selbst sinnvoll (z. B. Coin-Haelften und/oder Zeit: bis 2025 Suche, 2026-01-01 bis 2026-05-09 Pruefung).
Wichtig: Der Markt ab Nov. 2025 war ein Abwaertsmarkt (BTC < SMA200); die alte Strategie war vor 2026 leicht positiv
(~+0,1 R) und 2026 negativ. Ein guter Filter muss in BEIDEN Marktphasen bestehen oder sich mechanisch daran anpassen.
Keine Feinoptimierung von Schwellen (hoechstens 2-3 runde Werte je Idee).

## Lieferung (alles in runde17/)
1. `filter.py` mit `masks(T, btc_daily) -> dict[name, np.ndarray[bool]]` (genau deine eingefrorenen Regeln, deterministisch,
   nur Informationen vor `ts`), plus `replay`, `stats`.
2. `KANDIDATEN.json`: Liste der eingefrorenen Regeln (Name, Begruendung, Ausdruck), maximal 10, Rangfolge nach deiner
   Erwartung. `PREREG.sha256` mit SHA256 von filter.py und KANDIDATEN.json.
3. `RUNDE17_CODEX.md`: Ideen, Begruendung, Entwicklungsergebnisse je Regel und Teilung, Grenzen.
4. Tests fuer filter.py (kein Lookahead: Merkmale aus btc_1d nur bis Vortag).
STOPP nach dem Freeze. Kein Zugriff auf Daten ab 10.05.2026.
