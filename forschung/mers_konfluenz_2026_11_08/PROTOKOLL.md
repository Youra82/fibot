# Konfluenz mit gerichteter Reaktion: vorab festgelegter Vergleich

Alle Varianten verlangen dieselbe Fibo-Kanal-Konfluenz (DEFAULTS + V2).
Keine Optimierung, keine Auswahl von Coins nach Ergebnis, keine Live-Aenderung.
Historie ist bereits erforscht: alle Resultate explorativ, kein frischer Holdout.

Varianten: L = bisheriger Limit-Einstieg; C = bullische Rueckeroberung;
P = C plus nachlassender Gegendruck; E = C plus gerichtete Energie;
PE = C plus beide Bedingungen; PEH = PE plus sinkende Histogramm-Entropie.
Shorts gespiegelt, identische Regeln.

Ein Touch ist exakt das bisherige Konfluenzereignis. Danach maximal vier
abgeschlossene Kerzen auf Reaktion warten. Schlusskurs muss ueber dem zuvor
bekannten Konfluenzlimit liegen, Kerze positiv sein. P: mittlerer negativer
ATR-normalisierter Close-Schritt der letzten zwei Kerzen kleiner als jener
der vorherigen drei, vorheriger Gegendruck > 0. E: aktueller normalisierter
Schritt > 0 und sein Quadrat groesser als der Mittelwert der drei vorherigen
quadrierten Schritte. PEH: Rendite-Histogrammentropie (20 Kerzen, 10 Bins)
kleiner als drei Kerzen zuvor. Entropie ist keine Messung zeitlicher Ordnung.

Eintritt am naechsten Open, mit 2 bp Schlupf; Entry/Exit je 6 bp Gebuehr.
L: Entry konservativ am Limit, ohne Preisverbesserung; ebenfalls 6 bp.
SL und TP des Touch-Setups eingefroren. SL-Beruehrung vor Bestaetigung
verwirft Setup. Einstieg jenseits SL/TP oder mit RR < 1 verworfen.
SL hat bei mehrdeutigen Kerzen Vorrang, TP nie in Eintrittskerze.
SL-Gaps zum schlechteren Open. Maximal 120 Kerzen Haltedauer.
Ein Trade pro Coin und Variante, auch ueber beide Richtungen.
Offene Trades am Datenende werden nicht als geschlossene Ergebnisse gewertet.
Keine Bestaetigung ueber Datenluecken, Trades mit Datenluecken ausgeschlossen.

4h gesamtes verfuegbares Universum, 1h als weitere Zeitskala. Letzte Zeile
je Datensatz vorsorglich entfernt. Gleicher deterministischer Coin-Split wie
bisher; Zeitraum vor 2026 und ab 2026 bis 15.10. sowie danach separat.
Erwartung in Netto-R (Preisrisiko bis SL), Notionalrendite, Gewinnquote,
Long/Short, Jahre, Coinbreite und Ergebnis ohne beste fuenf Coins berichten.
Stress: zusaetzlich 15 bp Roundtrip sowie 1 bp je angefangener 8h Haltedauer
(konservatives Funding-Szenario, keine historischen Fundingdaten).
28-Tage-Blockbootstrap, 2000 Wiederholungen, Konfidenzintervall auf
Kalendertagesbeitraegen inklusive Tage ohne Entry. Holm ueber zehn Hybridtests
(5 Varianten x 2 Timeframes). Keine Portfoliorendite aus Trade-Mitteln ableiten.
Robustheitskriterium: >=100 Trades, positives Tagesmittel mit Holm p<=.05,
positive mittlere Netto-R in beiden historischen Zeitfenstern und Coinhaelften,
positiv unter Stress und ohne beste 5 Coins. Juengste kurze Periode deskriptiv.
