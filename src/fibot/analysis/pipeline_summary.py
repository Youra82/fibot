# src/fibot/analysis/pipeline_summary.py
# Telegram-Zusammenfassung am Ende von run_pipeline.sh: alle Configs, die seit dem
# Pipeline-Start gespeichert wurden, mit In-Sample- und OOS-Ergebnis.
# Aufruf:  python src/fibot/analysis/pipeline_summary.py --since <unix-zeit> [--searched "BTC/4h ETH/1h"]

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fibot.utils.telegram import send_message  # noqa: E402

CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')


def build_summary(since: float, searched: str = '') -> str:
    rows = []
    for f in sorted(os.listdir(CONFIGS_DIR)):
        path = os.path.join(CONFIGS_DIR, f)
        if not (f.startswith('config_') and f.endswith('.json')) or os.path.getmtime(path) < since:
            continue
        c = json.load(open(path))
        b = c.get('_backtest', {})
        o = b.get('oos', {})
        name = f"{c['market']['symbol'].split('/')[0]} {c['market']['timeframe']}"
        ok = (o.get('pnl_pct', -1) >= 10 and o.get('max_drawdown', 99) <= 30
              and o.get('total_trades', 0) >= 10 and b.get('pnl_pct', -1) > 0)
        rows.append(f"{'✅' if ok else '▫️'} {name}: IS {b.get('pnl_pct', 0):+.1f}% (DD {b.get('max_drawdown', 0):.0f}%, "
                    f"{b.get('total_trades', 0)} Tr.) | OOS {o.get('pnl_pct', 0):+.1f}% "
                    f"(DD {o.get('max_drawdown', 0):.0f}%, {o.get('total_trades', 0)} Tr.)")
    head = "FiBot Pipeline abgeschlossen"
    if searched:
        head += f"\nGesucht: {searched}"
    if not rows:
        return head + "\nKeine neue Config gespeichert (keine gueltige oder bestehende besser)."
    n_ok = sum(r.startswith('✅') for r in rows)
    return (head + f"\nGespeichert: {len(rows)} Config(s), davon {n_ok} mit OOS >= 10 %, DD <= 30 %, >= 10 Trades\n\n"
            + "\n".join(rows) + "\n\nNaechster Schritt: show_results.sh Modus 3 (Portfolio) oder woechentlicher Auto-Optimizer.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', type=float, required=True)
    ap.add_argument('--searched', default='')
    a = ap.parse_args()
    msg = build_summary(a.since, a.searched)
    print(msg)
    try:
        tg = json.load(open(os.path.join(PROJECT_ROOT, 'secret.json'))).get('telegram', {})
        if tg.get('bot_token') and tg.get('chat_id'):
            send_message(tg['bot_token'], tg['chat_id'], msg)
            print("Zusammenfassung per Telegram gesendet.")
    except Exception as e:
        print(f"Telegram nicht gesendet: {e}")


if __name__ == '__main__':
    main()
