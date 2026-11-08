# Dynamisches Ziel (Payoff je Trade aus der Lage beim Einstieg) -- Präregistrierung 08.11.2026

Festgelegt VOR jeder Rechnung. Bot: alte Fibo-Kanal-Konfluenz (Detektor unverändert, 407 Configs ohne 5m, Trendfilter
`trend_ok`, `eligible` wie im Forschungsdatensatz). Für jeden gefüllten Einstieg werden alle Ziele parallel simuliert.

## Ziele und Stops
- Ziele: 1 R, 1,5 R, 2 R, 3 R (vom Limit aus, R = tatsächlicher Stopabstand) und Strukturziel (heute).
- Stops: S = Strukturstop (heute), A2 = Strukturstop, mindestens 2 Wilder-ATR14 der letzten abgeschlossenen Kerze entfernt
  (nur verbreitern). Gleiche Kerze: Stop zuerst. Kein Ziel in der Füllkerze. Kosten wie Forschungsdatensatz:
  0,06 % je Seite, Verlust-Trades zusätzlich 0,02 %. Ohne Zeitlimit (wie Export), offene Trades am Datenende entfallen.

## Merkmale beim Einstieg (nur abgeschlossene Kerzen)
`atr_rank` (Rang der eigenen ATR% unter den letzten 500 Kerzen), `stop_atr` (Strukturstop in ATR), `rr_struct`
(Strukturziel/Strukturstop), `impuls_atr` (Impuls A→B in ATR), Richtung, Zeitebene, BTC-Trend (edge_state, Vortag).

## Zeiträume
- Lernen: Einstiege bis 31.12.2025. Prüfen: 01.01.–09.05.2026. OOS (einmal): 10.05.–08.11.2026.

## Hypothesen (je in Lernen bestimmt, in Prüfen/OOS getestet)
- H1 Volatilität: Je höher `atr_rank`, desto weiter das beste Ziel (Terzile).
- H2 Impuls: Je größer `impuls_atr`, desto weiter das beste Ziel (Terzile).
- H3 Stop-Weite: Je größer `stop_atr`, desto weiter das beste Ziel (Terzile).
- H4 Kombiniert: Ziel je Zelle aus Zeitebene-Gruppe (kurz 15m/30m, lang 1h+) × Richtung × `atr_rank`-Terzil.

## Funktion (Kandidat)
Nachschlagetabelle: je Zelle das Ziel mit dem höchsten mittleren net_R im Lernzeitraum (mind. 100 Trades je Zelle,
sonst heutiges Strukturziel). Für jede Hypothese getrennt und für Stop S und A2 getrennt.

## Bestanden
Im Prüfzeitraum UND im OOS: dynamisches Ziel > festes bestes Ziel aus dem Lernzeitraum UND > heutiges Strukturziel
(mittleres net_R, eine Position je Coin), gepaarter Unterschied mit 28-Tage-Blockbootstrap-Intervall > 0.
Alle Hypothesen werden berichtet, keine nachträgliche Auswahl.

## Nachtrag 1 (vor Ergebnissicht der Hypothesen)
analyse.py: Typfehler in replay_mean behoben (Ausstiegszeiten tz-aware). Keine inhaltliche Aenderung.

## Nachtrag 2 (nach Ergebnis H1-H4, neue Hypothese)
H5 dynamischer Stop: je stop_atr-Terzil (Grenzen aus Lernen) das bessere aus {S_K, A2_K} im Lernzeitraum (n>=100).
Bestanden wie oben (Pruefen UND OOS besser als S_K, eine Position je Coin, gepaartes Blockintervall > 0).

## Nachtrag 3 (nach beschreibender Stopweiten-Tabelle)
H6 Segment-Tor: stop_atr-Terzile (Grenzen aus Lernen). Ein Einstieg wird nur gehandelt, wenn die virtuellen Trades
seines Segments mit Ausstieg (Kerzenende) in den letzten 60 Tagen im Mittel > 0 R lagen (>= 30 Trades, sonst handeln).
Fenster 60 Tage vorab festgelegt, nicht optimiert. Bericht: Lernen, Pruefen, OOS; eine Position je Coin; gepaart vs S_K.
