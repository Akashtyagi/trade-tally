# Google Sheets, Telegram, and Kite Connect

You need all three before buy/sell alerts and live prices work. The dashboard still starts without them.

Put secrets on the host (never commit them):

- `.env` — tokens and spreadsheet ID
- `secrets/google-credentials.json` — Google service account key (mounted into Podman)

---

## 1. Google Sheet access

### 1a. Create the spreadsheet

1. Open [Google Sheets](https://sheets.google.com) and use your existing workbook (the Aug24-27 layout is supported).
2. Set `GOOGLE_SHEETS_WORKSHEET` in `.env` to the **tab name** (example: `Aug24-27`). Use `*` to read the first tab.
3. The app looks for the header row that contains **Share**, **Current Quantity**, and **Minimum Shares Recom.** — it does not assume row 1.

**Open trades** (middle table) map as:

| Sheet column | Used as |
| --- | --- |
| Share | Symbol |
| Current Quantity | Held qty (until Kite overwrites) |
| Minimum Shares Recom. | Recommended qty (buy the difference if held is lower) |
| Entry Price | Avg / recommended buy price |
| Buy Range | `buy_low`–`buy_high` (e.g. `155-180`) |
| STOP LOSS | Stop loss (ignored when blank/0) |
| FIRST TARGET | Sell target (ignored when blank/0) |
| Comments | Notes |

**Trade Completed** (right table): Share, Quantity, Exit Price → closed trades.

Rupee formatting (`₹ 16,672.50`), `#DIV/0!`, and `#N/A` are ignored. Rows with a name but no quantity, holding, or entry (left-side sizer leftovers) are skipped.

4. Copy the spreadsheet ID from the URL:

```text
https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit
```

Set `GOOGLE_SHEETS_SPREADSHEET_ID=THIS_IS_THE_ID` in `.env`.

### 1b. Google Cloud service account

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or pick one).
3. **APIs & Services → Library** → enable **Google Sheets API**.
4. **APIs & Services → Credentials → Create credentials → Service account**.
   - Name e.g. `trade-tally`.
   - Skip extra roles (the sheet share is enough).
5. Open the service account → **Keys → Add key → JSON**. Download the file.
6. Save it as:

```text
~/repos/trade-tally/secrets/google-credentials.json
```

7. Open the JSON and copy `client_email` (looks like `trade-tally@PROJECT.iam.gserviceaccount.com`).
8. In Google Sheets: **Share** → paste that email → role **Editor** → uncheck “notify” → Share.

Podman mounts `./secrets` at `/app/secrets`. After replacing the JSON:

```bash
podman restart trade-tally
```

---

## 2. Telegram bot

1. In Telegram, open [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, pick a name and a username ending in `bot`.
3. Copy the **HTTP API token**. Put it in `.env`:

```bash
TELEGRAM_BOT_TOKEN=123456:ABC-def...
```

4. Open a chat with **your** new bot and tap **Start** (or send any message). The bot cannot message you until you do this.
5. Get your chat id:

```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"
```

Look for `"chat":{"id": 123456789}`. That number (can be negative for groups) is `TELEGRAM_CHAT_ID`.

Alternatively, message [@userinfobot](https://t.me/userinfobot) for your user id.

6. Put `TELEGRAM_CHAT_ID=123456789` in `.env`, then `podman restart trade-tally`.

7. Smoke test:

```bash
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="$TELEGRAM_CHAT_ID" \
  -d text="Trade Tally bot is connected"
```

---

## 3. Zerodha Kite Connect API

Kite is how the app reads **holdings** and **LTP**. It does not place orders.

1. Go to [https://developers.kite.trade/](https://developers.kite.trade/) and sign in with your Zerodha account.
2. Create a new app (Kite Connect). Personal / individual apps are free for this use.
3. Copy **API key** and **API secret** into `.env`:

```bash
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here
KITE_API_BASE_URL=https://api.kite.trade
KITE_REDIRECT_URL=http://127.0.0.1:8000/kite/callback/
```

4. In the Kite app settings, set **Redirect URL** to exactly:

```text
http://127.0.0.1:8000/kite/callback/
```

5. Restart the container so it picks up `.env`:

```bash
podman restart trade-tally
```

6. Open http://127.0.0.1:8000/ and click **Connect Kite**. Complete login on Zerodha. You land back on the dashboard.

**Daily token:** the access token expires around 06:00 IST the next day. Reconnect each trading morning before you rely on hourly alerts.

Until the key is no longer `your_api_key_here`, the app treats Kite as unconfigured (no holdings, no LTP, no price alerts).

---

## After all three are set

```bash
# Reload env inside the container
podman compose -f compose.yml up -d

# Optional: run checks ignoring market hours (to test Telegram/Sheet)
podman exec trade-tally uv run --no-dev python manage.py run_checks --force
```

Cron on the host already calls `run_checks` **without** `--force`, so nights and weekends stay silent.
