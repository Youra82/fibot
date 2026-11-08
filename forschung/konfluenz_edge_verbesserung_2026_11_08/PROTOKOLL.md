# Konfluenz verbessern: echte Auszahlungen statt Grafik verschieben

Vor dem Lauf festgelegt. Basis ist der bisherige, zurueckgesetzte
Kanal-Konfluenz-Bot mit seinen 17 aktuell aktiven Configs und bestehendem
HTF-/Tagestrendfilter. Keine fibot2-Regeln, kein neues Phasentor.

## Entwicklung und Vergleich

- Entwicklung: 01.01.2025 bis 09.05.2026, mindestens 100 geschlossene Trades
  fuer eine Kandidatenauswahl. Auswahl nach hoechstem unteren 2.5%-Quantil
  des 28-Tage-Blockbootstrap der mittleren Netto-R. Bei Gleichstand ID.
- Historischer Vergleich: 10.05.2026 bis letzter lokaler Datenstand am
  08.11.2026, Start 60 USDT. Ebenfalls erste und zweite Zeithaelfte berichten.
- Auswahl vor Auswertung des Vergleichs als JSON mit SHA256 einfrieren.
  ALLE Varianten berichten; keine nachtraegliche Neu-Auswahl im Vergleich.
- Beide Bereiche wurden bereits fuer Forschung und/oder Config-Auswahl
  verwendet: ausdruecklich KEIN unberuehrter Holdout und kein garantierter
  kuenftiger Profitabilitaetsnachweis.

## 18 vorab festgelegte Varianten

2 Einstiege x 2 Stops x 4 Ziele:
- L: bisheriger Limit-Fill; C: nach Beruehrung hoechstens vier abgeschlossene
  Kerzen auf Schluss zurueck jenseits des geplanten Limits und Kerzenkoerper
  in Handelsrichtung warten. Kein Strukturstopkontakt davor; Markt-Entry
  erst am folgenden Open. HTF-/Tagetrend am neuen Entry erneut pruefen.
- S: urspruenglicher Strukturstop; A2: Strukturstop nur nach aussen auf
  mindestens 2 Wilder-ATR14 Abstand erweitern, Groesse neu berechnen.
- K: urspruengliches Strukturziel; R15/R20/R30: 1.5/2/3 Preis-R ab dem
  jeweiligen tatsaechlichen Entry und dem jeweiligen Stop.
Die Kontrolle L_S_K ist Teil dieser 16 Kombinationen. Zusaetzlich L_S_H
und C_S_H: halbe Distanz vom Entry zum urspruenglichen Strukturziel.
Dies heisst nur bei TP an der Gegenkante geometrisch Kanalmitte.

Konfluenzdetektor und dessen Config-eigene Mindest-CRV-, Zonen- und
Impulspruefung bleiben eingefroren. Die Kandidatenfolge stammt aus dem
urspruenglichen Detektor; nach einer Beruehrung wird kein neues B fuer
eine zuvor verworfene Bestätigung erfunden. Keine neue Coin-Auswahl.

## Einheitliche Ausfuehrung

Alle Varianten inklusive Kontrolle im selben vereinfachten Kostenmodell:
6 bp je Seite auf Entry-/Exit-Notional, Markt-Entry/Stop 2 bp Schlupf,
Stop-Gap zum schlechteren Open, SL zuerst bei Intrabar-Mehrdeutigkeit,
TP fruehestens in Folgekerze. Strukturbruch vor Bestaetigung verwirft Setup.
Bestehende risk_per_entry_pct/Leverage je Config, mindestens 5 USDT Notional.
Keine historische Lot-/Tick-/Liquidationssimulation, keine Feindaten.

Je Config eine isolierte 60-USDT-Rechnung fuer Netto-R-Statistik; keine
Addition dieser Konten zu einer Portfoliorendite. Separat gemeinsamer
60-USDT-Kontoreplay, eine Position pro Coin, Marginreservierung je Position
und Konkurrenz um freie Margin. Feste Config-Auswahl, KEINE historische
woechentliche Portfoliooptimierung. MTM aus letzten bekannten abgeschlossenen
Kursen; offene Endpositionen gesondert melden und erhalten.

Veraenderte Exits veraendern Haltedauer und Positionssperren; alle Einstiege
neu durchlaufen, nicht nur die bisherigen 271 geschlossenen Trades umrechnen.
Kostenstress: +15 bp Roundtrip und 1 bp je angefangene 8h Haltedauer;
Positionsgroessen und gemeinsame Kontoentwicklung erneut rechnen.

## Bewertung

Netto-R, Trefferquote, Payoff und gemeinsame Unsicherheit vergleichen.
Ausgewaehlter Kandidat muss im historischen Vergleich gegenueber Kontrolle
positiv differieren, in beiden Zeithaelften positive Netto-Erwartung haben,
unter Kostenstress positiv sein und ein positives unteres 95%-Intervall
der Netto-Erwartung zeigen. Mindestzahl 100 geschlossene Vergleichstrades.
Kontorendite, MTM-Drawdown, offene Endpositionen und Konzentration berichten.
Auch ein Bestehen dieser historischen Kriterien bestaetigt keine unabhaengige
Edge. Bei Nichterfuellung keine Aktivierung im Live-Bot.
