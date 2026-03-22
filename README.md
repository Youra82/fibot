# fibot — Fibonacci Structure Trading Bot

Ein technischer Trading-Bot, der klassische Chart-Analyse automatisiert:
Fibonacci-Retracements, Strukturerkennung (Wedge, Triangle, Channel) und RSI/Volumen-Bestätigung.
Kein maschinelles Lernen — reine Preisstruktur-Logik, so wie ein Trader es von Hand einzeichnen würde.

> **Disclaimer:** Diese Software ist experimentell und dient ausschließlich Forschungszwecken.
> Der Handel mit Kryptowährungen birgt erhebliche finanzielle Risiken. Nutzung auf eigene Gefahr.

---

## Grundidee

Der Bot repliziert das, was ein erfahrener Techniker im Chart einzeichnet:

```
Schritt 1: Dominante Swing-Punkte finden
   ┌─────────────────────────────────────────┐
   │   Swing High (100%)                     │
   │       ╲                                 │
   │        ╲  ← Preisfall (Down-Move)       │
   │         ╲                               │
   │          ╲ 61.8% ← Entry-Zone           │
   │           ╲ 50.0%                       │
   │            ╲ 38.2% ← Entry-Zone         │
   │             ╲                           │
   │   Swing Low (0%)  ← Support             │
   └─────────────────────────────────────────┘

Schritt 2: Fibonacci-Retracement einzeichnen
   0%    = Swing Low   (aktuelles Tief)
   38.2% = erste Entry-Zone
   50.0% = mittlere Entry-Zone
   61.8% = letzte Entry-Zone vor SL
   78.6% = Stop-Loss-Niveau
   100%  = Swing High  (Take-Profit 1)
   127.2% / 161.8% = Extensions (aggressives TP)

Schritt 3: Marktstruktur einzeichnen
   Wedge ↘ / Triangle / Channel → ergibt den Bias

Schritt 4: Confluence prüfen
   Preis nahe Fib-Zone + RSI bestätigt + Volumen + Struktur-Support
   → LONG oder SHORT
```

**Beispiel: BTC/USDT 4H**

```
Swing High: 87.800  (100%)
Swing Low:  80.600  (0%)

Retracement-Levels:
  38.2%  →  83.551  ← Entry-Zone Anfang
  50.0%  →  84.200  ← Entry-Zone Mitte
  61.8%  →  85.050  ← Entry-Zone Ende
  78.6%  →  86.457  ← Stop-Loss
 161.8%  →  92.443  ← Take-Profit (goldene Extension)
```

Der Bot erkennt genau diese Strukturen und handelt sie automatisch — auf Bitget Futures.

---

## Architektur

```
fibot/
├── master_runner.py                   # Cronjob-Orchestrator für Live-Trading
├── auto_optimizer_scheduler.py        # Auto-Optimierung im Hintergrund (Scheduler)
├── show_results.sh                    # Interaktives Analyse-Menü (4 Modi)
├── run_pipeline.sh                    # Optuna-Optimierung für neue Configs
├── push_configs.sh                    # Optimierte Configs ins Repo pushen
├── install.sh                         # Erstinstallation auf VPS
├── update.sh                          # Git-Update (sichert secret.json)
├── cron_setup.sh                      # Cron-Job einrichten
├── settings.json                      # Aktive Strategien + Auto-Optimizer-Einstellungen
├── secret.json                        # API-Keys (nicht in Git)
│
└── src/fibot/
    ├── strategy/
    │   ├── fibonacci_logic.py         # KERN: Swing, Fib, Struktur, Signal
    │   ├── run.py                     # Entry Point für eine Strategie
    │   └── configs/
    │       └── config_BTCUSDTUSDT_4h_fib.json   # Parameter pro Symbol
    │
    ├── analysis/
    │   ├── backtester.py              # Walk-Forward Backtest (vektorisiert, O(N log N))
    │   ├── optimizer.py               # Optuna-Optimierung: findet beste Parameter
    │   ├── portfolio_simulator.py     # Chronologische Multi-Strategie-Simulation
    │   ├── interactive_chart.py       # Interaktive Plotly-Charts (Mode 4)
    │   └── show_results.py            # Portfolio-Analyse & Backtest-Anzeige
    │
    └── utils/
        ├── exchange.py                # Bitget CCXT Wrapper
        ├── trade_manager.py           # Entry / TP / SL / Tracker
        └── telegram.py                # Telegram-Benachrichtigungen
```

