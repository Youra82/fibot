# Vorregistrierung Konfluenz Runde 3 (Claude + Codex), 08.11.2026 – vor jeder Rechnung dieser Regeln auf P1/P2

Familie (Holm über 4): C1, C2, C3 (Codex, RUNDE3_CODEX.md, unverändert) und KS (Claude, unten). Basis: K0-Signal
(DEFAULTS+V2, 4h, 241 Coins, Long + Short gespiegelt). Kosten: Limit-Einstieg Maker 0,02 %, Ausstiege Taker 0,06 %
auf Ausstiegs-Notional + 0,02 % Schlupf. SL zuerst; TP frühestens Folgekerze; max. 120 Kerzen.
Mindest-Stop (User): Abstand Limit–SL ≥ 1,0 ATR(14) und ≥ 1 % – sonst keine Order (Codex-Konvention, kein Verbreitern).

- **C1:** K0-Einstieg, Ziel E + 1·D (D = Stop-Abstand). Kein Filter.
- **C2:** wie C1 + Long nur Coin > SMA50 (4h) und BTC-Tag > SMA200; Short nur Coin < SMA50 und BTC < SMA200.
- **C3:** K0-Einstieg; 50 % bei E + 1·D, 50 % am K0-Kanalziel; SL beider Hälften unverändert.
- **KS „Stop-Hunt unter der Zone“ (Claude):** Mechanismus: unter der 61,8-%/Kanallinie liegen Stops; ein Stich darunter wird
  zurückgekauft (verwandt mit dem belegten Wick-Rückkehr-Effekt). Solange ein gültiger K0-Plan besteht (alle K0-Bedingungen
  inkl. Schluss der Vorkerze über der Kanallinie), liegt zusätzlich eine Limit-Kauforder auf dem 78,6-%-Retracement f786.
  Fill wenn Tief ≤ f786 (Eröffnung darunter → Fill zur Eröffnung). SL = Tief von A − 0,25·ATR. Ziel = 50-%-Retracement f50.
  Mindest-Stop wie oben. Jeder Impuls B nur einmal (verbraucht beim Fill; Berührung der 61,8-Linie verbraucht ihn NICHT).

Bestehen (wie PREREG_KONFLUENZ_K0_K5): Tagesmittel > 0 in S, P1, P2; P1-Block-Bootstrap-p (28 Tage, +1-Korrektur) Holm 5 %
über 4; P1 Breite ≥ 55 % (Coins ≥ 5 Trades) und ohne Top-5 > 0; P1 Stress (+0,15 % + Funding 0,01 %/8 h) > 0.
Bekannt vor Registrierung: C1 auf S (eigene Vollsimulation, mit Stop-Verbreiterung statt Ablehnung) −0,13 R; Codex-Näherung
C1/C2/C3 auf S negativ. KS auf keinem Segment gerechnet.
