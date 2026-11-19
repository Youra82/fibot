"""Papierkonto mit echten Bitget-Kursen (identische Datei in jaegerbot, zockerbot und fibot).

Umschalten in settings.json: "echtgeld": {"aktiv": false}  -> Papierhandel, true -> echte Orders.
Kein Bitget-Schlüssel nötig: Kerzen und Kurse kommen öffentlich von Bitget (nur lesend).

Buchung wie an der Börse (isolierte Margin, USDT-Perpetuals):
  Einstieg/Ausstieg zum letzten Kurs ± Spread 0,05 %, Taker-Gebühr 0,06 % je Seite.
  SL, TP und Liquidation werden bei jedem Durchlauf mit den abgeschlossenen 1m-Kerzen seit der letzten
  Prüfung abgerechnet (bei Lücken über 3 Tage mit 15m-Kerzen). Erreicht eine Kerze Stopp und Ziel, gilt der
  Stopp (ungünstiger Fall). Liquidation bei Einstieg ∓ (1/Hebel − 0,5 %): die ganze Margin ist weg.
  Funding wie an der Börse: echte Bitget-Sätze (öffentlich), zu jeder Abrechnungsstunde, solange die Position
  offen ist, Positionswert × Satz vom Guthaben ab (Long bei positivem Satz) bzw. gutgeschrieben. Abruf höchstens
  einmal je volle Stunde und Position; schlägt er fehl, wird beim nächsten Durchlauf nachgebucht.
Die Datei konto.json liest auch das Cockpit (Kontostand, offene Positionen, geschlossene Trades).
"""
import json
import os
import time
import urllib.request

SPREAD = 0.0005
FEE = 0.0006
LIQ_PUFFER = 0.005
MIN_MS = 60_000
STUNDE_MS = 3_600_000
FUNDING_URL = ("https://api.bitget.com/api/v2/mix/market/history-fund-rate"
               "?symbol={sym}&productType=USDT-FUTURES&pageSize=100&pageNo={n}")


def funding_saetze(symbol, seit_ms=0):
    """Funding-Abrechnungen von Bitget (öffentlich) bis zurück zu seit_ms: [(Zeit ms, Satz)], aufsteigend.
    Satz > 0: Long zahlt an Short. Je Seite 100 Abrechnungen, höchstens 10 Seiten."""
    sym = symbol.split(":")[0].replace("/", "")
    out = {}
    for n in range(1, 11):
        with urllib.request.urlopen(FUNDING_URL.format(sym=sym, n=n), timeout=15) as r:
            d = json.loads(r.read())
        if str(d.get("code")) != "00000":
            raise RuntimeError(f"Bitget Funding {sym}: {d.get('msg')}")
        rows = d.get("data") or []
        out.update((int(x["fundingTime"]), float(x["fundingRate"])) for x in rows)
        if len(rows) < 100 or min(int(x["fundingTime"]) for x in rows) <= seit_ms:
            break
    return sorted(out.items())


def _now_ms():
    return int(time.time() * 1000)


def echtgeld_aktiv(settings: dict) -> bool:
    """Schalter aus settings.json. Fehlt der Eintrag, bleibt es beim bisherigen Echtgeld-Betrieb."""
    return bool((settings.get("echtgeld") or {}).get("aktiv", True))


def startkapital(settings: dict, standard: float = 100.0) -> float:
    return float((settings.get("echtgeld") or {}).get("papier_startkapital", standard))


