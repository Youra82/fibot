**Mein Urteil: Die 1-%-Obergrenze ist sinnvoll eingebaut, aber noch nicht durchgehend garantiert. Claudes Einwand gegen meinen Optimizer-Default `min_sl_atr=2.0` ist berechtigt. Die Forschung rechtfertigt derzeit keine zusätzliche dynamische Handelsregel; mehrere Aussagen sind jedoch stärker formuliert, als die Auswertungen tragen.**

Keine Dateien geändert. Alle elf hinterlegten SHA256-Prüfsummen stimmen. Die vollständige Testsuite und Forschungsrechnungen konnte ich mit diesem Auszug nicht reproduzieren: Paketstruktur, Configs, Kerzendaten und referenzierte Pickles fehlen. Die berichteten 101 Tests sind deshalb hier nicht unabhängig bestätigt.

### 1. Risiko-Code: konkrete Befunde

**Hohe Priorität: Der klassische Live-Pfad kann die Obergrenze überschreiten.**

In `src/trade_manager.py:183–185` hebt `calc_position_size()` die berechnete Menge auf das Exchange-Minimum an. `:713–718` macht das nach der Präzisionsrundung erneut. Das kann trotz gedeckeltem Eingangsparameter mehr als 1 % Stoprisiko erzeugen.

Beispiel: 34 USDT Kapital, 1 USDT Stopabstand, Mindestmenge 1 → erlaubt wären 0,34 Einheiten; gehandelt würde unter passenden Marginbedingungen 1 Einheit, also 2,94 % Stoprisiko.

**Korrektur:** Beide Anhebungen durch „Trade überspringen“ ersetzen. Nach Präzisionsrundung nochmals Menge, Margin und tatsächliches Stoprisiko prüfen. Mein vorhandener Konfluenz-Fix in `:795–803` behandelt diesen Fall bereits entsprechend.

**Hohe Priorität: Eine bereits wartende Konfluenzorder wird bei Risikosenkung nicht zwingend angepasst.**

`src/trade_manager.py:915–922` vergleicht Kerze, Richtung, Entry, SL und TP, aber weder Menge noch Risikobudget. Eine noch mit 3 % platzierte Order kann bei unverändertem Plan bestehen bleiben, obwohl jetzt 1 % gilt.

**Korrektur:** Vor dem frühen `return` auch die Restmenge gegen das aktuelle Budget prüfen und gegebenenfalls stornieren beziehungsweise verkleinern. Bereits gefüllte Positionen sind davon getrennt zu behandeln.

**Mittlere Priorität: Ungültige Risikowerte werden nicht zuverlässig abgefangen.**

`src/risk_cap.py:26–38` akzeptiert unter anderem boolesche Werte und nichtendliche Zahlen; das Config-Risiko wird überhaupt nicht auf Nichtnegativität geprüft. Ein schreibfreier Funktionscheck bestätigte: `-2` bleibt `-2`, `NaN` bleibt `NaN`.

**Korrektur:** Cap und Config-Risiko auf numerisch, endlich und nichtnegativ prüfen; boolesche Werte zurückweisen. Die vereinbarte Abschaltsemantik für `null`/0 ausdrücklich und getrennt behandeln. Fehlerhafte JSON-Struktur wie `live_trading_settings: null` ebenfalls verständlich melden.

**Mittlere Priorität: Backtests hängen jetzt implizit von einer veränderlichen Live-Datei ab.**

`src/risk_cap.py:20` liest bei jedem Aufruf `settings.json`; im Portfolio-Simulator geschieht das bei jedem Einstieg (`src/portfolio_simulator.py:249`). Damit kann sich eine laufende Simulation durch eine Settings-Änderung verändern.

**Korrektur:** Cap einmal je Backtest beziehungsweise Auswahllauf laden, explizit weiterreichen und im Ergebnis speichern. Live kann weiterhin je Zyklus neu geladen werden.

