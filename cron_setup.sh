#!/bin/bash
# FiBot — Cron-Job einrichten (VPS)
# Alle 15 Minuten: die Konfluenz-Strategie legt ihre Limit-Order zu Beginn jeder Kerze
# und zieht sie mit der Kanallinie nach -- das braucht einen kurzen Takt, unabhaengig
# vom Timeframe der Strategien. master_runner.py startet alle aktiven Strategien.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_CMD="*/15 * * * * cd $SCRIPT_DIR && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1"

echo "Füge Cron-Job hinzu:"
echo "  $CRON_CMD"
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
echo "Cron-Job eingerichtet."
crontab -l
