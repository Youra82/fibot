#!/bin/bash
# FiBot — Run Pipeline
# Runs backtests and saves results for configured symbols/timeframes
# Usage: ./run_pipeline.sh [--symbol BTC/USDT:USDT] [--timeframe 4h] [--days 365]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON=".venv/bin/python3"
if [ ! -f "$PYTHON" ]; then
    echo "ERROR: .venv nicht gefunden. Führe zuerst install.sh aus."
    exit 1
fi

SYMBOL="${1:-BTC/USDT:USDT}"
TIMEFRAME="${2:-4h}"
DATE_FROM="${3:-}"   # YYYY-MM-DD oder leer
DATE_TO="${4:-}"     # YYYY-MM-DD oder leer (= heute)
CAPITAL="${5:-1000}"

echo "=================================================="
echo "FiBot Pipeline"
echo "Symbol    : $SYMBOL"
echo "Timeframe : $TIMEFRAME"
if [ -n "$DATE_FROM" ]; then
    echo "Von       : $DATE_FROM"
    echo "Bis       : ${DATE_TO:-heute}"
else
    echo "Zeitraum  : auto (je nach Timeframe)"
fi
echo "Kapital   : $CAPITAL USDT"
echo "=================================================="

echo ""
echo ">>> Starte Backtest..."

ARGS="--symbol $SYMBOL --timeframe $TIMEFRAME --capital $CAPITAL"

if [ -n "$DATE_FROM" ]; then
    ARGS="$ARGS --from $DATE_FROM"
    [ -n "$DATE_TO" ] && ARGS="$ARGS --to $DATE_TO"
fi

$PYTHON src/fibot/analysis/backtester.py $ARGS

echo ""
echo ">>> Pipeline abgeschlossen."
echo "Ergebnisse unter: artifacts/results/"
