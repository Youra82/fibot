#!/bin/bash
# fibot/forschung/konfluenz/run_all.sh -- erweiterte Strategiesuche (Konfluenz)
# Stufen nacheinander, schnelle Timeframes zuerst; bereits vorhandene Kandidaten werden uebersprungen.
# Coins: Krypto-Perps >= 5 Mio USDT/Tag mit Historie ab dem jeweiligen In-Sample-Start (universe.json, 15.10.2026).
# Aufruf aus dem fibot-Ordner:  bash forschung/konfluenz/run_all.sh
set -u
cd "$(dirname "$0")/../.."
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python3
LOG=forschung/konfluenz

C2023="BTC ETH SOL XRP NEAR DOGE ADA LINK UNI BNB FIL AVAX XLM DOT BCH HBAR ARB AAVE FET CRV BLUR APT LTC INJ OP BAT RSR"
C2024="$C2023 SUI STRK PEPE WLD ONDO QNT PYTH TIA SEI"
C2025="$C2024 HYPE WAL ENA NIL TRUMP SIREN ZK TAO ARC AVA PENGU RENDER W"

echo "Stufe A: 6h 4h 2h 1h ($(date +%H:%M))"
$PY $LOG/search.py 8 --coins $C2023 --tfs 6h 4h 2h 1h > $LOG/searchA.log 2>&1
echo "Stufe B: 30m ($(date +%H:%M))"
$PY $LOG/search.py 8 --coins $C2024 --tfs 30m > $LOG/searchB.log 2>&1
echo "Stufe C: 15m ($(date +%H:%M))"
$PY $LOG/search.py 6 --coins $C2025 --tfs 15m > $LOG/searchC.log 2>&1
echo "Stufe D: 5m ($(date +%H:%M))"
$PY $LOG/search.py 5 --coins $C2025 --tfs 5m > $LOG/searchD.log 2>&1
echo "FERTIG ($(date +%H:%M))"
