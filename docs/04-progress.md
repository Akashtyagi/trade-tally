# 4. Progress and to-dos

Track alignment of the **codebase** with the **blueprint**. Update the Status column as work lands. Do not treat a checked box in git history as done unless the code matches [Features](02-features.md).

**Legend:** Done · Partial · Not started · Won’t do (legacy)

## 4.1 Snapshot (as of blueprint writing)

A first Django scaffold exists: UV, Django 5, Kite/Sheets/Telegram clients, `run_checks`, dashboard, close-to-sheet, pytest (27 tests). It was built to an **older** spec (MySQL, login, buy range + stop-loss, 5-minute scheduler, P/L on every page load).

| Blueprint requirement | Code today | Status |
| --- | --- | --- |
| Google Sheet as system of record for trades | Sheet sync **into MySQL** `TradeIdea`; UI reads DB | Partial |
| No real database for trades | MySQL/SQLite models, migrations, docker-compose MySQL | Not started (must remove) |
| Buy: held &lt; recommended → alert **difference** | Buy only if underweight **and** LTP inside `buy_low`–`buy_high`; message is not “buy N shares” | Partial |
| Recommended price (single) | `buy_low` / `buy_high` midpoint | Partial |
| Sell: LTP ≥ target | Yes, but also stop-loss alerts | Partial |
| Hourly cron on this Mac, **weekdays 09:15–15:30 IST only** | Host crontab `podman exec` + `run_checks` skips off-session | Done |
| Dashboard: budget + risk % | Missing Config tab / UI | Not started |
| P/L **only** on button click | P/L computed on every dashboard render | Not started |
| No auth | Dashboard is public | Done |
| Close trade writes sheet | Implemented (`status`, `closed_qty`, `closed_price`) | Done |
| Kite placeholders + login | Implemented; token in DB `KiteSession` | Partial |
| Telegram send | Implemented | Done |
| Tests | Parser, old alert rules, close, dashboard auth | Partial (must retarget) |

## 4.2 Milestone A — Product rules (alerts + sheet)

Priority: make hourly behaviour match the objective even if the DB still exists as a cache.

- [ ] Document and implement **Trades** columns: `recommended_qty`, `recommended_price`, `target` (keep `SHEET_COLUMN_MAP` for old headers).
- [ ] Add **Config** tab reader: `total_budget`, `risk_percentage`.
- [ ] Change `evaluate_alerts`: buy when `held < recommended`; payload includes `buy_qty`; compare LTP to `recommended_price` in the Telegram text (not buy zone).
- [ ] Sell when `ltp >= target` and `held > 0`; drop stop-loss from the default alert set (or gate it behind a flag).
- [ ] Ensure `run_checks` does **not** write P/L.
- [ ] Replace pytest cases for buy-zone / SL with difference-qty and target-only sell.

## 4.3 Milestone B — Dashboard (no auth, budget, manual P/L)

- [ ] Remove `login_required` and `/accounts/login/`; bind to `127.0.0.1`.
- [ ] Show total budget, risk %, implied risk amount.
- [ ] Show recommended vs held, difference, recommended price, LTP, target.
- [ ] Add **Calculate P/L** button → dedicated view; persist result to Config `last_pnl` / `last_pnl_at`.
- [ ] Stop computing net P/L on GET dashboard (show last stored value only).
- [ ] Keep close modal (full/partial) and sheet writeback.
- [ ] Colour closed profit/loss as specified.

## 4.4 Milestone C — No trade database

- [ ] Dashboard and `run_checks` operate on parsed sheet rows + Kite dicts only.
- [ ] Kite token → `.kite-session.json` (gitignored).
- [ ] Alert dedupe → local JSON (or equivalent), not `AlertLog`.
- [ ] Remove (or stop using) `TradeIdea`, `CloseEvent`, `HoldingSnapshot`, `AlertLog`, `KiteSession`.
- [ ] Drop MySQL from required setup; delete or ignore `docker-compose` DB service.
- [ ] Update `.env.example` (no `DB_*` required).

## 4.5 Milestone D — Market-hours job on this machine

- [x] Host crontab `podman exec`s `run_checks` on weekdays (09:15 and 10:00–15:00); see [Setup](05-setup.md)
- [x] `run_checks` returns immediately outside Mon–Fri 09:15–15:30 IST (`--force` to override)
- [x] Default `ENABLE_SCHEDULER=false` in compose
- [ ] Remove or demote GitHub Actions price-check as the primary mechanism

## 4.6 Milestone E — Docs and cleanup

- [x] Blueprint folder (`docs/`) — this set of files
- [x] Root README points here
- [x] Podman + integrations setup docs
- [ ] Trim obsolete setup (createsuperuser, MySQL) from [Setup](05-setup.md) once C/D are done
- [ ] README/sheet template screenshot or sample CSV in repo (optional)

## 4.7 Nice-to-haves (backlog)

- [ ] `Closes` tab: one row per partial close for accurate realized P/L
- [ ] Telegram “Kite token expired”
- [ ] NSE holiday calendar (skip Muhurat-only / closed days)
- [ ] `stop_loss` as optional second sell rule
- [ ] Show last cron run time on the dashboard (write `last_check_at` to Config **without** touching P/L)

## 4.8 How to update this file

When you finish a checkbox, mark it and add a one-line note:

```text
- [x] Remove login_required (2026-09-01)
```

If the product rules change, edit [Overview](01-overview.md) and [Features](02-features.md) first, then add new to-dos here.


## TO-DO
- [ ] How to find target between 1st, 2nd and 3rd 
- [ ] If LTP higher than Target, highlight and trigger message
- 