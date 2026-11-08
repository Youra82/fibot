**Prüfdauer: rund 6 Minuten. Keine Dateien geändert.**

**Ja, es besteht weiterhin ein P1 gegen den produktiven Push heute. Keine Freigabe.**

### 1. P1 – Weiterhin offene Order erlaubt volle Ersatzorder

**Datei/Zeile:** `src/trade_manager.py:1023–1027`, `:1051`

Nach dem Storno akzeptiert die Nachabfrage ausdrücklich auch `status == 'open'`. Bei `filled == 0` wird daraufhin der alte Tracker entfernt und eine volle Ersatzorder platziert. Eine weiterhin offene Order kann anschließend zusätzlich gefüllt werden; damit kann das vorgesehene Positionsrisiko überschritten werden.

Schreibfrei mit der Originalfunktion `confluence_cycle()` und simulierten Exchange-Antworten reproduziert:

| Stornoantwort | Nachabfrage alte Order | Ergebnis |
|---|---|---|
| `None` | `open`, `filled=0` | Eine Ersatzorder; Tracker zeigt anschließend nur die neue Order |
| `canceled`, `filled=0` | `open`, `filled=0` | Dasselbe Ergebnis |

`None` ist ein tatsächlich möglicher Rückgabewert des Exchange-Wrappers (`src/exchange.py:300–302`).

**Erforderliche Korrektur:** Solange die Nachabfrage `open` meldet, Tracker erhalten und Lauf beenden. Ersatz erst nach bestätigtem endgültigem Status ohne Ausführung erlauben. Diesen Fall zusätzlich als Regressionstest aufnehmen.

### 2. P2 – Beendete Teilfüllung kann den Einstieg dauerhaft blockieren

**Datei/Zeile:** `src/trade_manager.py:971–973`

Eine bereits beendete Order mit `filled > 0` beendet jeden weiteren Lauf unverändert. Ist die zugehörige Position zwischen zwei Läufen bereits wieder geschlossen worden, bleibt der Tracker dauerhaft auf `pending_entry`: Es gibt keine Position mehr zu verwalten und keinen Übergang zum verbrauchten Impuls.

**Erforderliche Korrektur:** Nach verlässlichem Positionsabgleich auch diesen Abschluss behandeln und den Impuls erhalten. Die unmittelbare Sperre gegen eine volle Ersatzorder ist richtig.

### Bestätigte Korrekturen

Die gezielten schreibfreien Funktionsprüfungen bestanden; Zustandsdateien und Historie wurden dabei durch Speicherobjekte ersetzt:

| Korrektur | Datei/Zeile | Ergebnis |
|---|---|---|
| Buchungen vor Start/Reset ignorieren | `src/risk_cap.py:195`, `:200`, `:252` | Bestätigt |
| Veralteten Snapshot verwerfen | `src/trade_manager.py:453`, `:472`; `src/risk_cap.py:191` | Peak bleibt im A/B-Fall 800 |
| Teilfüllung aus Stornoantwort oder Nachabfrage berücksichtigen | `src/trade_manager.py:1014–1022` | Keine Ersatzorder; Tracker bleibt |
| Unbekannten Status sperren | `src/trade_manager.py:967–970` | Bestätigt |
| Bill-IDs nach Zeit aufbewahren | `src/risk_cap.py:208–210` | 501 Bills wiederholt: Peak bleibt 1.501 |
| Netto-Null-Bewegungen nennen | `src/daily_live_vs_backtest_check.py:239–242` | Zwei Bewegungen bei Nettosumme null sichtbar |

### Notschließung und Prüfgrenzen

- **Impulserhalt bestätigt:** `src/trade_manager.py:681` verwendet `tracker_after_close()`; die Hilfsfunktion erhält bisherige und aktuelle Impulse (`:166–172`).
- **Testumfang korrekt eingeordnet:** `tests/test_risk_dynamik2.py:150–152` prüft den Folgelauf nach künstlich hergestelltem Schließzustand. Der tatsächliche Overshoot-Pfad wird dabei nicht ausgeführt.
- **144/144 nicht unabhängig bestätigt:** Die Testsammlung scheitert im gelieferten Auszug an `ModuleNotFoundError: fibot`; außerdem fehlt das referenzierte `test_confluence` (`tests/test_risk_dynamik2.py:131`, `:183`).
- Alle fünf Quelldateien bestehen die schreibfreie Syntaxprüfung.