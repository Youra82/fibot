# Präregistrierung: 30 Fibo-Wick-Konfluenz-Strategien, OOS = letzte 26 Wochen

Stand 08.11.2026, geschrieben VOR jeder Rechnung auf dem OOS-Fenster.

## Fenster
- Auswahl (Training): 10.05.2024 – 09.05.2026 (exklusiv 10.05.2026). Daten ab 10.05.2026 werden in Stufe 1 nicht geladen.
- OOS: 10.05.2026 – Datenende (08.11.2026). Erst nach dem SHA256-Freeze von `auswahl.json` gerechnet.

## Strategie-Familie (Long, je Coin × Zeitebene × Tiefe × Regel, eigenes Konto)
- Mitte = (Hoch5 + Tief5)/2 der abgeschlossenen Kerzen, ATR14, Bereich = Hoch/Tief der letzten 42 Kerzen.
- Kauf-Limit `band = Mitte × (1 − Tiefe)`, Tiefe ∈ {5, 7, 9, 11} %.
- Regel FIB: Fib-Marke 61,8/78,6/127,2/161,8 % des Bereichs innerhalb 0,25 ATR vom band.
  Regel R25: FIB und zusätzlich runde Zahl (2 signifikante Stellen) innerhalb 0,25 ATR.
- Freigabe: BTC-Tagesschluss des Vortags > SMA200 und > SMA50.
- Fill, wenn Tief ≤ band; Einstieg min(Open, band). Stop = Einstieg − max(10 %, 1 ATR, 1 %); im Fill-Bar gilt der Stop schon.
- Take-Profit ab der Folgekerze, sobald Hoch ≥ aktuelle Mitte (Ausführung max(Open, Mitte)). Zeitausstieg nach 59 Kerzen.
- Eine Position zur Zeit; neue Einstiege ab der Kerze nach dem Ausstieg.
- Größe: Risiko 15 % des Kontos je Trade bis zum Stop inkl. Kosten, höchstens Hebel 3 (Notional ≤ 3 × Konto).
- Kosten: Maker 0,02 %, Taker 0,06 %, Slippage 0,02 % auf Taker-Ausstiege, Funding 0,01 % je 8 h auf das Notional.
- DD: aus Konto vor dem Trade und dem tiefsten Tief während des Trades (konservativ, intrabar).

## Auswahl (nur Trainingsdaten)
Zulässig: DD ≤ 50 %, ≥ 8 Trades, Gewinn in mindestens 3 der 4 Trainings-Halbjahre, Rendite im letzten Trainings-Halbjahr
(10.11.2025 – 09.05.2026) > 10 %. Rangfolge nach Gesamtrendite im Training; höchstens eine Strategie je Coin. Die besten 30.

### Nachtrag 1 (vor jeder OOS-Rechnung, 08.11.2026)
Erster Auswahllauf: 4408 Kandidaten, 0 zulässig. Ursache: Der BTC-Filter war vom 10.11.2025 bis 09.05.2026 durchgehend
aus (2026Q1/Q2 Anteil 0,00), im letzten Halbjahr gab es also keinen einzigen Trade. Die Bedingung „letztes Halbjahr > 10 %"
ist damit unerfüllbar und entfällt. Neu: Gewinn in allen 3 Halbjahren mit Handel (10.05.2024 – 09.11.2025). Alles andere
bleibt unverändert. Der leere erste Auswahllauf wurde gelöscht, OOS-Daten wurden nicht gerechnet.

## Prüfung (OOS)
- Bestanden je Strategie: OOS-Rendite > 10 % und OOS-DD ≤ 50 %.
- Primär: Anzahl bestandener unter den 30 und mittlere OOS-Rendite.
- Vergleich Zufall: 10 000 Ziehungen von 30 Strategien (eine je Coin) aus allen Kandidaten mit ≥ 1 Trainings-Trade.
  p = Anteil der Ziehungen mit mindestens so vielen Bestandenen bzw. mindestens so hoher mittlerer OOS-Rendite.
- Nachweis erbracht nur, wenn p < 0,05 für beide UND mittlere OOS-Rendite der Auswahl > 0.

## Bekannte Grenzen
Survivorship (nur heute gelistete Coins), konstantes Funding, keine Lot-/Mindestmengen, Familie wurde nach der
Konto-Forschung bis 08.11.2026 ausgewählt (die Wick-Rückkehr ist seit Oktober bekannt).
