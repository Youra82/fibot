#!/usr/bin/env python3
# auto_optimizer_scheduler.py — FiBot Auto-Optimizer-Scheduler
#
# Wird von master_runner.py beim Start non-blocking aufgerufen.
# Prüft ob eine Portfolio-Optimierung fällig ist und führt sie
# automatisch aus (show_results.py --mode 3 --auto).
# Schreibt danach active_strategies in settings.json.

import json
import os
import sys
import subprocess
import logging
from datetime import datetime, timedelta

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT     = SCRIPT_DIR
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

SETTINGS_FILE    = os.path.join(PROJECT_ROOT, 'settings.json')
OPT_RESULTS_FILE = os.path.join(PROJECT_ROOT, 'artifacts', 'results', 'optimization_results.json')
CONFIGS_DIR      = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')
LAST_RUN_FILE    = os.path.join(PROJECT_ROOT, '.last_optimization_run')
IN_PROGRESS_FILE = os.path.join(PROJECT_ROOT, '.optimization_in_progress')
PYTHON_EXE       = os.path.join(PROJECT_ROOT, '.venv', 'bin', 'python3')
SHOW_RESULTS     = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'analysis', 'show_results.py')

log_dir = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'auto_optimizer.log')),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def _load_settings() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception as e:
        log.error(f"settings.json lesen fehlgeschlagen: {e}")
        return {}


def _interval_seconds(interval: dict) -> int:
    value = int(interval.get('value', 7))
    unit  = interval.get('unit', 'days')
    mult  = {'minutes': 60, 'hours': 3600, 'days': 86400, 'weeks': 604800}
    return value * mult.get(unit, 86400)


def _is_due(schedule: dict) -> tuple[bool, str]:
    """Gibt (fällig, grund) zurück."""
    now = datetime.now()

    # Verhindere parallele Läufe (max. 2h Laufzeit)
    if os.path.exists(IN_PROGRESS_FILE):
        age = now.timestamp() - os.path.getmtime(IN_PROGRESS_FILE)
        if age < 7200:
            return False, 'in_progress'
        os.remove(IN_PROGRESS_FILE)  # stale lock bereinigen
        log.warning("Stale in-progress-Lock entfernt.")

    # Erster Lauf
    if not os.path.exists(LAST_RUN_FILE):
        return True, 'first_run'

    with open(LAST_RUN_FILE) as f:
        last_run = datetime.fromisoformat(f.read().strip())

    # Interval-Check
    interval   = schedule.get('interval', {'value': 7, 'unit': 'days'})
    interval_s = _interval_seconds(interval)
    elapsed    = (now - last_run).total_seconds()
    if elapsed >= interval_s:
        return True, f'interval ({elapsed / 3600:.1f}h seit letztem Lauf)'

    # Wochenplan-Check (Wochentag + Stunde, 15-Min-Fenster)
    dow    = schedule.get('day_of_week', -1)
    hour   = schedule.get('hour',   -1)
    minute = schedule.get('minute',  0)
    if dow >= 0 and now.weekday() == dow and now.hour == hour:
        window_start = now.replace(minute=minute, second=0, microsecond=0)
        if abs((now - window_start).total_seconds()) <= 900:
            if (now.date() - last_run.date()).days >= 1:
                return True, f'scheduled (Wochentag {dow}, {hour:02d}:{minute:02d})'

    return False, 'not_due'


def _telegram_send(bot_token: str, chat_id: str, message: str):
    if not bot_token or not chat_id:
        return
    try:
        from fibot.utils.telegram import send_message
        send_message(bot_token, chat_id, message)
    except Exception as e:
        log.warning(f"Telegram-Fehler: {e}")


