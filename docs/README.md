# Trade Tally blueprint

This folder is the product and engineering blueprint for Trade Tally. Read it in order, or jump to the part you need.

## Objective (source of truth)

Django app that syncs planned trades from a Google Sheet, compares them to Zerodha holdings and live prices, and alerts you on Telegram whether to **buy** or **sell** based on sheet parameters. You can close trades from a small web UI; closes are written back to the sheet.

- **No application database for trades.** Read (and write closes) against Google Sheets.
- **Buy:** if held quantity is less than recommended quantity, alert to buy the **difference**, using current price vs recommended price.
- **Sell:** if current price is above target, alert to sell.
- **Runs on this machine.** A cron job compares portfolio prices to the sheet and sends alerts **only on weekdays during NSE/BSE trading hours** (09:15–15:30 IST). Outside that window it must not send buy/sell notifications.
- **Dashboard** shows net profit/loss so far, total budget, and risk percentage. **Calculate P/L only on a manual button click** — never on the hourly job.
- **No login.** The dashboard is open on localhost.

## Documents

1. [Overview](01-overview.md) — purpose, scope, principles
2. [Features and flows](02-features.md) — capabilities, rules, sequence of each use case
3. [Technical architecture](03-architecture.md) — components, sheet schema, integrations, market-hours cron
4. [Progress and to-dos](04-progress.md) — current code vs this blueprint, checklist
5. [Setup](05-setup.md) — Podman, cron, local UV
6. [Google / Telegram / Kite](06-integrations-setup.md) — credentials and sharing

When product intent and the existing codebase disagree, **this blueprint wins**. [Progress](04-progress.md) lists the gaps to close.