---

## Strategie im Detail

### Phase 1 — Swing-Erkennung

```
ZigZag-Pivot-Algorithmus (pivot_left=5, pivot_right=5):
  → Ein Hoch gilt als Pivot, wenn es das höchste der
    umliegenden 5 Kerzen links und 5 Kerzen rechts ist.
  → Gleich für Tiefs.

Aus allen Pivots in den letzten 100 Kerzen:
  → Dominanter Swing High = das höchste Pivot-Hoch
  → Dominanter Swing Low  = das niedrigste Pivot-Tief
  → Richtung: welcher Punkt kam zuletzt?
      "down" → Preis fiel (→ LONG-Setup)
      "up"   → Preis stieg (→ SHORT-Setup)
```

> Mindestbewegung: 1% zwischen High und Low, sonst kein Signal.

---

### Phase 2 — Fibonacci-Grid

```
Für LONG-Setup (Preis ist gefallen, sucht Unterstützung):
  0%    = Swing Low              ← aktuelles Tief
  23.6% = Low + 23.6% × (H-L)   ← erstes Fibonacci-Niveau
  38.2% = Low + 38.2% × (H-L)   ← Entry-Zone Anfang
  50.0% = Low + 50.0% × (H-L)   ← Entry-Zone Mitte
  61.8% = Low + 61.8% × (H-L)   ← Entry-Zone Ende
  78.6% = Low + 78.6% × (H-L)   ← Stop-Loss-Niveau
 100.0% = Swing High             ← Swing-Rückkehr
 127.2% = Low + 127.2% × (H-L)  ← Extension TP
 161.8% = Low + 161.8% × (H-L)  ← goldene Extension TP (Optimizer-Standard)

Für SHORT-Setup (Preis ist gestiegen, sucht Widerstand):
  → Spiegelverkehrt: gemessen vom Swing High nach unten
```

---

### Phase 3 — Strukturerkennung + Toleranzzone

Der Bot legt automatisch Trendlinien durch die Pivot-Hochs und Pivot-Tiefs
(lineare Regression) und klassifiziert das Ergebnis.

**Wichtig:** Eine Trendlinie ist keine exakte Linie — Preise testen sie immer
mit etwas Abstand. Deshalb berechnet der Bot eine **ATR-basierte Toleranzzone**
um jede Trendlinie:

```
Toleranzzone = Trendlinie ± (structure_tolerance_atr_mult × ATR)

Beispiel (BTC/USDT 4H, ATR = 800 USDT, Mult = 0.3):

  Trendlinie (Support) = 83.200
  Toleranz             = 0.3 × 800 = 240 USDT

  Support-Zone:  82.960 ──────── 83.200 ──────── 83.440
                 (Untergrenze)  (Linie)  (Obergrenze)

  → Preis zwischen 82.960 und 83.440 = "testet die Unterstützung" → Confluence-Bonus
  → Preis unter 82.960               = echter Breakdown (kein False-Breakout)
  → Preis über 83.440                = oberhalb der Struktur (kein Support-Kontakt)
```

| Strukturtyp | Beschreibung | Bias |
|---|---|---|
| `wedge_down` | Absteigende Keile (beide Linien fallen, konvergieren) | Bullisch |
| `wedge_up` | Aufsteigende Keile (beide Linien steigen, konvergieren) | Bärisch |
| `triangle` | Symmetrisches Dreieck (Linien konvergieren gegenläufig) | Neutral |
| `channel_down` | Absteigender Kanal (parallele fallende Linien) | Bärisch |
| `channel_up` | Aufsteigender Kanal (parallele steigende Linien) | Bullisch |

---

### Phase 4 — Signal & Confluence

Ein LONG-Signal entsteht, wenn **alle** Bedingungen erfüllt sind:

