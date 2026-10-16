#!/bin/bash
# fibot/forschung/konfluenz/run_day.sh -- Tagessuche 16.10.2026 (Stufen nacheinander, schnelle TF zuerst)
# Kandidaten, die schon existieren, werden uebersprungen. Abbruch von aussen per timeout.
set -u
cd "$(dirname "$0")/../.."
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python3
L=forschung/konfluenz
S=$L/search.py

C2023="BTC ETH SOL XRP NEAR DOGE ADA LINK UNI BNB FIL AVAX XLM DOT BCH HBAR ARB AAVE FET CRV BLUR APT LTC INJ OP BAT RSR"
C2024="SUI STRK PEPE WLD ONDO QNT PYTH TIA SEI"
C2025="HYPE WAL ENA NIL TRUMP SIREN ZK TAO ARC AVA PENGU RENDER W"

echo "Stufe 1 $(date +%H:%M)"; $PY $S 8 --coins $C2025 --tfs 1h 4h 6h 30m --start 2025-04-01 > $L/day1.log 2>&1
echo "Stufe 2 $(date +%H:%M)"; $PY $S 8 --coins $C2024 --tfs 6h --start 2024-04-01 > $L/day2.log 2>&1
echo "Stufe 3 $(date +%H:%M)"; $PY $S 6 --coins $C2023 $C2024 $C2025 --tfs 15m --start 2025-04-01 > $L/day3.log 2>&1
echo "Stufe 4 $(date +%H:%M)"; $PY $S 5 --coins $C2023 $C2024 $C2025 --tfs 5m --start 2025-10-01 > $L/day4.log 2>&1
echo "FERTIG $(date +%H:%M)" > $L/day.done
