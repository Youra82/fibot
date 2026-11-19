"""Papierkonto mit echten Bitget-Kursen (identische Datei in jaegerbot, zockerbot und fibot).

Umschalten in settings.json: "echtgeld": {"aktiv": false}  -> Papierhandel, true -> echte Orders.
Kein Bitget-Schlüssel nötig: Kerzen und Kurse kommen öffentlich von Bitget (nur lesend).

Buchung wie an der Börse (isolierte Margin, USDT-Perpetuals):
  Einstieg/Ausstieg zum letzten Kurs ± Spread 0,05 %, Taker-Gebühr 0,06 % je Seite.
  SL, TP und Liquidation werden bei jedem Durchlauf mit den abgeschlossenen 1m-Kerzen seit der letzten
  Prüfung abgerechnet (bei Lücken über 3 Tage mit 15m-Kerzen). Erreicht eine Kerze Stopp und Ziel, gilt der
  Stopp (ungünstiger Fall). Liquidation bei Einstieg ∓ (1/Hebel − 0,5 %): die ganze Margin ist weg.
Die Datei konto.json liest auch das Cockpit (Kontostand, offene Positionen, geschlossene Trades).
"""
import json
import os
import time

SPREAD = 0.0005
FEE = 0.0006
LIQ_PUFFER = 0.005
MIN_MS = 60_000


def _now_ms():
    return int(time.time() * 1000)


def echtgeld_aktiv(settings: dict) -> bool:
    """Schalter aus settings.json. Fehlt der Eintrag, bleibt es beim bisherigen Echtgeld-Betrieb."""
    return bool((settings.get("echtgeld") or {}).get("aktiv", True))


def startkapital(settings: dict, standard: float = 100.0) -> float:
    return float((settings.get("echtgeld") or {}).get("papier_startkapital", standard))


