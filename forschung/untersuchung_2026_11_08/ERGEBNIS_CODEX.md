# Unabhängige Prüfung des fibot

Nur bereitgestellte Dateien gelesen und offline gerechnet; keine Orders, keine Codeänderungen. Referenzen beziehen sich auf den gelieferten Code, dessen historische Einsatzstände nicht belegt sind.

**Urteil:** Den Kontorückgang erklären überwiegend verlustreiche reguläre Trades und Gebühren. Stop-Ausführungen kosten zusätzlich Geld. Der Re-Entry-Bug besteht, hat im beobachteten Zeitraum aber netto Gewinn beigetragen. Mehrere weitere Kontrollfehler sind im Code vorhanden; ihre tatsächlichen Verlustbeträge sind nicht nachweisbar.

## A. Zusätzliche Codefehler

1. **Storno scheitert oder Orderstatus unbekannt: trotzdem neuer Entry.** `code/src/fibot/utils/trade_manager.py:892–940`: Bei fehlgeschlagener Orderabfrage wird der Tracker gelöscht (921); nach Stornofehler wird ebenfalls weitergehandelt (915–919). Zwischen Positionsabfrage (464) und Storno kann die alte Order außerdem gefüllt werden. Ohne erneute Prüfung von Position, Restmenge und bestätigtem Storno folgt eine neue Order. Konkretes Szenario: alte Limitorder bleibt nach Timeout aktiv, neue Order kommt hinzu, beide füllen → überhöhtes Risiko. Auch teilweise gefüllte, noch offene Orders benötigen diese Absicherung. In den CSVs kein eindeutig zuordenbarer Schadensbetrag.

2. **Die Grenze von neun Positionen wird live nicht durchgesetzt.** `code/master_runner.py:94–133` startet alle aktiven Strategien; `trade_manager.py:464` fragt nur das jeweilige Symbol ab. `max_open_positions` wird im Live-Pfad nicht geprüft. Aktuell sind 17 Strategien aktiv. Bei genügend Margin können mehr als neun Positionen entstehen; parallele Guthabenabfragen reservieren zudem kein gemeinsames Risikobudget. Beobachtet wurden unter den 63 gelisteten Positionen höchstens vier gleichzeitig: Kontrollfehler, aber kein belegter historischer Verlust dadurch.

3. **Symbolweite Börsenaktionen treffen auf Tracker je Timeframe.** `trade_manager.py:31–34,464,493–528,624–627,866`; `exchange.py:338–360`; `master_runner.py:107–108`. Zwei Timeframes desselben Symbols können dieselbe aggregierte Position verwalten, gegenseitig Orders stornieren und beim Overshoot die gesamte Position anhand eines fremden Trackers schließen. Der Preis-Fallback prüft weder zugehörige Strategie noch Schutzmenge. Beim Teamwechsel von beispielsweise PYTH 2h auf 4h bleibt eine alte 2h-Order erhalten, weil der Housekeeper nur das Symbol berücksichtigt. Im aktuellen Team keine doppelten Symbole; historischer Schaden nicht belegt.

4. **Notschließung entfernt zuerst den Schutz.** `trade_manager.py:624–641`: Erst alle Orders stornieren, dann Market-Close. Scheitert der Close, bleibt die Position möglicherweise ohne SL/TP bis zum nächsten Lauf. Die anschließende Positionskontrolle ist nicht strikt (629; `exchange.py:398–402`), ein API-Fehler kann den Tracker irrtümlich leeren. `housekeeper_routine` hat dasselbe Problem (135–150). Der normale erste Positionsabruf ist dagegen korrekt strikt abgesichert.

5. **Sizing kann seine eigene Kappung überschreiben.** `trade_manager.py:789–794` kappt zunächst auf freie Margin und hebt anschließend auf die Mindestmenge an, ohne Risiko/Margin erneut zu prüfen. Beispiel: 0,1 USDT frei, Hebel 5, Preis 10, Mindestmenge 1 → Kappung 0,0475 Stück, anschließend 1 Stück mit 2 USDT Marginbedarf. Zusätzlich behandelt `exchange.py:209–219` echte freie Margin von null als fehlenden Wert und ersetzt sie durch Equity/Total. Das führt zu falschen Größen bzw. abgelehnten Orders. Gebühren werden beim Zielrisiko nicht berücksichtigt; ein Stop kostet daher mehr als die eingestellten 1,5–3 %. Kein Nachweis einer historisch dadurch zu großen Position.

