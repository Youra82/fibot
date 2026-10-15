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
# Ausnahme Strategie-Wechsel (Fibo -> Fibo-Kanal-Konfluenz, 2026-10): eine Konfluenz-Config
# aus git wird nie von einer alten Fibo-Config des VPS ueberschrieben. Alte Fibo-Configs
# wandern nach configs_alt_fibo/ (nicht geloescht), und das aktive Portfolio kommt dann
# aus dem git-Stand von settings.json, weil das alte nur Fibo-Configs referenziert.
MIGRATED=0
if [ -d configs.bak ]; then
    MIGRATED=$(CONFIGS_DIR="$CONFIGS_DIR" python3 - <<'PYEOF2'
import json, os, shutil
cfg_dir = os.environ['CONFIGS_DIR']
bak, alt = 'configs.bak', os.path.join(os.path.dirname(cfg_dir), 'configs_alt_fibo')
def is_conf(path):
    try:
        return json.load(open(path)).get('strategy', {}).get('type') == 'confluence'
    except Exception:
        return False
git_has_conf = any(is_conf(os.path.join(cfg_dir, f)) for f in os.listdir(cfg_dir) if f.endswith('.json'))
for f in os.listdir(bak):
    src, dst = os.path.join(bak, f), os.path.join(cfg_dir, f)
    if git_has_conf and os.path.exists(dst) and is_conf(dst) and not is_conf(src):
        continue
    shutil.copy2(src, dst)
moved = 0
if git_has_conf:
    os.makedirs(alt, exist_ok=True)
    for f in os.listdir(cfg_dir):
        path = os.path.join(cfg_dir, f)
        if f.endswith('.json') and not is_conf(path):
            shutil.move(path, os.path.join(alt, f))
            moved += 1
print(1 if moved else 0)
PYEOF2
)
    rm -rf configs.bak
    echo "    Configs (VPS-eigene Optimizer-Ergebnisse) wiederhergestellt."
    [ "$MIGRATED" == "1" ] && echo "    Alte Fibo-Configs nach configs_alt_fibo/ verschoben (Strategie-Wechsel)."
fi
if [ "$MIGRATED" != "1" ] && [ -n "$SAVED_STRATEGIES" ] && [ "$SAVED_STRATEGIES" != "[]" ]; then
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
