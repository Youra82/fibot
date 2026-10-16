#!/bin/bash
# Stufe 6 (16.10.): 6h fuer die Stufe-5-Coins + 5 weitere Coins (>= 1 Mio USDT/Tag) auf allen guten TF
cd "$(dirname "$0")/../.."
PY=.venv/Scripts/python.exe; [ -x "$PY" ] || PY=.venv/bin/python3
L=forschung/konfluenz
echo "Stufe 6 $(date +%H:%M)" >> $L/day.log
$PY $L/search.py 8 --coins ETHFI JUP SHIB MAGIC --tfs 6h --start 2024-04-01 > $L/day6.log 2>&1
$PY $L/search.py 8 --coins ZRO ANIME S VIRTUAL RAY FARTCOIN EPIC GRASS AERO VVV MUBARAK BR --tfs 6h --start 2025-04-01 >> $L/day6.log 2>&1
$PY $L/search.py 6 --coins ZIL EIGEN JTO OGN KAS --tfs 6h 4h 2h 1h 30m 15m --start 2025-04-01 >> $L/day6.log 2>&1
echo "FERTIG $(date +%H:%M)" > $L/stage6.done
