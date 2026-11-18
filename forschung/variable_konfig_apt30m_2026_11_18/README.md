# fibot APT 30m: variable Config mit Parameter-Kurven (18.11.2026)

## Vorab festgelegt (vor Auswertung des ungesehenen Zeitraums)

- **Config:** APT/USDT 30m Konfluenz (Live-Config). Trendfilter wie live, 1 Position zur Zeit,
  Kosten 0,17 % Round-Trip, Ausstieg wie `signal_exit` (SL vor TP bei gleicher Kerze).
- **Variable Parameter (11):** pivot_k, window, max_break_frac, fib_lo, fib_hi, fib_sl,
  zone_tol_atr, sl_buf_atr, min_rr, max_age_mult, b_near_upper_atr. Raster = 69.120 Kombinationen,
  alle per CUDA (RTX 3060 Ti) gerechnet; Kernel gegen den Python-Originalcode abgeglichen (`verify.py`).
- **Zeiträume:** Entwicklung 01.03.2023 – 30.04.2026 (38 Monate). Ungesehen 01.05.2026 – Datenende.
- **Stützpunkt je Monat:** Top 1 % der Kombinationen nach Netto-R im Fenster Vormonat/Monat/Folgemonat
  (nur Entwicklungsdaten); Stützpunkt = Mittelwert jedes Parameters über diese Top 1 %.
- **Kurve je Parameter:** lokal-lineare Glättung (Gauß-Kern, Bandbreite h Monate). Fortsetzung in den
  ungesehenen Zeitraum = lineare Verlängerung der Kurve am Ende der Entwicklung. Werte werden auf den
  Rasterbereich begrenzt und auf den nächsten Rasterwert gerundet. Parameterwechsel nur zum Monatsanfang.
- **„Funktioniert“** = Monat mit mindestens einem Trade und Netto-R > 0. Quote = solche Monate / Monate mit Trades.
- **Wahl von h:** größtes h aus {1; 1,5; 2; 3; 4; 6; 9; 12}, mit dem die Kurven-Config in der Entwicklung
  ≥ 60 % erreicht. Erreicht keins 60 %: h mit der höchsten Quote.
- **Bewertung ungesehen:** Kurve (Hauptergebnis) gegen Kurve flach gehalten und gegen die feste Live-Config;
  dazu Rang unter allen 69.120 festen Kombinationen. Die Kurve gilt als besser, wenn sie im ungesehenen
  Zeitraum mehr Netto-R als die feste Config hat **und** die Monatsquote ≥ 60 % hält.
- Einschränkung: APT als Coin wurde am 15.10. mit Wissen über Mai–Okt. 2026 gewählt.

## Ergebnis (Lauf 18.11.2026, Daten bis 18.11. 19:30 UTC, Laufzeit 27 s)

Gewählte Glättung: **h = 3 Monate** (größtes h mit ≥ 60 % in der Entwicklung: 67 %).

| Variante | Entw. Quote | Entw. R | ungesehen Quote | ungesehen R | Trades | PnL bei 1 % | DD | Rang unter 69.120 festen |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Kurve (Hauptergebnis) | 67 % | +53,5 | 60 % (3/5) | **+19,7** | 21 | +19,9 % | 7,8 % | 99 % |
| Kurve flach gehalten | 67 % | +53,5 | 50 % (3/6) | +16,9 | 22 | +16,7 % | 7,7 % | 97 % |
| feste Live-Config | 68 % | +42,8 | 67 % (4/6) | +10,9 | 19 | +11,1 % | 4,5 % | 87 % |

- Vorab-Kriterium (mehr R als fest **und** Quote ≥ 60 %): **knapp erfüllt** (3 von 5 Monaten).
- Alle 8 Glättungen schlagen die feste Config ungesehen (+12,3 bis +19,7 R gegen +10,9 R).
- Der Großteil des Vorteils kommt vom **Parameterstand am Ende der Entwicklung** (flach: +16,9 R), die
  Trend-Verlängerung bringt nur +2,8 R zusätzlich.
- Nur 4,9 % aller festen Kombinationen erreichen in der Entwicklung ≥ 60 % Monatsquote.
- 21 Trades sind wenig; der Vorsprung von +8,8 R liegt bei etwa einer Standardabweichung.