def _update_settings(portfolio_files: list) -> bool:
    """Schreibt das optimale Portfolio als active_strategies in settings.json."""
    try:
        strategies = []
        for fname in portfolio_files:
            cfg_path = os.path.join(CONFIGS_DIR, fname)
            if not os.path.exists(cfg_path):
                log.warning(f"Config nicht gefunden: {fname}")
                continue
            with open(cfg_path) as f:
                cfg = json.load(f)
            market = cfg.get('market', {})
            risk   = cfg.get('risk',   {})
            strategies.append({
                'symbol':             market.get('symbol',             ''),
                'timeframe':          market.get('timeframe',          ''),
                'leverage':           risk.get('leverage',             10),
                'margin_mode':        risk.get('margin_mode',   'isolated'),
                'risk_per_entry_pct': risk.get('risk_per_entry_pct', 1.0),
                'active':             True,
            })

        if not strategies:
            log.error("Keine gültigen Strategien zum Schreiben.")
            return False

        with open(SETTINGS_FILE) as f:
            settings = json.load(f)
        settings.setdefault('live_trading_settings', {})['active_strategies'] = strategies
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)

        log.info(f"settings.json aktualisiert — {len(strategies)} Strategie(n):")
        for s in strategies:
            log.info(f"  {s['symbol']} ({s['timeframe']})  lev={s['leverage']}x  risk={s['risk_per_entry_pct']}%")
        return True

    except Exception as e:
        log.error(f"settings.json Update fehlgeschlagen: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='FiBot Auto-Optimizer-Scheduler')
    parser.add_argument('--force', action='store_true',
                        help='Optimierung sofort erzwingen (ignoriert enabled + Schedule)')
    args = parser.parse_args()

    settings = _load_settings()
    opt_cfg  = settings.get('optimization_settings', {})

    if args.force:
        log.info("--force gesetzt: Optimierung wird sofort gestartet.")
        reason = 'force'
    else:
        if not opt_cfg.get('enabled', False):
            log.info("Auto-Optimizer deaktiviert (enabled: false).")
            return

        schedule = opt_cfg.get('schedule', {})
        due, reason = _is_due(schedule)

        if not due:
            log.info(f"Optimierung nicht fällig ({reason}).")
            return

    log.info("=" * 55)
    log.info(f"Starte Auto-Optimierung — Grund: {reason}")
    log.info("=" * 55)

    # Telegram-Credentials lesen
    bot_token, chat_id = '', ''
    try:
        with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
            secrets = json.load(f)
        tg        = secrets.get('telegram', {})
        bot_token = tg.get('bot_token', '')
        chat_id   = tg.get('chat_id',   '')
    except Exception:
        pass

    send_tg = opt_cfg.get('send_telegram_on_completion', False)

    # In-progress Marker setzen
    open(IN_PROGRESS_FILE, 'w').close()

    start_time = datetime.now()
    try:
        capital  = float(opt_cfg.get('start_capital',     1000))
        max_dd   = float(opt_cfg.get('max_drawdown_pct',   30))
        min_wr   = float(opt_cfg.get('min_win_rate_pct',    0))

        # Aktive Coins aus settings.json lesen (nur diese optimieren)
        active_symbols = []
        for s in settings.get('live_trading_settings', {}).get('active_strategies', []):
            sym = s.get('symbol', '')
            coin = sym.split('/')[0]
            if coin and coin not in active_symbols:
                active_symbols.append(coin)
        log.info(f"Aktive Coins aus settings.json: {active_symbols}")

        # Lookback automatisch aus den Configs der aktiven Coins bestimmen
        lookback_setting = opt_cfg.get('lookback_days', 'auto')
        if str(lookback_setting).lower() == 'auto':
            from fibot.analysis.backtester import auto_days_for_timeframe
            max_days = 365  # Fallback
            try:
                for fname in os.listdir(CONFIGS_DIR):
                    if not (fname.startswith('config_') and fname.endswith('.json')):
                        continue
                    # nur Configs der aktiven Coins berücksichtigen
                    if active_symbols and not any(
                        fname.upper().startswith(f'CONFIG_{c}') for c in active_symbols
                    ):
                        continue
                    with open(os.path.join(CONFIGS_DIR, fname)) as f:
                        cfg = json.load(f)
                    tf = cfg.get('market', {}).get('timeframe', '')
                    if tf:
                        max_days = max(max_days, auto_days_for_timeframe(tf))
            except Exception as e:
                log.warning(f"Lookback-Auto-Berechnung fehlgeschlagen, nutze 365: {e}")
            lookback = max_days
            log.info(f"Lookback auto: {lookback} Tage")
        else:
            lookback = int(lookback_setting)

        date_from = (datetime.now() - timedelta(days=lookback)).strftime('%Y-%m-%d')
        date_to   = datetime.now().strftime('%Y-%m-%d')

        log.info(f"Parameter: Kapital={capital} USDT | MaxDD={max_dd}% | WR>={min_wr}% | "
                 f"Zeitraum: {date_from} → {date_to}")

        # Pairs-String für Startnachricht: nur aktive Coins + ihre Configs
        pairs_str = ', '.join(active_symbols) if active_symbols else 'alle Coins'
        try:
            pairs = []
            for fname in sorted(os.listdir(CONFIGS_DIR)):
                if not (fname.startswith('config_') and fname.endswith('.json')):
                    continue
                if active_symbols and not any(
                    fname.upper().startswith(f'CONFIG_{c}') for c in active_symbols
                ):
                    continue
                with open(os.path.join(CONFIGS_DIR, fname)) as f:
                    cfg = json.load(f)
                sym = cfg.get('market', {}).get('symbol', '')
                tf  = cfg.get('market', {}).get('timeframe', '')
                if sym and tf:
                    pairs.append(f"{sym.split('/')[0]}/{tf}")
            if pairs:
                pairs_str = ', '.join(pairs)
        except Exception:
            pass

        if send_tg:
            _telegram_send(bot_token, chat_id,
                f"FiBot Auto-Optimizer GESTARTET\n"
                f"Paare: {pairs_str}\n"
                f"Kapital: {capital} USDT | MaxDD: {max_dd}% | {lookback} Tage\n"
                f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        cmd = [
            PYTHON_EXE, SHOW_RESULTS,
            '--mode',          '3',
            '--capital',       str(capital),
            '--target-max-dd', str(max_dd),
            '--min-wr',        str(min_wr),
            '--from',          date_from,
            '--to',            date_to,
            '--auto',
        ]
        if active_symbols:
            cmd += ['--symbols', ' '.join(active_symbols)]

        proc = subprocess.run(
            cmd, cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=3600,
        )

        # Log-Ausgabe (letzte 5000 Zeichen reichen)
        output = proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout
        log.info(f"show_results.py Ausgabe:\n{output}")

        if proc.returncode != 0:
            log.error(f"show_results.py Fehler (rc={proc.returncode}):\n{proc.stderr[-1000:]}")
            if send_tg:
                _telegram_send(bot_token, chat_id,
                    f"FiBot Auto-Optimierung FEHLER (rc={proc.returncode})\n"
                    f"{proc.stderr[-300:]}")
            return

        # Ergebnis lesen
        if not os.path.exists(OPT_RESULTS_FILE):
            log.error("optimization_results.json nicht gefunden.")
            return

        with open(OPT_RESULTS_FILE) as f:
            opt = json.load(f)
        portfolio_files = opt.get('optimal_portfolio', [])

        if not portfolio_files:
            log.warning("Kein optimales Portfolio in optimization_results.json.")
            if send_tg:
                _telegram_send(bot_token, chat_id,
                    "FiBot Auto-Optimierung: Kein Portfolio gefunden.")
            return

        success = _update_settings(portfolio_files)
        elapsed = (datetime.now() - start_time).total_seconds()

        # Last-run Timestamp speichern
        with open(LAST_RUN_FILE, 'w') as f:
            f.write(datetime.now().isoformat())

        if success and send_tg:
            strat_lines = '\n'.join(f"  - {fn}" for fn in portfolio_files)
            _telegram_send(bot_token, chat_id,
                f"FiBot Auto-Optimierung abgeschlossen ({elapsed / 60:.1f} min)\n"
                f"Kapital: {capital} USDT | MaxDD: {max_dd}% | {lookback} Tage\n"
                f"Optimales Portfolio ({len(portfolio_files)} Strategie(n)):\n{strat_lines}")

        log.info(f"Auto-Optimierung erfolgreich abgeschlossen in {elapsed / 60:.1f} min.")

    except subprocess.TimeoutExpired:
        log.error("Timeout: Optimierung hat zu lange gedauert (>60 min).")
        if send_tg:
            _telegram_send(bot_token, chat_id, "FiBot Auto-Optimierung: Timeout!")
    except Exception as e:
        log.error(f"Unerwarteter Fehler: {e}", exc_info=True)
        if send_tg:
            _telegram_send(bot_token, chat_id, f"FiBot Auto-Optimierung FEHLER: {e}")
    finally:
        if os.path.exists(IN_PROGRESS_FILE):
            os.remove(IN_PROGRESS_FILE)


if __name__ == '__main__':
    main()
