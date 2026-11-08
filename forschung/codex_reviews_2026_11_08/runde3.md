Die Prüfung dauerte rund **2 Minuten 20 Sekunden**. Keine Dateien geändert.

**Urteil: Den vorliegenden Stand noch nicht produktiv ausrollen.** Die feste Risikoobergrenze ist deutlich verbessert. Bei Orderverwaltung, Kapitalbewegungen und Impulssperre bleiben jedoch Fehler, die einen Push heute verhindern sollten.

**1. P1 – Fehlgeschlagene Orderstatusabfrage ermöglicht weiterhin eine zweite Order**

**Fundstellen:** `src/trade_manager.py:943–946`, `:996–997`, `:1014–1019`.

Wirft `fetch_order()` eine Exception, wird nur eine Warnung geschrieben. `status` bleibt `None`; der allgemeine `else`-Zweig entfernt anschließend die wartende Order aus dem Tracker. Danach kann eine neue Order platziert werden, während die alte weiterhin offen ist.

**Schreibfrei mit der Originalfunktion reproduziert:** eine neue Order, **kein Storno**, Tracker überschrieben.

Die Korrektur für Storno-Exceptions greift hier nicht. Bei fehlendem oder unbekanntem Orderstatus muss der Lauf mit unverändertem Tracker enden.

**2. P1 – Verzögert eingelesene Einzahlungen werden doppelt im Höchststand berücksichtigt**

**Fundstellen:** `src/trade_manager.py:449–455`; `src/risk_cap.py:185`, `:190`, `:252`.

Beobachtungen ohne vollständigen Kontoauszug dürfen den Höchststand bereits erhöhen. Wird der zugehörige Einzahlungsbeleg später abgeholt, addiert der Code dessen Betrag nochmals.

**Schreibfrei reproduziert:**

| Schritt | Equity | Gespeicherter Höchststand |
|---|---:|---:|
| Ausgangspunkt | 1.000 | 1.000 |
| Einzahlung bereits im Kontostand, Bill noch nicht verarbeitet | 1.500 | 1.500 |
| Bill über +500 nachträglich verarbeitet | 1.500 | **2.000** |

Dadurch entsteht ein künstlicher Drawdown von 25 %. Das kann durch die Abrufdrosselung, API-Fehler oder parallele Strategieprozesse auftreten.

Zusätzlich werden Equity und Bills außerhalb der Sperre zu unterschiedlichen Zeitpunkten abgerufen (`src/trade_manager.py:444`, `:452`). Ein alter Equity-Snapshot von 1.000 zusammen mit einer Auszahlung von 200 führt durch `max(peak, equity)` erneut zu Peak 1.000. Bei anschließend korrekter Equity 800 ergibt sich fälschlich Faktor **0,333 statt 1,0**.

Die Dateisperre schützt die Schreibtransaktion, aber nicht die zeitliche Konsistenz ihrer Eingangsdaten. Benötigt wird eine gemeinsame, nachvollziehbare Abstimmung von Kontostand und Kapitalbewegungen.

**3. P1 – Der zusätzliche Doppel-Einstieg-Fix verliert seine Sperre bei einer Notschließung**

**Fundstellen:** `src/trade_manager.py:635–661`, `:904`, `:911–915`, `:999`.

Der Preis-Overshoot-Pfad schließt die Position und schreibt anschließend einen vollständig leeren Tracker (`:661`). Damit verschwinden sowohl der aktuelle `b_ts` als auch sämtliche bisherigen `consumed_b`.

Im nächsten Lauf findet `confluence_cycle()` keinen offenen Tracker mehr, dessen Impuls es verbrauchen könnte. Derselbe Impuls kann erneut gehandelt werden.

Beim bestätigten Schließen müssen die bisherigen verbrauchten Impulse erhalten und der aktuelle Impuls hinzugefügt werden. Die neuen Prüfungen decken normale Schließungen ab; diese Tracker-Löschung umgeht sie.

**4. P2 – Die Historie kann weiterhin zukünftige Höchststände in frühere Zeitfenster übertragen**

**Fundstellen:** `src/risk_cap.py:185–188`, `:231–242`; `src/daily_live_vs_backtest_check.py:239–243`.

Ein verspätet eingelesener Bill erhält seinen ursprünglichen Buchungszeitpunkt, enthält aber den **heute berechneten** Höchststand. Dieser kann bereits spätere Kontobeobachtungen enthalten.

Beispiel: Nach einer Beobachtung bei Zeitpunkt 3.000 wird ein Bill von Zeitpunkt 2.000 importiert. Der dabei protokollierte Peak wird von `peak_at(2500)` als historischer Zustand akzeptiert, obwohl seine Berechnung Informationen von Zeitpunkt 3.000 enthält.

