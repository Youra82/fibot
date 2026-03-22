#!/bin/bash
# FiBot — Parameter-Optimierungs-Pipeline
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}======================================================="
echo "       FiBot — Fibonacci Optimierungs-Pipeline"
echo -e "=======================================================${NC}"

VENV_PATH=".venv/bin/activate"
PYTHON=".venv/bin/$PYTHON"
OPTIMIZER="src/fibot/analysis/optimizer.py"

if [ ! -f "$VENV_PATH" ]; then
    echo -e "${RED}Fehler: Virtuelle Umgebung nicht gefunden. Bitte install.sh ausführen.${NC}"
    exit 1
fi
source "$VENV_PATH"
echo -e "${GREEN}✔ Virtuelle Umgebung wurde erfolgreich aktiviert.${NC}"

# --- Aufräum-Assistent ---
echo ""
echo -e "${YELLOW}Möchtest du alle alten, generierten Configs vor dem Start löschen?${NC}"
read -p "Dies wird für einen kompletten Neustart empfohlen. (j/n) [Standard: n]: " CLEANUP_CHOICE
CLEANUP_CHOICE="${CLEANUP_CHOICE:-n}"
if [[ "$CLEANUP_CHOICE" == "j" || "$CLEANUP_CHOICE" == "J" ]]; then
    echo -e "${YELLOW}Lösche alte Konfigurationen...${NC}"
    rm -f src/fibot/strategy/configs/config_*.json
    echo -e "${GREEN}✔ Aufräumen abgeschlossen.${NC}"
else
    echo -e "${GREEN}✔ Alte Ergebnisse werden beibehalten.${NC}"
fi

# --- Interaktive Abfrage ---
read -p "Handelspaar(e) eingeben (ohne /USDT, z.B. BTC ETH): " SYMBOLS
read -p "Zeitfenster eingeben (z.B. 1h 4h): " TIMEFRAMES

echo -e "\n${BLUE}--- Empfehlung: Optimaler Rückblick-Zeitraum ---${NC}"
printf "+-------------+--------------------------------+\n"
printf "| Zeitfenster | Empfohlener Rückblick (Tage)   |\n"
printf "+-------------+--------------------------------+\n"
printf "| 5m, 15m     | 15 - 90 Tage                   |\n"
printf "| 30m, 1h     | 180 - 365 Tage                 |\n"
printf "| 2h, 4h      | 550 - 730 Tage                 |\n"
printf "| 6h, 1d      | 1095 - 1825 Tage               |\n"
printf "+-------------+--------------------------------+\n"
read -p "Startdatum (JJJJ-MM-TT) oder 'a' für Automatik [Standard: a]: " START_DATE_INPUT
START_DATE_INPUT="${START_DATE_INPUT:-a}"
read -p "Enddatum (JJJJ-MM-TT) [Standard: Heute]: " END_DATE
END_DATE="${END_DATE:-$(date +%F)}"
read -p "Startkapital in USDT [Standard: 1000]: " START_CAPITAL
START_CAPITAL="${START_CAPITAL:-1000}"
read -p "Anzahl Trials [Standard: 200]: " N_TRIALS
N_TRIALS="${N_TRIALS:-200}"
read -p "CPU-Kerne [Standard: 1]: " N_JOBS
N_JOBS="${N_JOBS:-1}"

echo -e "\n${YELLOW}Wähle einen Optimierungs-Modus:${NC}"
echo "  1) Strenger Modus (Profitabel & Sicher)"
echo "  2) 'Finde das Beste'-Modus (Max Profit)"
read -p "Auswahl (1-2) [Standard: 1]: " OPTIM_MODE
OPTIM_MODE="${OPTIM_MODE:-1}"

read -p "Max Drawdown % [Standard: 30]: " MAX_DD
MAX_DD="${MAX_DD:-30}"

if [ "$OPTIM_MODE" == "1" ]; then
    read -p "Min Win-Rate % [Standard: 55]: " MIN_WR
    MIN_WR="${MIN_WR:-55}"
else
    MIN_WR=0
fi

