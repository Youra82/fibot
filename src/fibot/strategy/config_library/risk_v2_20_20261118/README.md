# FiBot Risk-Policy-v2-Variantenbibliothek

Diese Bibliothek enthaelt 20 unterschiedliche Konfluenz-Configs, die am
18.11.2026 mit CUDA gesucht und anschliessend vollstaendig nachgetestet wurden.

Zeitraum und Auswahlregeln:

- Parametersuche: Marktdaten vor dem 01.05.2026
- Interne Validierung: die letzten 180 Tage vor dem 01.05.2026
- Separater Test: 01.05.2026 bis 17.11.2026
- positive PnL in Training, interner Validierung und separatem Test
- maximal 30 Prozent Drawdown im separaten Test
- mindestens 5 Trades im separaten Test
- Risk Policy v2 mit mindestens 0,30 Prozent, 0,30 ATR und 3 Ticks Stop-Abstand
- identische OOS-Handelsfolgen wurden als Duplikate entfernt

Zusammensetzung:

- 6 Varianten APT/USDT:USDT 30m
- 5 Varianten APT/USDT:USDT 1h
- 4 Varianten BAT/USDT:USDT 1h
- 5 Varianten DOT/USDT:USDT 2h

Die Dateien sind eine Variantenbibliothek und duerfen nicht gleichzeitig fuer
dasselbe Symbol aktiviert werden. Bis ein kausal getesteter Marktregime-Selektor
vorhanden ist, bleiben die normalen Live-Configs in `strategy/configs` aktiv.
`manifest.json` enthaelt Parameter, Pre-OOS-, Validierungs- und OOS-Kennzahlen
sowie die reproduzierbare Auswahlreihenfolge.
