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

SETTINGS_FILE     = os.path.join(PROJECT_ROOT, 'settings.json')
CONFIGS_DIR       = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')
LAST_RUN_FILE     = os.path.join(PROJECT_ROOT, '.last_optimization_run')
IN_PROGRESS_FILE  = os.path.join(PROJECT_ROOT, '.optimization_in_progress')
PORTFOLIO_SCRIPT  = os.path.join(PROJECT_ROOT, 'run_portfolio_optimizer.py')

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
    """Sendet eine plain-text Nachricht (kein MarkdownV2 — Emojis + Sonderzeichen unverändert)."""
    if not bot_token or not chat_id:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={'chat_id': chat_id, 'text': message},
            timeout=10,
        )
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
    if send_tg:
        _telegram_send(bot_token, chat_id,
            f"🔍 FiBot Portfolio-Optimizer GESTARTET\n"
            f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Führt frische Backtests aller Configs durch und wählt bestes Portfolio.")

    # In-progress Marker setzen
    open(IN_PROGRESS_FILE, 'w').close()

    try:
        constraints = opt_cfg.get('constraints', {})
        capital    = float(opt_cfg.get('start_capital', 100))
        max_dd     = float(constraints.get('max_drawdown_pct', 30))
        start_date = opt_cfg.get('start_date', 'auto')
        end_date   = opt_cfg.get('end_date',   'auto')

        cmd = [sys.executable, PORTFOLIO_SCRIPT,
               '--capital', str(capital), '--max-dd', str(max_dd), '--auto-write']
        if start_date not in ('auto', '', None):
            cmd += ['--start-date', start_date]
        if end_date not in ('auto', '', None):
            cmd += ['--end-date', end_date]
        log.info(f"Starte Portfolio-Optimizer: {' '.join(str(x) for x in cmd)}")
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, timeout=7200)
        rc   = proc.returncode
        log.info(f"Portfolio-Optimizer beendet (rc={rc}).")

        elapsed = (datetime.now() - start_time).total_seconds()
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)
        dur_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

        # Last-run Timestamp speichern
        with open(LAST_RUN_FILE, 'w') as f:
            f.write(datetime.now().isoformat())

        if send_tg:
            if rc == 0:
                try:
                    with open(SETTINGS_FILE) as sf:
                        stg = json.load(sf)
                    active = [s for s in stg.get('live_trading_settings', {})
                              .get('active_strategies', []) if s.get('active')]
                    lines = [f"✅ FiBot Portfolio-Optimizer abgeschlossen (Dauer: {dur_str})"]
                    if active:
                        lines.append(f"\n✔ Aktives Portfolio ({len(active)} Strategie(n)):")
                        for s in active:
                            lines.append(f"• {s['symbol'].split('/')[0]}/{s['timeframe']}")
                    _telegram_send(bot_token, chat_id, '\n'.join(lines))
                except Exception:
                    _telegram_send(bot_token, chat_id,
                        f"✅ FiBot Portfolio-Optimizer abgeschlossen (Dauer: {dur_str})")
            else:
                _telegram_send(bot_token, chat_id,
                    f"❌ FiBot Portfolio-Optimizer FEHLER (rc={rc}, Dauer: {dur_str})")

        log.info(f"Auto-Optimierung abgeschlossen in {elapsed / 60:.1f} min.")

    except subprocess.TimeoutExpired:
        log.error("Timeout: Portfolio-Optimizer hat zu lange gedauert.")
        if send_tg:
            _telegram_send(bot_token, chat_id, "FiBot Portfolio-Optimierung: Timeout!")
    except Exception as e:
        log.error(f"Unerwarteter Fehler: {e}", exc_info=True)
        if send_tg:
            _telegram_send(bot_token, chat_id, f"FiBot Portfolio-Optimierung FEHLER: {e}")
    finally:
        if os.path.exists(IN_PROGRESS_FILE):
            os.remove(IN_PROGRESS_FILE)


if __name__ == '__main__':
    main()
