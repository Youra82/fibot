#!/bin/bash
# FiBot — Update (VPS)
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ">>> Sichere secret.json..."
cp secret.json secret.json.bak

echo ">>> Git update..."
git fetch origin
git reset --hard origin/main

echo ">>> Stelle secret.json wieder her..."
cp secret.json.bak secret.json
rm secret.json.bak

echo ">>> Bereinige Python-Cache..."
find . -type f -name "*.pyc" -delete
find . -type d -name "__pycache__" -delete

echo ">>> Setze Berechtigungen..."
chmod +x *.sh

echo ">>> Update abgeschlossen."
