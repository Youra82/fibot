# FiBot: Backpropagation als Config-Selektor

Stand: 18.11.2026. Dieses Modul ist Forschung und wird **nicht live geladen**.

## Idee

Ausgangspunkt waren die beiden verlinkten Lektionen
[What is backpropagation really doing?](https://www.3blue1brown.com/lessons/backpropagation/)
und [Backpropagation calculus](https://www.3blue1brown.com/lessons/backpropagation-calculus/).
Sie wurden nicht als Ersatz fuer die
FiBot-Kernstrategie verwendet. Kanal-, Fibonacci-, Stop- und Orderlogik bleiben
unveraendert. Ein kleines Ensemble bewertet nur die bereits gueltigen Signale der
20 Risk-Policy-v2-Varianten anhand von 43 kausalen Markt-, Signal- und
Config-Merkmalen. Trainiert wurde mit PyTorch/CUDA auf der RTX 3060 Ti.

Merkmale einer Kerze werden um genau eine abgeschlossene Kerze verschoben. Labels,
deren Trade eine Train-/Validierungsgrenze ueberschreitet, werden verworfen.

## Zeitliche Trennung

- Training: bis 01.11.2025
- Schwellenwahl/Validierung: 02.11.2025 bis 30.04.2026
- ungesehener Test: 01.05.2026 bis 17.11.2026
- zusaetzlich vier rollende Vorabfenster von Mai 2024 bis Mai 2026

Innerhalb jedes einzelnen Laufs wurde der Mai-November-Test erst nach Training,
Schwellenwahl und Entscheidung des Walk-forward-Gates ausgewertet. Da danach
mehrere Architekturen anhand dieses Resultats miteinander verglichen wurden, ist
dieser Zeitraum fuer eine weitere Modellauswahl nicht mehr als voellig
unberuehrt zu bezeichnen. Er bleibt frei von technischem Trainings-Leakage, ist
aber kein Ersatz fuer neue Forward-Daten.

## Ergebnis des robusteren linearen Modells

| Gruppe | Feste v01 | Neural | Gate-Entscheidung | Ergebnis des Gates |
|---|---:|---:|---|---:|
| APT 1h | +26,35 % | +10,49 % | Neural (Fehlentscheidung) | +10,49 % |
| APT 30m | +24,48 % | +12,54 % | Fest | +24,48 % |
| BAT 1h | +1,50 % | +3,59 % | Neural | +3,59 % |
| DOT 2h | +5,81 % | -1,01 % | Fest | +5,81 % |

BAT verbessert sich leicht, bei zugleich hoeherem Drawdown (10,04 % statt
7,94 %). APT 1h zeigt, dass selbst drei positive Vorabfenster keine stabile
Auswahl im spaeteren Markt garantieren. Auch nichtlineare MLP-Varianten wurden
getestet; sie aenderten diese grundsaetzliche Aussage nicht.

## Entscheidung

Keine automatische Aktivierung im Live-Bot. Die Stichprobe pro Gruppe ist mit
44 bis 140 OOS-Kandidaten klein, und der Router verbessert nicht alle Gruppen
robust. Die bestehenden Risk-Policy-v2-Configs und die harte Stop-Sicherung
bleiben der sichere Stand. Eine spaetere Aktivierung braucht weitere echte
Forward-Daten und eine vorab festgelegte Freigaberegel.

Reproduzierbarer Lauf:

```powershell
$env:PYTHONPATH='src'
forschung/gpu_benchmark_2026_11_15/.venv/Scripts/python.exe `
  neural_selector_experiment.py --objective win --architecture linear `
  --output artifacts/optimization/neural_selector_linear_20261118
```
