# src/fibot/utils/risk_cap.py
# Feste Obergrenze fuer das Risiko je Einstieg -- EINE Funktion fuer Live-Handel, Backtester, Portfolio-Simulator
# und Teamauswahl (Live = Backtest). Hintergrund (Forschung 08.11.2026, forschung/kontostand_2026_11_08):
# das vom Optimizer je Config vergebene Risiko (1-3 %) fuehrte bei bis zu 9 parallelen Positionen zu 38-60 % Drawdown;
# 1 % je Einstieg hielt den Drawdown in den gerechneten Zeitraeumen bei 21-34 % (vereinfachte Kontorechnung).
#
# Wert: live_trading_settings.max_risk_per_entry_pct in settings.json; fehlt der Eintrag, gilt DEFAULT_MAX_RISK_PCT
# (wirkt so auch auf dem VPS, dessen settings.json von update.sh bewahrt wird). null oder 0 = ausdruecklich keine
# Obergrenze. Ungueltige Werte (negativ, NaN, unendlich, true/false, Text) brechen sichtbar ab.
# Gemeint ist das Preisrisiko bis zum geplanten Stop; Gebuehren und Schlupf kommen hinzu.
# Backtests lesen den Wert EINMAL je Lauf (max_risk_pct) und reichen ihn als cap= weiter (Codex-Review 08.11.2026).
import contextlib
import json
import math
import os
import time

DEFAULT_MAX_RISK_PCT = 1.0
SETTINGS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'settings.json'))
_UNSET = object()


def _number(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} muss eine Zahl sein, nicht {value!r}.')
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} muss endlich und nichtnegativ sein, nicht {value!r}.')
    return value


def max_risk_pct(settings_file: str = None):
    """Obergrenze in Prozent (z. B. 1.0) oder None (ausdruecklich keine Obergrenze)."""
    path = settings_file or SETTINGS_FILE
    try:
        with open(path, encoding='utf-8') as f:
            settings = json.load(f)
    except FileNotFoundError:
        return DEFAULT_MAX_RISK_PCT
    live = settings.get('live_trading_settings', {}) if isinstance(settings, dict) else None
    if not isinstance(live, dict):
        raise ValueError(f'{path}: live_trading_settings muss ein Objekt sein.')
    value = live.get('max_risk_per_entry_pct', _UNSET)
    if value is _UNSET:
        return DEFAULT_MAX_RISK_PCT
    if value is None:
        return None
    value = _number('max_risk_per_entry_pct', value)
    return None if value == 0 else value


# ---------------------------------------------------------------- dynamische Anpassung an den Kontoverlauf
# Risiko = gedeckeltes Risiko x Faktor, Faktor = max(floor, 1 - Drawdown/dd_full). Drawdown = Rueckgang vom
# Konto-Hoechststand. Mit jedem neuen Hoch wieder voller Einsatz. Forschung: forschung/kontostand_2026_11_08
# (1 % Basis, Pool 38: DD 32/34/21/28/30 % -> 23/25/16/20/21 %, Rendite kleiner). Standard: an.
DEFAULT_DYNAMIC = {'enabled': True, 'dd_full': 0.30, 'floor': 0.25}
PEAK_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'artifacts', 'db', 'equity_peak.json'))


def dynamic_settings(settings_file: str = None) -> dict:
    """live_trading_settings.dynamic_risk = {enabled, dd_full, floor}; fehlt -> DEFAULT_DYNAMIC."""
    path = settings_file or SETTINGS_FILE
    try:
        with open(path, encoding='utf-8') as f:
            raw = (json.load(f).get('live_trading_settings') or {}).get('dynamic_risk', {})
    except FileNotFoundError:
        raw = {}
    if raw is None:
        raw = {'enabled': False}
    if not isinstance(raw, dict):
        raise ValueError('dynamic_risk muss ein Objekt sein.')
    d = {**DEFAULT_DYNAMIC, **raw}
    if not isinstance(d['enabled'], bool):
        raise ValueError('dynamic_risk.enabled muss true/false sein.')
    d['dd_full'] = _number('dynamic_risk.dd_full', d['dd_full']); d['floor'] = _number('dynamic_risk.floor', d['floor'])
    if not 0 < d['dd_full'] <= 1 or not 0 < d['floor'] <= 1:
        raise ValueError('dynamic_risk: dd_full und floor muessen in (0, 1] liegen.')
    return d


def drawdown_factor(equity, peak, dyn: dict = None) -> float:
    """Faktor 0 < f <= 1 aus aktuellem Kontostand und Hoechststand."""
    dyn = dyn or DEFAULT_DYNAMIC
    if not dyn['enabled'] or not peak or peak <= 0:
        return 1.0
    dd = max(0.0, 1.0 - float(equity) / float(peak))
    return max(dyn['floor'], 1.0 - dd / dyn['dd_full'])


HISTORY_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'artifacts', 'db', 'equity_history.jsonl'))
HISTORY_MAX_LINES = 20000