```
1. Swing-Richtung = "down"  (Preis ist zuvor gefallen)
2. Preis liegt in der Entry-Zone [38.2% – 61.8%]
3. RSI < rsi_oversold (45)  → überverkaufte Zone
4. Volumen ≥ vol_ratio_min × 20-Perioden-MA
5. Struktur-Bias = "bullish" oder "neutral"
6. Optional: Preis nahe Struktur-Support → +1.5 Bonus-Score
7. Optional: Breakout nach oben → +2.0 Bonus-Score

R:R ≥ min_rr (1.5) → sonst kein Signal

Gesamt-Score (0–10):
  ≥ min_signal_score (4.0) → Signal wird gehandelt
  < min_signal_score       → Signal wird ignoriert
```

Ein SHORT-Signal läuft analog: Swing-Richtung "up", RSI > 55, Struktur bärisch.

---

### Phase 5 — Entry, SL und TP

```
Entry:   Limit-Order leicht unterhalb (Long) / oberhalb (Short)
         des aktuellen Preises (0.05% Delta → sauberer Fill)

SL:      max(ATR × 1.5, Fibonacci 78.6%)
         → der engere Wert wird genommen (SL so nah wie möglich)

TP:      Fibonacci 161.8% (goldene Extension — Standard nach Optimierung)
         konfigurierbar: 100% / 127.2% / 161.8% via fib_tp1_level

Alle TP/SL werden als Trigger-Market-Orders direkt nach Fill platziert.
Gehen TP/SL verloren (VPS-Neustart), werden sie beim nächsten Cycle
automatisch aus dem Tracker wiederhergestellt.
```

> **Warum 161.8% als TP?** Low Win-Rate (~16–18%) kombiniert mit hohem R:R (~1:14)
> liefert einen besseren Expected Value als High Win-Rate + niedriges R:R.
> Beispiel: 18% WR × 14 R:R − 82% × 1 = +1.70 vs. 55% WR × 2 − 45% = +0.65

---

### Beispiel-Signal (Telegram-Ausgabe)

```
FiBot Signal — BTC/USDT:USDT (4h)
Richtung : LONG
Entry    : 83.420,00  (38.2–61.8 Retracement)
SL       : 81.950,00  (-1.76%)
TP1      : 92.443,00  (+10.82%) [Fib 161.8%]
R:R      : 1:6.15
Score    : 7.0/10
Struktur : wedge_down (bullish)
Swing    : H=87.800 / L=80.600
Grund    : LONG | RSI überverkauft (41.2) | Volumen 1.43x
           | Struktur: wedge_down (bullish)
           | Preis nahe Struktur-Support (83.200) | R:R 6.15
```

---

## Fibonacci-Levels Referenz

| Level | Ratio | Rolle im System |
|---|---|---|
| 0% | 0.000 | Swing-Extrem (Ausgangspunkt) |
| 23.6% | 0.236 | Erstes Retracement (schwaches Level) |
| **38.2%** | **0.382** | **Entry-Zone Anfang** |
| **50.0%** | **0.500** | **Entry-Zone Mitte (stärkstes Level)** |
| **61.8%** | **0.618** | **Entry-Zone Ende (letzter Einstieg)** |
| 78.6% | 0.786 | Stop-Loss-Niveau |
| 100% | 1.000 | Swing-Rückkehr |
| 127.2% | 1.272 | Extension TP |
| **161.8%** | **1.618** | **goldene Extension TP (Optimizer-Standard)** |

---

## Konfiguration

### `settings.json` — Aktive Strategien & Auto-Optimizer

```json
{
  "live_trading_settings": {
    "active_strategies": [
      {
        "symbol": "BTC/USDT:USDT",
        "timeframe": "4h",
        "leverage": 3,
        "margin_mode": "isolated",
        "risk_per_entry_pct": 0.5,
        "active": true
      }
    ]
  },
  "optimization_settings": {
    "enabled": false,
    "schedule": {
      "day_of_week": 6,
      "hour": 3,
      "minute": 0,
      "interval": {
        "value": 7,
        "unit": "days"
      }
    },
    "start_capital": 1000,
    "max_drawdown_pct": 30,
    "min_win_rate_pct": 0,
    "lookback_days": 365,
    "send_telegram_on_completion": true
  }
}
```

