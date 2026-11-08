Die Prüfung dauerte rund 1 Minute 30 Sekunden.

**Urteil: Noch nicht für den produktiven Einsatz freigeben.** Mehrere Korrekturen aus Runde 1 sind umgesetzt; die neue Kontoverlauf-Anpassung enthält jedoch Fehler bei Nebenläufigkeit, Kontobewertung und historischem Abgleich. Keine Dateien geändert.

Die folgenden Zeilennummern beziehen sich auf die mitgelieferten Dateien unter `src/`; bei ausschließlich im Diff vorhandenen Änderungen nenne ich dessen Zeilen.

1. **Hohe Priorität: Der Höchststand kann bei parallelen Prozessen sinken.**

   **Fundstelle:** `src/risk_cap.py:92–103`.

   `os.replace()` verhindert eine teilweise geschriebene Zieldatei, schützt aber nicht die gesamte Folge aus Lesen, Vergleichen und Schreiben. Zwei Prozesse können beide 100 lesen; einer schreibt 120, anschließend überschreibt der andere diesen Wert mit 110. Genau diesen Ablauf habe ich mit Dateizugriffen im Arbeitsspeicher reproduziert: Endstand **110 statt 120**. Dadurch fällt die Risikobremse anschließend zu schwach aus.

   **Korrektur:** Eine prozessübergreifende Sperre über die gesamte Transaktion legen und den gespeicherten Wert erst innerhalb der Sperre lesen. Alternativ eine Datenbanktransaktion verwenden. Auch Rücksetzungen müssen dieselbe Sperre benutzen.

2. **Hohe Priorität: Freies Guthaben wird im klassischen Pfad fälschlich als Konto-Equity behandelt.**

   **Fundstelle:** `src/trade_manager.py:691–701`; gemeinsame Höchststandsdatei in `src/risk_cap.py:110`.

   Der klassische Pfad reicht `fetch_balance_usdt()` an `live_risk_pct()` weiter. Bereits belegte Margin sieht dadurch wie ein Handelsverlust aus. Bei unveränderter Equity von 1.000 USDT und 500 USDT freiem Guthaben ergibt die Funktion gegenüber einem Höchststand von 1.000 den Mindestfaktor **0,25 statt 1,0**. Das habe ich numerisch bestätigt.

   Zusätzlich hängt der Inhalt derselben Höchststandsdatei davon ab, welcher Strategiepfad sie aktualisiert.

   **Korrektur:** In beiden Pfaden Gesamt-Equity für Höchststand, Drawdown und Risikobetrag verwenden. Freies Guthaben separat ausschließlich für die Marginbegrenzung berücksichtigen.

3. **Hohe Priorität: Einzahlungen und Auszahlungen werden nicht von Handelsgewinnen und Verlusten getrennt.**

   **Fundstelle:** `src/risk_cap.py:88–110`.

   Eine Auszahlung von 150 aus einem unveränderten 1.000-USDT-Konto erzeugt künstlich 15 % Drawdown und halbiert den Risikoanteil. Einzahlungen können umgekehrt einen bestehenden Drawdown verdecken. Die dokumentierte Lösung „Datei löschen“ setzt außerdem vorhandenen Handelsdrawdown zurück und konkurriert mit laufenden Schreibern.

   **Korrektur:** Externe Kapitalbewegungen erfassen und die Drawdown-Reihe kapitalflussbereinigt führen, beispielsweise über einen Anteilswert. Einen bewussten Neustart der Risikohistorie als explizite, protokollierte und gesperrte Operation implementieren. Den Zustand an das konkrete Konto binden.

4. **Hohe Priorität: Unterschiedliche Kerzenraster erzeugen künstlichen Drawdown im Simulator.**

   **Fundstelle:** `src/portfolio_simulator.py:297–312`.

   Offene PnL wird nur berücksichtigt, wenn die jeweilige Strategie am aktuellen Zeitstempel eine Kerze besitzt. Fehlt diese, verschwindet ihr offenes Ergebnis vorübergehend vollständig aus `total_eq`.

   Schreibfrei reproduziert mit zwei unterschiedlichen Zeitrastern und unveränderten Positionskursen:

   | Zeitpunkt | Simulierte Equity |
   |---|---:|
   | 00:00 | 1.150 |
   | 00:30 | 1.000 |
   | 01:00 | 1.150 |

   Ergebnis: **13,04 % künstlicher MaxDD**. Die neue Risikobremse reagiert auf diesen Bewertungsfehler und verändert dadurch zusätzlich die Positionsgrößen.

   **Korrektur:** Für jede offene Position den letzten zum Bewertungszeitpunkt tatsächlich bekannten Preis fortschreiben. Keine Position wegen eines fehlenden Datenpunkts mit null offener PnL bewerten.

