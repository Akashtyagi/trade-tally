# 1. Overview

## What this project is

Trade Tally is a **personal trading checklist** that lives on your Mac. You keep “which trades to take” in a Google Sheet (recommended quantity, recommended price, target, budget, risk). The app:

1. Reads that sheet (no MySQL/SQLite store for trades).
2. Reads your **Zerodha** holdings and last traded prices via Kite Connect.
3. On **weekdays during market hours** (see below), an hourly job decides whether you should **buy more** or **sell**, and messages **Telegram**.
4. Shows a **no-login dashboard** with positions, budget, risk %, and a **manual** “Calculate P/L” button.
5. Lets you **mark a trade closed** (full or partial) at a price you type; that close is written back to the sheet.

It is not a broker, not an order router, and not a multi-user product. You still place orders in Kite/Console. This app only **tells you what the sheet says you should do** and **keeps the sheet in sync when you close something**.

## Who it is for

You (Akash): a software engineer who already maintains a sheet of planned equity trades and a Zerodha account, and who wants Telegram nudges plus a simple local panel — without paying for hosting or running a real database.

## Design principles

| Principle | Meaning |
| --- | --- |
| Sheet is source of truth | Planned qty, prices, targets, status, closes, budget, and risk live in Google Sheets. The UI is a view + a few write-backs. |
| No trade database | Do not persist `TradeIdea` / close events in MySQL. Hourly jobs and the dashboard read the sheet (and Kite) on demand. |
| Alerts are periodic; P/L is not | Cron may send buy/sell Telegram messages **only while the cash market is open**. Net P/L, invested, and related figures refresh **only** when you click **Calculate P/L**. |
| Market hours only | NSE/BSE equity: **Monday–Friday, 09:15–15:30 IST**. No alerts on weekends, before open, or after close. |
| Local-first | Process and cron run on this machine. The Mac must be on (and Kite token valid) during the trading session. |
| Free stack | Django + UV, Google Sheets API, Telegram Bot API, Kite personal app, macOS `launchd`/cron. |
| No auth on the dashboard | Bound to localhost. Anyone who can open the browser on this Mac sees the panel. |

## What it is not

- Not an automated order placer (no `place_order` in the product scope).
- Not a cloud SaaS. GitHub Actions / Render were an earlier idea; the blueprint is **cron on this Mac, gated to weekday trading hours**.
- Not a replacement for the sheet. If the sheet is wrong, alerts and the UI will be wrong.
- Not a tax or accounting tool. P/L is indicative (avg buy vs close/LTP).

## Success looks like

- You update a row on the sheet (e.g. recommended 50 INFY @ 1450, target 1700).
- On the next **in-session** cron run, if you hold 10 and LTP is at or below the recommended buy context, Telegram says **buy 40**. No message if the market is closed.
- If LTP is above target, Telegram says **sell**.
- The dashboard lists every sheet row with live (or last-fetched) prices, budget, and risk %.
- Clicking **Calculate P/L** recomputes net profit/loss from sheet + holdings and shows it. The hourly job does not change that number.
- Closing 20 shares at 1480 in the UI updates the same sheet row (`status`, closed qty/price, remaining).

## Glossary

| Term | Meaning |
| --- | --- |
| Recommended quantity | Sheet field: how many shares the plan says you should hold. |
| Held quantity | Actual quantity from Kite holdings (portfolio), matched by `exchange:symbol`. |
| Difference | `max(recommended_qty - held_qty, 0)` — size of the buy alert. |
| Recommended price | Sheet field: planned entry / reference buy price. Used in the buy alert copy and to judge whether current price is attractive vs plan. |
| Target | Sheet field: sell trigger. If LTP ≥ target, send a sell alert. |
| LTP | Last traded price from Kite. |
| Total budget | Capital you are willing to deploy (sheet **Config** tab or equivalent). Shown on the dashboard. |
| Risk percentage | Max loss you accept on the book or per-trade, stored on the sheet and shown on the dashboard. Formula for display is documented in [Features](02-features.md). |
