#!/bin/bash
# FiBot — Sicherheitscheck
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}--- Starte FiBot Sicherheitscheck ---${NC}"

if [ ! -f ".venv/bin/activate" ]; then
    echo -e "${RED}Fehler: Virtuelle Umgebung nicht gefunden. Bitte install.sh ausfuehren.${NC}"
    exit 1
fi
source .venv/bin/activate

echo "Fuehre Pytest aus..."
echo "Hinweis: test_live_confluence_order_on_bitget handelt ECHT auf Bitget (PEPE, ca. 6 USDT, wird sofort"
echo "geschlossen, Kosten wenige Cent). Ueberspringen mit:  FIBOT_SKIP_LIVE=1 ./run_tests.sh"
if python3 -m pytest tests/ -v -s; then
    echo -e "${GREEN}Pytest erfolgreich. Alle Tests bestanden.${NC}"
    EXIT_CODE=0
else
    PYTEST_EXIT_CODE=$?
    if [ $PYTEST_EXIT_CODE -eq 5 ]; then
        echo -e "${GREEN}Pytest beendet: Keine Tests gefunden.${NC}"
        EXIT_CODE=0
    else
        echo -e "${RED}Pytest fehlgeschlagen (Exit Code: $PYTEST_EXIT_CODE).${NC}"
        EXIT_CODE=$PYTEST_EXIT_CODE
    fi
fi

deactivate
echo -e "${BLUE}--- Sicherheitscheck abgeschlossen ---${NC}"
exit $EXIT_CODE