| Feld | Standard | Erklärung |
|---|---|---|
| `enabled` | `false` | Auto-Optimizer ein/ausschalten |
| `day_of_week` | `6` | Wochentag (0=Montag, 6=Sonntag) für geplanten Lauf |
| `hour` / `minute` | `3` / `0` | Uhrzeit für geplanten Lauf (03:00 Uhr) |
| `interval.value/unit` | `7 days` | Mindestabstand zwischen zwei Optimierungen |
| `start_capital` | `1000` | Startkapital für die Simulation |
| `max_drawdown_pct` | `30` | Max. erlaubter Drawdown (Portfolio-Simulation) |
| `min_win_rate_pct` | `0` | Min. Win-Rate (0 = kein Limit) |
| `lookback_days` | `"auto"` | Historische Tage: `"auto"` = max. Wert über alle Config-Timeframes (15m→180, 1h→365, 4h→730, 1d→1095), oder feste Zahl |
| `send_telegram_on_completion` | `true` | Ergebnis via Telegram senden |

> **Erster Start:** Beim ersten Lauf nach `enabled: true` startet die Optimierung sofort
> (keine `.last_optimization_run` Datei vorhanden). Danach greift das Interval.

### `configs/config_BTCUSDTUSDT_4h_fib.json` — Strategie-Parameter

```json
{
  "market": {
    "symbol": "BTC/USDT:USDT",
    "timeframe": "4h"
  },
  "strategy": {
    "swing_lookback": 100,
    "pivot_left": 5,
    "pivot_right": 5,
    "structure_lookback": 60,

    "fib_entry_min": 0.382,
    "fib_entry_max": 0.618,
    "fib_sl_level": 0.786,
    "fib_tp1_level": 1.618,

    "rsi_period": 14,
    "rsi_oversold": 45,
    "rsi_overbought": 55,
    "volume_ratio_min": 1.0,
    "atr_period": 14,
    "atr_sl_multiplier": 1.5,

    "min_rr": 1.5,
    "min_signal_score": 4.0
  },
  "risk": {
    "leverage": 3,
    "margin_mode": "isolated",
    "risk_per_entry_pct": 0.5
  }
}
```

| Parameter | Standard | Erklärung |
|---|---|---|
| `swing_lookback` | 100 | Kerzen für Swing-Suche |
| `pivot_left` / `pivot_right` | 5 | Pivot-Bestätigung: n Kerzen links/rechts |
| `structure_lookback` | 60 | Kerzen für Trendlinien-Berechnung |
| `fib_entry_min` | 0.382 | Untere Entry-Zone (38.2%) |
| `fib_entry_max` | 0.618 | Obere Entry-Zone (61.8%) |
| `fib_sl_level` | 0.786 | Stop-Loss-Fibonacci-Level (78.6%) |
| `fib_tp1_level` | 1.618 | TP-Extension (1.0=100%, 1.272=127.2%, 1.618=161.8%) |
| `structure_tolerance_atr_mult` | 0.3 | Puffer um Trendlinie = ATR × Faktor |
| `rsi_oversold` | 45 | RSI-Schwelle für LONG |
| `rsi_overbought` | 55 | RSI-Schwelle für SHORT |
| `volume_ratio_min` | 1.0 | Volumen muss ≥ MA × dieser Faktor sein |
| `atr_sl_multiplier` | 1.5 | SL = ATR × dieser Faktor |
| `min_rr` | 1.5 | Mindest-Risiko-Rendite-Verhältnis |
| `min_signal_score` | 4.0 | Signal-Score 0–10: unter diesem Wert kein Trade |
| `leverage` | 3 | Hebel (Bitget Futures) |
| `margin_mode` | isolated | isolated oder cross |
| `risk_per_entry_pct` | 0.5 | % des Kontostands als Risiko pro Trade |

> **Optimizer-Parameter:** `leverage`, `risk_per_entry_pct`, `margin_mode` und
> `fib_tp1_level` werden vom Optimizer automatisch bestimmt. Nicht manuell ändern —
> `run_pipeline.sh` überschreibt sie.

