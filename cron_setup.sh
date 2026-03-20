#!/bin/bash
# FiBot — Cron-Job einrichten (VPS)
# Läuft alle 4 Stunden (passend zum 4h Timeframe)
# Für andere Timeframes anpassen:
#   1h  → */1 * * * *  (jede Stunde)
#   4h  → 0 */4 * * *  (alle 4 Stunden)
#   1d  → 0 0 * * *    (täglich Mitternacht)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_CMD="0 */4 * * * cd $SCRIPT_DIR && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1"

echo "Füge Cron-Job hinzu:"
echo "  $CRON_CMD"
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
echo "Cron-Job eingerichtet."
crontab -l
