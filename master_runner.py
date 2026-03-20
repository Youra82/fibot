# master_runner.py — FiBot Master Runner
# Reads active strategies from settings.json and launches run.py for each.
# Designed to be called by a cron job (once per interval).

import json
import subprocess
import sys
import os
import time
import logging

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

log_dir  = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'master_runner.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()]
)


def main():
    settings_file = os.path.join(SCRIPT_DIR, 'settings.json')
    secret_file   = os.path.join(SCRIPT_DIR, 'secret.json')
    run_script    = os.path.join(SCRIPT_DIR, 'src', 'fibot', 'strategy', 'run.py')
    python_exe    = os.path.join(SCRIPT_DIR, '.venv', 'bin', 'python3')

    if not os.path.exists(python_exe):
        logging.critical(f"Python-Interpreter nicht gefunden: {python_exe}")
        return

    logging.info("=" * 55)
    logging.info("FiBot Master Runner")
    logging.info("=" * 55)

    try:
        with open(settings_file, 'r') as f:
            settings = json.load(f)
        with open(secret_file, 'r') as f:
            secrets = json.load(f)
    except FileNotFoundError as e:
        logging.critical(f"Datei nicht gefunden: {e}")
        return
    except json.JSONDecodeError as e:
        logging.critical(f"JSON-Fehler: {e}")
        return

    if not secrets.get('fibot'):
        logging.critical("Kein 'fibot'-Account in secret.json gefunden.")
        return

    live_settings    = settings.get('live_trading_settings', {})
    active_strategies = live_settings.get('active_strategies', [])

    if not active_strategies:
        logging.warning("Keine aktiven Strategien in settings.json.")
        return

    processes = []
    for strategy in active_strategies:
        if not strategy.get('active', False):
            continue
        symbol    = strategy['symbol']
        timeframe = strategy['timeframe']
        logging.info(f"  Starte: {symbol} ({timeframe})")

        cmd = [python_exe, run_script, '--symbol', symbol, '--timeframe', timeframe]
        proc = subprocess.Popen(cmd, cwd=SCRIPT_DIR)
        processes.append((symbol, timeframe, proc))
        time.sleep(0.5)

    # Wait for all to finish
    for symbol, timeframe, proc in processes:
        try:
            proc.wait(timeout=300)  # max 5 min per run
            rc = proc.returncode
            if rc != 0:
                logging.warning(f"  {symbol} ({timeframe}) beendet mit Code {rc}")
            else:
                logging.info(f"  {symbol} ({timeframe}) erfolgreich abgeschlossen.")
        except subprocess.TimeoutExpired:
            logging.error(f"  {symbol} ({timeframe}) Timeout! Prozess wird beendet.")
            proc.kill()

    logging.info("Master Runner abgeschlossen.")


if __name__ == "__main__":
    main()