class PapierKonto:
    def __init__(self, path: str, start: float, ccxt_ex, now_fn=_now_ms, funding_fn=funding_saetze):
        self.path, self.ex, self.now, self.funding_fn = path, ccxt_ex, now_fn, funding_fn
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
             "funding": 0.0, "funding_bis_ms": now,
             "checked_ms": (now // MIN_MS + 1) * MIN_MS}      # ab der nächsten vollen Minute prüfen
        self.positionen.append(p)
        self.save()
        return p

    # --- Funding ---
    def funding_buchen(self, p, bis_ms, kerzen=None):
        """Funding-Abrechnungen nach p['funding_bis_ms'] bis bis_ms buchen (Guthaben und p['funding']).
        Kurs zur Abrechnung: Eröffnungskurs der Kerze zu dieser Zeit, sonst Einstiegskurs.
        Gibt False zurück, wenn Bitget nicht erreichbar war (dann wird später nachgebucht)."""
        seit = p.setdefault("funding_bis_ms", p["opened_ms"])
        p.setdefault("funding", 0.0)
        if bis_ms // STUNDE_MS <= seit // STUNDE_MS:      # keine volle Stunde dazwischen -> keine Abrechnung
            return True
        try:
            saetze = self.funding_fn(p["symbol"], seit)
        except Exception:
            return False
        kurs_bei = {int(k[0]): float(k[1]) for k in (kerzen or [])}
        for t, satz in saetze:
            if seit < t <= bis_ms:
                betrag = (-1 if p["side"] == "long" else 1) * satz * p["qty"] * kurs_bei.get(t, p["entry"])
                self.s["cash"] += betrag
                p["funding"] += betrag
        p["funding_bis_ms"] = int(bis_ms)
        return True

    def schliessen(self, p, kurs, grund, t_ms=None, liquidiert=False, mit_spread=True, kerzen=None):
        t_ms = int(t_ms or self.now())
        funding_ok = self.funding_buchen(p, t_ms, kerzen)
        if liquidiert:
            px, gross, fee_out = p["liq"], -p["margin"], 0.0
        else:
            px = (kurs * (1 - SPREAD) if p["side"] == "long" else kurs * (1 + SPREAD)) if mit_spread else kurs
            gross, fee_out = self.offen_pnl(p, px), p["qty"] * px * FEE
        self.s["cash"] += max(0.0, p["margin"] + gross - fee_out)
        # Funding ist schon im Guthaben gebucht (während der Haltedauer) und zählt zum Ergebnis des Trades
        pnl = max(-p["margin"], gross - fee_out) - p["fee_in"] + p.get("funding", 0.0)
        c = {"symbol": p["symbol"], "side": p["side"], "qty": p["qty"], "entry": p["entry"],
             "exit": px, "lev": p["lev"], "margin": p["margin"], "pnl": pnl,
             "fee": p["fee_in"] + fee_out, "funding": p.get("funding", 0.0),
             "opened_ms": p["opened_ms"], "closed_ms": t_ms, "grund": grund}
        if not funding_ok:
            c["funding_unvollstaendig"] = True          # Bitget beim Schließen nicht erreichbar
        self.s["closed"].append(c)
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
            geschlossen = False
            for t, o, h, l, c, *_ in kerzen:
                lng = p["side"] == "long"
                stop = (max(p["sl"] or 0.0, p["liq"]) if lng else min(p["sl"] or float("inf"), p["liq"]))
                getroffen = (l <= stop) if lng else (h >= stop)
                if getroffen:
                    if p["sl"] is None or (lng and p["liq"] >= p["sl"]) or (not lng and p["liq"] <= p["sl"]):
                        fertig.append(self.schliessen(p, p["liq"], "Liquidation", t + step, liquidiert=True, kerzen=kerzen))
                    else:
                        fill = min(o, p["sl"]) if lng else max(o, p["sl"])   # Lücke über den Stopp: Eröffnungskurs
                        fertig.append(self.schliessen(p, fill, "SL", t + step, kerzen=kerzen))
                    geschlossen = True
                    break
                if p["tp"] is not None and ((h >= p["tp"]) if lng else (l <= p["tp"])):
                    fill = max(o, p["tp"]) if lng else min(o, p["tp"])
                    fertig.append(self.schliessen(p, fill, "TP", t + step, mit_spread=False, kerzen=kerzen))
                    geschlossen = True
                    break
                p["checked_ms"] = t + step
            if not geschlossen:
                self.funding_buchen(p, p["checked_ms"], kerzen)   # Funding bis zur zuletzt geprüften Kerze
        self.save()
        return fertig
