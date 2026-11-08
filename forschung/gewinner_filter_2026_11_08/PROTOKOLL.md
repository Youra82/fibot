# Einfache Gewinnerfilter, festgelegt vor historischem Lauf

Anlass: sieben bekannte Live-Gewinner; EMA200-Ausrichtung und breitere Stops
fallen auf, trennen aber bisher nicht profitabel. Keine perfekte Trennung suchen.

Historische 58.957 Konfluenzereignisse aller 407 bestehenden Configs.
Configs sind historisch optimiert; Daten mehrfach untersucht. Daher explorativ,
keine frische Out-of-Sample-Evidenz, keine automatische Live-Aktivierung.
38 ausgewaehlte Configs separat berichten, Auswahl selbst hat Pruefdaten genutzt.

Merkmale aus Kerzen, die vor dem Beginn der Entry-Kerze abgeschlossen waren:
EMA200-Seite, EMA200-Steigung ueber 10 Kerzen, Stop/ATR14 (Wilder),
RSI14, ADX14, Volumen/20. Stop und TP aus Ereignis bekannt. Keine Merkmale
der Fill-Kerze, MFE, Haltedauer oder spaeteren Marktreaktion als Filter.
Mindestens 200 bekannte Kerzen und keine ungueltigen Preisrisiken.

Feste Liste im Skript: EMA200, EMA200 plus Steigung; Stop/ATR >= 1/1.5/2/2.5;
EMA200 plus diese Stops; CRV <= 2/3/5; EMA200 plus CRV <= 3/5;
EMA200 + Stop/ATR >= 1.5/2 + CRV <= 3;
Volumen >= 1, ADX >= 25, RSI in mittlerem Bereich 40..60;
EMA200 + Stop/ATR >= 1.5 + Volumen >= 1. Keine nachtraeglichen Schwellen.

Auswahl: deterministischer Coin-Split Seed 20261108. Nur Coinhaelfte A
vor 2026, Trades abgeschlossen vor 2026. Mindestens 200 Trades.
Rang nach mittlerer Netto-R, genau einen besten Kandidaten einfrieren.
Diagnostische Pruefung: Coinhaelfte B vor 2026; A und B 2026 bis 15.10.;
ab 15.10. separat, bereits bekannt. An Grenzen offene Positionen nicht
als abgeschlossene Trainings-/Pruefergebnisse werten und Positionssperre
dennoch uebertragen. Eine Position je Coin, alle Timeframes zusammen.
Deterministische Reihenfolge Zeit, Coin, Config. Ohne Kapital-/Marginlimit,
keine behauptete Kontorendite. Entry-Ereignisfolge aus altem Detektor fix.

R im Quelldatensatz enthaelt 0.12% Roundtripgebuehren. Zusaetzlich 2 bp
Stop-Schlupf bei Verlusten. Stress: 15 bp extra plus 1 bp pro angefangene
8h Haltedauer. Keine historische Funding-/Intrabarrekonstruktion.
7-Tage-zensierte Datengrenzen nicht erforderlich: offene Positionen fehlen
im Quellexport; diesen Survivorship offener Trades explizit nennen.

Kriterien fuer belastbaren Forschungskandidaten: positive Netto-R in allen
drei laengeren Pruefsegmenten, mindestens 50 Trades je Segment, positive
Stress-Erwartung, positiv ohne beste fuenf Coins. 28-Tage-Blockbootstrap
95%-Intervall der taeglichen R-Summen auf vereinigten Pruefdaten > 0.
Kein Live-Einbau allein auf Basis dieser mehrfach verwendeten Historie.
