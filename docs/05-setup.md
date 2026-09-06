# 5. Setup

How to run Trade Tally on your Mac with **Podman**. Credentials for Google, Telegram, and Kite are in [Integrations setup](06-integrations-setup.md).

## 5.1 Prerequisites

- macOS with [Podman](https://podman.io/) (`podman version` should work)
- This repo: `~/repos/trade-tally`
- (Later) Google Sheet, Telegram bot, Kite app — [Integrations setup](06-integrations-setup.md)

## 5.2 Run with Podman (supported path)

```bash
cd ~/repos/trade-tally
cp .env.example .env          # then fill secrets when you have them
mkdir -p secrets
podman machine start          # if Podman says the machine is not running
podman compose -f compose.yml up -d --build
```

- UI: http://127.0.0.1:8000/ (no login)
- Container name: `trade-tally`
- SQLite lives in the `trade-tally-data` volume
- Google JSON is mounted from `./secrets/google-credentials.json`

Useful commands:

```bash
podman ps
podman logs -f trade-tally
podman exec trade-tally uv run --no-dev python manage.py run_checks --force   # test now
podman compose -f compose.yml down
```

### Market-hours cron → Podman

The host crontab does **not** run Django itself. It runs [`scripts/cron-run-checks.sh`](../scripts/cron-run-checks.sh), which `podman exec`s into `trade-tally` and calls `manage.py run_checks`.

`run_checks` exits immediately outside **Monday–Friday 09:15–15:30 IST** (no Telegram). Install:

```bash
chmod +x scripts/cron-run-checks.sh scripts/install-macos-cron.sh
./scripts/install-macos-cron.sh
```

That installs:

```cron
15 9 * * 1-5  .../scripts/cron-run-checks.sh
0 10-15 * * 1-5  .../scripts/cron-run-checks.sh
```

Set the Mac timezone to **Kolkata (IST)** or convert the hours. The Mac must be **awake** during the session; the container must be **running**. Logs: `/tmp/trade-tally-cron.log`.

Keep `ENABLE_SCHEDULER=false` so APScheduler does not double-fire inside the container.

### UV on the host (optional, without Podman)

```bash
cd ~/repos/trade-tally
uv sync --group dev
cp .env.example .env
uv run python manage.py migrate
uv run python manage.py runserver 127.0.0.1:8000
```

## 5.3 Integrations

Follow **[Google / Telegram / Kite](06-integrations-setup.md)** for API keys and sharing the sheet. The container starts without them; alerts and live prices stay empty until they are set.

## 5.4 Environment file

Copy [`.env.example`](../.env.example) and fill at least:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Django CSRF/signing |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | Which sheet to read |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Alerts |
| `KITE_API_KEY` / `KITE_API_SECRET` | Holdings and LTP |
| `ENABLE_SCHEDULER` | Keep `false` when using host cron |
| `MARKET_OPEN` / `MARKET_CLOSE` | Default `09:15` / `15:30` IST |
| `CRON_SECRET` | Optional HTTP webhook `/internal/run-checks` |

## 5.5 Tests (on the host)

```bash
cd ~/repos/trade-tally
uv sync --group dev
uv run pytest
```

## 5.6 Checklist before trusting alerts

- [ ] Podman container `trade-tally` is running (`podman ps`)
- [ ] Spreadsheet shared with the service account; JSON in `secrets/`
- [ ] Telegram test message received
- [ ] Kite connected the same trading day from the dashboard
- [ ] Host crontab installed; `/tmp/trade-tally-cron.log` shows a skip after hours and a real run in session
- [ ] Mac timezone IST (or crontab hours converted); Mac awake 09:15–15:30 on weekdays

## 5.7 Tradebook ingest

After you add one or more **Tradebook - …** tabs (Zerodha tradebook CSV pasted into the same spreadsheet):

```bash
chmod +x scripts/ingest-tradebook.sh
./scripts/ingest-tradebook.sh
```

Rebuild the container first if you just pulled new code (`podman compose -f compose.yml up -d --build`). The script prefers `podman exec trade-tally` so the dashboard database is updated. Options: `--dry-run`, `--no-close`, `--csv-dir zerodha_files`.