class PapierKonto:
    def __init__(self, path: str, start: float, ccxt_ex, now_fn=_now_ms):
        self.path, self.ex, self.now = path, ccxt_ex, now_fn
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.s = json.load(f)
        else:
            self.s = {"start": float(start), "cash": float(start), "positions": [], "closed": [],
                      "einzahlungen": [], "erstellt_ms": self.now()}
            self.save()

    # --- Speicher ---
    def save(self):
        self.s["aktualisiert_ms"] = self.now()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.s, f, indent=1)
        os.replace(tmp, self.path)

    # --- Abfragen ---
    @property
    def positionen(self):
        return self.s["positions"]

    def position(self, symbol, side):
        return next((p for p in self.positionen if p["symbol"] == symbol and p["side"] == side), None)

    @staticmethod
    def liq_preis(entry, side, lev):
        d = 1 / lev - LIQ_PUFFER
        return entry * (1 - d) if side == "long" else entry * (1 + d)

    @staticmethod
    def offen_pnl(p, kurs):
        return (1 if p["side"] == "long" else -1) * (kurs - p["entry"]) * p["qty"]

    def realisiert(self):
        """Kasse + gebundene Margin (ohne offene Gewinne/Verluste)."""
        return self.s["cash"] + sum(p["margin"] for p in self.positionen)

    def kontostand(self, kurse=None):
        """Realisiert + offene Gewinne/Verluste (je Position höchstens −Margin)."""
        kurse = kurse or {}
        eq = self.realisiert()
        for p in self.positionen:
            k = kurse.get(p["symbol"])
            if k:
                eq += max(-p["margin"], self.offen_pnl(p, k))
        return eq

    def kurs(self, symbol):
        return float(self.ex.fetch_ticker(symbol)["last"])

    # --- Buchungen ---
    def eroeffnen(self, symbol, side, qty, kurs, lev, sl=None, tp=None):
        if self.position(symbol, side):
            raise ValueError(f"Papierkonto: {symbol} {side} ist schon offen")
        px = kurs * (1 + SPREAD) if side == "long" else kurs * (1 - SPREAD)
        margin, fee = qty * px / lev, qty * px * FEE
        if margin + fee > self.s["cash"] + 1e-9:
            raise ValueError(f"Papierkonto: zu wenig freies Guthaben ({self.s['cash']:.2f} USDT, nötig {margin + fee:.2f})")
        self.s["cash"] -= margin + fee
        now = self.now()
        p = {"symbol": symbol, "side": side, "qty": qty, "entry": px, "lev": lev, "margin": margin, "fee_in": fee,
             "sl": sl, "tp": tp, "liq": self.liq_preis(px, side, lev), "opened_ms": now,
             "checked_ms": (now // MIN_MS + 1) * MIN_MS}      # ab der nächsten vollen Minute prüfen
        self.positionen.append(p)
        self.save()
        return p

    def schliessen(self, p, kurs, grund, t_ms=None, liquidiert=False, mit_spread=True):
        if liquidiert:
            px, gross, fee_out = p["liq"], -p["margin"], 0.0
        else:
            px = (kurs * (1 - SPREAD) if p["side"] == "long" else kurs * (1 + SPREAD)) if mit_spread else kurs
            gross, fee_out = self.offen_pnl(p, px), p["qty"] * px * FEE
        self.s["cash"] += max(0.0, p["margin"] + gross - fee_out)
        pnl = max(-p["margin"], gross - fee_out) - p["fee_in"]
        self.s["closed"].append({"symbol": p["symbol"], "side": p["side"], "qty": p["qty"], "entry": p["entry"],
                                 "exit": px, "lev": p["lev"], "margin": p["margin"], "pnl": pnl,
                                 "opened_ms": p["opened_ms"], "closed_ms": int(t_ms or self.now()), "grund": grund})
        self.positionen.remove(p)
        self.save()
        return pnl

    def setze(self, symbol, side, sl=None, tp=None):
        p = self.position(symbol, side)
        if p is None:
            return False
        if sl is not None:
            p["sl"] = sl
        if tp is not None:
            p["tp"] = tp
        self.save()
        return True

    # --- Abrechnung SL / TP / Liquidation ---
    def _kerzen(self, symbol, seit_ms, bis_ms):
        tf, step = ("1m", MIN_MS) if bis_ms - seit_ms <= 3 * 86_400_000 else ("15m", 15 * MIN_MS)
        out, since = [], seit_ms
        for _ in range(400):
            batch = self.ex.fetch_ohlcv(symbol, tf, since, 200)
            batch = [c for c in batch if c[0] >= since and c[0] + step <= bis_ms]
            if not batch:
                break
            out += batch
            since = batch[-1][0] + step
            if since + step > bis_ms:
                break
        return out, step

    def abrechnen(self):
        """Alle offenen Positionen mit den Kerzen seit der letzten Prüfung abrechnen. Speichert immer
        (Zeitstempel = Lebenszeichen für das Cockpit). Gibt die geschlossenen Trades zurück."""
        now, fertig = self.now(), []
        for p in list(self.positionen):
            try:
                kerzen, step = self._kerzen(p["symbol"], p["checked_ms"], now)
            except Exception:
                continue                                    # Netz-Hickser: nächster Durchlauf prüft dieselben Kerzen
            for t, o, h, l, c, *_ in kerzen:
                lng = p["side"] == "long"
                stop = (max(p["sl"] or 0.0, p["liq"]) if lng else min(p["sl"] or float("inf"), p["liq"]))
                getroffen = (l <= stop) if lng else (h >= stop)
                if getroffen:
                    if p["sl"] is None or (lng and p["liq"] >= p["sl"]) or (not lng and p["liq"] <= p["sl"]):
                        fertig.append(self.schliessen(p, p["liq"], "Liquidation", t + step, liquidiert=True))
                    else:
                        fill = min(o, p["sl"]) if lng else max(o, p["sl"])   # Lücke über den Stopp: Eröffnungskurs
                        fertig.append(self.schliessen(p, fill, "SL", t + step))
                    break
                if p["tp"] is not None and ((h >= p["tp"]) if lng else (l <= p["tp"])):
                    fill = max(o, p["tp"]) if lng else min(o, p["tp"])
                    fertig.append(self.schliessen(p, fill, "TP", t + step, mit_spread=False))
                    break
                p["checked_ms"] = t + step
        self.save()
        return fertig