Grafiken: `parameter_kurven.png`, `ergebnis.png`. Zahlen: `summary.json`.

## Nachtrag 18.11.2026: gleiche Methode auf SHIB 30m, BAT 1h, DOT 2h (vorab festgelegt)

- Regeln unverändert (Stützpunkte, Glättung, Wahl von h, Kriterium). Ungesehen weiterhin ab 01.05.2026.
- Raster je Coin = APT-Raster **plus** der Wert der jeweiligen Live-Config (max_age „keine Grenze“ als eigener
  Rasterwert). Nicht variierte Teile (min_width_atr, touch_atr, tp_mode) wie in der Live-Config.
- Entwicklung beginnt im ersten vollen Monat ≥ 60 Tage nach Datenbeginn (Trendfilter-Vorlauf).
- **Gesamturteil Methode:** bestanden, wenn die Kurve in mindestens 2 der 3 neuen Coins das Einzelkriterium
  erfüllt (mehr R als die feste Live-Config **und** ungesehene Monatsquote ≥ 60 %).

### Ergebnis Nachtrag (Lauf 18.11.2026; SHIB/BAT/DOT Daten bis 17.11.)

Kernel vorher gegen Python geprüft: alle 4 Coins × 2 Kombis × 2 Richtungen identisch (`verify_log.txt`).

| Coin | Raster | h | Entw.-Quote Kurve | ungesehen R Kurve / flach / fest | Trades Kurve | Quote ungesehen Kurve / fest | Rang Kurve / fest | Einzelkriterium |
|---|---:|---:|---:|---|---:|---|---|---|
| APT 30m | 69.120 | 3 | 67 % | **+19,7** / +16,9 / +10,9 | 21 | 60 % / 67 % | 99 % / 87 % | erfüllt |
| SHIB 30m | 69.120 | 3 | 62 % | **+8,8** / +6,0 / −1,1 | 17 | 50 % / 40 % | 94 % / 22 % | nicht (Quote) |
| BAT 1h | 225.792 | 1 | 54 % (Ziel verfehlt) | **+11,1** / +2,5 / +3,9 | 10 | 60 % / 60 % | 87 % / 53 % | erfüllt |
| DOT 2h | 169.344 | 2 | 61 % | **+3,8** / +1,7 / +1,1 | 2 | 100 % / 60 % | 80 % / 61 % | erfüllt (nur 2 Trades) |

- **Gesamturteil vorab-Regel: bestanden (3 der 3 neuen Coins schlagen fest im R, 2 von 3 erfüllen auch die Quote).**
- Summe ungesehen: Kurve **+43,4 R**, flach +27,1 R, fest +14,9 R. Die Kurve schlägt in **allen 4 Coins** sowohl
  die feste Config als auch die flach gehaltene Kurve -> die Trendfortsetzung trägt hier tatsächlich bei.
- Schwächen: DOT-Kurve wird sehr eng (Zone 0,5–0,618, Toleranz 0,1) -> nur 2 Trades; BAT erreicht die
  60 % in der Entwicklung nur ohne Glättung (h=1). Wenige Trades je Coin, Monatsquote bleibt rauschig.

Grafiken je Coin: `ergebnisse/<COIN_TF>/parameter_kurven.png`, `ergebnis.png`; Übersicht `ergebnisse/uebersicht.png`.

## Teil 2 (18.11.2026): Parameter nach aktueller Marktlage statt nach Zeit (vorab festgelegt)

- **Marktlage je Kerze** (nur abgeschlossene Kerzen bis i-1):
  - Schwankung = Std. der Log-Renditen letzte 48 h / Std. letzte 30 Tage.
  - Trend = Effizienz-Quote 72 h = |Close(i-1) − Close(i-1-n)| / Σ|ΔClose|.
  - Je Merkmal Terzile aus der Entwicklung → 3 × 3 = 9 Marktlagen. Gleiches für alle 4 Coins.
- **Parameter je Marktlage:** Top 1 % der Kombinationen nach Netto-R der Trades, die in dieser Marktlage eröffnet
  wurden (nur Entwicklung) → Mittelwert je Parameter → auf Raster gerundet. Wechsel sofort, wenn die Lage wechselt.
- **Vergleich ungesehen (ab 01.05.2026):** feste Live-Config, Monats-Kurve (Teil 1), Gegentest: dieselbe Zuordnung
  mit um 30–300 Tage zirkulär verschobener Marktlage (20 Verschiebungen).