@contextlib.contextmanager
def _locked(path):
    """Prozessuebergreifende Sperre fuer Lesen-Vergleichen-Schreiben (Codex-Review: os.replace allein reicht nicht)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.lock', 'a+') as fh:
        if os.name == 'nt':
            import msvcrt
            fh.seek(0)
            for _ in range(200):
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise TimeoutError(f'Sperre {path}.lock nicht erhalten')
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read_state(path):
    """None = noch nie angelegt. Beschaedigt/ungueltig -> ValueError (kein stilles Vergessen eines Drawdowns)."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            st = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f'Hoechststand-Datei {path} beschaedigt ({e}). Pruefen oder bewusst zuruecksetzen '
                         f'(python -m fibot.utils.risk_cap reset).')
    if not isinstance(st, dict):
        raise ValueError(f'Hoechststand-Datei {path}: Objekt erwartet.')
    peak = _number('peak', st.get('peak'))
    if peak <= 0:
        raise ValueError(f'Hoechststand-Datei {path}: peak muss > 0 sein.')
    st['peak'] = peak
    seen = st.get('seen_bills') or {}
    if isinstance(seen, list):                      # aeltere Form (nur IDs)
        seen = {str(b): 0 for b in seen}
    st['seen_bills'] = seen
    st.setdefault('last_bill_ms', None); st.setdefault('version', 0); st.setdefault('baseline_ms', 0)
    return st


def state_version(path: str = None):
    """Versionszaehler des Kontoverlaufs (None = noch nicht angelegt). Fuer optimistische Abstimmung (Codex Runde 4)."""
    path = path or PEAK_FILE
    with _locked(path):
        st = _read_state(path)
    return None if st is None else int(st['version'])


def _write_state(path, st):
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f)
    os.replace(tmp, path)


def _history(event: dict):
    path = HISTORY_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(event) + '\n')
    if os.path.getsize(path) > HISTORY_MAX_LINES * 160:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()[-HISTORY_MAX_LINES:]
        tmp = f'{path}.{os.getpid()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        os.replace(tmp, path)


def observe_equity(equity: float, flows=None, path: str = None, now_ms: int = None, expected_version=False):
    """Live: Kontostand beobachten, Ein-/Auszahlungen einrechnen, Hoechststand fortschreiben -- alles unter EINER Sperre.
    flows: [(bill_id, ms, betrag)] aus dem Kontoauszug (positiv = Einzahlung). Einzahlung hebt den Hoechststand um den
    Betrag, Auszahlung senkt ihn -- Kapitalbewegungen erzeugen so keinen Drawdown und verdecken keinen.
    VORAUSSETZUNG (Codex Runde 3): flows ist der VOLLSTAENDIGE Kontoauszug bis zum Zeitpunkt des Kontostands
    (siehe trade_manager.observe_account: Auszug -> Kontostand -> Auszug, nur bei gleichem Ergebnis). Sonst koennte
    eine schon im Kontostand enthaltene, aber noch nicht verbuchte Einzahlung den Hoechststand doppelt anheben."""
    path = path or PEAK_FILE
    equity = _number('equity', equity)
    if equity <= 0:
        raise ValueError('Kontostand <= 0 -- nicht beobachtbar (API-Fehler?).')
    now_ms = now_ms or int(time.time() * 1000)
    with _locked(path):
        st = _read_state(path)
        if expected_version is not False and (None if st is None else int(st['version'])) != expected_version:
            return None                     # Zustand hat sich waehrend der Abfragen geaendert -> Snapshot verwerfen
        if st is None:
            # Ausgangspunkt: alles bis jetzt ist im Kontostand enthalten -> aeltere Buchungen nie nachtraeglich zaehlen
            st = {'peak': equity, 'seen_bills': {}, 'last_bill_ms': now_ms, 'baseline_ms': now_ms, 'version': 0}
            _history({'ms': now_ms, 'event': 'start', 'equity': equity, 'peak': equity})
        seen = st['seen_bills']
        for bill_id, ms, amount in sorted(flows or [], key=lambda x: x[1]):
            bill_id = str(bill_id)
            if bill_id in seen or int(ms) <= int(st.get('baseline_ms') or 0):
                continue
            amount = float(amount)
            st['peak'] = max(st['peak'] + amount, 1e-9)
            seen[bill_id] = int(ms)
            st['last_bill_ms'] = max(st['last_bill_ms'] or 0, int(ms))
            # Punkt 4: Protokoll-Zeit = Beobachtungszeit (der Hoechststand enthaelt Wissen bis jetzt), Buchungszeit extra
            _history({'ms': now_ms, 'buchung_ms': int(ms), 'event': 'kapitalbewegung', 'betrag': amount, 'peak': st['peak']})
        # IDs so lange behalten, wie die Abfrage zurueckreicht (Ueberlappung 1 h + Reserve), nicht nach Anzahl kuerzen
        horizon = int(st.get('flows_checked_ms') or now_ms) - 6 * 3_600_000
        st['seen_bills'] = {b: m for b, m in seen.items() if m >= horizon}
        st['peak'] = max(st['peak'], equity)
        st['version'] = int(st['version']) + 1
        st['updated_ms'] = now_ms
        if flows is not None:
            st['flows_checked_ms'] = now_ms
        _write_state(path, st)
        _history({'ms': now_ms, 'event': 'beobachtung', 'equity': equity, 'peak': st['peak']})
        return st['peak']