---

## Installation

#### 1. Projekt klonen

```bash
git clone https://github.com/Youra82/fibot.git
cd fibot
```

#### 2. Installations-Skript ausführen

```bash
chmod +x install.sh
./install.sh
```

#### 3. API-Keys eintragen

```bash
cp secret.json.template secret.json
nano secret.json
```

```json
{
  "fibot": [
    {
      "name": "Main Account",
      "apiKey": "DEIN_API_KEY",
      "secret": "DEIN_SECRET",
      "password": "DEIN_PASSPHRASE"
    }
  ],
  "telegram": {
    "bot_token": "DEIN_BOT_TOKEN",
    "chat_id": "DEINE_CHAT_ID"
  }
}
```

---

## Workflow

#### 1. Parameter optimieren — `run_pipeline.sh`

Die Pipeline findet automatisch die besten Strategie-Parameter für jedes Symbol
und jeden Timeframe per **Optuna-Optimierung** und speichert sie als Config-JSON.

```bash
chmod +x run_pipeline.sh
./run_pipeline.sh
```

```
Symbol(e) (z.B. BTC ETH): BTC ETH SOL
Timeframe(s) (z.B. 4h oder 1h 4h): 4h 1d
Startkapital: 1000
Trials: 200
Max Drawdown: 30
```

Was optimiert wird:

| Parameter | Bereich | Bedeutung |
|---|---|---|
| `fib_tp1_level` | 1.0 / 1.272 / 1.618 | TP-Extension (161.8% = mehr R:R) |
| `swing_lookback` | 50–200 Kerzen | Wie weit zurück nach Swings suchen |
| `pivot_left/right` | 2–8 Kerzen | Pivot-Bestätigung |
| `rsi_oversold/bought` | 30–70 | RSI-Filter-Grenzen |
| `volume_ratio_min` | 0.5–2.0× | Volumen-Bestätigung |
| `min_signal_score` | 2.0–7.0 | Mindest-Score für Entry |
| `leverage` | 2–20× | Hebelwirkung (DD-begrenzt) |
| `risk_per_entry_pct` | 0.5–8.0% | Risiko pro Trade (DD-begrenzt) |

Ergebnis: `src/fibot/strategy/configs/config_BTCUSDTUSDT_4h_fib.json`

> **Tipp:** 200 Trials für erste Ergebnisse, 500 Trials für finale Optimierung.

#### 2. Ergebnisse prüfen — `show_results.sh`

```bash
chmod +x show_results.sh
./show_results.sh
```

```
Wähle einen Analyse-Modus:
  1) Einzel-Analyse              (jede Strategie wird isoliert getestet)
  2) Manuelle Portfolio-Simulation  (du wählst das Team)
  3) Automatische Portfolio-Optimierung  (der Bot wählt das beste Team)
  4) Interaktive Charts          (Candlestick + Entry/Exit-Marker)
```

**Modus 1 — Einzel-Analyse:**
Backtestet alle vorhandenen Configs isoliert. Fragt Startdatum, Enddatum,
Startkapital. Ausgabe als sortierte Zusammenfassungstabelle (nach PnL):

```
=========================================================================================
                        Zusammenfassung aller Einzelstrategien
=========================================================================================
  Strategie               Trades  Win Rate %    PnL %  Max DD %  Endkapital
  ADA/USDT:USDT (1h)         282       24.82  1613.40     19.26      428.35
  ETH/USDT:USDT (1h)         199       20.60   299.07     17.59       99.77
=========================================================================================
```

**Modus 2 — Manuelle Portfolio-Simulation:**
Zeigt alle verfügbaren Configs nummeriert. Auswahl z.B. `1 3 5` oder `alle`.
Bot backtestet die gewählten Strategien isoliert und zeigt kombinierte Portfolio-Performance.

**Modus 3 — Automatische Portfolio-Optimierung:**
Greedy-Algorithmus findet das beste Portfolio unter vorgegebenen Randbedingungen
(Max Drawdown, optionale Min Win-Rate). Coin-Kollisionsschutz: gleicher Coin
in zwei Timeframes (BTC 4h + BTC 1d) ist blockiert.

