---
name: google-sheet
description: Maps financial-advisor equity messages onto the Trade Tally Google Sheet (Aug24-27 layout), fills qty/TCP/target cells with the live formulas, and tallies recommendation dumps such as zerodha_files/trades.txt. Use when adding or updating sheet rows, ingesting advisor recs, explaining Share/Buy Range/STOP LOSS/targets/TCP, or writing Google Sheet trade data.
---

# Google Sheet fill spec (Trade Tally)

This repo tracks **advisor equity recs** in a Google worksheet (default tab `Aug24-27`). The sheet is the plan source of truth. Django syncs it; Kite owns **held Quantity** and P/L cells.

Do **not** use `docs/02-features.md` as the column list. Use [columns.md](columns.md). Worked recs: [examples.md](examples.md). Dump ingest: [ingest.md](ingest.md).

## When to apply

- User asks to fill, tally, or update the Google Sheet from advisor text
- Questions about what a sheet column means or who writes it
- Ingest of `zerodha_files/trades.txt` or similar message dumps

## Workbook geography

One tab, three blocks on the same header row:

1. **Left sizer** (A–H) — corpus `A5`, global max allocation `B2`. Do not invent trade rows from sizer leftovers.
2. **Open trades** — **J5:Z** (comments AA). **L** is the NSE/BSE ticker. Append after the last contiguous Share (S No 38), not far down the sheet.
3. **Trade completed** — **AC5:AK** (comments AL). Close-only messages go here.

## Add or update an open row

Copy this checklist:

```
- [ ] Classify message: new buy / update existing / skip
- [ ] Confirm NSE ticker (never invent)
- [ ] Fill Date, Share, Risk Percentage (lower of a range), Buy Range, Entry Price, STOP LOSS, targets, Comments
- [ ] Write qty / TCP / max-investment **formulas** (do not hardcode unless SL >= entry)
- [ ] Leave Quantity, Current P/L, Total Investment alone
```

**New buy**

1. Ticker: map company name → NSE symbol using [examples.md](examples.md). A single token like `SBCL` or `IMFA` is already the ticker. If missing, look up and **ask** before writing.
2. **Risk Percentage** (column M on the live tab): allocation from the message. If `2.5-3%` or `2–3%`, store the **lower** only (`2.5%` or `2%`). Sheet percent (`0.025`) or `2.5%` text is fine if Excel treats it as percent in the qty formula (`$A$5*M12`).
3. **Buy Range**: advisor buy band only (`8000-8320`). Single buy → `8320-8320`. If they also say **Some in dips upto Rs X**, the range is `X` to the Buy-at high (`Buy at 2000, dips 1800` → `1800-2000`). Targets are not this field.
4. **Entry Price**: plan/fill inside the band. Use the **low** of a buy band (`550-555` → `550`) unless they gave one price. If live LTP is known and **lower** than that plan, store `min(plan, LTP)` so allocation uses the cheaper price.
5. **STOP LOSS**, **FIRST/SECOND/THRID TARGET**, **Comments** (thesis, holding period, weekly close, leftover). Keep the live typo **THRID TARGET**.
6. **Qty** (Maximum Shares Recom. / P): write this formula, adjusting the row number (example row 12):

```excel
=MIN(ROUNDDOWN(($A$5*M12)/(N12-V12),0),ROUNDDOWN(($A$5*$B$2)/N12,0))
```

If `Entry − SL <= 0`, do not write the formula; skip or ask.

7. **TCP** and **max investment suggested** — see [columns.md](columns.md). Prefer formulas with the same row refs.

**Updates** (hit target, book %, trade closed): patch the **existing** Share row. Do not add a second row for the same ticker on this tab.

**Skip:** IPO apply/GMP, index commentary, gold/silver (unless clearly an equity ticker already on the sheet), SIP-only, “watch video”, non-trade chat.

## Do not

- Overwrite **Quantity** (held), **Current P/L**, or **Total Investment** from recs
- Guess tickers
- Put target prices in Buy Range
- Fill sizer calculator rows (names with no plan qty/entry/range)
- Treat Django `TradeIdea` as the plan; sync the sheet then the app