- **Bestanden**, wenn die Marktlage-Config ungesehen in ≥ 3 von 4 Coins mehr R als die feste Config hat **und** in
  ≥ 3 von 4 Coins über dem Median des Gegentests liegt.

### Ergebnis Teil 2 (Marktlage Schwankung × Trend)

| Coin | Marktlage ungesehen R | fest | Monats-Kurve | Gegentest-Median | Rang vs. Gegentest | Entw. R (in-sample) |
|---|---:|---:|---:|---:|---:|---:|
| APT 30m | +5,2 | +10,9 | +19,7 | +3,7 | 55 % | +124,0 |
| SHIB 30m | −7,0 | −1,1 | +8,8 | +7,2 | 5 % | +85,5 |
| BAT 1h | +9,2 | +3,9 | +11,1 | +5,3 | 75 % | +62,0 |
| DOT 2h | +6,8 | +1,1 | +3,8 | +0,6 | 100 % | +42,4 |

**Nicht bestanden** (schlägt fest nur in 2/4). Riesige In-sample-Werte, ungesehen schwach → überangepasst.
Die Merkmale (Schwankung, Effizienz) waren geraten, nicht aus den Kurven abgeleitet.

## Teil 3 (18.11.2026): Wovon hingen die Monats-Kurven ab? (`abhaengigkeit.py`)

Stützpunkte aus Teil 1 gegen 9 Merkmale desselben 3-Monats-Fensters, Spearman, Permutation mit Blockverschiebung.

- **Kein Merkmal erklärt die Kurven über alle Coins.** Stärkster gepoolter Zusammenhang |rho| 0,37
  (Fib-Zone Anfang ↔ Dochtanteil); reiner Zufall liefert bei 88 Paaren im Median 0,31, 95-%-Grenze 0,39.
- **Je Coin gibt es starke, aber verschiedene Treiber** (SHIB: Zonen-Toleranz ↔ ATR −0,74, Fib-Anfang ↔ Docht −0,70;
  APT: Zonen-Toleranz ↔ Effizienz −0,59, Stop-Puffer ↔ Zeit −0,56). Sie widersprechen sich zwischen den Coins.
- **Einziges Muster mit gleicher Richtung in allen 4 Coins:** Richtung/Abstand zum 90-Tage-Hoch ↔ Tiefe der Fib-Zone.
  Steigender Markt nahe am Hoch → tiefere Zone (fib_hi rho +0,26…+0,42), breitere Toleranz, höherer Zonenanfang. Schwach.
- Schwankung und Trend-Effizienz (Grundlage von Teil 2) zeigen keinen gemeinsamen Zusammenhang → erklärt das Scheitern.
- Zeit allein erklärt fast nichts (|rho| ≤ 0,16 gepoolt) → die Kurven sind keine langsamen Trends, sondern folgen
  coin-eigenen Phasen.

Grafiken: `ergebnisse_abhaengigkeit/abhaengigkeit_heatmap.png`, `staerkste_zusammenhaenge.png`; Tabelle `zusammenhaenge.csv`.

## Teil 4 (18.11.2026): Regler über die Wirkung (vorab festgelegt)

- Jeden Tag 00:00 UTC: Score jeder Kombination = Netto-R aller Trades, die in den letzten **W Tagen geschlossen**
  wurden (nur bekannte Ergebnisse, kein Blick nach vorn); Gleichstände per Score der letzten 365 Tage aufgelöst.
- Neue Parameter für diesen Tag = Mittel der Top 1 % → auf Raster gerundet. Keine weitere Glättung.
- W aus {14, 30, 60, 90} Tagen: höchster Entwicklungs-R unter den W mit Entwicklungs-Monatsquote ≥ 60 %
  (sonst höchster Entwicklungs-R). Der Regler ist von Natur aus Walk-forward; nur W wird in der Entwicklung gewählt.
- Gegentest „veralteter Regler“: gleicher Ablauf, aber Score-Fenster um 120–365 Tage zurückversetzt (10 Läufe).
- **Bestanden**, wenn der Regler ungesehen (ab 01.05.2026) in ≥ 3 von 4 Coins mehr R als die feste Config hat,
  in ≥ 3 von 4 über dem Median des Gegentests liegt **und** in der Summe mehr R als die Monats-Kurve (Teil 1) bringt.

