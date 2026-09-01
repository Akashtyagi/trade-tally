# Trade Tally

Personal, machine-local tracker for planned equity trades.

The Google Sheet is the system of record. The Django UI reads that sheet, compares it to Zerodha holdings and live prices, sends Telegram buy/sell alerts, and can close trades (writing back to the sheet). There is no application database for trade data. Net P/L is calculated only when you click a button.

This root file is the entry point. The full blueprint lives in [`docs/`](docs/README.md).

| Document | What it covers |
| --- | --- |
| [Overview](docs/01-overview.md) | What this project is, who it is for, what it is not |
| [Features and flows](docs/02-features.md) | Core features, business rules, end-to-end use cases |
| [Technical architecture](docs/03-architecture.md) | Stack, modules, data flow, sheet contract, cron |
| [Progress and to-dos](docs/04-progress.md) | What is built vs the blueprint, remaining work |
| [Setup](docs/05-setup.md) | Podman image, host cron talking to the container |
| [Google, Telegram, Kite](docs/06-integrations-setup.md) | How to get API access for each integration |

Quick start is in [Setup](docs/05-setup.md).
