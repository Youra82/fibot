# Suche nach einem trennenden Konfluenzfilter

58957 historische Ereignisse, 407 Configs; 58845 mit gueltigen Vorabmerkmalen. Bereits untersuchte und fuer Parameteroptimierung verwendete Historie. Kein frischer Profitabilitaetsnachweis. Pro Coin eine Position, alle Timeframes gemeinsam; kein Kontokapitalmodell.

Nur aus Trainingsdaten ausgewaehlt: **VOL1**. Diagnostische Robustheitspruefung: **nicht bestanden**. 95%-Blockbootstrapintervall der taeglichen R-Summen in vereinigten Pruefsegmenten: [-1.3333779191976893, 0.630464763612028].

| Regel | Suche A vor 2026 R (n) | Pruefung B vor 2026 R (n) | A 2026 R (n) | B 2026 R (n) | Ab 15.10. R (n) |
|---|---:|---:|---:|---:|---:|
| BASE | +0.131 (8825) | +0.191 (8824) | -0.244 (8015) | -0.159 (7544) | -0.405 (1359) |
| EMA200 | +0.118 (6284) | +0.159 (6252) | -0.150 (5840) | -0.149 (5374) | -0.334 (981) |
| EMA200_SLOPE | +0.122 (6260) | +0.158 (6221) | -0.151 (5815) | -0.150 (5362) | -0.330 (976) |
| STOP_ATR_1 | +0.105 (6343) | +0.136 (6294) | -0.140 (6217) | -0.138 (5673) | -0.254 (1029) |
| EMA_STOP_1 | +0.086 (4744) | +0.137 (4681) | -0.128 (4694) | -0.124 (4255) | -0.209 (798) |
| STOP_ATR_1.5 | +0.097 (4441) | +0.154 (4342) | -0.107 (4554) | -0.153 (4129) | -0.171 (764) |
| EMA_STOP_1.5 | +0.092 (3398) | +0.147 (3320) | -0.085 (3523) | -0.119 (3181) | -0.132 (574) |
| STOP_ATR_2 | +0.127 (2817) | +0.143 (2841) | -0.095 (3067) | -0.109 (2781) | -0.095 (485) |
| EMA_STOP_2 | +0.118 (2191) | +0.163 (2216) | -0.079 (2398) | -0.080 (2203) | -0.039 (377) |
| STOP_ATR_2.5 | +0.146 (1761) | +0.142 (1781) | -0.054 (1956) | -0.035 (1816) | -0.126 (304) |
| EMA_STOP_2.5 | +0.156 (1397) | +0.141 (1407) | -0.033 (1555) | -0.005 (1455) | -0.090 (240) |
| RR_MAX_2 | +0.094 (2472) | +0.112 (2366) | -0.147 (2346) | -0.084 (2063) | -0.176 (372) |
| RR_MAX_3 | +0.105 (5007) | +0.120 (4863) | -0.151 (4937) | -0.129 (4276) | -0.233 (821) |
| RR_MAX_5 | +0.074 (7383) | +0.115 (7100) | -0.177 (6842) | -0.168 (6141) | -0.299 (1149) |
| EMA_RR_3 | +0.098 (3717) | +0.127 (3550) | -0.119 (3698) | -0.097 (3210) | -0.201 (620) |
| EMA_RR_5 | +0.056 (5369) | +0.125 (5181) | -0.160 (5061) | -0.142 (4532) | -0.254 (876) |
| EMA_STOP_1.5_RR3 | +0.098 (2988) | +0.135 (2852) | -0.074 (3035) | -0.097 (2707) | -0.129 (502) |
| EMA_STOP_2_RR3 | +0.135 (2057) | +0.153 (2048) | -0.095 (2160) | -0.075 (2022) | -0.051 (343) |
| VOL1 | +0.172 (4182) | +0.169 (4350) | -0.225 (3413) | -0.115 (3116) | -0.346 (581) |
| ADX25 | +0.164 (4584) | +0.181 (4652) | -0.207 (3946) | -0.086 (3863) | -0.255 (658) |
| RSI40_60 | +0.108 (8128) | +0.138 (8138) | -0.273 (7413) | -0.167 (6948) | -0.452 (1252) |
| EMA_STOP_1.5_VOL1 | +0.056 (1310) | +0.192 (1282) | -0.053 (1153) | -0.054 (1024) | -0.122 (191) |

## Ausgewaehlter Kandidat im Detail

{
  "search": {
    "n": 4182,
    "R": 0.1721606853859473,
    "sum_R": 719.9759862840316,
    "stress_R": -0.06866581972945948,
    "win": 0.29100908656145386,
    "without_top5_R": 0.0967674478415101,
    "coins": 40
  },
  "all": {
    "n": 15658,
    "R": 0.008527331583680426,
    "sum_R": 133.52095793726812,
    "stress_R": -0.283648980194744,
    "win": 0.2744284072039852,
    "without_top5_R": -0.02558115999793942,
    "coins": 80
  },
  "selected38_subset_of_universe_replay": {
    "n": 1555,
    "R": 0.2892003746454773,
    "sum_R": 449.70658257371724,
    "stress_R": 0.027619358352492497,
    "win": 0.30289389067524114,
    "without_top5_R": 0.15299283372441513,
    "coins": 28
  },
  "B_before2026": {
    "n": 4350,
    "R": 0.1688728756599403,
    "sum_R": 734.5970091207403,
    "stress_R": -0.08037263434714771,
    "win": 0.29172413793103447,
    "without_top5_R": 0.09572579260737143,
    "coins": 40
  },
  "A_2026": {
    "n": 3413,
    "R": -0.22492686749908705,
    "sum_R": -767.6753987743841,
    "stress_R": -0.5843089156217424,
    "win": 0.2572516847348374,
    "without_top5_R": -0.2919493929730395,
    "coins": 40
  },
  "B_2026": {
    "n": 3116,
    "R": -0.11453837335817188,
    "sum_R": -356.9015713840636,
    "stress_R": -0.4568628976943044,
    "win": 0.2535301668806162,
    "without_top5_R": -0.2511700900253899,
    "coins": 40
  },
  "recent": {
    "n": 581,
    "R": -0.345860950915822,
    "sum_R": -200.94521248209256,
    "stress_R": -0.6702248520515584,
    "win": 0.23752151462994836,
    "without_top5_R": -0.47673190850475017,
    "coins": 77
  }
}

## Grenzen

- Historische Config-Optimierung und wiederverwendete Daten beschraenken die Aussagekraft aller Segmente.
- Quellexport enthaelt nur geschlossene Ereignisse. Am Datenende noch offene Positionen fehlen; kein vollstaendiger Live-Replay.
- Ereignisfolge des urspruenglichen Detektors bleibt fix. Ein Filter erzeugt keine neuen Impuls-Setups.
- Gebuehren und konservativer Stop-Schlupf enthalten; kein historisches Funding, Orderbuch oder Intrabar-Replay.
- Netto-R statt Trefferquote entscheidet. Eine nachtraeglich auf die sieben Gewinner zugeschnittene Regel ist kein belastbarer Filter.
- Produktionscode und settings.json wurden nicht geaendert.

Separate Replay-Pruefung der 38 Configs mit bestehendem Trendfilter: actual38_with_trend.json. Das Feld selected38_subset_of_universe_replay ist dagegen nur ein Teilbestand des Universums-Replays.
