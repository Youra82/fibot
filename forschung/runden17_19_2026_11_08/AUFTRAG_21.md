# Auftrag 21 (Runde 18): Eigene, neue Fibonacci-/Konfluenz-Strategie fuer den fibot -- unabhaengig von Claude

Claude und du arbeitet ab jetzt UNABHAENGIG mit unterschiedlichen Ideen; nach jeder Runde werden Ideen und Ergebnisse
verglichen. Claude verwahrt die OOS-Daten (ab 10.05.2026) und rechnet den einzigen gemeinsamen OOS-Test mit
kumulierter Holm-Korrektur ueber ALLE je getesteten Kandidaten (bisher 13, siehe RUNDE17_CODEX.md / Runde 17 OOS:
keiner bestanden, alte Kanal-Konfluenz im OOS -0,33 R/Trade; beste Filter ~0).

## Was bisher NICHT funktioniert hat (nicht wiederholen)
- Filter auf die alte Kanal-Konfluenz (EMA200, ADX, RSI, Volumen, Stop-ATR, CRV, BTC-Regime, Phasentore).
- Je-Coin-/TF-Optimierung: Trainings-Rang -> OOS-Rang Korrelation ~ -0,07 (Rauschen).
- Fibo-Wick (Limit Mitte - x %, Fib + runde Zahl + MTF): mehr Trades -> stetig schlechter.
- Umkehr der alten Konfluenz.
Bekannt robust ist nur die Docht-Rueckkehr (Limit deutlich unter kurzfristiger Mitte, Ziel Mitte, Stop weit).

## Deine Aufgabe (kreativ, frei)
Entwirf eine NEUE Strategieidee mit Fibonacci-/Konfluenzbezug, mechanisch begruendet, und HOECHSTENS 5 eingefrorene
Varianten. Long und/oder Short erlaubt. Stop nicht enger als 1 ATR der Strategie-Zeitebene. Kein Je-Coin-Tuning.

## Daten (nur diese)
`runde18/daten/{30m,1h,4h}/<COIN>_<tf>.csv` (160 Coins, 2022-01-01 bis 09.05.2026, Spalten timestamp,open,high,low,close,volume)
und `runde18/daten/BTC_1d.csv`. Nichts anderes lesen (insbesondere nichts unter C:\Users\matol\Desktop\botprojekte\fibot\forschung
oder artifacts). Kein Netzwerk.

## Lieferformat (Pflicht, damit Claude den OOS-Test fahren kann)
`runde18/strategie.py` mit
```python
VARIANTEN = ['name1', ...]            # max 5
def trades(root: str, variante: str) -> pandas.DataFrame
```
`root` hat dieselbe Struktur wie `runde18/daten` (Claude ruft es spaeter mit Daten bis 08.11.2026 auf). Rueckgabe: eine Zeile
je Trade mit Spalten coin, tf, dir, ts (Einstieg, UTC), exit_ts, ret (Netto-Rendite auf das Notional in Prozent, nach
Kosten Maker 0,02 % / Taker 0,06 % / Slippage 0,02 % auf Taker, Funding 0,01 %/8h), stress_ret (doppelte Kosten).
Kein Lookahead: Signal nur aus abgeschlossenen Kerzen, Fill nur wenn der Preis im Folgebalken erreicht wird; Stop vor TP
in derselben Kerze. Hoechstens eine Position je Coin und Variante gleichzeitig. Deterministisch, keine Datumskonstanten
ausser Warmup-Logik. Laufzeit auf allen Daten unter 20 Minuten.

## Entwicklung
Deine Teilung: Suche bis 2025-06-30, Pruefung 2025-07-01 bis 2026-05-09 (enthaelt Auf- und Abwaertsmarkt).
Bewertung: mittlere ret je Trade, stress_ret, ohne Top-5-Coins, 28-Tage-Blockbootstrap, Trades. Ziel fuer den OOS:
ret > 0 bei >= 100 Trades in 26 Wochen. Begruendet, warum deine Varianten in BEIDEN Marktphasen funktionieren sollten.

## Lieferung
strategie.py, Tests (kein Lookahead), `KANDIDATEN18.json`, `PREREG18.sha256` (SHA256 von strategie.py und KANDIDATEN18.json),
`RUNDE18_CODEX.md` (Idee, Mechanismus, Entwicklungsergebnisse, Grenzen). STOPP nach dem Freeze.
