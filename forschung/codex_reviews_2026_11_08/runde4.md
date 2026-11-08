**Prüfdauer: rund 2 Minuten. Keine Dateien geändert.**

**Ja, es sprechen weiterhin P1-Befunde gegen einen produktiven Push heute.** Die Änderungen beheben mehrere Fälle aus Runde 3, aber die Kapitalabstimmung und der Orderersatz bleiben fehlerhaft.

### 1. P1 – Einzahlung vor dem ersten Start wird doppelt berücksichtigt

**Datei/Zeile:** `src/trade_manager.py:453–457`; `src/risk_cap.py:180`, `:187`, `:210`.

Beim ersten Start wird die aktuelle Equity übernommen, ohne vorhandene Bills als bereits enthalten zu markieren. Der nächste Abruf beginnt durch die einstündige Überlappung **vor diesem Startpunkt**. Eine dort liegende Einzahlung wird nochmals auf den Peak addiert.

Schreibfrei mit der Originalfunktion reproduziert:

| Schritt | Equity | Peak |
|---|---:|---:|
| Start nach einer Einzahlung von 500 | 1.500 | 1.500 |
| Folgelauf importiert deren Bill | 1.500 | **2.000** |

Der Risikofaktor fällt dadurch auf **0,25**, obwohl kein Handelsverlust entstanden ist. Dafür braucht es keine verzögerte Veröffentlichung durch Bitget.

**Korrektur:** Beim Initialisieren einen eindeutigen Abgleichspunkt samt bereits enthaltenen Bill-IDs speichern. Die Überlappung darf Buchungen vor diesem Ausgangspunkt nicht erneut kapitalwirksam machen. Dasselbe Problem besteht beim Reset: `src/risk_cap.py:233` speichert keinen solchen Ausgangspunkt.

### 2. P1 – Parallele Beobachtungen können eine Auszahlung wieder aufheben

**Datei/Zeile:** `src/trade_manager.py:461–470`; `src/risk_cap.py:177`, `:193`.

Beide Kontoauszüge und die Equity werden weiterhin **außerhalb der Zustandssperre** abgefragt. Identische Bill-IDs innerhalb eines Prozesses verhindern keine überholten Schreibvorgänge:

1. Prozess A liest vor einer Auszahlung konsistent Equity 1.000 und keine Bills; anschließend wird er unterbrochen.
2. Prozess B liest nach der Auszahlung konsistent Equity 800 und Bill −200; er speichert Peak 800.
3. Prozess A läuft weiter und hebt den Peak mit seinem alten Snapshot wieder auf 1.000.

Schreibfrei reproduziert: Bei Equity 800 entsteht danach Faktor **0,333 statt 1,0**.

**Korrektur:** Die gesamte Abstimmung pro Konto serialisieren oder mit einer Zustandsversion arbeiten: Hat sich der Zustand seit Beginn der Abfragen geändert, Snapshot verwerfen und neu abfragen. Die bisherige Sperre schützt nur die Schreibtransaktion.

### 3. P1 – Erfolgreiches Storno mit Teilfüllung erlaubt volle Ersatzorder

**Datei/Zeile:** `src/trade_manager.py:998–1014`, `:1033–1038`.

Nur bei `res is None` wird nach dem Storno erneut abgeglichen. Eine erfolgreiche Stornoantwort kann jedoch bereits ausgeführte Mengen enthalten. Der Code ignoriert diese und platziert eine volle Ersatzorder.

Schreibfrei mit der Originalfunktion und simulierten Exchange-Antworten reproduziert:

```text
Orderstatus: open
Stornoantwort: {'id': 'old', 'status': 'canceled', 'filled': 2}
Ergebnis: eine neue volle Order; alter Tracker überschrieben
```

Eine Teilfüllung zwischen ursprünglicher Positionsabfrage und Storno kann damit das vorgesehene Positionsrisiko überschreiten.

**Korrektur:** Nach jedem Storno Ausführungen und Position strikt abgleichen. Bei Teilfüllung zunächst die Position verwalten und den Impuls erhalten; keine volle Ersatzorder platzieren.

