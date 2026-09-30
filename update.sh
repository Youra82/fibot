#!/bin/bash
# FiBot — Update (VPS)
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIGS_DIR="src/fibot/strategy/configs"

echo ">>> Sichere secret.json..."
cp secret.json secret.json.bak

# Der Auto-Optimizer schreibt auf dem VPS eigene Configs (auch fuer Coins, die es im
# Repo gar nicht gibt, z.B. PEPE) und das aktive Portfolio in settings.json. Beides
# wird nie automatisch nach GitHub gepusht -- ohne Sicherung wuerde git reset --hard
# jeden Deploy auf den letzten gepushten (ggf. monatealten) Stand zuruecksetzen.
# Gleiches Muster wie ltbbot (Fix 2026-09-24).
echo ">>> Sichere Configs und aktives Portfolio..."
if [ -d "$CONFIGS_DIR" ]; then
    rm -rf configs.bak
    cp -r "$CONFIGS_DIR" configs.bak
fi
SAVED_STRATEGIES=""
SAVED_MAX_POS=""
if [ -f settings.json ]; then
    SAVED_STRATEGIES=$(python3 -c "import json; s=json.load(open('settings.json')); print(json.dumps(s.get('live_trading_settings',{}).get('active_strategies',[])))" 2>/dev/null || true)
    SAVED_MAX_POS=$(python3 -c "import json; s=json.load(open('settings.json')); print(json.dumps(s.get('live_trading_settings',{}).get('max_open_positions')))" 2>/dev/null || true)
fi

echo ">>> Git update..."
git fetch origin
git reset --hard origin/main

echo ">>> Stelle secret.json wieder her..."
cp secret.json.bak secret.json
rm secret.json.bak

# VPS-eigene Configs gewinnen ueber den git-Stand; neue, nur in git existierende
# Configs bleiben erhalten (nur ueberschreiben, nie loeschen).
if [ -d configs.bak ]; then
    cp -r configs.bak/. "$CONFIGS_DIR"/
    rm -rf configs.bak
    echo "    Configs (VPS-eigene Optimizer-Ergebnisse) wiederhergestellt."
fi
if [ -n "$SAVED_STRATEGIES" ] && [ "$SAVED_STRATEGIES" != "[]" ]; then
    SAVED_STRATEGIES="$SAVED_STRATEGIES" SAVED_MAX_POS="$SAVED_MAX_POS" python3 -c "
import json, os
s = json.load(open('settings.json'))
lt = s.setdefault('live_trading_settings', {})
lt['active_strategies'] = json.loads(os.environ['SAVED_STRATEGIES'])
max_pos = json.loads(os.environ.get('SAVED_MAX_POS') or 'null')
if max_pos is not None:
    lt['max_open_positions'] = max_pos
json.dump(s, open('settings.json', 'w'), indent=2)
" && echo "    active_strategies wiederhergestellt."
fi

echo ">>> Bereinige Python-Cache..."
find . -type f -name "*.pyc" -delete
find . -type d -name "__pycache__" -delete

echo ">>> Setze Berechtigungen..."
chmod +x *.sh

echo ">>> Update abgeschlossen."
