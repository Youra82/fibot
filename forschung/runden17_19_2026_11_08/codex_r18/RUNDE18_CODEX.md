# Runde 18 / Auftrag 21

## Ergebnis und Entscheidung

Zwei neue, vor dem ersten Backtest festgelegte Varianten untersucht und unveraendert eingefroren. Beide werden wegen negativer Entwicklungsergebnisse abgelehnt. Keine Empfehlung fuer Handel oder OOS-Auswahl. Die ausfuehrbaren Varianten werden zur Reproduzierbarkeit geliefert; falls Claude sie dennoch im gemeinsamen OOS testet, zaehlen beide zur kumulierten Holm-Familie (13 bisher + 2 = 15 nach Auftragsstand). Kein OOS gelesen oder gerechnet. Nach Erstellung des Hash-Manifests endet die Arbeit.

## Idee und mechanische Hypothese

Impuls-Ruecklauf nach Spannenbruch, nicht die alte Kanal-Konfluenz und keine Docht-Rueckkehr zur Mitte: Ein grosser gerichteter Koerper durchbricht die letzten 20 abgeschlossenen 4h-Kerzen und schliesst nahe dem Extrem. Der Ruecklauf an 38,2 % bzw. 61,8 % dieses Impulsbalkens erlaubt einen guenstigeren Fortsetzungseinstieg. Die Konfluenz besteht aus Spannenbruch, gerichteter Expansion und Fibonacci-Ruecklauf; das Ziel ist eine 61,8-%-Extension ueber das Impulsextrem hinaus. Fuer beide Varianten gelten exakt dieselben Coins und Regeln.

Hypothese fuer beide Marktphasen: Gerichtete Expansion und anschliessende Liquiditaetsaufnahme koennten in steigenden wie fallenden Maerkten auftreten; Long und Short sind mechanisch gespiegelt. Es gibt kein benoetigtes positives Marktdrift-Regime. Dies ist eine Begruendung der Hypothese, kein empirischer Nachweis. Die Resultate widerlegen hier einen nutzbaren Vorteil, besonders auf der Shortseite.

## Exakte Ausfuehrung

Nur 4h-Dateien aus dem uebergebenen root; Zeitstempel werden als Kerzenbeginn interpretiert. ATR ist das einfache Mittel von 14 True Ranges, inklusive gerade abgeschlossener Signalkerze. Long: Schluss ueber vorherigem 20-Bar-Hoch, positiver Koerper mindestens 1,5 ATR, gesamte Spanne maximal 4 ATR, Schluss im oberen Viertel. Short gespiegelt. Limit am Fibonacci-Ruecklauf wird erst nach Signalkerzenschluss fuer maximal drei Folgebalken aktiv. Fill nur bei low <= Limit <= high; kein unterstellter Fill ausserhalb der Handelsspanne. Keine Verbesserung bei guenstigen Eroeffnungsluecken. Fehlende 4h-Kerzen loeschen offene Orders.

Stop jenseits des Impulsankers plus 0,25 ATR Puffer, Abstand zum Einstieg mindestens eine Signal-ATR. Ziel ist das Impulsextrem plus/minus 0,618 der Impulsspanne. Stop hat auch im Einstiegsbalken Vorrang vor Ziel; bei Stopluecke gilt die schlechtere Eroeffnung. Diese OHLC-Konvention kann Verluste vor dem tatsaechlichen Intrabar-Fill unterstellen und ist bewusst pessimistisch. Zeitexit am Schluss des Balkens mit Index Einstieg+18 (bei lueckenlosen Daten maximal 76 Stunden). Waehrend Position oder Order keine neue Order; kein Wiedereinstieg im Exitbalken. Eine Position je Coin und Variante. Offene Positionen am Datenende bleiben offen, es gibt keinen kuenstlichen Endexit. root darf spaeter laenger sein, im Strategiecode existieren keine Datumsgrenzen.

Entry Maker 0,02 %, Ziel Maker 0,02 %, Stop/Zeitexit Taker 0,06 % plus 0,02 % Slippage. Funding linear 0,01 % je acht Stunden, fuer beide Richtungen belastet. Kosten in Prozent des Einstiegsnotionals; stress_ret verdoppelt alle Kosten inkl. Funding und Slippage. Funding bis Ende des Exitbalkens; Einstieg ts am Beginn des Fillbalkens und exit_ts am Ende des Exitbalkens sind konservative OHLC-Zeitkonventionen, keine Tickzeiten. ret ist Prozent Notional, nicht R und keine gehebelte Kontorendite.

## Entwicklungsergebnisse

Keine Parametersuche, keine Nachoptimierung, keine Auswahl anhand von Coins. Beide Varianten wurden gleichzeitig fuer Suche und Pruefung ausgewertet; die Pruefung wurde genau einmal eingesehen. Suche bis 30.06.2025, Pruefung 01.07.2025 bis einschliesslich 09.05.2026. Fuer jede Teilperiode muessen Einstieg und abgeschlossener Exit darin liegen; grenzueberschreitende Trades sind ausgeschlossen, die Simulation selbst laeuft kontinuierlich.