### 4. P2 – Nichtleerer unbekannter Orderstatus bleibt ungeschützt

**Datei/Zeile:** `src/trade_manager.py:962`, `:1015–1016`.

Der neue Schutz greift ausschließlich bei `None`. Jeder andere unerwartete Status landet weiterhin im allgemeinen `else`, löscht die wartende Order aus dem Tracker und erlaubt einen Neueinstieg.

Mit simuliertem Status `"mystery"` reproduziert: **eine neue Order, zwei Tracker-Schreibvorgänge**. Bei `None` dagegen korrekt: keine Order, keine Tracker-Änderung.

**Korrektur:** Nur ausdrücklich bekannte endgültige Status freigeben; alle übrigen erhalten den Tracker und beenden den Lauf.

### 5. P2 – Begrenzte Bill-Liste macht wiederholte Abrufe nicht dauerhaft idempotent

**Datei/Zeile:** `src/risk_cap.py:192`, `:210`.

Es bleiben nur 500 Bill-IDs gespeichert, während die Abfrage mindestens eine Stunde überlappt. Enthält das Abruffenster mehr als 500 Kapitalbewegungen, werden entfernte IDs erneut verarbeitet.

Schreibfrei reproduziert: 501 Einzahlungen à 1 ergeben zunächst Peak 1.501; derselbe unveränderte Auszug erhöht ihn beim nächsten Abgleich auf **1.502**.

**Korrektur:** Deduplizierungsdaten anhand des tatsächlich benötigten Zeitfensters aufbewahren, statt unabhängig davon auf 500 IDs zu kürzen.

### 6. P2 – Kapitalbewegungen mit Nettosumme null bleiben im Bericht unsichtbar

**Datei/Zeile:** `src/daily_live_vs_backtest_check.py:239`, `:565–568`.

`_window_flows()` liefert nur die Nettosumme. Einzahlung +500 und spätere Auszahlung −500 ergeben null; deshalb erscheint kein Hinweis. Zwischenzeitlich hätte der Simulator aber anderes Kapital und andere Positionsgrößen verwenden müssen.

**Korrektur:** Zusätzlich das Vorhandensein einzelner Kapitalbewegungen zurückgeben und daran den Näherungshinweis knüpfen.

### Bestätigte Korrekturen und Prüfgrenzen

- `None` als Orderstatus beendet den Lauf unverändert.
- `tracker_after_close()` erhält bisherige und aktuelle Impulse; Overshoot und Housekeeper verwenden die Funktion.
- `peak_at()` ignoriert Kapitalbewegungsereignisse und wählt den größten passenden Beobachtungszeitstempel.
- Cap, ungültige Risikowerte, Drawdown-Faktor und Tracker-Erhalt bestanden schreibfreie Funktionsprüfungen.
- Alle fünf Quelldateien bestehen die Syntaxprüfung.

**139/139 konnte ich nicht bestätigen:** Die Testsammlung scheitert im gelieferten Auszug an `ModuleNotFoundError: fibot`. Außerdem ruft der Test namens „Notschließung … im echten Ablauf“ die Hilfsfunktion direkt auf (`tests/test_risk_dynamik2.py:150`); den tatsächlichen Overshoot-Pfad führt er nicht aus.

### Zur ausdrücklich genannten Bitget-Annahme

Zwei identische Kontoauszüge sind ein nützlicher Konsistenzcheck, aber kein Nachweis einer atomaren Zuordnung zur Equity. Die eingeräumte Verzögerung bleibt damit grundsätzlich möglich.

Praktikabel wären ein einzelner Konto-Beobachter beziehungsweise eine serialisierte Abstimmung, ein sauberer Initialisierungspunkt und gespeicherte Beobachtungen für nachträgliche Korrekturen bei verspäteten Bills. Ohne eine verlässliche zeitliche Zuordnung von Buchung und Kontostandsänderung bleibt diese Zuordnung eine Annahme. **Die P1-Befunde oben bestehen bereits unabhängig davon und sollten vor dem produktiven Push behoben werden.**