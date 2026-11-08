# Trading-Edge: Erwartung, Kosten und Wachstum gemeinsam pruefen

Ergaenzung fuer den bisherigen Fibo-Kanal-Konfluenz-Bot. Die Strategie,
Team-Auswahl, Stops, Ziele und Live-Risiken bleiben unveraendert.

## Bezug zum Video

Quelle: [The Math Every Trader Gets Wrong — Fractal Flow](https://www.youtube.com/watch?v=imzIcg530RY).
Die oeffentliche Videobeschreibung nennt Erwartungswert, Kostenverluste,
Streuung, Drawdowns und geometrisches Wachstum als Themen. Titel und
Beschreibung konnten gelesen werden; die Untertitel waren zum Zeitpunkt
dieser Ergaenzung nicht abrufbar. Dies ist keine vollstaendige Wiedergabe
oder Implementierung aller Aussagen des Videos. Die folgenden Formeln
und Rechnungen werden im Code eigenstaendig getestet.

## Neue Analyse 13

```bash
./run_analysis.sh --no-telegram
# Auswahl 13
```

Oder vom Projektverzeichnis auf Linux/VPS:

```bash
.venv/bin/python3 src/fibot/analysis/analysis_suite.py \
  --analysis 13 --scope aktiv --from 2026-05-10 --to 2026-11-08 \
  --capital 60 --no-telegram
```

Die Analyse verwendet die vorhandenen Backtests. Sie sendet mit
`--no-telegram` keine Nachrichten und setzt keine Orders. Der Datenlader
kann fehlende historische Kerzen read-only von der Boerse nachladen.
Ergebnisse stehen wie bisher unter `artifacts/analysis/`.

## Was ausgewertet wird

1. **Tatsaechliches Netto-R:** Netto-PnL des Backtest-Trades geteilt durch
   `Kontrakte * abs(Entry - SL)`. Die Kosten werden fuer diese neue Analyse
   nicht noch einmal unabhaengig vom Backtester geschaetzt. Das bleibt die
   Kostenqualitaet des vorhandenen Backtesters, keine nachtraeglich perfekte
   Funding-/Slippageabrechnung.
2. **Erwartungswert:** `p * mittlerer Nettogewinn - q * mittlerer Nettoverlust`.
   Null-Trades werden separat gezaehlt. Die Rechnung entspricht dem Mittel
   aller Netto-R, nicht dem Mindest-CRV in einer Config.
3. **Payoff und Ausgleich:** durchschnittlicher Nettogewinn geteilt durch
   durchschnittlichen Nettoverlust. Ohne Null-Trades ist die ausgleichende
   Trefferquote `1 / (1 + Payoff)`. Die Grenze bedeutet null Erwartung,
   nicht einen belastbaren Vorteil.
4. **Kostenverlust:** Unterschied zwischen mittlerem Brutto-R und Netto-R.
   Ein Bruttovorteil kann durch Kosten vollstaendig verschwinden.
5. **Geometrisches Wachstum:** `mean(log(1 + f * Netto-R))` bei konstantem
   Risikobudget `f`. Positive arithmetische Erwartung reicht bei hohem Risiko
   nicht zwingend fuer positives geometrisches Wachstum. Beispiel:
   +50% und -40% ergeben zusammen -10%, trotz positivem arithmetischem Mittel.
6. **Erholung vom Drawdown:** Nach einem Verlustanteil `d` ist
   `d / (1 - d)` Gewinn zur Erholung erforderlich: -20% brauchen +25%,
   -50% brauchen +100%.
7. **Streuung und Unsicherheit:** 28-Tage-Bloecke nach Ausstiegsdatum halten
   zeitlich benachbarte und am gleichen Tag geschlossene Trades zusammen.
   Der Bericht zeigt einen empirischen 95%-Bereich der Netto-Erwartung,
   Verlust- und Drawdownhaeufigkeiten im Blockmodell. Bei weniger als drei
   Kalenderbloecken gibt es kein Konfidenzurteil.
8. **Risikomodell:** Vergleich derselben R-Folge bei 0.25%, 0.5%, 1%, 2%
   und 5% konstantem Risiko. Das Stichprobenmaximum des log-Wachstums wird
   numerisch mit den tatsaechlichen R-Werten bestimmt. Es ist ausdruecklich
   keine Empfehlung und wird nicht in Einstellungen zurueckgeschrieben.

## Grenzen der Aussagen

- Die Wachstumsrechnung unterstellt aufeinanderfolgende Trades mit festem
  Risikobudget. Sie ist kein gemeinsamer Portfolio-Replay mit ueberlappenden
  Positionen, Marginbindung, Mindestmengen oder offenen Buchverlusten.
- Isolierte Strategieergebnisse werden nicht zu einer Kontorendite addiert.
- Empirische Resampling-Haeufigkeiten sind keine garantierten kuenftigen
  Verlust- oder Ruinwahrscheinlichkeiten. Neue Marktphasen und ausserhalb
  der Stichprobe liegende Verluste fehlen im Modell.
- Das Konfidenzintervall korrigiert nicht fuer die Auswahl vieler Configs,
  wiederholte Optimierung oder bereits mehrfach verwendete Pruefdaten.
- Ein negativer Erwartungswert wird durch einen anderen Hebel nicht positiv.
  Ein geaendertes TP/SL braucht neue vollstaendige Trades und einen neuen
  Test; die erreichte Trefferquote darf dabei nicht konstant angenommen werden.

Die neue Analyse hilft, eine behauptete Edge zu pruefen. Sie erzeugt selbst
keinen profitablen Kanal und schaltet keine Strategie automatisch frei.
