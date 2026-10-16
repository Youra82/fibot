#!/bin/bash
# fibot/forschung/konfluenz/watch_until.sh ZIEL
# Uebernimmt neue OOS-bestaetigte Configs (auswahl.py --write + lokaler Commit) und beendet die
# Suche, sobald ZIEL bestaetigte Strategien erreicht sind (dann Push). Eine Zeile je Ereignis.
cd "$(dirname "$0")/../.."
PY=.venv/Scripts/python.exe
ZIEL=${1:-40}
DONE=${2:-forschung/konfluenz/day.done}
count() { $PY forschung/konfluenz/auswahl.py 2>/dev/null | head -1 | sed 's/.*Kriterien: \([0-9]*\).*/\1/'; }
cnt=$(count)
echo "Start: $cnt bestaetigt, Ziel $ZIEL"
while true; do
    grep -q "Traceback\|MemoryError" forschung/konfluenz/day4.log forschung/konfluenz/day5.log 2>/dev/null && { echo "FEHLER in Stufe 4/5"; exit 1; }
    c=$(count)
    if [ -n "$c" ] && [ "$c" != "$cnt" ]; then
        ls src/fibot/strategy/configs > /tmp/vv.txt
        $PY forschung/konfluenz/auswahl.py --write > /dev/null
        for f in $(ls src/fibot/strategy/configs | diff /tmp/vv.txt - | grep "^>" | cut -c3-); do
            n=${f:7:-9}; echo "NEU ($cnt -> $c): $($PY forschung/konfluenz/auswahl.py | grep "$n" | tr -s ' ')"
        done
        git add src/fibot/strategy/configs > /dev/null 2>&1
        git commit -q -m "config: weitere OOS-bestaetigte Konfluenz-Config(s), jetzt $c

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" > /dev/null 2>&1
        cnt=$c
    fi
    if [ -n "$cnt" ] && [ "$cnt" -ge "$ZIEL" ]; then
        powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*search.py*' -or \$_.CommandLine -like '*run_day.sh*' -or \$_.CommandLine -like '*run_stage5.sh*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" > /dev/null 2>&1
        echo "ZIEL ERREICHT: $cnt bestaetigte Strategien -- Suche gestoppt, Push: $(git push origin main 2>&1 | tail -1)"
        exit 0
    fi
    [ -f "$DONE" ] && { echo "Suche regulaer beendet bei $cnt"; exit 0; }
    sleep 180
done
