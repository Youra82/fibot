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

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║        FiBot — Fibonacci Trading Bot     ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Wähle einen Analyse-Modus:${NC}"
echo "  1) Einzel-Backtest             (Symbol + Zeitraum frei wählen)"
echo "  2) Alle aktiven Strategien     (backtestet alle aus settings.json)"
echo "  3) Ergebnisse anzeigen         (gespeicherte Backtest-JSONs)"
echo "  4) Live Signal-Check           (aktuelles Fib-Signal für ein Symbol)"
echo ""
read -p "Auswahl (1-4) [Standard: 3]: " MODE
MODE="${MODE//[$'\r\n ']/}"

if [[ ! "$MODE" =~ ^[1-4]?$ ]]; then
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

    read -p "Symbol (z.B. BTC/USDT:USDT) [Standard: BTC/USDT:USDT]: " SYMBOL
    SYMBOL="${SYMBOL//[$'\r\n']/}"
    [ -z "$SYMBOL" ] && SYMBOL="BTC/USDT:USDT"

    read -p "Timeframe (z.B. 4h, 1h, 1d) [Standard: 4h]: " TF
    TF="${TF//[$'\r\n ']/}"
    [ -z "$TF" ] && TF="4h"

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
        --mode 1 \
        --symbol "$SYMBOL" \
        --timeframe "$TF" \
        --capital "$CAPITAL" \
        $DATE_ARGS

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
# Modus 3: Gespeicherte Ergebnisse anzeigen
# ─────────────────────────────────────────
elif [ "$MODE" == "3" ]; then
    echo ""
    $PYTHON src/fibot/analysis/show_results.py --mode 3

# ─────────────────────────────────────────
# Modus 4: Live Signal-Check
# ─────────────────────────────────────────
elif [ "$MODE" == "4" ]; then
    echo ""
    echo -e "${CYAN}--- Live Signal-Check ---${NC}"

    read -p "Symbol (z.B. BTC/USDT:USDT) [Standard: BTC/USDT:USDT]: " SYMBOL
    SYMBOL="${SYMBOL//[$'\r\n']/}"
    [ -z "$SYMBOL" ] && SYMBOL="BTC/USDT:USDT"

    read -p "Timeframe (z.B. 4h, 1h) [Standard: 4h]: " TF
    TF="${TF//[$'\r\n ']/}"
    [ -z "$TF" ] && TF="4h"

    echo ""
    $PYTHON src/fibot/analysis/show_results.py \
        --mode 4 \
        --symbol "$SYMBOL" \
        --timeframe "$TF"
fi

deactivate