### Ergebnis Teil 4 (Regler über die Wirkung)

| Coin | W gewählt | Entw. R (Walk-forward) je W 14/30/60/90 | ungesehen Regler | fest | Monats-Kurve | veralteter Regler Median (Rang) |
|---|---:|---|---:|---:|---:|---:|
| APT 30m | 14 | −7 / −16 / −26 / −36 | +12,7 | +10,9 | +19,7 | +3,6 (70 %) |
| SHIB 30m | 90 | −18 / −35 / −27 / −11 | +2,1 | −1,1 | +8,8 | +7,0 (20 %) |
| BAT 1h | 30 | −15 / −13 / −47 / −31 | +16,1 | +3,9 | +11,1 | +7,0 (90 %) |
| DOT 2h | 30 | −15 / −12 / −21 / −16 | +0,5 | +1,1 | +3,8 | +0,6 (50 %) |

**Nicht bestanden:** schlägt fest 3/4 ✓, über Gegentest-Median nur 2/4 ✗, Summe +31,4 R < Monats-Kurve +43,4 R ✗.

**Wichtigster Befund:** In der Entwicklung (echter Walk-forward, 2023–04/2026) ist der Regler in **allen 16
Kombinationen aus Coin × Fenster negativ**. „Die zuletzt besten Parameter nehmen“ hat über 3 Jahre Geld gekostet –
was gerade gut lief, war danach eher schlechter (Glück der Gewinner kehrt sich um). Die positiven Werte im
ungesehenen Zeitraum kommen von einer günstigen Phase für diese 4 Coins (auch die festen Configs sind dort positiv).

Folgerung für Teil 1: Die Monats-Kurve wurde nur an **einem** ungesehenen Zeitraum geprüft. Bevor sie live geht,
muss sie selbst Walk-forward über die Entwicklung laufen (monatlich nur mit Vergangenheit neu angepasst).

## Teil 5 (18.11.2026): Übergeordneter Zeitrahmen regelt die Fib-Zone (vorab festgelegt)

- **HTF-Lage in Handelsrichtung**, aus abgeschlossenen Tageskerzen (Wert des Vortags):
  Long: Abstand Tagesschluss zum 90-Tage-Hoch; Short: Abstand zum 90-Tage-Tief. Rang dieses Abstands unter den
  letzten 365 Tagen (mind. 120) → Drittel: **nah am Extrem (starker Trend) / mittel / weit weg (schwacher Trend)**.
  (Richtung selbst gibt weiterhin der bestehende Trendfilter vor.)
- **Geregelt nur:** fib_lo, fib_hi, zone_tol_atr. Die übrigen 8 Parameter = Live-Config.
- **Walk-forward, monatlich:** Für Monat m wählt jede Lage die Zonen-Einstellung mit dem höchsten Netto-R aus allen
  Trades **vor** Monat m in dieser Lage (mind. 10 Trades, sonst Live-Werte). Auswertung ab 6 Monaten Vorlauf bis heute.
- **Vergleiche:** (a) feste Live-Config, (b) „ohne Lage“: gleiche Monats-Neuwahl der Zone, aber nur eine Lage,
  (c) Gegentest: Lage zirkulär um 60–300 Tage verschoben, 20 Läufe.
- **Bestanden**, wenn in ≥ 3 von 4 Coins: Walk-forward-R gesamt > „ohne Lage“ **und** > Gegentest-Median,
  **und** ungesehen (ab 05/2026) R ≥ feste Config in ≥ 3 von 4 Coins.

### Ergebnis Teil 5 (HTF-Lage regelt Fib-Zone, Walk-forward)

| Coin | WF gesamt HTF | ohne Lage | fest (in-sample) | Gegentest-Median (Rang) | ungesehen HTF / ohne / fest |
|---|---:|---:|---:|---:|---|
| APT 30m | +44,1 | +46,8 | +49,4 | +43,3 (60 %) | +12,1 / +8,6 / +10,9 |
| SHIB 30m | +4,9 | +10,9 | +1,8 | +10,7 (15 %) | +0,6 / +9,0 / −1,1 |
| BAT 1h | +21,6 | +5,1 | +5,1 | +5,7 (100 %) | +8,2 (3 Tr) / +3,9 / +3,9 |
| DOT 2h | +4,1 | −2,4 | +11,2 | +5,7 (30 %) | +2,3 / +1,1 / +1,1 |

