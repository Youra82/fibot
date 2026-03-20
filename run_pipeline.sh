#!/bin/bash
# FiBot — Parameter-Optimierungs-Pipeline
# Findet die besten Fib-Strategie-Parameter per Optuna und speichert sie als Config.
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

# --- Aufräum-Assistent ---
echo ""
echo -e "${YELLOW}Möchtest du alle alten, generierten Configs vor dem Start löschen?${NC}"
read -p "Dies wird für einen kompletten Neustart empfohlen. (j/n) [Standard: n]: " CLEANUP_CHOICE
CLEANUP_CHOICE="${CLEANUP_CHOICE//[$'\r\n ']/}"
CLEANUP_CHOICE="${CLEANUP_CHOICE:-n}"
if [[ "$CLEANUP_CHOICE" == "j" || "$CLEANUP_CHOICE" == "J" ]]; then
    echo -e "${YELLOW}Lösche alte Konfigurationen...${NC}"
    rm -f src/fibot/strategy/configs/config_*.json
    echo -e "${GREEN}✔ Aufräumen abgeschlossen.${NC}"
else
    echo -e "${GREEN}✔ Alte Ergebnisse werden beibehalten.${NC}"
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     FiBot — Parameter-Optimierung        ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Findet die besten Fibonacci-Parameter per Optuna.${NC}"
echo -e "${YELLOW}Ergebnis wird als Config gespeichert (z.B. config_BTCUSDTUSDT_4h_fib.json).${NC}"
echo ""

# ─────────────────────────────────────────
# Symbol(e) und Timeframe(s)
# ─────────────────────────────────────────
read -p "Symbol(e) (z.B. BTC ETH oder BTC/USDT:USDT) [Standard: BTC]: " SYMBOLS_INPUT
SYMBOLS_INPUT="${SYMBOLS_INPUT//[$'\r\n']/}"
[ -z "$SYMBOLS_INPUT" ] && SYMBOLS_INPUT="BTC"

read -p "Timeframe(s) (z.B. 4h oder 1h 4h 1d) [Standard: 4h]: " TFS_INPUT
TFS_INPUT="${TFS_INPUT//[$'\r\n']/}"
[ -z "$TFS_INPUT" ] && TFS_INPUT="4h"

# ─────────────────────────────────────────
# Zeitraum
# ─────────────────────────────────────────
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

# ─────────────────────────────────────────
# Kapital & Trials
# ─────────────────────────────────────────
read -p "Startkapital in USDT [Standard: 1000]: " CAPITAL
CAPITAL="${CAPITAL//[$'\r\n ']/}"
[[ ! "$CAPITAL" =~ ^[0-9]+(\.[0-9]+)?$ ]] && CAPITAL=1000

echo ""
echo -e "${YELLOW}Empfohlene Trials:${NC}"
echo "  Schnell:   50–100  (grobe Suche)"
echo "  Standard:  200     (gutes Ergebnis)"
echo "  Gründlich: 500+    (best möglich, dauert länger)"
read -p "Anzahl Optuna-Trials [Standard: 200]: " TRIALS
TRIALS="${TRIALS//[$'\r\n ']/}"
[[ ! "$TRIALS" =~ ^[0-9]+$ ]] && TRIALS=200

read -p "Max Drawdown %% [Standard: 30]: " MAX_DD
MAX_DD="${MAX_DD//[$'\r\n ']/}"
[[ ! "$MAX_DD" =~ ^[0-9]+(\.[0-9]+)?$ ]] && MAX_DD=30

read -p "Min Win-Rate %% [Standard: 0]: " MIN_WR
MIN_WR="${MIN_WR//[$'\r\n ']/}"
[[ ! "$MIN_WR" =~ ^[0-9]+(\.[0-9]+)?$ ]] && MIN_WR=0

# ─────────────────────────────────────────
# Start
# ─────────────────────────────────────────
echo ""
echo -e "${CYAN}Starte Optimierung für: ${BOLD}$SYMBOLS_INPUT${NC} ${CYAN}/ Timeframes: ${BOLD}$TFS_INPUT${NC}"
echo ""

$PYTHON src/fibot/analysis/optimizer.py \
    --symbols $SYMBOLS_INPUT \
    --timeframes $TFS_INPUT \
    --capital "$CAPITAL" \
    --trials "$TRIALS" \
    --max-dd "$MAX_DD" \
    --min-wr "$MIN_WR" \
    $DATE_ARGS

echo ""
echo -e "${GREEN}Pipeline abgeschlossen. Configs gespeichert in src/fibot/strategy/configs/${NC}"
echo -e "${YELLOW}Tipp: Führe nun ./show_results.sh → Modus 1 oder 2 aus um die neuen Configs zu testen.${NC}"

deactivate