Alle Werte der folgenden Tabelle sind Prozent je Trade.

| Variante | Suche Trades | Suche netto | Pruefung Trades | Pruefung netto | Stress | Ohne Top 5 | 28T-Bootstrap 95 % |
|---|---:|---:|---:|---:|---:|---:|---|
| impuls_382 | 6308 | -0,5594 | 2626 | -0,4179 | -0,5386 | -0,5139 | [-1,3578; 0,5028] |
| impuls_618 | 3679 | -0,6200 | 1556 | -0,7993 | -0,9222 | -0,9348 | [-1,4677; 0,0171] |

Top 5 werden je Auswertungsperiode nach summierter Nettorendite ermittelt und entfernt; dies ist eine retrospektive Robustheitsdiagnose, keine handelbare Coinauswahl. Die verbleibenden Pruef-Trades sind 2532 bzw. 1499. Konkrete Coins und Richtungsergebnisse stehen in entwicklung.json.

Zusaetzliche feste Kalenderdiagnose, ohne Regimeerkennung: 01.07.-30.11.2025 liefert -0,0514 % / -0,9900 %, 01.12.2025-09.05.2026 liefert -0,6859 % / -0,6782 % (382 / 618). Diese Abschnitte sind keine anhand von BTC gemessenen Marktphasen. Die Symmetrie liefert jedenfalls keinen robusten positiven Erwartungswert in beiden Abschnitten.

Bootstrap: 10.000 Ziehungen zusammenhaengender, nicht ueberlappender 28-Tage-Kalenderbloecke mit Zuruecklegen; alle Coins eines Blocks gemeinsam, leere Bloecke eingeschlossen, letzter Teilblock bleibt enthalten. Mittelwert aus Summe Renditen / Summe Trades der gezogenen Bloecke. Seed 18021. In der Pruefung nur 12 Bloecke: erhebliche Unsicherheit und kein Beweis fuer Unabhaengigkeit oder Signifikanz. Keine lokalen Holm-p-Werte, da der gemeinsame echte OOS ausschliesslich bei Claude liegt. Die Entwicklungsfrequenz ist hoch genug fuer das Handelszahlziel plausibel, aber weder >=100 Trades in zukuenftigen 26 Wochen noch positive OOS-Rendite sind nachgewiesen.

## Tests, Daten und Reproduktion

Ausschliesslich die im Auftrag erlaubten CSVs unter runde18/daten gelesen. Keine alten Strategien, Berichte, Forschungs-/Artifacts-Daten oder Netzwerkzugriffe. 30m, 1h und BTC_1d wurden nur zur Datenintegritaet geprueft, nicht als Strategieinputs genutzt. datenpruefung.json dokumentiert Umfang und Zeitgrenzen.

Sechs synthetische Unittests bestehen: kein Fill auf Signalkerze, Folgebalkenfill und Stop-vor-Ziel, unberuehrtes Limit/Orderverfall, Praefix- und Zukunftsaenderungsinvarianz, Short-Spiegelung, ungueltige Variante. Zusaetzlich acht echte Praefixvergleiche auf BTC/ETH, beiden Varianten und zwei Schnittstellen. Der Export abgeschlossener Trades aendert sich durch spaetere Kerzen nicht. Tests beweisen keine Freiheit von allen Modellfehlern; Markt-Mikrostruktur und Maker-Warteschlangen bleiben unmodelliert.

Gemessene Laufzeit fuer alle 160 4h-Coins: 14,4 / 14,0 Sekunden pro Variante, deutlich unter 20 Minuten. Python wie vorgegeben: C:/Users/matol/Desktop/botprojekte/fibot/.venv/Scripts/python.exe. Reproduktion: test_strategie.py, pruefung.py und auswertung.py mit diesem Interpreter ausfuehren. Trades und vollstaendige Kennzahlen liegen als trades_impuls_382.csv, trades_impuls_618.csv und entwicklung.json vor.

PREREG18.sha256 enthaelt SHA256 ueber die exakten Bytes von strategie.py und KANDIDATEN18.json. Es handelt sich um den Freeze vor zukuenftigem OOS, nicht um einen nachweisbaren Zeitstempel vor der bereits erfolgten Entwicklungspruefung.

Datenumfang laut Integritaetspruefung: 4h 160 Dateien, 1h 120, 30m 62. Die im Auftrag pauschal genannten 160 Coins sind somit nur auf 4h vollstaendig vorhanden. BTC_1d beginnt bereits am 27.07.2019; diese erlaubte Datei wurde ausschliesslich auf Zeitgrenzen geprueft und fuer die Strategie nicht verwendet. Alle Dateien enden spaetestens am 09.05.2026.