Außerdem wählt `peak_at()` den letzten passenden Eintrag in Dateireihenfolge, nicht den mit dem größten passenden Zeitstempel. Rückdatierte Bills und unterschiedlich lange Prozessläufe verletzen diese Annahme.

Bloßes Sortieren reicht nicht: Buchungszeitpunkt und Zeitpunkt der Zustandsbeobachtung müssen getrennt werden; historische Zustände benötigen eine kausale Rekonstruktion.

**5. P2 – Der Tagesbericht rekonstruiert Startkapital weiterhin ohne Kapitalbewegungen**

**Fundstellen:** `src/daily_live_vs_backtest_check.py:550–553`, `:274–275`.

Vom heutigen Kontostand werden offene PnL und abgeschlossene Handelsresultate abgezogen. Einzahlungen und Auszahlungen innerhalb des Berichtsfensters bleiben enthalten.

Bei Startkapital 1.000, Einzahlung 500 und ohne Trades beginnt die historische Simulation deshalb mit **1.500 statt 1.000**. Ein korrekter historischer Peak allein behebt das nicht; auch spätere Kapitalbewegungen fehlen im Simulatorablauf.

Ältere Positionen fehlen weiterhin mit Margin und offener PnL. Das steht zwar im Kommentar (`:237`), erzeugt aber keinen entsprechenden sichtbaren Berichtshinweis.

**Antworten auf die ausdrücklich gestellten Fragen**

- **Linux-/Windows-Sperre:** Die kritische Zustandsänderung liegt jetzt vollständig unter derselben Dateisperre (`src/risk_cap.py:95–122`, `:175`, `:201`, `:219`). Beim Prozessende werden die Betriebssystem-Sperren freigegeben; eine zurückbleibende `.lock`-Datei hält keine Sperre. Für denselben Zustandspfad sehe ich auch bei Historienkürzung keinen zyklischen Deadlock: `_history()` fordert keine weitere Sperre an (`:152–163`). Windows bricht nach ungefähr zehn Sekunden erfolglosen Wartens ab. Ein Prozessabbruch garantiert allerdings keine gemeinsame Atomizität von Zustand und Historie; diese werden separat geschrieben (`:188–193`).

- **Vorzeichen der Bitget-Bills:** Die offizielle Dokumentation benennt `trans_from_exchange` als Eingang und `trans_to_exchange` als Ausgang. Das Feld `amount` beschreibt sie jedoch lediglich als „Amount“; ein ausdrückliches Vorzeichenversprechen für Transfers fehlt. Daher ist die Annahme „Auszahlung immer negativ“ für `src/exchange.py:540–542` durch diese Dokumentation **nicht ausreichend bestätigt**. Vor Freigabe sollten echte, anonymisierte Ein-/Ausgangsantworten als Vertragsfälle geprüft werden. [Bitget Account Bills](https://www.bitget.com/docs/catalog/classic-contract-account/classic-contract-account)

- **Erster Live-Lauf:** Peak = aktuelle Equity ist als ausdrücklich gewählter Beginn einer neuen Historie sinnvoll (`src/risk_cap.py:177–179`). Er berücksichtigt keinen früheren Drawdown. Für eine Übernahme vorhandener Risikohistorie wäre ein bekannter Ausgangshöchststand nötig.

- **Gesamt-Equity:** Die klassische Kapitalbasis ist korrigiert (`src/trade_manager.py:720–735`). Die lokal installierte CCXT-Version 4.5.73 ordnet Futures-`total` tatsächlich `accountEquity` zu; Bitget definiert dieses einschließlich unrealisierter PnL. Damit ist `src/exchange.py:553–554` für diesen Kontotyp plausibel. [Bitget Kontodefinition](https://www.bitget.com/docs/catalog/classic-contract-account/classic-contract-account)

**Bestätigte Korrekturen und Prüfgrenzen**

Schreibfrei bestätigt wurden Obergrenze, `cap=0`, Drawdown-Faktor und Ablehnung ungültiger Risikowerte. Den Simulatorfall mit unterschiedlichen Kerzenrastern habe ich ebenfalls ausgeführt: **0 % künstlicher Drawdown**. Die Mengenaufrundung wird im klassischen und im Konfluenzpfad abgefangen (`src/trade_manager.py:739`, `:832`).

Die Behauptung **131/131 grün** konnte ich mit diesem Auszug nicht nachprüfen: Die Testsammlung scheitert an `ModuleNotFoundError: fibot`; weitere referenzierte Testmodule fehlen ebenfalls. Alle fünf vollständigen Quelldateien bestehen die Syntaxprüfung. Die oben genannten Order- und Kapitalflussfehler wurden isoliert im Speicher reproduziert.