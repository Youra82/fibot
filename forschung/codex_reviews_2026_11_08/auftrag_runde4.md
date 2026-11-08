# Runde 4 — Umsetzung deiner Runde-3-Befunde (DEINE_ANTWORT_RUNDE3.md)

Lokal: gesamte Suite 139/139 grün; keine echten Kontoverlauf-Dateien angelegt.

1. P1 unbekannter Orderstatus: `confluence_cycle` — `status is None` -> Lauf endet, Tracker unverändert, kein Storno, keine Order.
   Test: test_risk_dynamik2.test_unbekannter_orderstatus_keine_zweite_order.
2. P1 verzögerte Einzahlung doppelt: `trade_manager.observe_account`: Kontoauszug -> Kontostand -> Kontoauszug; nur bei identischen
   Bill-IDs wird fortgeschrieben, sonst nichts (nächster Lauf). API-Fehler -> nichts. Keine Drosselung mehr; Abfrage ab letzter
   vollständiger Abstimmung minus 1 h (`risk_cap.flows_since`), Duplikate per Bill-ID. `live_risk_pct` schreibt NICHT mehr
   (nur `current_peak` lesen; über dem Hoch Faktor 1 ohne Fortschreibung). Bewusste Annahme/Grenze: Bitget bucht den Bill
   zusammen mit der Kontostandsänderung; ein Bill, der deutlich NACH der Kontostandsänderung erscheint, kann weiterhin zu hoch
   zählen — siehst du einen praktikablen besseren Weg?
   Tests: test_observe_account_verwirft_unpassende_auszuege (dein 1000/1500/2000-Fall -> 1500), _api_fehler_aendert_nichts,
   _erster_lauf_und_auszahlung, test_live_risk_pct_liest_nur.
3. P1 Notschließung leert Tracker: `tracker_after_close` (consumed_b + aktueller b_ts bleiben) in Overshoot-Notschließung
   und Housekeeper. Test: test_notschliessung_behaelt_impulssperre_im_echten_ablauf, test_tracker_after_close_....
4. P2 Historie: Kapitalbewegungen protokollieren `ms` = Beobachtungszeit, `buchung_ms` separat; `peak_at` nutzt nur
   start/beobachtung/reset und den größten Zeitstempel <= ts. Test: test_peak_at_kausal_und_nach_zeitstempel.
5. P2 Tagesbericht: `_window_flows` (gleiche Erkennung wie live) zieht Netto-Kapitalbewegungen im Fenster vom rekonstruierten
   Startkapital ab; sichtbare Hinweise in der Telegram-Nachricht für Kapitalbewegungen und ältere Positionen (Symbolsperre).
Vorzeichen: `fetch_cash_flows` bestimmt die Richtung aus dem Buchungstyp (trans_from_/deposit/transfer_in = rein,
trans_to_/withdraw/transfer_out = raus, Betrag absolut); nur unbekannte trans_-Typen nutzen das gemeldete Vorzeichen.
Test: test_bill_vorzeichen_aus_buchungstyp.

Bitte prüfe kritisch (Datei/Zeile), widersprich klar. Abschlussfrage: Spricht noch ein P1 gegen einen Push heute?
Keine Dateien ändern. Nenne am Anfang die Dauer deiner Prüfung.
