# src/fibot/strategy/run.py
# FiBot — Strategy Entry Point

import os
import sys
import json
import logging
import argparse
import time
from logging.handlers import RotatingFileHandler

import ccxt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from fibot.utils.exchange import Exchange
from fibot.utils.telegram import send_message
from fibot.utils.trade_manager import full_trade_cycle


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(symbol: str, timeframe: str) -> logging.Logger:
    safe = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    log_dir = os.path.join(PROJECT_ROOT, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'fibot_{safe}.log')

    logger_name = f'fibot_{safe}'
    logger = logging.getLogger(logger_name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(
            f'%(asctime)s [fibot/{safe}] %(levelname)s: %(message)s', datefmt='%H:%M:%S'))
        logger.addHandler(ch)
        logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config(symbol: str, timeframe: str) -> dict:
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')
    safe = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    config_path = os.path.join(configs_dir, f"config_{safe}_fib.json")

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Config nicht gefunden: {config_path}\n"
            f"Bitte erstelle die Datei oder führe run_pipeline.sh aus.")

    with open(config_path, 'r') as f:
        config = json.load(f)

    required = ['market', 'strategy', 'risk']
    for key in required:
        if key not in config:
            raise ValueError(f"Config unvollständig: '{key}' fehlt in {config_path}")

    return config


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="FiBot — Fibonacci Trading Bot")
    parser.add_argument('--symbol',    required=True,  help="Handelspaar (z.B. BTC/USDT:USDT)")
    parser.add_argument('--timeframe', required=True,  help="Zeitrahmen (z.B. 4h)")
    args = parser.parse_args()

    symbol    = args.symbol
    timeframe = args.timeframe
    logger    = setup_logging(symbol, timeframe)

    try:
        params  = load_config(symbol, timeframe)
        secrets_path = os.path.join(PROJECT_ROOT, 'secret.json')
        with open(secrets_path, 'r') as f:
            secrets = json.load(f)

        accounts      = secrets.get('fibot', [])
        if isinstance(accounts, dict):
            accounts = [accounts]
        telegram_cfg  = secrets.get('telegram', {})

        if not accounts:
            logger.critical("Kein 'fibot'-Account in secret.json gefunden.")
            sys.exit(1)

    except FileNotFoundError as e:
        logger.critical(f"Datei nicht gefunden: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.critical(f"Config-Fehler: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Initialisierungsfehler: {e}", exc_info=True)
        sys.exit(1)

    for account in accounts:
        account_name = account.get('name', 'Standard')
        logger.info(f"Starte FiBot für {symbol} ({timeframe}) | Account: {account_name}")
        try:
            exchange = Exchange(account)
            full_trade_cycle(exchange, params, telegram_cfg, logger)
        except ccxt.AuthenticationError:
            logger.critical("Authentifizierungsfehler! API-Keys prüfen.")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Fehler in Trade-Cycle: {e}", exc_info=True)
            send_message(
                telegram_cfg.get('bot_token', ''),
                telegram_cfg.get('chat_id', ''),
                f"FiBot KRITISCHER FEHLER ({symbol} {timeframe}): {e}"
            )
            sys.exit(1)

    logger.info(f">>> FiBot Lauf abgeschlossen: {symbol} ({timeframe}) <<<")


if __name__ == "__main__":
    main()
