# Runde 3 — Claudes Umsetzung deiner Runde-2-Befunde (Antwort liegt als DEINE_ANTWORT_RUNDE2.md bei)

Der User will heute ALLES fertig: feste 1-%-Obergrenze UND die dynamische Kontoverlauf-Anpassung. Diff: alle_aenderungen.diff;
vollständige Dateien unter src/ und tests/. Lokal: gesamte Suite 131/131 grün (ohne verworfene fibot2/wick-Paritätsläufe);
dabei werden keine echten Kontoverlauf-Dateien angelegt (tests/conftest.py isoliert PEAK_FILE und HISTORY_FILE).

| Dein Punkt | Umsetzung | Test (tests/) |
|---|---|---|
| 1 Höchststand sinkt bei Parallelität | `risk_cap._locked` (fcntl auf Linux/VPS, msvcrt auf Windows) um Lesen-Vergleichen-Schreiben in `observe_equity`, `flow_check_due`, `reset_peak` | test_risk_dynamik: 6 echte Prozesse × 20 Aufrufe, Endstand = Maximum |
| 2 freies Guthaben statt Equity (klassisch) | klassisch: `fetch_equity_usdt` für Risikobetrag und Faktor, freies Guthaben nur für die Margin (`calc_position_size(free_balance=)`) | test_klassisch_margin_gegen_freies_guthaben |
| 3 Ein-/Auszahlungen | `Exchange.fetch_cash_flows` (Bill-API, Muster aus cockpit/ltbbot: trans_*/deposit/withdraw), `observe_equity(flows=)`: Höchststand += Betrag, Bills dedupliziert, protokolliert; `reset_peak` gesperrt + protokolliert, CLI `python -m fibot.utils.risk_cap reset --kontostand X --grund "..."` | Ein-/Auszahlung, Doppelmeldung, observe_account |
| 4 künstlicher DD bei Kerzenrastern | Simulator bewertet offene Positionen mit letztem bekannten Kurs (`last_px`, `_marked_total`) | test_simulator_kein_kuenstlicher_drawdown_bei_unterschiedlichen_rastern |
| 5 Kapitalbasis Live ≠ Simulator | Simulator: Risikobetrag UND Faktor aus `_marked_total()` (realisiert + offen zum letzten Kurs), `dyn_peak` vorher aktualisiert. Reihenfolge A (Ausstiege) vor B (Einstiege) je Kerze bleibt eine dokumentierte Kerzen-Näherung. | test_simulator_rechnet_kontoverlauf_wie_live |
| 6 zukünftiger Höchststand im Tagesbericht | Live schreibt jede Beobachtung mit Zeitstempel nach artifacts/db/equity_history.jsonl; Bericht nimmt `peak_at(Fensterbeginn)`; fehlt er -> Hinweis „Näherung“ in der Telegram-Nachricht. Ältere Positionen bleiben Symbolsperren (im Hinweis-Kommentar dokumentiert). | test_reset_protokolliert_und_peak_at |
| 7 Storno-Fehler -> zweite Order | Storno-Exception -> return ohne Ersatzorder, Tracker bleibt; Storno liefert None -> Status abfragen, nur bei canceled/expired/rejected weiter; Budget nicht prüfbar -> Budget 0 -> Order wird storniert | test_storno_fehler_erzeugt_keine_zweite_order |
| 8 Höchststand nur bei Einstiegen | `observe_account` am Anfang JEDES `full_trade_cycle` (alle Strategieprozesse, 15-Min-Takt), auch bei offenen Positionen; Abruf des Kontoauszugs gedrosselt (10 Min) | test_observe_account_rechnet_kapitalbewegung_ein |
| 9 beschädigter Zustand | `_read_state`: fehlend = Erstinitialisierung; kaputtes JSON/NaN/negativ/kein Objekt -> ValueError (keine stille Rücksetzung); Reset darf beschädigte Datei bewusst überschreiben | test_beschaedigter_hoechststand_scheitert_sichtbar (5 Fälle) |
| 10 klassische Rundung | nach Rundung: Menge > vorher -> kein Trade | — (Code: trade_manager klassischer Pfad) |
| cap=0 | `capped_risk_pct(cap=0)` = keine Obergrenze, wie in settings.json | test_cap_null_... |
| start_peak im Ergebnis | Simulator-Ergebnis enthält `start_peak` | — |
| Protokoll klassisch / Kommentare | Config/Obergrenze/nach Obergrenze + Kontoverlauf-Zeile; Kommentare „tatsächlich gehandelt“ entschärft | — |

**Zusätzlich gefunden und behoben (bitte mitprüfen):** Wurde eine Konfluenzorder gefüllt und die Position zwischen zwei Läufen wieder
geschlossen, legte `confluence_cycle` für DENSELBEN Impuls sofort eine neue Order (alter Doppel-Einstieg-Bug, live z. B. PYTH 4× in 45 Min.).
Jetzt: `consumed_b` im Tracker (letzte 30 Impulse), gefüllte Impulse (Fill+Exit zwischen Läufen und normal geschlossene Position) werden
nie wieder gehandelt.

Bitte prüfe kritisch und widersprich klar (Datei/Zeile). Insbesondere:
- Ist die Sperre auf Linux (fcntl) und Windows korrekt, auch bei Abbruch eines Prozesses? Deadlock-Risiko bei gleichzeitiger Historie-Kürzung?
- `fetch_cash_flows`: Vorzeichen von `amount` bei Bitget-Bills (Auszahlung negativ?) — ich habe das Cockpit-Muster übernommen.
- Erster Live-Lauf: Höchststand = aktueller Kontostand (keine Rückwirkung). Sinnvoll?
- Gibt es noch einen Punkt, der einen Push heute verhindern sollte?
Keine Dateien ändern. Antwort auf Deutsch, strukturiert, mit Datei/Zeile. Nenne am Anfang die Dauer deiner Prüfung.