for symbol in $SYMBOLS; do
    for timeframe in $TIMEFRAMES; do

        # --- Datumsberechnung ---
        if [ "$START_DATE_INPUT" == "a" ]; then
            lookback_days=365
            case "$timeframe" in
                5m|15m) lookback_days=60 ;;
                30m|1h) lookback_days=365 ;;
                2h|4h)  lookback_days=730 ;;
                6h|1d)  lookback_days=1095 ;;
            esac
            FINAL_START_DATE=$(date -d "$lookback_days days ago" +%F)
            echo -e "${YELLOW}INFO: Automatisches Startdatum für $timeframe (${lookback_days} Tage Rückblick): $FINAL_START_DATE${NC}"
        else
            FINAL_START_DATE="$START_DATE_INPUT"
        fi

        echo -e "\n${BLUE}=======================================================${NC}"
        echo -e "${BLUE}  Bearbeite Pipeline für: $symbol ($timeframe)${NC}"
        echo -e "${BLUE}  Datenzeitraum: $FINAL_START_DATE bis $END_DATE${NC}"
        echo -e "${BLUE}=======================================================${NC}"

        # Config-Dateiname bestimmen (Kurzname BTC → BTC/USDT:USDT → BTCUSDTUSDT)
        if [[ "$symbol" != *"/"* ]]; then
            FULL_SYM="${symbol}/USDT:USDT"
        else
            FULL_SYM="$symbol"
        fi
        SAFE_SYM=$(echo "$FULL_SYM" | tr -d '/: ')
        CONFIG_FILE="src/fibot/strategy/configs/config_${SAFE_SYM}_${timeframe}_fib.json"

        # Altes PnL aus bestehender Config lesen (falls vorhanden)
        OLD_PNL=""
        if [ -f "$CONFIG_FILE" ]; then
            OLD_PNL=$($PYTHON -c "
import json, sys
try:
    d = json.load(open('$CONFIG_FILE'))
    print(d.get('_backtest', {}).get('pnl_pct', ''))
except: pass
" 2>/dev/null)
            cp "$CONFIG_FILE" "${CONFIG_FILE}.bak"
            echo -e "${YELLOW}  Backup erstellt: ${CONFIG_FILE}.bak (PnL: ${OLD_PNL}%)${NC}"
        fi

        echo -e "\n${GREEN}>>> Starte Fibonacci-Optimierung für $symbol ($timeframe)...${NC}"
        $PYTHON "$OPTIMIZER" \
            --symbols "$symbol" \
            --timeframes "$timeframe" \
            --from "$FINAL_START_DATE" \
            --to "$END_DATE" \
            --capital "$START_CAPITAL" \
            --trials "$N_TRIALS" \
            --jobs "$N_JOBS" \
            --max-dd "$MAX_DD" \
            --min-wr "$MIN_WR"

        if [ $? -ne 0 ]; then
            echo -e "${RED}Fehler im Optimierer für $symbol ($timeframe). Überspringe...${NC}"
            # Backup wiederherstellen falls vorhanden
            if [ -f "${CONFIG_FILE}.bak" ]; then
                cp "${CONFIG_FILE}.bak" "$CONFIG_FILE"
                echo -e "${YELLOW}  Backup wiederhergestellt nach Fehler.${NC}"
            fi
        elif [ -n "$OLD_PNL" ] && [ -f "$CONFIG_FILE" ]; then
            # Neues PnL auslesen und vergleichen
            NEW_PNL=$($PYTHON -c "
import json, sys
try:
    d = json.load(open('$CONFIG_FILE'))
    print(d.get('_backtest', {}).get('pnl_pct', ''))
except: pass
" 2>/dev/null)
            # Vergleich: neues PnL schlechter als altes?
            WORSE=$($PYTHON -c "
try:
    old, new = float('$OLD_PNL'), float('$NEW_PNL')
    print('yes' if new < old else 'no')
except: print('no')
" 2>/dev/null)
            if [ "$WORSE" == "yes" ]; then
                cp "${CONFIG_FILE}.bak" "$CONFIG_FILE"
                echo -e "${YELLOW}  Ergebnis schlechter (alt=${OLD_PNL}% > neu=${NEW_PNL}%) — alte Config beibehalten.${NC}"
            else
                echo -e "${GREEN}  Ergebnis verbessert oder gleich (alt=${OLD_PNL}% → neu=${NEW_PNL}%) — neue Config gespeichert.${NC}"
            fi
        fi

        # Backup aufräumen
        rm -f "${CONFIG_FILE}.bak"
    done
done

deactivate
echo -e "\n${BLUE}✔ Alle Pipeline-Aufgaben erfolgreich abgeschlossen!${NC}"
