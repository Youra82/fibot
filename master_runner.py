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
from fibot.utils.team_history import record_team, strategy_key
from fibot.utils.papier import echtgeld_aktiv

log_dir  = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'master_runner.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()]
)


def _run_auto_optimizer():
    """Startet den Auto-Optimizer-Scheduler non-blocking im Hintergrund."""
    scheduler  = os.path.join(SCRIPT_DIR, 'auto_optimizer_scheduler.py')
    python_exe = os.path.join(SCRIPT_DIR, '.venv', 'bin', 'python3')
    if not os.path.exists(scheduler) or not os.path.exists(python_exe):
        return
    log_path = os.path.join(SCRIPT_DIR, 'logs', 'auto_optimizer.log')
    try:
        subprocess.Popen(
            [python_exe, scheduler],
            stdout=open(log_path, 'a'),
            stderr=subprocess.STDOUT,
            cwd=SCRIPT_DIR,
        )
        logging.info("[Auto-Optimizer] Scheduler gestartet (prüft ob Optimierung fällig).")
    except Exception as e:
        logging.warning(f"[Auto-Optimizer] Konnte Scheduler nicht starten: {e}")


def _run_daily_check():
    """Taeglicher Live-vs-Backtest-Abgleich im Hintergrund (prueft selbst, ob faellig)."""
    script     = os.path.join(SCRIPT_DIR, 'daily_live_vs_backtest_check.py')
    python_exe = os.path.join(SCRIPT_DIR, '.venv', 'bin', 'python3')
    if not os.path.exists(script) or not os.path.exists(python_exe):
        return
    try:
        subprocess.Popen([python_exe, script],
                         stdout=open(os.path.join(SCRIPT_DIR, 'logs', 'daily_live_vs_backtest_check.log'), 'a'),
                         stderr=subprocess.STDOUT, cwd=SCRIPT_DIR)
    except Exception as e:
        logging.warning(f"[Live-vs-Backtest] Konnte Tagescheck nicht starten: {e}")