**Nicht bestanden:** > ohne Lage nur 2/4, > Gegentest-Median nur 2/4 (ungesehen ≥ fest 4/4 erfüllt).
Die gewählten Zonen je Lage widersprechen sich zwischen den Coins (keine gemeinsame Regel „starker Trend → X“).
Nur BAT profitiert deutlich. Nebenbefund: vorsichtige Neuwahl (nur 3 Parameter, ganze Vergangenheit) bleibt im
Walk-forward positiv – anders als der schnelle Tages-Regler aus Teil 4.

## Teil 6 (18.11.2026): Monats-Kurve im echten Walk-forward (vorab festgelegt)

- Für jeden Monat m (ab 12 Monaten Vorlauf): Stützpunkte nur aus Monaten < m (Fenster Vormonat/Monat/Folgemonat,
  am Rand auf < m gekürzt; Top 1 %; Gleichstände nach Netto-R aller Monate < m). Kurve lokal-linear, **h = 3**
  (fest, wie bei APT/SHIB in Teil 1), um 1 Monat fortgesetzt, auf Raster gerundet. Daneben „flach“ (ohne Steigung).
- Empfindlichkeit (nur berichtet): h = 1,5 und h = 6.
- Vergleiche: „ohne Lage“ aus Teil 5 (vorsichtige Zonen-Neuwahl, Walk-forward), Zufall: je Monat Mittel von
  zufälligen 1 % der Kombinationen (20 Läufe), feste Live-Config (bis 04/2026 in-sample).
- **Bestanden**, wenn in ≥ 3 von 4 Coins: Walk-forward-R gesamt > „ohne Lage“ **und** > Zufalls-Median **und**
  Walk-forward-R vor 05/2026 > 0.

### Ergebnis Teil 6 (Monats-Kurve Walk-forward)

| Coin | Kurve h=3 WF gesamt | davon vor 05/2026 | ungesehen | „ohne Lage“ (Zonen-Neuwahl) | Zufall-Median | fest (in-sample) |
|---|---:|---:|---:|---:|---:|---:|
| APT 30m | +17,3 | −1,9 | +19,2 | **+38,0** | +8,5 | +41,8 |
| SHIB 30m | −8,8 | −8,7 | −0,1 | **+11,4** | +0,8 | +1,2 |
| BAT 1h | −1,6 | −14,1 | +12,5 | **+4,4** | −8,9 | +4,4 |
| DOT 2h | −13,7 | −10,7 | −3,1 | **−4,0** | −8,8 | +9,6 |

**Nicht bestanden** (WF vor 05/2026 in 0/4 positiv). Das Ergebnis von Teil 1 kam aus dem einen günstigen Zeitraum.
Die vorsichtige Zonen-Neuwahl (3 Parameter, ganzes Gedächtnis) ist im ehrlichen Walk-forward die beste variable Form.

## Teil 7 (18.11.2026): Langsame Anpassung weniger Parameter ausbauen (vorab festgelegt)

- Walk-forward monatlich ab Monat 12 (wie Teil 6). Nicht angepasste Parameter = Live-Config.
- **Gruppen:** Zone (fib_lo, fib_hi, zone_tol) | Stop (fib_sl, sl_buf) | Ziel/Filter (min_rr, max_age) |
  Zone+Stop | Zone+Stop+Ziel | alle 11.
- **Gedächtnis:** alles | 24 Monate | 12 Monate | Halbwertszeit 12 Monate (exponentiell).
- **Regel:** max. Netto-R (≥ 10 Trades) | max. R pro Trade (≥ 20 Trades). Sonst Live-Werte.
- 48 Varianten je Coin. **Wahl der Variante nur nach Summe WF-R vor 05/2026 über alle 4 Coins**; danach ungesehen.
- **Bestanden**, wenn die gewählte Variante ungesehen in der Summe mehr R als die feste Config bringt **und** in ≥ 3 von 4
  Coins ≥ fest ist. Berichtet wird zusätzlich, wie viele der 48 Varianten vor 05/2026 die Zonen-Neuwahl übertreffen.