Die Basis-Strategie wird gegen die **Portfolio-Simulation-DD** validiert (nicht nur
gegen den Einzel-Backtester). Das stellt sicher, dass die Bedingung im Ergebnis
auch tatsächlich eingehalten wird.

```
1/3: Suche Basis-Strategie (Portfolio-Sim-DD muss <= 30.00%)...
  OK config_ADAUSDTUSDT_1h_fib.json     Sim: 428.35 USDT  Sim-DD: 19.26%
  -- config_AAVEUSDTUSDT_30m_fib.json   Sim: 256.75 USDT  Sim-DD: 42.38%

2/3: Beste Basis: config_ADAUSDTUSDT_1h_fib.json
     Portfolio-Simulation: 428.35 USDT, Sim-DD: 19.26%

3/3: Suche beste Team-Kollegen...
-> Fuege hinzu: config_ETHUSDTUSDT_1h_fib.json
   (Neues Kapital: 510.00 USDT, Max DD: 22.40%)

=======================================================
     Ergebnis der automatischen Portfolio-Optimierung
=======================================================
Endkapital:    510.00 USDT (+410.00%, +410.00 USDT)
Portfolio MaxDD: 22.40%
Liquidiert:    NEIN
=======================================================
```

Am Ende wird angeboten:
- `settings.json` mit dem optimalen Portfolio zu aktualisieren
- Interaktiven Portfolio-Equity-Chart als HTML zu erstellen (`artifacts/charts/fibot_portfolio_equity.html`)
- Excel-Tabelle aller Trades zu erstellen (`artifacts/charts/fibot_trades.xlsx`)
- Beides via Telegram zu senden

**Modus 4 — Interaktive Charts:**
Liest alle aktuellen Configs aus `src/fibot/strategy/configs/` und zeigt sie zur Auswahl.
Nach der Auswahl: Startdatum, Enddatum, Kapital eingeben → Backtest wird frisch berechnet
→ HTML-Chart in `artifacts/charts/fibot_*.html` mit 5 Panels:
Candlestick + Fib-Levels, Volumen, RSI, ATR, Signal-Score.

#### 3. Configs ins Repo pushen — `push_configs.sh`

Nach erfolgreicher Optimierung die neuen Configs direkt ins Repo pushen,
damit der VPS sie per `update.sh` holen kann:

```bash
chmod +x push_configs.sh
./push_configs.sh
```

Das Skript:
- Prüft ob `config_*_fib.json` Dateien vorhanden sind
- Staged + committet nur die Configs (keine anderen Dateien)
- Pusht auf `origin/main`, führt bei Konflikt automatisch Rebase durch

#### 4. VPS aktualisieren

```bash
./update.sh
```

Sichert `secret.json`, holt neue Configs per `git reset --hard`, stellt `secret.json` wieder her.

#### 5. Live schalten

```bash
nano settings.json
# active_strategies befüllen (manuell oder via show_results.sh Mode 3)
```

#### 6. Cronjob einrichten

```bash
chmod +x cron_setup.sh
./cron_setup.sh
```

Oder manuell:

```bash
crontab -e
```

```cron
# FiBot — alle 4 Stunden (passend zum 4h Timeframe)
0 */4 * * * cd /root/fibot && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1

# FiBot — stündlich (für 1h Timeframe)
5 * * * * cd /root/fibot && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1
```

> Offset von 5 Minuten nach der vollen Stunde empfohlen (Börse braucht ~1–2 Min
> um die Kerze zu schließen).

---

## Auto-Optimierung

Der Bot kann das Portfolio **vollautomatisch** neu optimieren — ohne manuellen Eingriff.
Der Scheduler läuft bei jedem `master_runner.py`-Start im Hintergrund und prüft,
ob eine Optimierung fällig ist.

### Aktivieren

```bash
nano settings.json
# "enabled": true setzen unter optimization_settings
```

### Zeitplan-Optionen

```json
"schedule": {
  "day_of_week": 6,
  "hour": 3,
  "minute": 0,
  "interval": { "value": 7, "unit": "days" }
}
```

