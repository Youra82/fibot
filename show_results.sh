#!/bin/bash
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

VENV_PATH=".venv/bin/activate"
PYTHON=".venv/bin/python3"

if [ ! -f "$VENV_PATH" ]; then
    echo -e "${RED}Fehler: .venv nicht gefunden. Erst install.sh ausführen.${NC}"
    exit 1
fi

source "$VENV_PATH"

# ─────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────
VALID_TFS="1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w"

# "BTC" → "BTC/USDT:USDT", "BTC/USDT:USDT" bleibt unverändert
expand_symbol() {
    local s="$1"
    if [[ "$s" != */* ]]; then
        echo "${s^^}/USDT:USDT"
    else
        echo "$s"
    fi
}

validate_tf() {
    local tf="$1"
    for v in $VALID_TFS; do
        [ "$tf" == "$v" ] && echo "$tf" && return 0
    done
    echo -e "${RED}Ungültiger Timeframe '$tf'. Erlaubt: $VALID_TFS${NC}" >&2
    return 1
}

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║        FiBot — Fibonacci Trading Bot     ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Wähle einen Analyse-Modus:${NC}"
echo "  1) Einzel-Backtest             (Symbol + Zeitraum frei wählen)"
echo "  2) Alle aktiven Strategien     (backtestet alle aus settings.json)"
echo "  3) Portfolio-Optimierer        (beste Coins/TFs für deine Randbedingungen)"
echo "  4) Live Signal-Check           (aktuelles Fib-Signal für ein Symbol)"
echo "  5) Interaktive Charts          (Candlestick + Entry/Exit-Marker)"
echo ""
read -p "Auswahl (1-5) [Standard: 3]: " MODE
MODE="${MODE//[$'\r\n ']/}"

if [[ ! "$MODE" =~ ^[1-5]?$ ]]; then
    echo -e "${RED}Ungültige Eingabe. Verwende Standard (3).${NC}"
    MODE=3
fi
MODE=${MODE:-3}

# ─────────────────────────────────────────
# Modus 1: Einzel-Backtest
# ─────────────────────────────────────────
if [ "$MODE" == "1" ]; then
    echo ""
    echo -e "${CYAN}--- Einzel-Backtest ---${NC}"

    read -p "Symbol(e) (z.B. BTC ETH oder BTC/USDT:USDT) [Standard: BTC]: " SYMBOLS_INPUT
    SYMBOLS_INPUT="${SYMBOLS_INPUT//[$'\r\n']/}"
    [ -z "$SYMBOLS_INPUT" ] && SYMBOLS_INPUT="BTC"

    read -p "Timeframe(s) (z.B. 4h oder 1h 4h 1d) [Standard: 4h]: " TFS_INPUT
    TFS_INPUT="${TFS_INPUT//[$'\r\n']/}"
    [ -z "$TFS_INPUT" ] && TFS_INPUT="4h"

    echo ""
    echo -e "${YELLOW}Zeitraum wählen:${NC}"
    echo "  a) Automatisch (je nach Timeframe empfohlen)"
    echo "  b) Von–Bis Datum"
    echo "  c) Von Datum bis heute"
    read -p "Auswahl (a/b/c) [Standard: a]: " DATE_MODE
    DATE_MODE="${DATE_MODE//[$'\r\n ']/}"
    [ -z "$DATE_MODE" ] && DATE_MODE="a"

    DATE_ARGS=""
    if [ "$DATE_MODE" == "b" ]; then
        read -p "Startdatum (JJJJ-MM-TT): " DATE_FROM
        DATE_FROM="${DATE_FROM//[$'\r\n ']/}"
        read -p "Enddatum   (JJJJ-MM-TT): " DATE_TO
        DATE_TO="${DATE_TO//[$'\r\n ']/}"
        [[ "$DATE_FROM" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && DATE_ARGS="--from $DATE_FROM"
        [[ "$DATE_TO"   =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && DATE_ARGS="$DATE_ARGS --to $DATE_TO"
    elif [ "$DATE_MODE" == "c" ]; then
        read -p "Startdatum (JJJJ-MM-TT): " DATE_FROM
        DATE_FROM="${DATE_FROM//[$'\r\n ']/}"
        [[ "$DATE_FROM" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && DATE_ARGS="--from $DATE_FROM"
    fi

    read -p "Startkapital in USDT [Standard: 1000]: " CAPITAL
    CAPITAL="${CAPITAL//[$'\r\n ']/}"
    [[ ! "$CAPITAL" =~ ^[0-9]+(\.[0-9]+)?$ ]] && CAPITAL=1000

    for RAW_SYM in $SYMBOLS_INPUT; do
        SYMBOL=$(expand_symbol "$RAW_SYM")
        for TF in $TFS_INPUT; do
            if ! validate_tf "$TF" > /dev/null; then continue; fi
            echo ""
            $PYTHON src/fibot/analysis/show_results.py \
                --mode 1 \
                --symbol "$SYMBOL" \
                --timeframe "$TF" \
                --capital "$CAPITAL" \
                $DATE_ARGS
        done
    done

# ─────────────────────────────────────────
# Modus 2: Alle aktiven Strategien
# ─────────────────────────────────────────
elif [ "$MODE" == "2" ]; then
    echo ""
    echo -e "${CYAN}--- Alle aktiven Strategien aus settings.json ---${NC}"

    echo ""
    echo -e "${YELLOW}Zeitraum wählen:${NC}"
    echo "  a) Automatisch (je nach Timeframe empfohlen)"
    echo "  b) Von–Bis Datum"
    echo "  c) Von Datum bis heute"
    read -p "Auswahl (a/b/c) [Standard: a]: " DATE_MODE
    DATE_MODE="${DATE_MODE//[$'\r\n ']/}"
    [ -z "$DATE_MODE" ] && DATE_MODE="a"

    DATE_ARGS=""
    if [ "$DATE_MODE" == "b" ]; then
        read -p "Startdatum (JJJJ-MM-TT): " DATE_FROM
        DATE_FROM="${DATE_FROM//[$'\r\n ']/}"
        read -p "Enddatum   (JJJJ-MM-TT): " DATE_TO
        DATE_TO="${DATE_TO//[$'\r\n ']/}"
        [[ "$DATE_FROM" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && DATE_ARGS="--from $DATE_FROM"
        [[ "$DATE_TO"   =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && DATE_ARGS="$DATE_ARGS --to $DATE_TO"
    elif [ "$DATE_MODE" == "c" ]; then
        read -p "Startdatum (JJJJ-MM-TT): " DATE_FROM
        DATE_FROM="${DATE_FROM//[$'\r\n ']/}"
        [[ "$DATE_FROM" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && DATE_ARGS="--from $DATE_FROM"
    fi

    read -p "Startkapital in USDT [Standard: 1000]: " CAPITAL
    CAPITAL="${CAPITAL//[$'\r\n ']/}"
    [[ ! "$CAPITAL" =~ ^[0-9]+(\.[0-9]+)?$ ]] && CAPITAL=1000

    echo ""
    $PYTHON src/fibot/analysis/show_results.py \
        --mode 2 \
        --capital "$CAPITAL" \
        $DATE_ARGS

# ─────────────────────────────────────────
# Modus 3: Portfolio-Optimierer
# ─────────────────────────────────────────
elif [ "$MODE" == "3" ]; then
    echo ""
    echo -e "${CYAN}--- Portfolio-Optimierer ---${NC}"
    echo -e "${YELLOW}Findet die optimale Coin/Timeframe-Kombination aus deinen vorhandenen Configs.${NC}"
    echo ""

    read -p "Startkapital in USDT [Standard: 1000]: " CAPITAL
    CAPITAL="${CAPITAL//[$'\r\n ']/}"
    [[ ! "$CAPITAL" =~ ^[0-9]+(\.[0-9]+)?$ ]] && CAPITAL=1000

    read -p "Max Drawdown % [Standard: 30]: " TARGET_DD
    TARGET_DD="${TARGET_DD//[$'\r\n ']/}"
    [[ ! "$TARGET_DD" =~ ^[0-9]+(\.[0-9]+)?$ ]] && TARGET_DD=30

    read -p "Min Win-Rate % (0 = kein Limit) [Standard: 0]: " MIN_WR
    MIN_WR="${MIN_WR//[$'\r\n ']/}"
    [[ ! "$MIN_WR" =~ ^[0-9]+(\.[0-9]+)?$ ]] && MIN_WR=0

    echo ""
    echo -e "${YELLOW}Zeitraum wählen:${NC}"
    echo "  a) Automatisch (365 Tage Rückblick)"
    echo "  b) Von–Bis Datum"
    echo "  c) Von Datum bis heute"
    read -p "Auswahl (a/b/c) [Standard: a]: " DATE_MODE
    DATE_MODE="${DATE_MODE//[$'\r\n ']/}"
    [ -z "$DATE_MODE" ] && DATE_MODE="a"

    DATE_ARGS=""
    if [ "$DATE_MODE" == "b" ]; then
        read -p "Startdatum (JJJJ-MM-TT): " DATE_FROM
        DATE_FROM="${DATE_FROM//[$'\r\n ']/}"
        read -p "Enddatum   (JJJJ-MM-TT): " DATE_TO
        DATE_TO="${DATE_TO//[$'\r\n ']/}"
        [[ "$DATE_FROM" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && DATE_ARGS="--from $DATE_FROM"
        [[ "$DATE_TO"   =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && DATE_ARGS="$DATE_ARGS --to $DATE_TO"
    elif [ "$DATE_MODE" == "c" ]; then
        read -p "Startdatum (JJJJ-MM-TT): " DATE_FROM
        DATE_FROM="${DATE_FROM//[$'\r\n ']/}"
        [[ "$DATE_FROM" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && DATE_ARGS="--from $DATE_FROM"
    fi

    echo ""
    $PYTHON src/fibot/analysis/show_results.py \
        --mode 3 \
        --capital "$CAPITAL" \
        --target-max-dd "$TARGET_DD" \
        --min-wr "$MIN_WR" \
        $DATE_ARGS

    # --- Angebot: settings.json mit optimalem Portfolio aktualisieren ---
    OPT_FILE="artifacts/results/optimization_results.json"
    if [ -f "$OPT_FILE" ]; then
        echo ""
        echo -e "${YELLOW}Möchtest du settings.json mit dem optimalen Portfolio aktualisieren?${NC}"
        read -p "Dies setzt active_strategies auf die gefundenen Strategien. (j/n) [Standard: n]: " UPDATE_SETTINGS
        UPDATE_SETTINGS="${UPDATE_SETTINGS:-n}"
        if [[ "$UPDATE_SETTINGS" == "j" || "$UPDATE_SETTINGS" == "J" ]]; then
            $PYTHON - <<'PYEOF'
import json, os, sys

PROJECT_ROOT = os.getcwd()
opt_file     = os.path.join(PROJECT_ROOT, "artifacts", "results", "optimization_results.json")
settings_file = os.path.join(PROJECT_ROOT, "settings.json")
configs_dir  = os.path.join(PROJECT_ROOT, "src", "fibot", "strategy", "configs")

with open(opt_file) as f:
    opt = json.load(f)

portfolio_files = opt.get("optimal_portfolio", [])
if not portfolio_files:
    print("Kein Portfolio in optimization_results.json gefunden.")
    sys.exit(0)

strategies = []
for fname in portfolio_files:
    cfg_path = os.path.join(configs_dir, fname)
    if not os.path.exists(cfg_path):
        continue
    with open(cfg_path) as f:
        cfg = json.load(f)
    market = cfg.get("market", {})
    risk   = cfg.get("risk",   {})
    strategies.append({
        "symbol":            market.get("symbol", ""),
        "timeframe":         market.get("timeframe", ""),
        "leverage":          risk.get("leverage", 10),
        "margin_mode":       risk.get("margin_mode", "isolated"),
        "risk_per_entry_pct": risk.get("risk_per_entry_pct", 1.0),
        "active":            True,
    })

if not os.path.exists(settings_file):
    print(f"settings.json nicht gefunden: {settings_file}")
    sys.exit(1)

with open(settings_file) as f:
    settings = json.load(f)

settings.setdefault("live_trading_settings", {})["active_strategies"] = strategies

with open(settings_file, "w") as f:
    json.dump(settings, f, indent=2)

print(f"settings.json aktualisiert mit {len(strategies)} Strategie(n):")
for s in strategies:
    print(f"  {s['symbol']} ({s['timeframe']})  lev={s['leverage']}x  risk={s['risk_per_entry_pct']}%")
PYEOF
        else
            echo -e "${GREEN}settings.json wurde nicht geändert.${NC}"
        fi
    fi

# ─────────────────────────────────────────
# Modus 4: Live Signal-Check
# ─────────────────────────────────────────
elif [ "$MODE" == "4" ]; then
    echo ""
    echo -e "${CYAN}--- Live Signal-Check ---${NC}"

    read -p "Symbol(e) (z.B. BTC ETH oder BTC/USDT:USDT) [Standard: BTC]: " SYMBOLS_INPUT
    SYMBOLS_INPUT="${SYMBOLS_INPUT//[$'\r\n']/}"
    [ -z "$SYMBOLS_INPUT" ] && SYMBOLS_INPUT="BTC"

    read -p "Timeframe(s) (z.B. 4h oder 1h 4h) [Standard: 4h]: " TFS_INPUT
    TFS_INPUT="${TFS_INPUT//[$'\r\n']/}"
    [ -z "$TFS_INPUT" ] && TFS_INPUT="4h"

    for RAW_SYM in $SYMBOLS_INPUT; do
        SYMBOL=$(expand_symbol "$RAW_SYM")
        for TF in $TFS_INPUT; do
            if ! validate_tf "$TF" > /dev/null; then continue; fi
            echo ""
            $PYTHON src/fibot/analysis/show_results.py \
                --mode 4 \
                --symbol "$SYMBOL" \
                --timeframe "$TF"
        done
    done

# ─────────────────────────────────────────
# Modus 5: Interaktive Charts
# ─────────────────────────────────────────
elif [ "$MODE" == "5" ]; then
    echo ""
    echo -e "${CYAN}--- Interaktive Charts ---${NC}"
    echo -e "${YELLOW}Wählt aus gespeicherten Backtest-Ergebnissen und öffnet einen interaktiven Chart.${NC}"
    echo ""
    $PYTHON src/fibot/analysis/show_results.py --mode 5
fi

deactivate