6. **Rundung ohne abschließende Risikoprüfung.** `exchange.py:512–520`: Entry, SL und TP werden getrennt gerundet; danach werden weder Reihenfolge noch tatsächlicher Stop-Abstand geprüft. Bei engem Stop können Entry und SL auf denselben Tick fallen. Die Precision-Helfer geben bei Fehlern sogar den ungerundeten Ausgangswert zurück (174–189). Wahrscheinliche Folgen sind Ablehnung oder verändertes Risiko; keine entsprechende Schadenssumme belegt. Fehler beim Setzen von Hebel/Margin werden ebenfalls nur geloggt (426–468), obwohl das Sizing den gewünschten Hebel voraussetzt.

## B. Tatsächliche Ausführung

- Seit 15.10.: 63 gefüllte Entries, sämtlich **Limitorders**. Kein Fill verletzt das jeweilige Limit. Eine sofort ausführbare Limitorder kann trotzdem Taker sein: bei Entries mit Preset-Schutz zeigen 51 Gebühren von 0,02 %, neun von 0,06 %. Der Backtest berechnet pauschal 0,06 % pro Seite und ist insoweit konservativer.
- 59 Konfluenz-Exits sind börsenseitige Stop-/TP-Market-Ausführungen: 52 `loss_market`, sieben `profit_market`. Kein Konfluenz-Exit ist als gewöhnlicher API-Market-Close ausgewiesen. Die einzige solche API-Schließung seit 15.10. betrifft PEPE vor dem Umbau, netto rund −0,0073 USDT; ohne Log kein sicherer Nachweis einer Notschließung. Zwei andere gewöhnliche Market-Closes kamen von iOS.
- Stop-Fills gegenüber dem **gerundeten Preset-SL**, gewichtet mit geschlossener Menge: netto **3,6675 USDT schlechter**, davon **1,8801** bei regulären Trades und **1,7874** bei Duplikaten. Das ist Ausführungsabweichung einschließlich möglicher Trigger-/Spread-Effekte, keine isolierte Messung reinen Orderbuch-Schlupfs. WAL 31.10., erster Trade: SL 0,03096, Exit 0,03103, 4.995 Stück → 0,34965 USDT Mehrverlust.
- PYTH-Re-Entry 04.11. 15:16: Short-Limit 0,067, Fill 0,06752, Preset-SL 0,06707, Exit 0,06757. Der bessere Short-Einstieg lag bereits jenseits des Stops. Die 1,3855 USDT Exit-Abweichung zum Preset darf deshalb nicht ohne die günstige Entry-Abweichung als zusätzliche Gesamtbelastung interpretiert werden.
- PYTH-Gebühren erreichen **1,158 R**, bezogen auf das gerundete geplante Preisrisiko. Beim ersten PYTH-Trade: Preisrisiko nur 0,19614 USDT, Gebühren 0,15032 USDT. Kleine Positionsverluste sind mit Margin-Kappung vereinbar, beweisen diese aber nicht. Historische Guthaben-/Margin-Snapshots fehlen. PYTH 2h mit Hebel 5 entspricht seiner Config; keine nachgewiesene unerwartete Hebelkappung oder Liquidation.

## C. Verlustzerlegung

Aus `bitget_orders.csv`, Buchungen seit 15.10.:

| Beitrag | Brutto USDT | Gebühren USDT | Netto USDT |
|---|---:|---:|---:|
| 52 reguläre Konfluenz-Trades | −27,5829 | −3,6143 | −31,1972 |
| 7 zusätzliche Einstiege | +4,4342 | −1,6117 | +2,8225 |
| 4 Alt-/Testpositionen | −0,4566 | −0,0530 | −0,5096 |
| 2 ältere, jetzt geschlossene BTC-/XRP-Positionen | +4,0083 | −0,0288 | +3,9795 |
| **Gesamt** | **−19,5969** | **−5,3078** | **−24,9048** |

