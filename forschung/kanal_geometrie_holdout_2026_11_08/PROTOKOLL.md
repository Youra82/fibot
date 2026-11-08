# Kanal-Konfluenz: Geometrie und unabhaengige Pruefung

Status: Pruefbestand fehlt. Noch kein neuer unabhaengiger Ergebnislauf.

## Daten-Audit

Die bisher verfuegbaren historischen Bereiche sind nicht mehr ungesehen:

- Vor 2026: Config-Optimierung, Strategiesuche und Gewinnerfilter.
- 2026 bis 14.10.: zahlreiche Variantenpruefungen und Portfolioauswahl.
- Ab 15.10. bis 08.11.: Live-Verlustanalyse, MERS-/Filtertests und fibot2.
- Ab August: Kontobacktest und Einzelanalyse aller 141 geschlossenen Trades.
- Fremde Coins aus dem geobot-Bestand: bereits Generalisierungstests und
  breite Untersuchungen mit 241 Coins, keine ungepruefte Kontrollgruppe mehr.

Diese Einordnung stuetzt sich auf die vorliegenden Protokolle und Auswertungen.
Ein neues Datumslimit, Zufalls-Split oder Dateiname macht dieselben Ergebnisse
nicht wieder unabhaengig. Ein bislang unangetasteter anderer historischer
Bestand muss vor dem Ergebnislauf konkret benannt und seine Nutzung geprueft
werden. Bereits bekannte Daten duerfen ausschliesslich Entwicklung sein.

## Vorab begrenzte Variantenfamilie

Konfluenz-Detektor und Config-Pool einfrieren. Keine nachtraegliche Coinwahl.
Zunaechst maximal 16 Kombinationen, keine freie Parametersuche:

- Einstieg: bisheriges Limit oder Reaktionsbestaetigung nach Beruehrung.
  Bestaetigung = Schluss zurueck auf der erwarteten Seite des geplanten Limits
  und Kerze in Handelsrichtung, hoechstens vier Kerzen nach Beruehrung.
  Kein Stopkontakt vor Bestaetigung. Ausfuehrung erst am folgenden Open.
- Stop: vorhandener struktureller Stop oder derselbe Stop mit Mindestabstand
  2 ATR14 nach Wilder. Beim zweiten Ansatz Stop nur weiter nach aussen setzen,
  niemals einen bereits weiteren Strukturstop verengen. Positionsgroesse
  danach anhand des tatsaechlichen neuen Abstands neu berechnen.
- Ziel: vorhandenes Strukturziel oder 1.5 R, 2 R, 3 R ab tatsaechlichem Entry.

Jede Variante ist eine eigene Strategie einschliesslich ihres Phasentors.
Virtuelle Ereignisse und deren Sichtbarkeit muessen mit den geaenderten
Exits neu berechnet werden. Kein blosses Umrechnen der bisherigen 141 Trades.
Auch veraenderte Haltedauer, Coin-Sperren, wartende Orders und dadurch neu
moegliche beziehungsweise blockierte Einstiege sind neu zu simulieren.
Die bestehende fibot2-Variante bleibt eine separate unveraenderte Kontrolle.

## Auswahl und Einfrieren

Auf bekannten Entwicklungsdaten zeitlich fortschreitend pruefen. Trainings-
und Pruefgrenzen nach dem Zeitpunkt geschlossener Trades ziehen. Vorlauf
nur fuer kausal bekannte Indikatoren und virtuelle Historie benutzen.
Maximal einen Kandidaten anhand Entwicklung auswaehlen und vor dem echten
Holdout mit Quellcode-, Parameter- und Datenmanifest-Hashes einfrieren.
Keine Tests aller Kandidaten mit nachtraeglicher Gewinnerwahl im Holdout.

## Ausfuehrung und Ergebnis

- Start 60 USDT; 0.7% geplantes Preisrisiko pro Einstieg; Budget und Coin-Sperre
  wie aktueller fibot2. Kerzenraster, Zeitzonen und Enddatum vorab fixieren.
- Gebuehren, Stop-Gaps, Schlupf, Funding-Szenario, Boersen-Mindestmengen und
  Tick-/Mengenschritte explizit modellieren. Ohne passende historische
  Boersenmetadaten Ergebnis als vereinfachte Simulation kennzeichnen.
- SL vor TP bei unbekannter Intrabar-Reihenfolge; kein rueckwirkender
  Bestaetigungseinstieg. Offene Endpositionen samt gebundener Mittel und
  Mark-to-Market-Ergebnis berichten, nicht verschwinden lassen.
- Trefferquote, mittlerer Nettogewinn/-verlust, Payoff, Netto-Erwartung,
  Profitfaktor, Trades, Monats-/Coinbeitraege, realisierter und MTM-Drawdown.
- Kostenstress +15 bp Roundtrip und Funding-Szenario separat.
- Positiver Nettoertrag und positive mittlere Netto-R; 95%-Blockbootstrap-
  Intervall der taeglichen Netto-Ergebnisse oberhalb null; positiv unter
  Kostenstress und ohne die fuenf besten Coins. Mindestens 100 geschlossene
  Trades und 90 Kalendertage fuer eine abschliessende Bewertung. Bei weniger
  Beobachtungen lautet das Ergebnis 'unzureichende Evidenz'.

Auch bestandene Kriterien sind Evidenz fuer den bezeichneten Test, keine
Garantie zukuenftiger Profitabilitaet. Keine Aenderung am Live-Bot durch
dieses Protokoll und keine Orders waehrend der Untersuchung.
