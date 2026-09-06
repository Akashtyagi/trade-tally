# Ingest advisor message dumps

Default dump: `zerodha_files/trades.txt` (WhatsApp-style blocks).

## Split

Split on the repeated header line:

```text
36 Months Equity Trades 1st August 2024 to 1st August 2027:
```

Each block after a header is one message. Walk **oldest → newest** so later “hit target / closed” patches earlier buys.

## Classify

| Kind | Signals | Action |
| --- | --- | --- |
| **skip** | IPO, GMP, listing gains, lot size, index, Nifty, gold, silver, SIP only, “watch video”, ratio charts | Ignore |
| **new_buy** | `Buy at` / `Buy in` plus a price or range, and a named stock | Add row if Share not already on the **open** block |
| **update** | Hit 1st/2nd target, book profit, trade closed, trail SL, add more | Patch existing Share row; never duplicate ticker |

Same company name on this tab → one open row. Closed lots belong in the completed block via close/tradebook, not a second open row.

## Diff vs sheet

1. Read the Aug24-27 (or primary) tab; collect open-block **Share** tickers.
2. For each `new_buy`, map ticker; if already present, treat leftover text as **update** (comments / targets) unless the user wants a new period tab.
3. Write only plan cells and formulas ([SKILL.md](SKILL.md)). Leave Quantity / Current P/L / Total Investment.

## After writes

Sync sheet → app (`sync_from_sheet`) so TCP and T1/T2/T3 show on the share detail page.

## Ambiguous tickers

Stop and ask. Do not write a guessed symbol.