- **`interval`**: Mindestabstand zwischen zwei Läufen (z.B. alle 7 Tage)
- **`day_of_week` + `hour`**: Zusätzlich geplanter Lauf (z.B. jeden Samstag 03:00 Uhr)
- Beide Mechanismen greifen unabhängig voneinander

Unterstützte Einheiten für `interval.unit`: `minutes`, `hours`, `days`, `weeks`

### Ablauf

```
master_runner.py startet
  └─ auto_optimizer_scheduler.py (Hintergrund, non-blocking)
       ├─ Prüft .last_optimization_run
       ├─ Wenn fällig: Telegram "Optimierung gestartet"
       ├─ Setzt .optimization_in_progress (verhindert parallele Läufe)
       ├─ Führt aus: show_results.py --mode 3 --auto
       │    (verwendet start_capital / max_drawdown_pct / lookback_days aus settings.json)
       ├─ Liest optimization_results.json
       ├─ Schreibt active_strategies in settings.json
       ├─ Speichert Timestamp in .last_optimization_run
       └─ Telegram "Optimierung abgeschlossen" mit Portfolio-Details
          + Portfolio-Chart HTML + Excel-Tabelle (artifacts/charts/)
```

### Manuell auslösen

```bash
# Scheduler direkt starten (prüft ob fällig, hält sich an enabled + Schedule)
.venv/bin/python3 auto_optimizer_scheduler.py

# Sofort erzwingen — ignoriert enabled und Schedule (für Tests)
.venv/bin/python3 auto_optimizer_scheduler.py --force
```

> `--force` überspringt den `enabled`-Check und den Zeitplan-Check.
> Nützlich um nach einer Konfigurationsänderung direkt zu testen,
> ob der Ablauf korrekt funktioniert.

### Log ansehen

```bash
tail -f logs/auto_optimizer.log
```

### Dateien

| Datei | Beschreibung |
|---|---|
| `.last_optimization_run` | Timestamp des letzten Laufs (nicht in Git) |
| `.optimization_in_progress` | Lock-Datei während laufender Optimierung |
| `artifacts/results/optimization_results.json` | Letztes Optimierungs-Ergebnis |
| `artifacts/charts/fibot_portfolio_equity.html` | Interaktiver Portfolio-Chart |
| `artifacts/charts/fibot_trades.xlsx` | Excel-Tabelle aller Trades |
| `logs/auto_optimizer.log` | Vollständiges Protokoll |

---

## Tägliche Verwaltung

#### Logs ansehen

```bash
tail -f logs/cron.log
tail -n 100 logs/fibot_BTCUSDTUSDT_4h.log
tail -f logs/auto_optimizer.log
grep -i "ERROR" logs/fibot_BTCUSDTUSDT_4h.log
```

#### Manuell testen

```bash
.venv/bin/python3 master_runner.py
```

#### Einzelne Strategie direkt starten

```bash
.venv/bin/python3 src/fibot/strategy/run.py --symbol BTC/USDT:USDT --timeframe 4h
```

#### show_results.py direkt aufrufen

```bash
# Modus 1: alle Configs isoliert
.venv/bin/python3 src/fibot/analysis/show_results.py \
    --mode 1 --from 2024-01-01 --capital 1000

# Modus 2: manuelle Portfolio-Simulation
.venv/bin/python3 src/fibot/analysis/show_results.py \
    --mode 2 --configs "config_BTCUSDTUSDT_1d_fib.json config_ETHUSDTUSDT_6h_fib.json" \
    --from 2024-01-01 --capital 1000

# Modus 3: automatische Portfolio-Optimierung (interaktiv)
.venv/bin/python3 src/fibot/analysis/show_results.py \
    --mode 3 --capital 1000 --target-max-dd 30 --from 2024-01-01

# Modus 3: non-interaktiv (wie Auto-Optimizer, kein Prompt)
.venv/bin/python3 src/fibot/analysis/show_results.py \
    --mode 3 --capital 1000 --target-max-dd 30 --from 2024-01-01 --auto

# Modus 4: interaktive Charts
.venv/bin/python3 src/fibot/analysis/show_results.py --mode 4
```

#### Trade-Status prüfen

