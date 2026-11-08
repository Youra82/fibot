# Runde 2 — Claudes Umsetzung deiner Korrekturen + dynamische Kontoverlauf-Anpassung (User-Wunsch)

Deine erste Antwort liegt als DEINE_ERSTE_ANTWORT.md bei. Umgesetzt (Diff: alle_aenderungen.diff):

1. Mindestmenge: `calc_position_size` hebt nicht mehr an -> kein Trade; klassischer Pfad hebt nach Rundung nicht erneut an.
2. Liegende Konfluenzorder: bei gleichem Plan wird die Menge gegen das aktuelle Risikobudget geprueft, zu gross -> ersetzt.
3. risk_cap.py: Validierung (bool, NaN, inf, negativ, Text -> ValueError; Config-Risiko ebenso); `live_trading_settings: null` -> Fehler;
   `null`/0 = ausdruecklich keine Obergrenze; `cap=` friert den Wert ein.
4. Portfolio-Simulator liest Obergrenze und Dynamik EINMAL je Lauf, beide stehen im Ergebnis.
5. Protokoll live: Config-Risiko, Obergrenze, effektives Risiko.
6. Anzeige/Analyse: analysis_suite (Analyse 10, 13) und show_results mit gedeckeltem Risiko; Einsatz-Fallback als "Risiko" beschriftet.
7. Dein Optimizer-Default `min_sl_atr` -> 0.0, Kommentar in confluence_logic korrigiert.
8. Verhaltenstests statt Quelltextpruefung (tests/test_risk_cap.py, 21 Tests), tests/conftest.py isoliert die Hoechststand-Datei.
   Gesamte Suite lokal 117/117 gruen.

NEU auf ausdruecklichen Wunsch des Users ("dynamisches System, das sich an Markt oder Kontoverlauf anpasst"):
Kontoverlauf-Anpassung: Risiko = min(Config, 1 %) x max(0,25; 1 - DD/30 %), DD vom Konto-Hoechststand (inkl. offener Positionen).
- Live: `risk_cap.live_risk_pct` (Hoechststand in artifacts/db/equity_peak.json, atomar, steigt nur) in Konfluenz- und klassischem Pfad,
  auch beim Pruefen liegender Orders. Einstellbar: live_trading_settings.dynamic_risk {enabled, dd_full, floor}; Standard an; null = aus.
- Portfolio-Simulator: gleicher Faktor mit letztem Gesamtkontostand und separatem Hoechststand `dyn_peak` (gemeldeter MaxDD bleibt ab Start);
  `start_peak` = Live-Hoechststand im Tagesbericht (daily_live_vs_backtest_check._live_peak).
- Einzel-Backtester (Optimizer-Ranking je Config) bekommt bewusst KEINE Dynamik: Live wirkt der Faktor auf Kontoebene, das kann ein
  Einzel-Config-Backtest nicht abbilden. Einverstanden?
Forschung dazu (vereinfachte Kontorechnung mit deinen Einwaenden aus Runde 1): forschung/ergebnis_bremse_1pct.txt
(Pool 38: DD 32/34/21/28/30 % -> 23/25/16/20/21 %, Rendite deutlich kleiner in starken Phasen).

Bitte pruefe kritisch, widersprich klar, nenne konkrete Korrekturen mit Datei/Zeile. Besonders:
- Race-Conditions der Hoechststand-Datei (mehrere Strategie-Prozesse je Cron-Lauf), Einzahlungen/Auszahlungen (Hoechststand-Reset).
- Ob live `fetch_equity_usdt` (inkl. unrealisiert) und der Simulator (`total_eq` der letzten Kerze) ausreichend gleich sind.
- Ob der klassische Pfad mit `balance` (freies Guthaben) statt Equity den Faktor falsch rechnet.
- Ob etwas fehlt, bevor der User pushen sollte.
Keine Dateien aendern. Antwort auf Deutsch.