58,60 − 24,9048 = 33,6952 USDT, gegenüber angegebenen 33,74. Die Differenz von 0,0448 USDT ist mit gerundetem Startwert vereinbar; Funding und sonstige Kontobuchungen sind nicht vollständig enthalten.

Die präzise Positionsliste summiert sich auf −28,8332 USDT, ist also **keine vollständige Kontorechnung**: Die zwei älteren Gewinnpositionen fehlen. Die 63 zugeordneten Orderpaare ergeben −28,8842 USDT; die zusätzliche Differenz von +0,0510 USDT zum Positionsexport bleibt ohne Funding-/Kontobuchungen ungeklärt.

Innerhalb der regulären Bruttoverluste stecken die genannten 1,8801 USDT Stop-Abweichung. Bei Exits exakt am Preset-SL, sonst unveränderten Trades, wären es −25,7027 USDT brutto. Gebühren und Stop-Abweichungen sind damit relevant, erklären aber nicht allein den Verlust. Diese Beträge sind bereits in der Tabelle enthalten, nicht zusätzlich abzuziehen. Ein exakter kausaler Gegenlauf nach Bugfix ist wegen veränderter Equity und späterer Handelsmöglichkeiten nicht ableitbar.

## D. Widerspruch und Einordnung zu Claude

- **56/59 stimmt nur für die Ergebniskategorie.** Kategorie UND Ausstiegsminute stimmen bei **50/59** überein. Ohne die sieben Duplikate: **50/52**. MAGIC 25.10. und OP 28.10. stehen im 1m-Vergleich noch auf `open`. Rohkerzen fehlen; diese gelieferten Vergleichsergebnisse kann ich zählen, aber nicht unabhängig neu simulieren.
- **Die sieben Re-Entries waren insgesamt profitabel:** laut präzisem Positionsexport +2,8370 USDT, nach Orderpaaren +2,8225. Sechs verlustreiche Duplikate wurden vom WAL-Gewinn +5,4232 übertroffen. Sie sind ein Fehler, aber keine Nettoverlustursache dieses Zeitraums.
- **„Kein used_b live“ ist technisch zu pauschal.** `plan_next_order` ruft `plan_both` auf (`confluence_logic.py:449`); dort wird `used_b` aus historischen Kerzen rekonstruiert (322–367). Es fehlt die persistente Bindung an tatsächliche Live-Fills, besonders innerhalb der laufenden Kerze. Der bloße Same-Candle-Guard des anderen Strategiepfads behebt das nicht.
- **„Auswahl ohne Vorhersagekraft“ ist nicht belegt.** Ohne Filter berichtet F2 signifikante positive Rangkorrelationen: IS→OOS ρ=0,134, p=0,007; OOS→HOLD ρ=0,281, p gerundet 0,000. Der Unterschied ausgewählt/übrig ist zwar nur +0,003 R, aber sein 90-%-Intervall [−0,859; +0,896] viel zu breit für einen Gleichheitsnachweis. Positive Rangkorrelation bedeutet allerdings noch keine profitable Strategie.
- **Kein belastbarer Profitabilitätsnachweis:** F1 ohne Filter netto −0,149 R als Mittel der Config-Mittel, gepoolt −0,292 R. „Brutto ±0,00 R“ ist aus den gelieferten Aggregaten nicht nachrechenbar. F4 fehlt vollständig; die 407 Rohdatensätze fehlen ebenfalls. Die ausgewählten 38 haben ihren sogenannten OOS-Zeitraum als Auswahlfilter verbraucht. Das begründet Selektionsskepsis, beweist aber nicht, dass jeder frühere Ertrag ausschließlich Auswahlrauschen war.
- **6/52 Gewinner und 12,6515 erwartete Treffer** aus Σ1/(1+CRV) sind rechnerisch korrekt. Die Erwartung setzt ein ideales gebührenfreies Null-Drift-Modell voraus; korrelierte Signale und Gebühren verhindern eine direkte Gleichsetzung mit einem belastbaren Signifikanztest oder einer kausalen Verlustzerlegung.