def melde_umschaltung(papier, secrets):
    """Modus merken; bei einem Wechsel einmal per Telegram melden (wie jaegerbot/zockerbot)."""
    pfad = os.path.join(PROJECT_ROOT, 'artifacts', 'modus.json')
    neu = 'papier' if papier else 'echtgeld'
    try:
        with open(pfad, encoding='utf-8') as f:
            alt = json.load(f).get('modus')
    except (OSError, ValueError):
        alt = None
    if alt == neu:
        return
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, 'w', encoding='utf-8') as f:
        json.dump({'modus': neu}, f)
    if alt is None and not papier:
        return                       # Erstlauf im bisherigen Echtgeld-Betrieb: nichts zu melden
    text = ("FiBot umgeschaltet auf ECHTGELD: ab jetzt echte Orders auf Bitget." if not papier else
            "FiBot umgeschaltet auf PAPIER: keine echten Orders mehr (Konto artifacts/papier/konto.json). "
            "Wartende echte Entry-Limits werden storniert; laufende Echtgeld-Positionen behalten SL/TP auf Bitget.")
    logging.info(text)
    try:
        from fibot.utils.telegram import send_message
        tg = secrets.get('telegram', {})
        if tg.get('bot_token') and tg.get('chat_id'):
            send_message(tg['bot_token'], tg['chat_id'], text)
    except Exception:
        pass


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

    # Auto-Optimizer im Hintergrund starten (non-blocking)
    _run_auto_optimizer()

    try:
        with open(settings_file, 'r') as f:
            settings = json.load(f)
        papier = not echtgeld_aktiv(settings)
        if papier and not os.path.exists(secret_file):
            secrets = {}             # Papier laeuft ohne Schluessel (dann ohne Telegram)
        else:
            with open(secret_file, 'r') as f:
                secrets = json.load(f)
    except FileNotFoundError as e:
        logging.critical(f"Datei nicht gefunden: {e}")
        return
    except json.JSONDecodeError as e:
        logging.critical(f"JSON-Fehler: {e}")
        return

    melde_umschaltung(papier, secrets)
    logging.info(f"Modus: {'PAPIER (keine echten Orders, artifacts/papier/konto.json)' if papier else 'ECHTGELD'}")
    if not papier and not secrets.get('fibot'):
        logging.critical("Kein 'fibot'-Account in secret.json gefunden.")
        return

    live_settings    = settings.get('live_trading_settings', {})
    active_strategies = live_settings.get('active_strategies', [])

    if not active_strategies:
        logging.warning("Keine aktiven Strategien in settings.json.")
        return

    # Taeglicher Live-vs-Backtest-Abgleich liest das echte Bitget-Konto -> nur im Echtgeld-Betrieb
    if not papier:
        _run_daily_check()

    # Housekeeper: Entry-Orders von Symbolen ausserhalb active_strategies (nach Portfolio-Wechsel
    # liegengeblieben) stornieren -- sonst werden sie spaeter ungesteuert gefuellt.
    # Papiermodus: auf Bitget kuemmert sich kein Prozess mehr um echte Entry-Limits -> alle stornieren
    # (tradeSide 'open'; SL/TP laufender Echtgeld-Positionen bleiben). Papier-Orders wie gewohnt.
    active_symbols = {s['symbol'] for s in active_strategies if s.get('active', False)}
    if papier:
        try:
            from fibot.utils.exchange import PapierExchange
            from fibot.utils.papier import startkapital
            konto = os.path.join(PROJECT_ROOT, 'artifacts', 'papier', 'konto.json')
            for sym, oid in PapierExchange(konto, startkapital(settings, 100.0)).cancel_stale_entry_orders(active_symbols):
                logging.warning(f"Housekeeper (Papier): Order {oid} auf {sym} ausserhalb des Portfolios storniert.")
        except Exception as e:
            logging.error(f"Housekeeper (Papier) fehlgeschlagen: {e}")
    try:
        from fibot.utils.exchange import Exchange
        from fibot.utils.telegram import send_message
        if papier and not secrets.get('fibot'):
            raise LookupError('kein Bitget-Konto in secret.json -- echte Entry-Limits nicht geprueft')
        acc = secrets['fibot'][0] if isinstance(secrets['fibot'], list) else secrets['fibot']
        cancelled = Exchange(acc).cancel_stale_entry_orders(set() if papier else active_symbols)
        for sym, oid in cancelled:
            logging.warning(f"Housekeeper: liegengebliebene Entry-Order {oid} auf {sym} "
                            f"(nicht in active_strategies) storniert.")
        if cancelled:
            tg = secrets.get('telegram', {})
            send_message(tg.get('bot_token'), tg.get('chat_id'),
                         "FiBot Housekeeper: alte Entry-Order(s) ausserhalb des Portfolios storniert: "
                         + ", ".join(s.split('/')[0] for s, _ in cancelled))
    except Exception as e:
        logging.error(f"Housekeeper: Stornieren alter Entry-Orders fehlgeschlagen: {e}")

    processes = []
    started_keys = []
    for strategy in active_strategies:
        if not strategy.get('active', False):
            continue
        symbol    = strategy['symbol']
        timeframe = strategy['timeframe']
        logging.info(f"  Starte: {symbol} ({timeframe})")
        started_keys.append(strategy_key(symbol, timeframe))

        cmd = [python_exe, run_script, '--symbol', symbol, '--timeframe', timeframe]
        env = {**os.environ, 'FIBOT_PAPIER': '1' if papier else '0'}
        proc = subprocess.Popen(cmd, cwd=SCRIPT_DIR, env=env)
        processes.append((symbol, timeframe, proc))
        time.sleep(3.0)

    # Teamhistorie: welches Portfolio ab wann live lief (fuer Live-vs-Backtest-Abgleich)
    try:
        if not papier and record_team(started_keys, source='master_runner'):
            logging.info(f"Teamhistorie: neues Team aufgezeichnet ({len(started_keys)} Strategien).")
    except Exception as e:
        logging.warning(f"Teamhistorie nicht geschrieben: {e}")

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