def flows_since(path: str = None):
    """Ab wann der Kontoauszug abgefragt werden muss (letzte vollstaendige Abstimmung minus 1 h Ueberlappung;
    doppelte Buchungen werden ueber die Bill-ID erkannt) -- None = noch kein Kontoverlauf."""
    path = path or PEAK_FILE
    with _locked(path):
        st = _read_state(path)
    if st is None:
        return None
    return max(0, int(st.get('flows_checked_ms') or st.get('updated_ms') or 0) - 3_600_000)


def current_peak(path: str = None):
    """Gespeicherter Hoechststand (nur lesen) oder None."""
    path = path or PEAK_FILE
    with _locked(path):
        st = _read_state(path)
    return None if st is None else st['peak']


def reset_peak(equity: float, reason: str, path: str = None) -> float:
    """Bewusster, protokollierter Neustart des Kontoverlaufs. Gleiche Sperre wie observe_equity."""
    path = path or PEAK_FILE
    equity = _number('equity', equity)
    if equity <= 0 or not reason:
        raise ValueError('Reset braucht Kontostand > 0 und einen Grund.')
    now_ms = int(time.time() * 1000)
    with _locked(path):
        try:
            old = _read_state(path)
        except ValueError:
            old = None                       # beschaedigte Datei darf bewusst ueberschrieben werden
        st = {'peak': equity, 'seen_bills': (old or {}).get('seen_bills', {}), 'last_bill_ms': now_ms, 'baseline_ms': now_ms,
              'version': int((old or {}).get('version', 0)) + 1}
        _write_state(path, st)
        _history({'ms': now_ms, 'event': 'reset', 'grund': reason, 'equity': equity, 'peak': equity,
                  'alter_peak': (old or {}).get('peak')})
    return equity


def peak_at(ts_ms: int):
    """Zustand (Hoechststand, Kontostand) aus der juengsten BEOBACHTUNG mit Zeit <= ts_ms (groesster Zeitstempel,
    nicht Dateireihenfolge) oder None. Kapitalbewegungen zaehlen erst mit ihrer Beobachtung (Codex Runde 3)."""
    best = None
    try:
        with open(HISTORY_FILE, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get('event') not in ('start', 'beobachtung', 'reset') or not e.get('peak'):
                    continue
                if e.get('ms', 0) <= ts_ms and (best is None or e['ms'] >= best['ms']):
                    best = e
    except FileNotFoundError:
        return None
    return best


def live_risk_pct(capped_pct: float, equity: float, logger=None) -> float:
    """Live: gedeckeltes Risiko x Kontoverlauf-Faktor (gleiche Formel wie im Portfolio-Simulator).
    equity = GESAMT-Kontostand inkl. offener Positionen (nicht das freie Guthaben)."""
    dyn = dynamic_settings()
    stored = current_peak() if dyn['enabled'] else None          # nur LESEN -- fortgeschrieben wird in observe_account
    if dyn['enabled'] and stored is None and logger is not None:
        logger.warning("Kontoverlauf noch nicht beobachtet -- Faktor 1,0 bis zur ersten Beobachtung.")
    peak = max(stored or equity, equity)
    f = drawdown_factor(equity, peak, dyn)
    if logger is not None:
        logger.info(f"Kontoverlauf: Kapital {equity:.2f} | Hoechststand {peak:.2f} | Faktor {f:.2f} | "
                    f"Risiko {capped_pct:.3f} % -> {capped_pct * f:.3f} %")
    return capped_pct * f


def capped_risk_pct(risk_pct, cap=_UNSET, settings_file: str = None) -> float:
    """Risiko je Einstieg in Prozent nach Anwendung der Obergrenze. cap= (Prozent oder None) friert den Wert ein,
    sonst wird er aus settings.json gelesen."""
    risk_pct = _number('risk_per_entry_pct', risk_pct)
    if cap is _UNSET:
        cap = max_risk_pct(settings_file)
    elif cap is not None:
        cap = _number('max_risk_per_entry_pct', cap) or None      # 0 = keine Obergrenze (wie in settings.json)
    return risk_pct if cap is None else min(risk_pct, cap)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Kontoverlauf (Hoechststand) anzeigen oder bewusst zuruecksetzen.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('zeigen')
    r = sub.add_parser('reset'); r.add_argument('--kontostand', type=float, required=True); r.add_argument('--grund', required=True)
    a = ap.parse_args()
    if a.cmd == 'zeigen':
        print(json.dumps(_read_state(PEAK_FILE), indent=1))
    else:
        print('Neuer Hoechststand:', reset_peak(a.kontostand, a.grund))