5. **Hohe Priorität: Live und Simulator verwenden unterschiedliche Kapitalbasen und Bewertungszeitpunkte.**

   **Fundstelle:** `src/portfolio_simulator.py:196–204,255–259,284–312`; `src/trade_manager.py:780–786`.

   Live berechnet den Risikobetrag aus aktueller Gesamt-Equity. Der Simulator berechnet den Faktor aus dem alten `total_eq`, multipliziert ihn aber mit dem realisierten Kontostand `equity`. Offene Gewinne und Verluste wirken damit unterschiedlich auf die Positionsgröße.

   Zudem ändern Ausstiege und Sofortverluste bereits `equity`, während `total_eq` und `dyn_peak` für weitere Einstiege noch unverändert bleiben. Im Abschnitt A werden sogar Ausstiege anhand des Hochs/Tiefs der aktuellen Kerze verbucht, bevor Abschnitt B deren neue Einstiege behandelt. Diese Ereignisreihenfolge ist kein zuverlässiger Live-Nachbau.

   **Korrektur:** Eine gemeinsame, zeitlich kausale Kontobewertung definieren: bekannte Preise, Ausführungen, Gebühren und offene PnL zum jeweiligen Entscheidungszeitpunkt; daraus Faktor und Risikobetrag berechnen. Bei Kerzendaten die unvermeidbare Näherung ausdrücklich dokumentieren und gegen einen feineren Ereignisablauf testen.

   **Zur konkreten Frage nach `fetch_equity_usdt()`:** Dessen Implementierung fehlt im Auszug. Ob tatsächlich vollständige Equity einschließlich unrealisierter PnL geliefert wird, kann ich deshalb nicht bestätigen. Der Simulator ist bereits unabhängig davon nicht ausreichend gleichwertig.

6. **Hohe Priorität: Der Tagesbericht verwendet einen zukünftigen Höchststand für historische Einstiege.**

   **Fundstelle:** `src/daily_live_vs_backtest_check.py:231–236,269–270`.

   `_live_peak()` liest den heutigen Höchststand und übergibt ihn als Höchststand **vor** dem simulierten Zeitraum. Ein erst innerhalb des Fensters erreichtes Hoch reduziert dadurch rückwirkend frühere Positionsgrößen. Derselbe historische Zeitraum kann morgen ein anderes Ergebnis liefern.

   Zusätzlich werden ältere Positionen nur als Symbolsperren übergeben (`:268`); ihre Margin und offene PnL fehlen im simulierten Konto. Die Startkapitalrekonstruktion (`:545–547`) berücksichtigt externe Kapitalbewegungen ebenfalls nicht.

   **Korrektur:** Historische Equity-/Höchststands-Snapshots zum Fensterbeginn speichern und vorhandene Positionen samt Bewertung übernehmen. Fehlen diese Daten, den Bericht als Näherung kennzeichnen; die Aussage „dieselbe Anpassung wie live“ ist derzeit falsch.

7. **Hohe Priorität: Die Ersetzung einer zu großen Order kann eine zweite Order erzeugen.**

   **Fundstelle:** `src/trade_manager.py:933–960`.

   Schlägt `cancel_order()` fehl, wird nur eine Warnung geschrieben. Anschließend wird der Tracker geleert und eine neue Order platziert. Die bisherige, zu große Order kann weiterhin liegen; bei ausreichender Margin können beide gefüllt werden.

   **Korrektur:** Nach fehlgeschlagener oder unklarer Stornierung keine Ersatzorder platzieren. Den bisherigen Tracker erhalten und den tatsächlichen Order-/Positionszustand erneut abgleichen. Auch eine Füllung während der Stornierung behandeln.

   Weiterhin bleibt bei fehlgeschlagener Budgetprüfung die Order unverändert liegen (`:924–932`). Damit ist die Obergrenze für diesen Fehlerfall ausdrücklich **nicht garantiert**. Dafür braucht es eine definierte Fehlerstrategie und einen entsprechenden Verhaltenstest.

8. **Mittlere Priorität: Der Konto-Höchststand wird nur bei Einstiegsentscheidungen beobachtet.**

   **Fundstelle:** `src/trade_manager.py:645,699,785,923`; `src/risk_cap.py:110`.

   Bei laufenden Positionen endet der Zyklus vor den neuen Höchststandsaufrufen. Ohne neue Einstiegspläne kann ein zwischenzeitliches Equity-Hoch unbemerkt bleiben. Der Simulator aktualisiert seinen Höchststand dagegen an jedem Zeitstempel.

   **Korrektur:** Kontoweite Equity unabhängig von Einstiegssignalen regelmäßig erfassen und den Höchststand zentral fortschreiben. Die Abtastfrequenz zwischen Live und Simulation angleichen beziehungsweise deren Unterschied ausweisen.

