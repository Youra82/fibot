# Vom Nutzer gewaehlter historischer Vergleich

Nach dem Daten-Audit hat der Nutzer den Test auf den letzten 26 Wochen
gewuenscht. Zeitraum: 10.05.2026 00:00 Europe/Berlin bis zum letzten lokal
verfuegbaren abgeschlossenen Kurs am 08.11.2026. Start 60 USDT.

Dieser Lauf ist KEIN echter ungesehener Holdout. Alle 16 vorab beschriebenen
Kombinationen werden vollstaendig berichtet, nicht nachtraeglich nur ein Sieger.
Daneben eine Kontrolle mit unveraenderten strukturellen Stops und Zielen,
Mindest-Stop 2 ATR als Verwerfungsregel statt Stop-Verbreiterung (F0).

Die urspruengliche Konfluenz-Planfolge bleibt fuer alle Varianten gleich.
Sie enthaelt bereits die Config-eigene Mindest-CRV-/Impulspruefung und deren
Verbrauch von B bei erster Beruehrung. Geaenderte Ausstiege und Bestaetigungen
erzeugen keine neue Kanal- oder Impulssuche. Dieser feste Kandidatenbestand
wird explizit als Grenze der Untersuchung ausgewiesen.

Gemeinsame Modellannahmen: Entry-Limit konservativ zum Limit; bestaetigter
Entry zum folgenden Open mit 2 bp Schlupf; SL zuerst bei Mehrdeutigkeit;
kein TP in Entry-Kerze; Stop-Gap zum schlechteren Open plus 2 bp Schlupf;
6 bp Gebuehr pro Seite. Funding im Basismodell null, im Stress 1 bp je
angefangene 8h zusaetzlich zu 15 bp Roundtrip. Das Phasentor wird je Variante
und Kostenszenario anhand ihrer eigenen abgeschlossenen virtuellen Ereignisse
berechnet, 14 Tage/15 Ereignisse/Mittel > 0. Keine Nutzung spaeterer Resultate.

Eine wartende Order oder Position belegt ihren Coin. Nicht gefuellte
Limitorders reservieren Nominalbudget bis zum Ende ihrer Kerze. Risiko 0.7%
der realisierten Equity, Nominalbudget 10x Equity, mindestens 5 USDT Notional.
Keine behauptete historische Lot-/Tick-/Maintenance-Margin-Paritaet, weil
zeitpunktgerechte Boersenmetadaten nicht vorliegen. Long/Short symmetrisch.

Offene Trades am Ende werden erhalten und mit letztem bekannten Schlusskurs
bewertet. MTM-Drawdown wird auf dem 15m-Raster mit den letzten verfuegbaren
abgeschlossenen Kerzen je Coin berechnet; bei groberen oder lueckenhaften
Reihen ist dies keine Intrabar-Drawdownmessung. Keine Liquidationssimulation.

Ergebnis: realisierte und markierte Equity, offene Endpositionen, Trades,
Trefferquote, Payoff, mittlere Netto-R, Profitfaktor, Monats-/Coinbeitraege,
Kostenstress. Keine Live-Aenderung aufgrund dieses explorativen Laufs.
