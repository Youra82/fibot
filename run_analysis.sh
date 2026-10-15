#!/bin/bash
# run_analysis.sh — FiBot Analysen (Fibo-Kanal-Konfluenz)
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python3"
[ -f "$PYTHON" ] || PYTHON="$SCRIPT_DIR/.venv/Scripts/python.exe"
if [ ! -f "$PYTHON" ]; then
    echo -e "${RED}FEHLER: .venv nicht gefunden. Erst install.sh ausfuehren!${NC}"
    exit 1
fi
cd "$SCRIPT_DIR"

NO_TELEGRAM=""
for arg in "$@"; do
    [ "$arg" = "--no-telegram" ] && NO_TELEGRAM="--no-telegram"
done

echo ""
echo "======================================================="
echo -e "  ${BOLD}FiBot — Analysen (Fibo-Kanal-Konfluenz)${NC}"
echo "======================================================="
echo ""
echo -e "  ${CYAN}── Fundament ───────────────────────────────────────${NC}"
echo "   1) In-Sample vs. Out-of-Sample      (Werte aus der Optimierung)"
echo "   2) Bootstrap-Signifikanz            (R/Trade mit 95 %-Bereich)"
echo "   3) Monte Carlo                      (DD-Verteilung, Verlustwahrscheinlichkeit)"
echo "   4) Gebuehren & Slippage"
echo ""
echo -e "  ${CYAN}── Robustheit ──────────────────────────────────────${NC}"
echo "   5) Parameter-Sensitivitaet          (+- eine Stufe je Parameter)"
echo "   6) Stabilitaet je Quartal"
echo "   7) Long vs. Short"
echo "   8) Regime BTC/SMA200 + Filter S6    (mit und ohne Filter)"
echo ""
echo -e "  ${CYAN}── Portfolio & Risiko ──────────────────────────────${NC}"
echo "   9) Korrelation der Strategien"
echo "  10) Kelly-Sizing"
echo "  11) Drawdown-Dauer"
echo "  12) Wochentag & Tageszeit"
echo ""
echo "   0) Alle Analysen nacheinander"
echo ""
read -p "Auswahl (0-12): " MODE
MODE="${MODE//[$'\r\n ']/}"
if ! [[ "$MODE" =~ ^([0-9]|1[0-2])$ ]]; then
    echo -e "${RED}Ungueltige Auswahl. Abbruch.${NC}"
    exit 1
fi

if [ "$MODE" != "1" ]; then
    read -p "Strategien: (a)ktives Portfolio oder (alle) Configs [Standard: a]: " SC
    SC="${SC//[$'\r\n ']/}"
    SCOPE="aktiv"; [ "$SC" == "alle" ] && SCOPE="alle"
    read -p "Startdatum (JJJJ-MM-TT) [Standard: 2025-01-01]: " SD
    SD="${SD//[$'\r\n ']/}"; SD="${SD:-2025-01-01}"
    read -p "Enddatum   (JJJJ-MM-TT) [Standard: Heute]: " ED
    ED="${ED//[$'\r\n ']/}"; ED="${ED:-$(date +%Y-%m-%d)}"
    read -p "Startkapital in USDT [Standard: 100]: " CAP
    CAP="${CAP//[$'\r\n ']/}"; [[ "$CAP" =~ ^[0-9]+(\.[0-9]+)?$ ]] || CAP=100
else
    SCOPE="alle"; SD="2025-01-01"; ED="$(date +%Y-%m-%d)"; CAP=100
fi

echo ""
"$PYTHON" src/fibot/analysis/analysis_suite.py --analysis "$MODE" --scope "$SCOPE" \
    --from "$SD" --to "$ED" --capital "$CAP" $NO_TELEGRAM