**Die Tests decken diese Garantien nicht ab.**

`src/test_risk_cap.py:47` ersetzt die Cap-Funktion im Live-Test durch eine Lambda-Funktion. `:72–73` prüft lediglich Quelltextfragmente, kein Sizing-Verhalten.

**Korrektur:** Verhaltenstests für beide Live-Pfade und beide Simulatoren ergänzen: Mindestmenge, Rundung, wartende Order nach Risikosenkung, ungültige Werte sowie kleinere Config-Risiken. Den Textvergleich durch einen kleinen numerischen Simulationsfall ersetzen.

Außerdem bedeutet die jetzige Berechnung **1 % Preisverlust bis zum geplanten Stop**. Gebühren und Ausführungskosten kommen hinzu; beispielsweise zieht `src/portfolio_simulator.py:279–280` Gebühren zusätzlich ab. Soll „1 %“ sämtliche modellierten Verlustkosten umfassen, muss die Positionsgröße diese im Nenner berücksichtigen.

### 2. Forschung: was trägt und was korrigiert werden muss

**Die positiven methodischen Punkte:** ATR und ATR-Rang werden in `pfade.py:64–70` aus der vorherigen Kerze genommen. G1, tägliche Auswahl und H6 berücksichtigen ausdrücklich den Zeitpunkt, zu dem ein Trade abgeschlossen bekannt ist. Lernquantile und Zieltabellen werden grundsätzlich auf früheren Daten bestimmt. Das ist eine brauchbare Grundlage.

**Die wesentlichen Einschränkungen:**

| Befund | Fundstelle und konkrete Korrektur |
|---|---|
| **Kapital wird zu früh freigegeben.** | `kontostand_2026_11_08/pool38.py:21–22,32` und `live17.py:19–20,30` verbuchen PnL mit dem Zeitstempel des Beginns der Ausstiegskerze. Deren späteres Hoch/Tief ist dann noch unbekannt. Mit Kerzendaten konservativ zum Kerzenende abrechnen oder feinere Ausführungszeiten verwenden. Dasselbe Problem betrifft die anderen Kontosimulatoren. |
| **Periodenergebnisse enthalten spätere Ausstiege.** | `pool38.py:15,33` filtert nur Einstiege und rechnet anschließend sämtliche offenen Trades endgültig ab. Das ist ein Einstiegskohorten-Ergebnis, keine Kontorendite exakt bis zum Periodenende. Zum Stichtag offene Positionen bewerten und spätere Ergebnisse ausschließen; Kohortenanalyse separat kennzeichnen. |
| **Drawdown ist kein vollständiger Equity-Drawdown.** | `pool38.py:19–33` und `live17.py:17–31` berücksichtigen nur realisierte Ergebnisse. Zwischenzeitliche offene Verluste fehlen. Zudem werden fällige Abschlüsse in Listenreihenfolge abgearbeitet. Chronologisch bündeln und Equity einschließlich offener Positionen messen. |
| **„Identische Trades“ stimmt nicht.** | Die Notionalgrenze in `pool38.py:31` lässt je Risikostufe andere Trades zu. Das Ergebnis zeigt selbst 2025 **699 versus 735 versus 740 Trades**. Für einen reinen Sizing-Vergleich die Tradefolge fixieren; den handelbaren Portfoliovergleich zusätzlich separat berichten. |
| **Forschungsmodell und Produktions-Simulator unterscheiden sich.** | Forschung überspringt bei Überschreitung einer globalen 10×-Notionalgrenze. `src/portfolio_simulator.py:254–263` verwendet individuelle Hebel, kappt auf verfügbare Margin und prüft Mindestnotional. Die Forschungszahlen sind deshalb kein Paritätsnachweis für die produktive Teamauswahl. |
| **Offene Varianten werden selektiv ausgeschlossen.** | `pfade.py:76–78` setzt nicht abgeschlossene Ergebnisse auf `NaN`; `analyse.py:44–48` mittelt anschließend je Variante über deren abgeschlossene Trades. Unterschiedliche Ziele können dadurch auf unterschiedlichen Stichproben verglichen werden. Gemeinsamen Bewertungshorizont beziehungsweise Stichtagsbewertung verwenden und offene Anteile ausweisen. |
| **Lernlabels können über die Lernfrist hinausreichen.** | `analyse.py:10,50–54` und `h5.py:6–10` grenzen nach Einstieg ab, verwenden aber möglicherweise erst später bekannte Ergebnisse. Für Tabellen und Lernquantile der Ergebnisanalyse nur rechtzeitig bekannte Labels verwenden. |
| **Bootstrap kann Scheingenauigkeit erzeugen.** | `h6.py:16–20` prüft keine Mindestzahl unabhängiger Blöcke. Der Bericht ab 15.10. zeigt deshalb `[+0,077; +0,077]` aus einem einzigen Kalenderblock. Bei zu wenigen Blöcken kein Konfidenzintervall ausgeben. |

