#!/bin/bash
# Stufe 5 (16.10.): 16 weitere Coins (>= 2 Mio USDT/Tag), startet nach run_day.sh
cd "$(dirname "$0")/../.."
PY=.venv/Scripts/python.exe; [ -x "$PY" ] || PY=.venv/bin/python3
L=forschung/konfluenz
until [ -f $L/day.done ]; do sleep 60; done
echo "Stufe 5 $(date +%H:%M)" >> $L/day.log
$PY $L/search.py 6 --coins ETHFI JUP SHIB MAGIC --tfs 4h 2h 1h 30m 15m --start 2024-04-01 > $L/day5.log 2>&1
$PY $L/search.py 6 --coins ZRO ANIME S VIRTUAL RAY FARTCOIN EPIC GRASS AERO VVV MUBARAK BR --tfs 4h 2h 1h 30m 15m --start 2025-04-01 >> $L/day5.log 2>&1
echo "FERTIG $(date +%H:%M)" > $L/stage5.done
