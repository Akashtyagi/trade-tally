# Column dictionary (Aug24-27 tab)

Letters are the live workbook. **L** is always the NSE/BSE ticker. Do not use `docs/02-features.md` as the column list.

## Summary / sizer

| A1 | Meaning | Who writes |
| --- | --- | --- |
| A5 | Corpus | You |
| B2 | Global max allocation (caps qty) | You |
| K2 | Remaining balance | Sheet formula |
| N2 | Active investment | Sheet formula |

## Open trades — J5:Z (comments AA)

Data starts at **row 5**. Last sequential Share is the last non-empty **L** before a gap (S No 38 sits on that last filled row). Append on the next empty **L** in this block. Never write open rows around row 199.

| Letter | Header | Who writes | Meaning |
| --- | --- | --- | --- |
| J | S No | Sheet (pre-numbered) | Open index |
| K | Date | Ingest if known | Idea date |
| L | Share | Ingest | **NSE/BSE ticker** |
| M | (risk %) | Ingest | Allocation as `0.02` (2%). Header may still say Share. Lower of a range. |
| N | Entry Price | Ingest if empty | Plan price inside Buy Range |
| O | Quantity | Kite / sync only | Held qty. Never write from recs. |
| P | Maximum Shares Recom. | Formula | Qty formula below |
| Q | Maximum Investment Suggested | Formula | Max-investment formula below |
| R | Total Investment | Sheet / Zerodha | Do not overwrite on rec ingest |
| S | Total Captial Percentage | Formula | `=DIVIDE(R{row},$A$5)` |
| T | Buy Range | Ingest if empty | Advisor band only |
| U | Current P/L | Formula | `=(GOOGLEFINANCE(L{row})-N{row})` |
| V | STOP LOSS | Ingest if empty | Stop |
| W | Sell Ratio | Formula | `=(O{row}*0.4)&" - "&(O{row}*0.3)&" - "&(O{row}*0.3)` |
| X | FIRST TARGET | Ingest if empty | T1 |
| Y | SECOND TARGET | Ingest if empty | T2 |
| Z | THRID TARGET | Ingest if empty | T3 (live typo) |
| AA | Comments | Ingest | Thesis / later notes |

**If L already exists:** fill only empty or `#DIV/0!` / `#VALUE!` plan cells. Leave complete rows alone.

```excel
=MIN(ROUNDDOWN(($A$5*M10)/(N10-V10),0),ROUNDDOWN(($A$5*$B$2)/N10,0))
=ROUND((P10*N10),0) & " : " & ROUND((P10*N10)/$A$5*100,1) & "%"
```

Skip the qty formula when `N − V <= 0`.

## Completed trades — AC5:AK (comments AL)

| Letter | Header | Who writes | Meaning |
| --- | --- | --- | --- |
| AC | S No | Ingest | Next index (pre-numbered empties exist) |
| AD | Share | Ingest | Ticker |
| AE | Entry Price | Ingest | Avg in from the close note if known |
| AF | Quantity | Ingest | Closed qty if known |
| AG | Exit Price | Ingest | Exit / target / CMP |
| AH | Total Cash Out | Formula | `=MULTIPLY(AF,AG)` |
| AI | P/L | Formula | `=PRODUCT(MINUS(AG,AE),AF)` |
| AJ | P/L Percentage | Formula | `=ROUND((AI/(AE*AF)),2)` |
| AK | Date | Ingest if known | Close date |
| AL | Comments | Ingest | Close note |

If **AD** already has the ticker, do not add a second close. Close-only messages do not create a J–Z open row.

## App writes (not rec ingest)

| Source | Writes |
| --- | --- |
| Zerodha sync | O Quantity, sometimes R |
| `run_checks` | O if it differs from Kite |
| Close UI / tradebook | May copy into AC–AK |