**Bei Auswahlverzerrung widerspreche ich Claude ausdrücklich:** Dass beide Varianten dieselben nachträglich ausgewählten Configs verwenden, beseitigt den Bias des Unterschieds nicht. Die Auswahl kann gerade mit der Wirkung des Filters zusammenhängen. `freigabe.py:9–10` formuliert das zu zuversichtlich.

Auch ein passender SHA256-Hash beweist den heutigen Dateistand, aber nicht unabhängig den Zeitpunkt der Festlegung. H5 und H6 wurden laut `PREREG.md` nach früheren Ergebnissichten ergänzt. Der bereits mehrfach betrachtete Zeitraum ist für diese Forschung kein frischer Bestätigungstest mehr.

**Meine Einordnung der Ergebnisse:**

- **Kelly:** Diese konkrete Variante verliert im späteren Zeitraum massiv. Sie schlägt dort aber die ebenfalls kollabierende Kontrolle. Daraus folgt weder ein belastbarer Nutzen noch eine allgemeine Widerlegung von Kelly. Zusätzlich fehlt in `kelly.py:14` die Normierung auf die tatsächliche Verlust-R-Höhe, wenn die binäre Kelly-Näherung als Risikoanteil verwendet werden soll.
- **G1/G2:** Kein belastbarer Freigabenutzen gezeigt. Positive Mittelwerte der aussortierten Trades sind bei den breiten Intervallen kein gesicherter Schadensnachweis.
- **Tägliche Auswahl:** Kein stabiler Vorteil. „Schlechter als alle und Zufall“ gilt allerdings nicht überall: Das 30-Tage-Modell liegt 2025 über beiden Vergleichsmitteln.
- **Dynamische Ziele:** Für Strukturstop S ist K in den ausgewiesenen drei Zeiträumen das beste der getesteten festen Ziele. **„K ist immer das beste Ziel“ ist falsch:** Bei A2 gewinnt im Lernzeitraum R30 mit +0,095 gegen K mit +0,087 R.
- **H6:** Weniger kumulierter Verlust bei weniger Trades ist ein anderes Ziel als höheres R je tatsächlich gehandeltem Trade. Beides getrennt bewerten; aktuell kein belastbarer Freigabenachweis.
- **Stopweiten:** Interessante explorative Diagnose. Die detaillierte Fünfperioden-Tabelle aus der Übergabe lässt sich aus den mitgelieferten Ergebnissen und Skripten nicht vollständig reproduzieren; Export und Erzeugungsskript nachreichen.

### 3. Mein `min_sl_atr=2.0`-Default

**Claude hat recht: Ich würde den automatischen Default zurücknehmen.** Eine nicht bestätigte Forschungsvariante darf nicht beim nächsten Pipeline-Lauf unbemerkt zur Produktionsvorgabe werden.

