#!/bin/bash
# FiBot — Parameter-Optimierungs-Pipeline (Fibo-Kanal-Konfluenz)
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}======================================================="
echo "   FiBot — Fibo-Kanal-Konfluenz Optimierungs-Pipeline"
echo -e "=======================================================${NC}"

VENV_PATH=".venv/bin/activate"
PYTHON=".venv/bin/python3"
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
if [ -z "${SYMBOLS// }" ] || [ -z "${TIMEFRAMES// }" ]; then
    echo -e "${RED}Fehler: Handelspaar und Zeitfenster sind Pflicht. Abbruch.${NC}"
    exit 1
fi

echo -e "\n${BLUE}--- Empfehlung: Rückblick-Zeitraum ---${NC}"
printf "+-------------+--------------------------------+\n"
printf "| Zeitfenster | Empfohlener Rückblick (Tage)   |\n"
printf "+-------------+--------------------------------+\n"
printf "| 15m, 30m    | 365 Tage                       |\n"
printf "| 1h - 1d     | 1095 - 1280 Tage               |\n"
printf "+-------------+--------------------------------+\n"
read -p "Startdatum (JJJJ-MM-TT) oder 'a' für Automatik [Standard: a]: " START_DATE_INPUT
START_DATE_INPUT="${START_DATE_INPUT:-a}"
read -p "Enddatum (JJJJ-MM-TT) [Standard: Heute]: " END_DATE
END_DATE="${END_DATE:-$(date +%F)}"
echo -e "${YELLOW}Optimiert wird nur bis zum OOS-Start; danach wird die Config unverändert getestet (Out-of-Sample).${NC}"
read -p "OOS-Start (JJJJ-MM-TT) [Standard: 180 Tage vor Enddatum]: " OOS_FROM
OOS_FROM="${OOS_FROM:-$(date -d "$END_DATE -180 days" +%F)}"
read -p "Startkapital in USDT [Standard: 100]: " START_CAPITAL
START_CAPITAL="${START_CAPITAL:-100}"
read -p "Anzahl Trials [Standard: 150]: " N_TRIALS
N_TRIALS="${N_TRIALS:-150}"
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
    # Konfluenz-Trades: wenige Treffer mit hohem Chance-Risiko -> Win-Rate typ. 20-35 %
    read -p "Min Win-Rate % [Standard: 20]: " MIN_WR
    MIN_WR="${MIN_WR:-20}"
else
    MIN_WR=0
fi

PIPELINE_START=$(date +%s)

for symbol in $SYMBOLS; do
    for timeframe in $TIMEFRAMES; do

        # --- Datumsberechnung ---
        if [ "$START_DATE_INPUT" == "a" ]; then
            lookback_days=1280
            case "$timeframe" in
                5m|15m|30m) lookback_days=365 ;;
            esac
            FINAL_START_DATE=$(date -d "$lookback_days days ago" +%F)
            echo -e "${YELLOW}INFO: Automatisches Startdatum für $timeframe (${lookback_days} Tage Rückblick): $FINAL_START_DATE${NC}"
        else
            FINAL_START_DATE="$START_DATE_INPUT"
        fi

        echo -e "\n${BLUE}=======================================================${NC}"
        echo -e "${BLUE}  Bearbeite Pipeline für: $symbol ($timeframe)${NC}"
        echo -e "${BLUE}  In-Sample: $FINAL_START_DATE bis $OOS_FROM | OOS: $OOS_FROM bis $END_DATE${NC}"
        echo -e "${BLUE}=======================================================${NC}"

        echo -e "\n${GREEN}>>> Starte Konfluenz-Optimierung für $symbol ($timeframe)...${NC}"
        $PYTHON "$OPTIMIZER" \
            --strategy confluence \
            --oos-from "$OOS_FROM" \
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
        fi
    done
done

# Zusammenfassung aller in diesem Lauf gespeicherten Configs (Konsole + Telegram)
$PYTHON src/fibot/analysis/pipeline_summary.py --since "$PIPELINE_START" --searched "$SYMBOLS / $TIMEFRAMES"

deactivate
echo -e "\n${BLUE}✔ Alle Pipeline-Aufgaben erfolgreich abgeschlossen!${NC}"
