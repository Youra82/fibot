# Forschungskandidat: EMA200 plus Mindest-Stopabstand

**Regel:** Long nur bei letztem abgeschlossenen Schlusskurs ueber EMA200, Short darunter. Der bereits strukturell geplante Stop muss mindestens 2 ATR14 (Wilder) vom Entry entfernt sein. Enge Setups verwerfen; den Stop nicht nachtraeglich verbreitern. Alle Merkmale muessen bei Orderaufgabe bekannt sein.

## Bekannte Live-Trades

Von 59 Konfluenz-Trades bleiben 11: vier Gewinner und sieben Verlierer; Summe der tatsaechlich gebuchten Netto-PnLs +3.0891 USDT. 48 werden verworfen, darunter drei Gewinner. Keine neu simulierte Kontorendite: Positionsgroessen und spaetere Einstiegschancen wurden nicht neu berechnet. Vier alte Test-Trades ohne zugeordneten Timeframe ausgeschlossen.

| Nr | Coin | Richtung | TF | Stop/ATR | Netto USDT |
|---:|---|---|---|---:|---:|
| 8 | TRUMP | short | 15m | 2.09 | +5.05 |
| 9 | FIL | short | 15m | 3.60 | +1.88 |
| 19 | SHIB | long | 1h | 4.21 | -1.53 |
| 24 | INJ | short | 15m | 2.26 | -0.69 |
| 28 | TRUMP | short | 15m | 2.33 | -0.89 |
| 30 | MAGIC | short | 15m | 2.37 | -1.16 |
| 33 | SHIB | short | 1h | 4.95 | +1.65 |
| 40 | FIL | short | 15m | 2.70 | -0.64 |
| 50 | FIL | short | 15m | 4.02 | +0.93 |
| 53 | FIL | short | 15m | 2.76 | -0.65 |
| 63 | NIL | short | 15m | 2.42 | -0.85 |

## Gegenpruefung

Breiter historischer Bestand mit 407 Configs, eine Position pro Coin: EMA200 + Stop >=2 ATR erzielt 2026 bis 15.10. auf Coinhaelfte A -0.079 R/Trade (2398 Trades), auf B -0.080 R/Trade (2203 Trades). Ab 15.10. -0.039 R/Trade (377 Trades). Damit kein allgemeiner Profitabilitaetsnachweis.

Nur 38 historisch ausgewaehlte Configs plus bestehender HTF-/Tagestrendfilter: ab 15.10. +0.356 R/Trade bei 13 simulierten Trades, sechs Gewinnern, neun Coins. Ohne die fuenf besten Coins -0.655 R/Trade; zu wenig unabhaengige Beobachtungen. Configs und Auswahl haben von den historischen Pruefdaten profitiert. Die historische ATR am Beginn der Entry-Kerze und die Live-ATR bei Orderaufgabe sind nicht immer identisch; historische Simulation und Live-Subset sind verschiedene Stichproben.

Die ausschlie?lich anhand alter Suchdaten ausgewaehlte Regel war VOL1 (Volumen >= 20er Mittel), nicht EMA_STOP_2. VOL1 besteht die spaeteren Pruefungen nicht. EMA_STOP_2 wird hier als diagnostischer Kandidat berichtet, nicht als unabhaengig bestaetigter Gewinner der Suche.

## Konsequenz

Kein getesteter Filter rechtfertigt hier eine profitable Live-Erwartung. Produktionscode und settings.json bleiben unveraendert. Fuer eine Verwendung braucht der Kandidat einen prospektiven Test auf allen kuenftigen Setups mit vorab fixierten Regeln und simultaner ungefilterter Referenz. Auch aussortierte Setups muessen virtuell weiterlaufen, sonst laesst sich die Trennung nicht messen. Keine nachtraegliche Wahl von Coins, ATR-Schwellen oder EMA-Perioden.

Details: ERGEBNIS.md, PROTOKOLL.md, actual38_with_trend.json sowie die beiden Live-CSV-Dateien.