```bash
cat artifacts/tracker/fibot_BTCUSDTUSDT_4h.json
```

---

## Signal-Score Erklärung

Der Score (0–10) aggregiert alle Confluence-Faktoren:

| Faktor | Score-Bonus | Bedingung |
|---|---|---|
| RSI überverkauft / überkauft | +2.0 | RSI < 45 (Long) oder > 55 (Short) |
| RSI moderat | +1.0 | RSI < 50 (Long) oder > 50 (Short) |
| Volumen erhöht | +1.5 | Volume ≥ MA × `volume_ratio_min` |
| Struktur-Bias passend | +1.5 | Struktur-Bias = bullish/neutral (Long) |
| Breakout in Signal-Richtung | +2.0 | Preis hat Struktur durchbrochen |
| Preis in Fib-Zone (kein Breakout) | +1.0 | Preis liegt innerhalb 38.2–61.8% |
| Preis nahe Struktur-Support/-Resistance | +1.5 | Abstand < 0.8% |

**Empfehlung:** `min_signal_score: 4.0` ist ein guter Ausgangswert.
Erhöhen auf 5–6 für selektivere, qualitativ hochwertigere Signale.

---

## Multi-Symbol betreiben

Mehrere Symbole laufen parallel — jedes als eigenständiger Prozess:

```json
"active_strategies": [
  { "symbol": "BTC/USDT:USDT", "timeframe": "1d", "leverage": 2, "risk_per_entry_pct": 0.5, "active": true },
  { "symbol": "ETH/USDT:USDT", "timeframe": "6h", "leverage": 3, "risk_per_entry_pct": 0.5, "active": true },
  { "symbol": "SOL/USDT:USDT", "timeframe": "4h", "leverage": 3, "risk_per_entry_pct": 0.5, "active": true }
]
```

**Wichtig:** Pro Coin nur ein Timeframe — kein `BTC 4h + BTC 1h` gleichzeitig
(Bitget verwaltet Positionen pro Coin, nicht pro Timeframe).

---

## Wichtige Regeln

- `secret.json` ist **nicht in Git** — wird von `update.sh` gesichert
- `artifacts/tracker/` ist **nicht in Git** — enthält offene Trade-Zustände
- `.last_optimization_run` ist **nicht in Git** — wird vom Auto-Optimizer verwaltet
- Immer erst `show_results.sh` → Modus 1 oder 3 (Backtest) bevor Live-Trading aktiviert wird
- Pro Coin maximal einen Timeframe in `active_strategies` eintragen
- `min_signal_score ≥ 4.0` empfohlen — darunter zu viele Fehlsignale
- Configs nie manuell bearbeiten — `run_pipeline.sh` überschreibt sie
- Neue Configs nach Optimierung mit `push_configs.sh` ins Repo pushen, dann VPS mit `update.sh` aktualisieren

---

## Automatische Zeiträume

| Timeframe | Tage | Kerzen (ca.) |
|---|---|---|
| 1m | 30 | ~43.000 |
| 3m / 5m / 15m | 60 – 90 | ~6.000 – 13.000 |
| 30m / 1h | 365 | ~17.500 / ~8.700 |
| **2h / 4h** | **730** | **~8.700 / ~4.380** |
| 6h / 8h / 12h / 1d | 1095 | ~4.380 – ~1.095 |
| 3d / 1w | 1825 | ~608 / ~260 |

Der Auto-Optimizer (`lookback_days: "auto"`) nimmt den **maximalen** Wert
über alle vorhandenen Config-Timeframes.

---

## Abhängigkeiten

```
ccxt>=4.2.0      # Exchange-Verbindung (Bitget)
pandas>=2.0.0    # Datenverarbeitung
numpy>=1.24.0    # Array-Operationen / lineare Regression
scipy>=1.11.0    # argrelmax/argrelmin für vektorisierten Backtester
optuna>=3.0.0    # Hyperparameter-Optimierung
requests>=2.31.0 # Telegram-Benachrichtigungen
plotly>=5.0.0    # Interaktive Charts
openpyxl>=3.1.0  # Excel-Export (Trades-Tabelle)
```
