# Advisor message → sheet cells

## Ticker map (grow this; do not invent missing names)

| Advisor name | NSE |
| --- | --- |
| Amber | AMBER |
| IOL Chemical, IOL Chemical & Pharma, IOLCP | IOLCP |
| Canara Bank | CANBK |
| Pricol | PRICOL |
| ANANTRAJ, Anant Raj | ANANTRAJ |
| Pennar, PENIND | PENIND |
| Triveni | TRIVENI |
| Interarch | INTERARCH |
| JTL, JTLIND | JTLIND |
| Mazdock, Mazagon | MAZDOCK |
| GRSE | GRSE |
| Ask Automotive | ASKAUTOLTD |
| Anthem Bio | ANTHEM |
| 360ONE Wam | 360ONE |
| UNO Minda | UNOMINDA |
| Endurance Technologies | ENDURANCE |
| Northern Arc | NORTHARC |
| India Glycol | INDIAGLYCO |
| LT Foods | LTFOODS |
| Bajaj Auto | BAJAJ-AUTO |
| Interglobe / Indigo | INDIGO |
| Zen Tech | ZENTEC |
| GRSE | GRSE |
| Biocon | BIOCON |
| NLC India | NLCINDIA |
| Phoenix Mills | PHOENIXLTD |
| Gabriel India | GABRIEL |
| Caplin Point | CAPLIPOINT |
| Azad Engineering | AZAD |
| JTEKT India | JTEKTINDIA |
| Tilak Nagar Industries | TI |
| Aeroflex | AEROFLEX |
| IMFA | IMFA |
| Kirloskar / Kirlosker Pneumatic | KIRLPNU |
| Larsen & Toubro, L&T | LT |
| NMDC | NMDC |
| SBCL | SBCL |
| Samhi Hotels | SAMHI |
| Himatsingka | HIMATSEIDE |
| Stylam Industries | STYLAMIND |
| Texmaco Rail | TEXRAIL |
| Waaree Energies | WAAREEENER |
| TD Power | TDPOWERSYS |
| TVS Motors | TVSMOTOR |
| Star Cements | STARCEMENT |
| IGIL | IGIL |

The first line of a message may already be the NSE ticker (`SBCL`, `IMFA`, `NMDC`). Treat a single ticker-like token as the Share symbol.

## Risk percentage

- `2% Allocation` → `2%` (0.02)
- `2.5% Allocation Max` → `2.5%`
- `Allocation of 2-3%` → **2%** (lower)
- `2.5-3%` → **2.5%**

## Targets

- `Target Rs 9999` → FIRST `9999`
- `Target 220 - 240` → FIRST `220`, SECOND `240`
- `Target 645 - 750` → FIRST `645`, SECOND `750`
- Three numbers → FIRST / SECOND / THRID TARGET
- `Hit 1st Target of Rs 120` + `next target of Rs 135` → keep T1, set T2 `135`, note the hit in Comments

## Example: Amber (single buy, single target)

Message (pattern):

```
Amber : Clean Technical Breakout on weekly charts.
Buy at Rs 8320, Stop loss Rs 6700 on weekly closing.
Target Rs 9999.
Allocation of 2-3% good to start. Moderate Trade.
```

| Field | Value |
| --- | --- |
| Share | AMBER |
| Risk Percentage | 2% |
| Buy Range | 8320-8320 |
| Entry Price | 8320 (or live LTP if lower) |
| STOP LOSS | 6700 |
| FIRST TARGET | 9999 |
| SECOND / THRID | empty |
| Comments | Weekly close SL. Cup & handle / supertrend. Moderate. Valuation high-PE sector. |
| Qty / TCP | Formulas on that Excel row |

## Example: IOL Chemical (single buy, target band, 2%)

```
IOL Chemical & Pharma : Buy at Rs 180
Stop loss Rs 140 on Daily Closing Basis.
Target 220 - 240
Short Term Trade as per Chart Breakout.
Holding Period 2-4 Months. Max Allocation 2%.
```

| Field | Value |
| --- | --- |
| Share | IOLCP |
| Risk Percentage | 2% |
| Buy Range | 180-180 |
| Entry Price | 180 |
| STOP LOSS | 140 |
| FIRST TARGET | 220 |
| SECOND TARGET | 240 |
| Comments | Daily close SL. Short term chart breakout. Holding 2-4 months. Max allocation 2%. |

## Example: Pricol (buy band, allocation 2.5%)

```
Pricol : Buy at 550 - 555 Range, Some in dips upto Rs 500.
Stop loss Rs 400 on weekly closing basis.
Target 645 - 750. Holding Period 6-8 Months.
2.5% Allocation Max, Moderate Trade.
```

| Field | Value |
| --- | --- |
| Share | PRICOL |
| Risk Percentage | 2.5% |
| Buy Range | 500-555 |
| Entry Price | 550 (low of the Buy-at band; dip 500 is the range floor) |
| STOP LOSS | 400 |
| FIRST TARGET | 645 |
| SECOND TARGET | 750 |
| Comments | Dips to 500 mentioned. Weekly close SL. Hold 6-8 months. Moderate. |

Qty formula still uses Entry (N) and SL (V). Dip-to-500 is the Buy Range floor (`500-555`), not the plan entry.