Konkrete Änderungen im durch `codex_lokal_min_sl_atr.diff` beschriebenen Zielcode:

- `optimizer.py:395`: `min_sl_atr` standardmäßig auf **0,0**.
- `optimizer.py:421`: ebenso **0,0**; 2,0 nur als ausdrücklich gewählte Versuchsvariante.
- `confluence_logic.py:34`: Kommentar zur angeblich aktuellen 2-ATR-Vorgabe korrigieren.
- `optimizer.py:503`: Den Umgang mit veralteten Ergebnissen getrennt erhalten; er ist kein Grund, den 2-ATR-Default beizubehalten.

Die Implementierung verbreitert den Stop **nach** dem ursprünglichen `min_rr`-Filter. Das effektive CRV kann damit unter das konfigurierte Minimum fallen. Für einen isolierten Variantenvergleich ist das nachvollziehbar; als Produktionsregel muss diese Semantik ausdrücklich entschieden und dokumentiert werden.

### 4. Die vier Fragen aus Abschnitt 4

**1. Übersehene Risiko-Lesestellen; Hebel senken?**

Ja:

- `src/analysis_suite.py:313`: Analyse 10 zeigt das ungedeckelte aktuelle Config-Risiko.
- `src/analysis_suite.py:374`: Analyse 13 berechnet Wachstum und Bootstrap mit diesem ungedeckelten Risiko.
- `src/show_results.py:868,876`: Die Ersatzberechnung verwendet ebenfalls den Rohwert. Außerdem ist `Equity × Risikoanteil` ein Risikobetrag, kein Notional. Bei vorhandenen Backtest-Trades besser `contracts × entry` verwenden.

Die hypothetische Risiko-Sensitivität in `analysis_suite.py:406` soll dagegen bewusst auch Werte über 1 % zeigen dürfen. `:172` bezeichnet einen Preisabstandsquotienten und braucht keinen Cap.

**Der Hebel muss für die Stoprisikosenkung nicht proportional sinken:** Die kleinere Positionsmenge reduziert das Risiko bereits. Eine Hebeländerung verändert Marginbedarf und möglicherweise ausführbare Trades und wäre eine zusätzliche Maßnahme.

**2. Erneute Teamauswahl nötig?**

**Ja, um ein unter der neuen Risikopolitik ausgewähltes Team zu erhalten.** PnL, Marginbelegung, ausgelassene Trades und damit Rankings können sich ändern. Alte gespeicherte Backtestwerte müssen unter derselben Cap-Einstellung neu berechnet oder als veraltet markiert werden.

Die Risikosenkung beim vorhandenen Team benötigt diesen Lauf technisch nicht. Ich würde die Auswahl ebenfalls **nicht automatisch starten**.

**3. Default 1 % im Code oder nur explizite Settings?**

**Mit 1 % als Rückfallwert einverstanden**, gerade wegen der bewahrten VPS-Settings. Zusätzlich den Wert explizit konfigurieren und beim Start protokollieren: Config-Risiko, Cap, effektives Risiko.

Ungültige Settings sollten sichtbar scheitern, statt wie fehlende Konfiguration behandelt zu werden. Backtests brauchen eine eingefrorene Cap-Einstellung im Ergebnis.

**4. Analyse 14 um R je Stopweite erweitern?**

**Ja, als Diagnose.** Grenzen vorab einfrieren, ATR ausschließlich aus abgeschlossenen Kerzen berechnen und je Segment Stichprobengröße, Netto-R, Unsicherheit und offene Trades zeigen. Strukturstopweite und tatsächlich verwendete Stopweite getrennt speichern.

Der Aussage, dort zeige sich **zuerst**, ob die Konfluenz wieder trägt, widerspreche ich: Das ist bisher eine plausible Hypothese, kein validierter Frühindikator. Daraus sollte vor einem neuen Vorwärtstest keine automatische Handelsfreigabe entstehen.