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

# Warnung bei kleinem Kapital: mit hohem eff. Risiko/Trade ist max_dd=30% kaum erreichbar.
# Der Optimizer würde intern auf 99% anheben — hier explizit fragen.
if (( $(echo "$START_CAPITAL < 50" | bc -l) )); then
    MIN_DD_SMALL=99
    if (( $(echo "$MAX_DD < $MIN_DD_SMALL" | bc -l) )); then
        echo ""
        echo -e "${YELLOW}HINWEIS: Bei ${START_CAPITAL} USDT Kapital und 14% eff. Risiko/Trade${NC}"
        echo -e "${YELLOW}         sind nach 2 Verlusten bereits ~26% Drawdown erreicht.${NC}"
        echo -e "${YELLOW}         Max-DD=${MAX_DD}% ist daher zu streng — der Optimizer${NC}"
        echo -e "${YELLOW}         wuerde 0 valide Configs finden.${NC}"
        read -p "Max-DD automatisch auf ${MIN_DD_SMALL}% anheben? (j/n) [Standard: j]: " RAISE_DD
        RAISE_DD="${RAISE_DD:-j}"
        if [ "$RAISE_DD" == "j" ]; then
            MAX_DD=$MIN_DD_SMALL
            echo -e "${GREEN}Max-DD wird auf ${MAX_DD}% gesetzt.${NC}"
        else
            echo -e "${YELLOW}Behalte Max-DD=${MAX_DD}%. Moeglicherweise werden 0 Configs gefunden.${NC}"
            # In diesem Fall: adaptive override im Optimizer NICHT anwenden
            # -> deaktiviere min_max_dd durch sehr kleines Kapital-Limit-Bypass
        fi
    fi
fi

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
        fi
    done
done

deactivate
echo -e "\n${BLUE}✔ Alle Pipeline-Aufgaben erfolgreich abgeschlossen!${NC}"
