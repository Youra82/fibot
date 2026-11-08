# Vorregistrierung Phasen-Tor für R25/R50 (User-Hinweis), 08.11.2026, vor der Rechnung
Tor-Code: ltbbot/src/ltbbot/strategy/phase_gate.py `multipliers_by_day` UNVERÄNDERT (LAM .1/.2/.4/.8, ≥3 Trades/Tag, ≥10 Tage,
Prior 20/0,5, m = 1 + clip(0,5 s, −1, 1)·a ∈ [0, 2]). Signal-Pool: alle Basis-Envelope-7-%-Trades (codex_ws/endtest_basis_trades.csv,
alle 241 Coins), Tagesquote = Trefferquote (ret > 0) der an Tag t geschlossenen Trades. Start der Tagesreihe: erster Pool-Tag.
Anwendung: Positionsgröße jedes R25/R50-Einstiegs an Tag t × m(t). m = 0 → kein Einstieg.
Bewertung: Kontosimulation (Codex runde5, sonst Claude konto_sim) mit und ohne Tor, Prüfzeitraum 01.01.2025–14.10.2026,
Bestehen wie AUFTRAG_7 (Endkapital > 34, MaxDD ≤ 30 %, ≥ 100 Trades/J).
