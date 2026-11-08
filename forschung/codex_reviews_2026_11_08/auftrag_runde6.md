# Runde 6 — Umsetzung deiner Runde-5-Befunde (DEINE_ANTWORT_RUNDE5.md). Lokal 147/147 grün.

1. P1: Nach dem Storno wird nur bei bestätigtem Endstatus (canceled/cancelled/expired/rejected) ohne Füllung ersetzt; meldet
   die Nachabfrage `open` (Stornoantwort None oder canceled), endet der Lauf mit unverändertem Tracker.
   Regressionstest test_nach_storno_noch_offen_keine_ersatzorder (beide Fälle aus deiner Tabelle).
   Die Test-Börse in tests/test_confluence.py (_mock_exchange) verhält sich jetzt wie Bitget: eine stornierte Order meldet danach
   `canceled`; jede neue Order bekommt eine eigene ID.
2. P2: Beendete Order mit filled > 0: Positionsabfrage (strict). Position offen -> Lauf endet (nächster Lauf verwaltet sie).
   Keine Position mehr -> Impuls verbraucht, Tracker aufgelöst (kein Dauer-Pending, kein Neueinstieg in denselben Impuls).
   Positionsstatus unklar -> Tracker bleibt. Test test_beendete_teilfuellung_ohne_position_verbraucht_impuls.
Hinweis: tests/test_confluence.py liegt diesmal bei.

Bitte kritisch prüfen (Datei/Zeile). Abschlussfrage: Gibt es noch einen P1 gegen den produktiven Push heute?
Wenn nein, bitte ausdrücklich „Freigabe“ schreiben (P2/P3 gern als Folgeaufgaben). Keine Dateien ändern. Dauer am Anfang.
