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
OPTIMIZER_PY     = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'analysis', 'optimizer.py')

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

    config_backups = {}  # fname → backup_path (für finally-Cleanup)
    start_time = datetime.now()
    try:
        constraints = opt_cfg.get('constraints', {})
        capital   = float(opt_cfg.get('start_capital',          1000))
        max_dd    = float(constraints.get('max_drawdown_pct',     30))
        min_wr    = float(constraints.get('min_win_rate_pct',      0))
        min_pnl   = float(constraints.get('min_pnl_pct',           0))
        n_trials  = int(opt_cfg.get('num_trials',                200))
        cpu_cores = int(opt_cfg.get('cpu_cores',                   1))

        # Symbols / Timeframes: "auto" → aus active_strategies lesen
        sym_setting = opt_cfg.get('symbols_to_optimize',    'auto')
        tf_setting  = opt_cfg.get('timeframes_to_optimize', 'auto')

        active_pairs = []  # list of (symbol, timeframe)
        if str(sym_setting).lower() == 'auto' or str(tf_setting).lower() == 'auto':
            for s in settings.get('live_trading_settings', {}).get('active_strategies', []):
                sym = s.get('symbol', '')
                tf  = s.get('timeframe', '')
                if sym and tf:
                    active_pairs.append((sym, tf))
        else:
            # Explizite Listen: alle Kombinationen
            syms = sym_setting if isinstance(sym_setting, list) else [sym_setting]
            tfs  = tf_setting  if isinstance(tf_setting,  list) else [tf_setting]
            for sym in syms:
                if '/' not in sym:
                    sym = f"{sym.upper()}/USDT:USDT"
                for tf in tfs:
                    active_pairs.append((sym, tf))

        if not active_pairs:
            log.error("Keine Paare für Optimierung gefunden.")
            return
        log.info(f"Paare: {[f'{s}/{t}' for s,t in active_pairs]}")

        # Lookback
        lookback_setting = opt_cfg.get('lookback_days', 'auto')
        if str(lookback_setting).lower() == 'auto':
            from fibot.analysis.backtester import auto_days_for_timeframe
            lookback = max(auto_days_for_timeframe(tf) for _, tf in active_pairs)
            log.info(f"Lookback auto: {lookback} Tage")
        else:
            lookback = int(lookback_setting)

        date_from = (datetime.now() - timedelta(days=lookback)).strftime('%Y-%m-%d')
        date_to   = datetime.now().strftime('%Y-%m-%d')

        log.info(f"Kapital={capital} USDT | MaxDD={max_dd}% | MinWR={min_wr}% | "
                 f"MinPnL={min_pnl}% | Trials={n_trials} | Jobs={cpu_cores} | "
                 f"Zeitraum: {date_from} → {date_to}")

        pairs_str = ', '.join(f"{sym.split('/')[0]}/{tf}" for sym, tf in active_pairs)

        if send_tg:
            _telegram_send(bot_token, chat_id,
                f"🚀 FiBot Auto-Optimizer GESTARTET\n"
                f"Paare: {pairs_str}\n"
                f"Trials: {n_trials}\n"
                f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Alte Ergebnisse lesen BEVOR show_results.py sie überschreibt
        old_pnl = {}
        if os.path.exists(OPT_RESULTS_FILE):
            try:
                with open(OPT_RESULTS_FILE) as f:
                    old_data = json.load(f)
                for r in old_data.get('all_results', []):
                    old_pnl[r['filename']] = r.get('pnl_pct', 0.0)
            except Exception:
                pass

        # ── Schritt 1: Optuna-Optimizer pro Paar ──────────────────────────
        log.info(f"Starte Optuna-Optimierung für {len(active_pairs)} Paar(e) "
                 f"({n_trials} Trials, {cpu_cores} CPU-Kern(e))...")

        # Config-Backups anlegen BEVOR optimizer.py überschreibt
        import shutil
        config_backups = {}  # fname → backup_path
        for sym, tf in active_pairs:
            safe  = f"{sym.replace('/', '').replace(':', '')}_{tf}"
            fname = f"config_{safe}_fib.json"
            cfg_path = os.path.join(CONFIGS_DIR, fname)
            if os.path.exists(cfg_path):
                bak = cfg_path + '.bak'
                shutil.copy2(cfg_path, bak)
                config_backups[fname] = bak
                log.info(f"  Backup: {fname}")

        opt_failed = []
        for sym, tf in active_pairs:
            opt_cmd = [
                PYTHON_EXE, OPTIMIZER_PY,
                '--symbols',    sym,
                '--timeframes', tf,
                '--from',       date_from,
                '--to',         date_to,
                '--capital',    str(capital),
                '--trials',     str(n_trials),
                '--jobs',       str(cpu_cores),
                '--max-dd',     str(max_dd),
                '--min-wr',     str(min_wr),
            ]
            log.info(f"  Optimiere {sym} ({tf}) ...")
            opt_proc = subprocess.run(
                opt_cmd, cwd=PROJECT_ROOT,
                capture_output=True, text=True, timeout=7200,
            )
            if opt_proc.returncode != 0:
                log.error(f"  optimizer.py Fehler für {sym}/{tf} "
                          f"(rc={opt_proc.returncode}):\n{opt_proc.stderr[-500:]}")
                opt_failed.append(f"{sym}/{tf}")
            else:
                log.info(f"  {sym} ({tf}) — Optimierung abgeschlossen.")
                out = opt_proc.stdout[-2000:] if len(opt_proc.stdout) > 2000 else opt_proc.stdout
                log.debug(f"  Output:\n{out}")

        if opt_failed:
            log.warning(f"Optimizer fehlgeschlagen für: {opt_failed} — "
                        f"fahre mit vorhandenen Configs fort.")

        # Configs nach Optimierung neu ermitteln (optimizer.py schreibt sie frisch)
        active_configs = []
        for sym, tf in active_pairs:
            safe  = f"{sym.replace('/', '').replace(':', '')}_{tf}"
            fname = f"config_{safe}_fib.json"
            if os.path.exists(os.path.join(CONFIGS_DIR, fname)):
                active_configs.append(fname)
            else:
                log.warning(f"Config nach Optimierung nicht gefunden: {fname} — übersprungen")

        if not active_configs:
            log.error("Keine Configs nach Optimierung verfügbar.")
            return

        # ── Schritt 2: Portfolio-Finder ───────────────────────────────────
        cmd = [
            PYTHON_EXE, SHOW_RESULTS,
            '--mode',          '3',
            '--capital',       str(capital),
            '--target-max-dd', str(max_dd),
            '--min-wr',        str(min_wr),
            '--from',          date_from,
            '--to',            date_to,
            '--auto',
            '--configs',       ' '.join(active_configs),
        ]

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
        all_results     = opt.get('all_results', [])

        if not portfolio_files:
            log.warning("Kein optimales Portfolio in optimization_results.json.")
            if send_tg:
                _telegram_send(bot_token, chat_id,
                    "FiBot Auto-Optimierung: Kein Portfolio gefunden.")
            return

        # Vergleich mit vorherigem Lauf: nur übernehmen wenn neuer PnL >= alter PnL
        new_pnl = {r['filename']: r.get('pnl_pct', 0.0) for r in all_results}
        kept        = []   # werden in settings.json geschrieben
        not_better  = []   # (filename, old_pnl_val, new_pnl_val)
        for fn in portfolio_files:
            old_val = old_pnl.get(fn)
            new_val = new_pnl.get(fn, 0.0)
            if old_val is not None and new_val < old_val:
                not_better.append((fn, old_val, new_val))
                log.info(f"Nicht übernommen (schlechter): {fn}  alt={old_val:.2f}%  neu={new_val:.2f}%")
            else:
                kept.append(fn)

        # Schlechtere Config-Dateien aus Backup wiederherstellen
        for fn, old_val, new_val in not_better:
            bak = config_backups.get(fn)
            if bak and os.path.exists(bak):
                shutil.copy2(bak, os.path.join(CONFIGS_DIR, fn))
                log.info(f"  Config wiederhergestellt: {fn} (alt={old_val:.2f}% > neu={new_val:.2f}%)")

        # Backups aufräumen
        for bak in config_backups.values():
            if os.path.exists(bak):
                os.remove(bak)

        if kept:
            success = _update_settings(kept)
        else:
            log.warning("Kein verbessertes Portfolio — settings.json bleibt unverändert.")
            success = False

        elapsed = (datetime.now() - start_time).total_seconds()

        # Last-run Timestamp speichern
        with open(LAST_RUN_FILE, 'w') as f:
            f.write(datetime.now().isoformat())

        if send_tg:
            # Dauer formatieren
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            s = int(elapsed % 60)
            dur_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

            in_port  = [r for r in all_results if r.get('in_portfolio') and r['filename'] in kept]
            # "Fehlgeschlagen" = nicht im Portfolio ODER im Portfolio aber nicht besser
            excluded_set = {fn for fn in portfolio_files if fn not in kept}
            excluded_port = [(fn, old_pnl.get(fn, 0.0), new_pnl.get(fn, 0.0)) for fn in excluded_set]
            excl_nonport  = [r for r in all_results if not r.get('in_portfolio')]
            total = len(all_results)
            gespeichert_n = len(kept)

            lines = [f"✅ FiBot Auto-Optimizer abgeschlossen (Dauer: {dur_str})", ""]

            if in_port:
                lines.append(f"✔ Gespeichert ({gespeichert_n}/{total}):")
                for r in in_port:
                    sym  = r.get('symbol', '?')
                    tf   = r.get('timeframe', '?')
                    pnl  = r.get('pnl_pct', 0.0)
                    fn   = r.get('filename', '')
                    sign = '+' if pnl >= 0 else ''
                    lines.append(f"• {sym.split('/')[0]}/{tf}: {sign}{pnl:.2f}% → {fn}")
            else:
                lines.append(f"✔ Gespeichert (0/{total}): — keine Verbesserung")

            failed_lines = []
            # Portfolio-Kandidaten die schlechter waren
            for fn, old_v, new_v in not_better:
                r = next((x for x in all_results if x['filename'] == fn), {})
                sym = r.get('symbol', fn)
                tf  = r.get('timeframe', '')
                failed_lines.append(
                    f"• {sym.split('/')[0]}/{tf}: existing_better_{old_v:.2f}pct"
                )
            # Nicht im Portfolio (DD/WR gefiltert)
            for r in excl_nonport:
                sym  = r.get('symbol', '?')
                tf   = r.get('timeframe', '?')
                pnl  = r.get('pnl_pct', 0.0)
                dd   = r.get('max_dd',  0.0)
                sign = '+' if pnl >= 0 else ''
                failed_lines.append(f"• {sym.split('/')[0]}/{tf}: {sign}{pnl:.2f}% (DD: {dd:.1f}%)")

            if failed_lines:
                lines.append("")
                lines.append(f"❌ Fehlgeschlagen ({len(failed_lines)}/{total}):")
                lines.extend(failed_lines)

            _telegram_send(bot_token, chat_id, '\n'.join(lines))

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
        # Stale Backups aufräumen (falls Fehler vor normalem Cleanup)
        for bak in config_backups.values():
            if os.path.exists(bak):
                os.remove(bak)


if __name__ == '__main__':
    main()
