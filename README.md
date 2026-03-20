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
   100%  = Swing High  (Take-Profit)
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
 100.0%  →  87.800  ← Take-Profit 1
 127.2%  →  89.958  ← Take-Profit 2 (Extension)
 161.8%  →  92.443  ← Take-Profit 3 (goldene Extension)
```

Der Bot erkennt genau diese Strukturen und handelt sie automatisch — auf Bitget Futures.

---

## Architektur

```
fibot/
├── master_runner.py                   # Cronjob-Orchestrator für Live-Trading
├── run_pipeline.sh                    # Backtest-Pipeline
├── install.sh                         # Erstinstallation auf VPS
├── update.sh                          # Git-Update (sichert secret.json)
├── cron_setup.sh                      # Cron-Job einrichten
├── settings.json                      # Aktive Strategien
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
    │   └── backtester.py              # Walk-Forward Backtest auf historischen Daten
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
 100.0% = Swing High             ← Take-Profit 1
 127.2% = Low + 127.2% × (H-L)  ← Take-Profit 2
 161.8% = Low + 161.8% × (H-L)  ← Take-Profit 3 (Extension)

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

Die Zone verhindert zwei häufige Fehler:
- **False Breakout:** Preis schießt kurz über die Linie, kehrt dann um → ohne Zone
  würde das als Breakout gewertet. Mit Zone muss der Preis die Zone komplett verlassen.
- **Missed Confluence:** Preis berührt die Linie nicht exakt, ist aber klar in der
  "Reaktionszone" → wird ohne Toleranz als "kein Kontakt" gezählt.

| Strukturtyp | Beschreibung | Bias |
|---|---|---|
| `wedge_down` | Absteigende Keile (beide Linien fallen, konvergieren) | Bullisch — Ausbruch nach oben erwartet |
| `wedge_up` | Aufsteigende Keile (beide Linien steigen, konvergieren) | Bärisch — Ausbruch nach unten erwartet |
| `triangle` | Symmetrisches Dreieck (Linien konvergieren gegenläufig) | Neutral — Ausbruch in Swing-Richtung |
| `channel_down` | Absteigender Kanal (parallele fallende Linien) | Bärisch |
| `channel_up` | Aufsteigender Kanal (parallele steigende Linien) | Bullisch |

**Breakout-Erkennung:** Ein Breakout wird nur registriert wenn der letzte Close
**außerhalb der Toleranzzone** schließt — nicht nur über/unter der nackten Trendlinie.

---

### Phase 4 — Signal & Confluence

Ein LONG-Signal entsteht, wenn **alle** Bedingungen erfüllt sind:

```
1. Swing-Richtung = "down"  (Preis ist zuvor gefallen)
2. Preis liegt in der Entry-Zone [38.2% – 61.8%]
   oder ist maximal proximity_pct (0.5%) entfernt
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

TP1:     Fibonacci 100%  (zurück zum Swing-Extreme)
TP2:     Fibonacci 127.2% (Extension, optional)

Alle TP/SL werden als Trigger-Market-Orders direkt nach Fill platziert.
Gehen TP/SL verloren (VPS-Neustart), werden sie beim nächsten Cycle
automatisch aus dem Tracker wiederhergestellt.
```

---

### Beispiel-Signal (Telegram-Ausgabe)

