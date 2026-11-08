# Runde 5 — Umsetzung deiner Runde-4-Befunde (DEINE_ANTWORT_RUNDE4.md). Lokal 144/144 grün.

1. P1 Einzahlung vor Start: Zustand speichert `baseline_ms` (Start/Reset); Bills mit Buchungszeit <= baseline_ms zählen nie.
   Test test_einzahlung_vor_dem_start_zaehlt_nie.
2. P1 veralteter Snapshot: Zustand hat `version`; `observe_account` liest die Version VOR den API-Abfragen und
   `observe_equity(..., expected_version=)` verwirft unter der Sperre, wenn sich der Zustand geändert hat.
   Test test_veralteter_snapshot_wird_verworfen (dein A/B-Fall: Peak bleibt 800).
3. P1 Teilfüllung beim Storno: nach JEDEM Storno `fetch_order`; Füllmenge aus Stornoantwort oder Abfrage > 0 -> keine Ersatzorder.
   Auch beendete Order (canceled/expired/rejected) mit filled > 0 -> keine Freigabe. Test test_keine_volle_ersatzorder[teilfuellung].
4. P2 unbekannter Status: nur open/closed/canceled/cancelled/expired/rejected bekannt, alles andere -> Lauf endet, Tracker bleibt.
   Test test_keine_volle_ersatzorder[unbekannter_status].
5. P2 Bill-IDs: Dict ID->Buchungszeit, gekürzt nach Zeit (Abfrageüberlappung 1 h + 5 h Reserve), nicht nach Anzahl.
   Test test_bill_ids_nach_zeit_nicht_nach_anzahl (501 Bills, zweiter Abgleich bleibt 1501).
6. P2 Netto-Null-Bewegungen: Bericht nennt Anzahl, auch bei Nettosumme 0.
Zur Notschließung: der Test nutzt den Tracker-Zustand nach `tracker_after_close` im echten `confluence_cycle`-Ablauf; der
Overshoot-Pfad selbst ruft ausschließlich `write_tracker(tracker_path, tracker_after_close(read_tracker(tracker_path)))` auf.

Bitte kritisch prüfen (Datei/Zeile). Abschlussfrage: Gibt es noch einen P1 gegen den produktiven Push heute?
Wenn nein, bitte ausdrücklich „Freigabe“ schreiben. Keine Dateien ändern. Dauer am Anfang nennen.
