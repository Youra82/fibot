# Dynamische Edge-Diagnose des bisherigen Fibot

Der Report zeigt den Zustand der historisch erzielten Netto-Auszahlungen.
Die Ausgleichslinie `p = 1 / (1 + Payoff)` bleibt fest. Datenpunkte,
rollierende Entwicklung und empirische Unsicherheit bewegen sich.
Es handelt sich um eine Diagnose, nicht um einen automatischen Entry-Filter.

## Aufruf

```bash
./run_analysis.sh --no-telegram
# Auswahl 14
```

Direkt, vom Projektverzeichnis unter Linux/VPS:

```bash
.venv/bin/python3 src/fibot/analysis/edge_dashboard.py \
  --scope aktiv --from 2026-05-10 --to 2026-11-08 --capital 60
```

Die direkte CLI nutzt nur vorhandene lokale Kerzen. Sie ruft keine
Boersen-API auf, sendet kein Telegram und setzt keine Orders. Standardziel:
`artifacts/analysis/edge_dashboard.html`, daneben die benutzten Trades als
CSV und der gesamte Snapshot als JSON. Ein anderes Ziel ist ueber `--out`
moeglich. Die HTML enthaelt Plotly und funktioniert offline.

## Datenbasis

- Aktuelle Config-Auswahl des zurueckgesetzten Kanal-Konfluenz-Bots,
  inklusive seines bestehenden HTF-/Tagestrendfilters. Keine fibot2-Trades.
- Warmup vor Beginn des Analysezeitraums fuer Signale und Trendmerkmale.
  Virtuelle Orders vor dem Start loesen keine Kontotrades aus.
- Jede Config wird einzeln mit dem bestehenden Backtester gerechnet.
  Die Ergebnisse sind ein statistischer Trade-Pool, kein gemeinsamer
  Konto-Replay. Offene Endpositionen werden nicht als geschlossene Trades
  gewertet und ihre Zahl in der Datenabdeckung vermerkt.
- Netto-R aus tatsaechlichem Backtest-PnL relativ zum urspruenglichen
  Kontraktrisiko. Ein Ergebnis gilt erst nach Ende der Ausstiegskerze als
  bekannt. Kostenqualitaet und Intrabarannahmen bleiben die des Backtesters.
- Heute ausgewaehlte Configs werden rueckblickend getestet. Das ist weder
  die historische Team-Abfolge noch eine aktuelle Live-Gewinnquote oder
  ein unberuehrter Out-of-Sample-Test.

## Feste Marktdefinition

BTC-Tagesdaten sind der ausdrueckliche Marktbezug. Fuer die Einstiegszeit
eines Trades werden ausschliesslich damals abgeschlossene Tage verwendet:

- Aufwaerts: BTC-Schluss > EMA50 + Wilder-ATR14.
- Abwaerts: BTC-Schluss < EMA50 - Wilder-ATR14.
- Dazwischen: Seitwaerts.
- Volatilitaet = ATR14 / Schluss. Niedrig unter dem 1/3-Quantil, hoch ueber
  dem 2/3-Quantil der vorherigen 252 Werte; dazwischen mittel. Mindestens
  126 vorherige Werte, ansonsten unbekannt. Die aktuelle Beobachtung ist
  nicht Teil ihrer eigenen Vergleichsschwellen.

Fehlende Tagesdaten werden nur aus vollstaendigen UTC-Tagen vorhandener
Intraday-Reihen ergaenzt. Angefangene oder lueckenhafte Tage entfallen.
Ein Tageszustand wird ab dem naechsten UTC-Tag verfuegbar. Er ist kein
sekundengenauer Zustand des Orderbuchs und keine individuelle Coin-Prognose.

## Bedienung

- Zeitfenster oder historischen Beurteilungszeitpunkt einstellen.
- Coin, Timeframe und Richtung waehlen.
- Optional auf letzte 30, 50, 100 oder 200 abgeschlossene Trades begrenzen.
- Marktphase manuell waehlen oder mit dem letzten bekannten BTC-Zustand
  abgleichen. Dies waehlt keine nachtraeglich beste Phase aus.
- Gesamtpunkt ohne Markt-/Letzte-N-Filter mit der Auswahl vergleichen.
- Die 50-Trade-Zeitspur verfolgt die historischen, jeweils bereits bekannten
  Netto-Auszahlungen. Weniger als 50 Trades erzeugen keine kuenstliche Spur.
- Trade-Auswahl als CSV speichern; Quelle und Abdeckung in der HTML pruefen.

## Unsicherheit und richtige Interpretation

500 gemeinsame Bootstrap-Ziehungen von 28-Tage-Kalenderbloecken. Alle Trades
desselben Tages bleiben zusammen. Mindestens 30 Trades und drei nichtleere
Bloecke; andernfalls 'zu wenig Evidenz'. Die Punktwolke zeigt gemeinsame
Schwankungen von Gewinnerquote und Payoff. Sie ist keine garantierte
zweidimensionale 95%-Konfidenzregion. Das berichtete 95%-Intervall gilt fuer
den mittleren Netto-R-Wert.

Null-Trades werden fuer den gezeichneten bedingten Punkt ausgeschlossen,
aber bei der Netto-Erwartung mitgezaehlt. Dadurch bleibt die feste
Ausgleichskurve korrekt. Ohne Gewinn- oder Verlustgruppe existiert kein
endlicher Payoff-Punkt.

'Historisch positiv' erfordert ein positives unteres Intervallende. Ein
Punkt oberhalb der Linie allein wird nicht als bestaetigte Edge bezeichnet.
Auch ein positives Intervall korrigiert nicht fuer Config-Optimierung,
viele ausprobierte Filter, Datenwiederverwendung oder Regimewechsel.

## Aktualisierung

Die Bedienelemente rechnen die vorhandenen Snapshot-Daten neu aus. Fuer
neue Kerzen muss der Datenbestand aktualisiert und der Report erneut
generiert werden. Zeitpunkt, Config-Hash und letzte Datenkerze je Config
stehen im Report. Es gibt keinen Hintergrunddienst und keine automatische
Veraenderung von Hebel, Stop, TP, Risiko oder Portfolio.

## Variantenvergleich vom 08.11.2026

Die Forschung unter `forschung/konfluenz_edge_verbesserung_2026_11_08/`
prueft 18 vorab definierte Kombinationen aus Einstieg, Stop und Ziel. Der
Offline-Bericht liegt in
`artifacts/edge_verbesserung_2026_11_08/VERGLEICH.html`; daneben liegen
Rohtrades, gemeinsamer 60-USDT-Kontoreplay, Input-Snapshot und die vor dem
Vergleich eingefrorene Auswahl. Reproduzieren mit `run.py`, danach
`report.py`; `test_engine.py` prueft die Ausfuehrung und `check_report.py`
validiert Daten und Browserbedienung. Vorausgesetzt werden die lokalen
Kerzen und der im Input-Snapshot dokumentierte alte Strategiestand.

Auf aelteren Auswahldaten gewinnt die Kontrolle. Ein mindestens zwei ATR
entfernter Stop mit entsprechend kleinerer Position wirkt im juengeren
Vergleich besser (0.299 statt 0.223 Netto-R/Trade). Das direkte 95%-Intervall
seiner Verbesserung umfasst aber null (-0.072 bis +0.224 R); im aelteren
Zeitraum war er schwaecher. Keine nachtraegliche Umdeutung zum ausgewaehlten
Sieger und keine Aktivierung im Live-Pfad. Die Daten wurden bereits fuer
Forschung und/oder Auswahl der heutigen Configs verwendet.
