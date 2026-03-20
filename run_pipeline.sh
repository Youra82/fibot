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
DAYS="${3:-}"        # leer = auto (Backtester leitet aus Timeframe ab)
CAPITAL="${4:-1000}"

echo "=================================================="
echo "FiBot Pipeline"
echo "Symbol    : $SYMBOL"
echo "Timeframe : $TIMEFRAME"
echo "Tage      : ${DAYS:-auto (je nach Timeframe)}"
echo "Kapital   : $CAPITAL USDT"
echo "=================================================="

echo ""
echo ">>> Starte Backtest..."
if [ -n "$DAYS" ]; then
    $PYTHON src/fibot/analysis/backtester.py \
        --symbol "$SYMBOL" \
        --timeframe "$TIMEFRAME" \
        --days "$DAYS" \
        --capital "$CAPITAL"
else
    # Kein --days → Backtester wählt automatisch passende Tage für den Timeframe
    $PYTHON src/fibot/analysis/backtester.py \
        --symbol "$SYMBOL" \
        --timeframe "$TIMEFRAME" \
        --capital "$CAPITAL"
fi

echo ""
echo ">>> Pipeline abgeschlossen."
echo "Ergebnisse unter: artifacts/results/"