```
📈 FiBot Signal — BTC/USDT:USDT (4h)
Richtung : LONG
Entry    : 83.420,00  (38.2–61.8 Retracement)
SL       : 81.950,00  (-1.76%)
TP1      : 87.800,00  (+5.25%) [Fib 100%]
TP2      : 89.300,00  (+7.05%) [Fib 127.2%]
R:R      : 1:2.98
Score    : 7.0/10
Struktur : wedge_down (bullish)
Swing    : H=87.800 / L=80.600
Grund    : LONG | RSI überverkauft (41.2) | Volumen 1.43x
           | Struktur: wedge_down (bullish)
           | Preis nahe Struktur-Support (83.200) | R:R 2.98
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
| 100% | 1.000 | Take-Profit 1 (zurück zum Swing-Hoch/Tief) |
| 127.2% | 1.272 | Take-Profit 2 (Extension) |
| 161.8% | 1.618 | Take-Profit 3 (goldene Extension) |

---

## Konfiguration

### `settings.json` — Aktive Strategien

```json
{
  "live_trading_settings": {
    "active_strategies": [
      {
        "symbol": "BTC/USDT:USDT",
        "timeframe": "4h",
        "active": true
      },
      {
        "symbol": "ETH/USDT:USDT",
        "timeframe": "4h",
        "active": false
      }
    ]
  }
}
```

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
    "fib_tp1_level": 1.000,
    "fib_tp2_level": 1.272,

    "proximity_pct": 0.5,

    "rsi_period": 14,
    "rsi_oversold": 45,
    "rsi_overbought": 55,
    "volume_ratio_min": 1.0,
    "atr_period": 14,
    "atr_sl_multiplier": 1.5,

    "min_rr": 1.5,
    "min_signal_score": 4.0,
    "candle_limit": 300
  },
  "risk": {
    "leverage": 10,
    "margin_mode": "isolated",
    "risk_per_entry_pct": 1.0
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
| `fib_tp1_level` | 1.000 | TP1 (100% = zurück zum Swing) |
| `fib_tp2_level` | 1.272 | TP2 (127.2% Extension) |
| `proximity_pct` | 0.5 | Toleranz in %: wie nah muss Preis am Fib-Level sein |
| `structure_tolerance_atr_mult` | 0.3 | Struktur-Toleranzzone: Puffer um Trendlinie = ATR × Faktor. 0.3 = eng (ruhige Märkte), 0.5 = weit (volatile Märkte) |
| `rsi_oversold` | 45 | RSI-Schwelle für LONG (unter = Einstieg erlaubt) |
| `rsi_overbought` | 55 | RSI-Schwelle für SHORT (über = Einstieg erlaubt) |
| `volume_ratio_min` | 1.0 | Volumen muss ≥ MA × dieser Faktor sein |
| `atr_sl_multiplier` | 1.5 | SL = ATR × dieser Faktor (ATR-basierter SL) |
| `min_rr` | 1.5 | Mindest-Risiko-Rendite-Verhältnis |
| `min_signal_score` | 4.0 | Signal-Score 0–10: unter diesem Wert kein Trade |
| `leverage` | 10 | Hebel (Bitget Futures) |
| `margin_mode` | isolated | isolated oder cross |
| `risk_per_entry_pct` | 1.0 | % des Kontostands als Risiko pro Trade |

---

## Installation 🚀

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

Das Skript erstellt die virtuelle Python-Umgebung und installiert alle Abhängigkeiten.

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

#### 1. Symbol und Timeframe wählen

```bash
nano settings.json
```

```json
{ "symbol": "BTC/USDT:USDT", "timeframe": "4h", "active": true }
```

#### 2. Config-Datei erstellen

Für jedes aktive Symbol muss eine Config-Datei existieren:

```
src/fibot/strategy/configs/config_BTCUSDTUSDT_4h_fib.json
src/fibot/strategy/configs/config_ETHUSDT_4h_fib.json
```

Dateinamen-Schema: `config_{SYMBOL ohne Sonderzeichen}_{TIMEFRAME}_fib.json`

Die mitgelieferte BTC-Config kann als Vorlage kopiert und angepasst werden.

#### 3. Backtest ausführen

```bash
./run_pipeline.sh BTC/USDT:USDT 4h 365 1000
#                 Symbol         TF  Tage Kapital
```

Der Backtester lädt 365 Tage historische Daten von Bitget (ohne API-Key)
und simuliert die Fib-Strategie im Walk-Forward-Verfahren.

**Ausgabe:**

```
=== FiBot Backtest: BTC/USDT:USDT (4h) ===
Kapital    : 1000.00 → 1342.17 USDT (+34.22%)
Trades     : 47 | W:29 L:18 | WR: 61.7%
Max DD     : 12.45%
Avg R:R    : 1:2.31
```

Ergebnisse werden gespeichert unter `artifacts/results/backtest_BTCUSDTUSDT_4h.json`.

#### 4. Live schalten

```bash
nano settings.json
# "active": true setzen

