#!/bin/bash
# FiBot — Installation
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ">>> Erstelle virtuelle Umgebung..."
python3 -m venv .venv

echo ">>> Installiere Abhängigkeiten..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo ">>> Erstelle notwendige Verzeichnisse..."
mkdir -p artifacts/tracker artifacts/results logs

echo ">>> Installation abgeschlossen."
echo "Kopiere jetzt secret.json.template → secret.json und füge deine API-Keys ein."