9. **Mittlere Priorität: Beschädigte Höchststandsdaten können die Bremse unbemerkt zurücksetzen.**

   **Fundstelle:** `src/risk_cap.py:94–96`.

   Fehlerhaftes JSON und nicht konvertierbare Werte werden wie ein fehlender Anfangszustand behandelt. Dadurch wird ein bestehender Drawdown vergessen. `NaN` und Unendlich werden als gespeicherter Höchststand sogar akzeptiert; beide Fälle habe ich schreibfrei bestätigt.

   **Korrektur:** Fehlende Erstinitialisierung von beschädigtem Zustand unterscheiden. Gespeicherte Werte auf numerisch, endlich und gültig prüfen; bei Beschädigung sichtbar abbrechen oder einen validierten Sicherungsstand verwenden.

10. **Mittlere Priorität: Die klassische Rundungssicherung ist noch unvollständig.**

    **Fundstelle:** `src/trade_manager.py:706–718`.

    Der Kommentar verspricht, Mengenerhöhungen zu verhindern. Tatsächlich werden nur Mindestmenge und positive Menge geprüft. Im Konfluenzpfad existiert der zusätzliche Vergleich gegen die vor Rundung erlaubte Menge bereits (`:795–799`).

    **Korrektur:** Diesen Vergleich auch klassisch ergänzen und nach der Rundung Stoprisiko und Marginbudget prüfen. Die Mindestmengen-Anhebung selbst ist korrekt entfernt.

**Weitere Punkte zur Umsetzung aus Runde 1**

- Die Validierung von Config-Risiko und Obergrenze ist wesentlich verbessert. Allerdings bedeutet `cap=0` direkt **null Risiko**, während derselbe Wert aus Settings „keine Obergrenze“ bedeutet (`src/risk_cap.py:47,124–126`). Die Semantik vereinheitlichen oder ausdrücklich unterscheiden und testen.
- Cap und Dynamikeinstellungen werden im Portfolio-Simulator einmal je Lauf gelesen und ausgegeben (`src/portfolio_simulator.py:80–81,333–334`). Für vollständige Reproduzierbarkeit fehlt mindestens der tatsächlich verwendete `start_peak` im Ergebnis.
- Die vollständige Risiko-Protokollierung steht nur im Konfluenzpfad (`src/trade_manager.py:859–861`). Klassisch fehlt die Kombination aus Config-Risiko, Cap und Endwert. Die Anzeige „effektiv“ im Konfluenz-Startlog bezeichnet außerdem zunächst nur den Wert **vor** der Dynamik.
- Optimizer-Default `min_sl_atr=0.0` und die Kennzeichnung des Einsatz-Fallbacks als Risiko sind im Diff umgesetzt. Analyse 10/13 berücksichtigen den festen Cap; Kommentare wie „tatsächlich gehandeltes Risiko“ sind seit Einführung der Kontodynamik zu stark.

**Einzel-Backtester ohne Dynamik: damit bin ich einverstanden.** Eine einzelne Config kann den gemeinsamen Kontoverlauf nicht nachbilden. Das Ergebnis muss als isoliertes Ranking unter festem Cap bezeichnet werden. Die endgültige Teamauswahl und Bewertung müssen anschließend unter der korrigierten Portfolio-Risikopolitik erfolgen.

**Prüfstand und notwendige Nachweise**

Alle sechs mitgelieferten Python-Dateien ließen sich im Arbeitsspeicher kompilieren. Nebenläufigkeitsfehler, Guthaben-/Equity-Verwechslung, ungültige Höchststandswerte und der künstliche Simulator-Drawdown wurden schreibfrei geprüft.

Die behaupteten **117 erfolgreichen Tests sind hier nicht unabhängig bestätigt**: Paket `fibot`, weitere Testmodule und die vollständige Anwendung fehlen. Die neuen Tests prüfen überwiegend einfache, synchronisierte Fälle; insbesondere Parallelzugriffe, Kapitalbewegungen, unterschiedliche Kerzenraster und fehlgeschlagene Stornierungen fehlen.

Auch die Forschungsrechnung ist nicht reproduzierbar: `forschung/bremse_1pct.py:5–6` benötigt die nicht mitgelieferten Dateien `pool38.py` und `live17.py`. Die Ergebnistabelle belegt deshalb hier weder die Behebung der früheren methodischen Einwände noch Produktionsparität.

Vor einem produktiven Push sollten die hohen Prioritäten behoben und genau diese Fehlerfälle durch Verhaltenstests abgesichert sein.