nano src/fibot/strategy/configs/config_BTCUSDTUSDT_4h_fib.json
# Parameter nach Backtest-Erkenntnissen anpassen
```

#### 5. Cronjob einrichten

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
0 */4 * * * cd /home/user/fibot && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1

# FiBot — für 1h Timeframe
5 * * * * cd /home/user/fibot && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1
```

> Tipp: Offset von 5 Minuten nach der vollen Stunde empfohlen (Börse braucht
> ~1–2 Min um die Kerze zu schließen und Daten bereitzustellen).

---

## Tägliche Verwaltung & Wichtige Befehle ⚙️

#### Logs ansehen

```bash
# Cronjob-Übersicht
tail -f logs/cron.log

# Einzelnes Symbol
tail -n 100 logs/fibot_BTCUSDTUSDT_4h.log

# Master Runner
tail -f logs/master_runner.log

# Fehler suchen
grep -i "ERROR" logs/fibot_BTCUSDTUSDT_4h.log
```

#### Manuell testen (einzelner Lauf)

```bash
cd ~/fibot
.venv/bin/python3 master_runner.py
```

#### Einzelne Strategie direkt starten

```bash
.venv/bin/python3 src/fibot/strategy/run.py --symbol BTC/USDT:USDT --timeframe 4h
```

#### Backtest direkt aufrufen

```bash
# Mit Default-Parametern
.venv/bin/python3 src/fibot/analysis/backtester.py \
    --symbol BTC/USDT:USDT \
    --timeframe 4h \
    --days 365 \
    --capital 1000

# Mit eigener Config
.venv/bin/python3 src/fibot/analysis/backtester.py \
    --symbol ETH/USDT:USDT --timeframe 1h --days 180 \
    --config src/fibot/strategy/configs/config_ETHUSDT_1h_fib.json
```

#### Trade-Status prüfen

```bash
# Zeigt offene Positionen im Tracker an
cat artifacts/tracker/fibot_BTCUSDTUSDT_4h.json
```

#### Bot aktualisieren

```bash
./update.sh
```

Sichert automatisch `secret.json` vor dem `git reset --hard`.

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
Verringern auf 3 für mehr Trades (auf Kosten der Qualität).

---

## Multi-Symbol betreiben

Mehrere Symbole laufen parallel — jedes als eigenständiger Prozess:

```json
"active_strategies": [
  { "symbol": "BTC/USDT:USDT", "timeframe": "4h", "active": true },
  { "symbol": "ETH/USDT:USDT", "timeframe": "4h", "active": true },
  { "symbol": "SOL/USDT:USDT", "timeframe": "1h", "active": true }
]
```

Für jedes Symbol muss eine eigene Config-Datei vorhanden sein.
Der master_runner startet pro Symbol einen separaten Python-Prozess.

---

## Wichtige Regeln

- `secret.json` ist **nicht in Git** — wird von `update.sh` gesichert
- `artifacts/tracker/` ist **nicht in Git** — enthält offene Trade-Zustände
- Immer erst `./run_pipeline.sh` (Backtest) bevor Live-Trading aktiviert wird
- Für jeden Timeframe den passenden Cron-Interval wählen (1h → jede Stunde, 4h → alle 4h)
- `min_signal_score ≥ 4.0` empfohlen — darunter zu viele Fehlsignale
- Pivot-Parameter (`pivot_left`, `pivot_right`) auf 3–4 reduzieren für 1h-Charts
- `swing_lookback` erhöhen auf 150+ für volatile Assets (mehr Kontext)

---

## Abhängigkeiten

```
ccxt>=4.2.0      # Exchange-Verbindung (Bitget)
pandas>=2.0.0    # Datenverarbeitung
numpy>=1.24.0    # Array-Operationen / lineare Regression
requests>=2.31.0 # Telegram-Benachrichtigungen
ta>=0.11.0       # ATR-Berechnung (trade_manager)
```
