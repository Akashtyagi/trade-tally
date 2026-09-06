"""Price / holdings checks and Telegram alerts."""

from __future__ import annotations

import logging
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from integrations import kite as kite_mod
from integrations import sheets as sheets_mod
from integrations import telegram as telegram_mod
from trades.models import AlertLog, AlertType, TradeIdea, TradeStatus

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def within_market_hours(now: datetime | None = None) -> bool:
    """NSE cash session, Mon–Fri, MARKET_OPEN–MARKET_CLOSE IST (default 09:15–15:30)."""
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    if now.weekday() >= 5:
        return False
    current = now.time()
    return parse_hhmm(settings.MARKET_OPEN) <= current <= parse_hhmm(settings.MARKET_CLOSE)


def ist_today(now: datetime | None = None):
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    return now.astimezone(IST).date()


NEAR_BUY_PAD = Decimal("200")


def is_in_buy_zone(ltp, buy_low, buy_high) -> bool:
    if ltp is None or buy_low is None or buy_high is None:
        return False
    return buy_low <= ltp <= buy_high


def is_near_buy_zone(ltp, buy_low, buy_high, pad=NEAR_BUY_PAD) -> bool:
    if ltp is None or buy_low is None or buy_high is None:
        return False
    return (buy_low - pad) <= ltp <= (buy_high + pad)


def is_underweight(holding_qty, recommended_qty) -> bool:
    holding = holding_qty if holding_qty is not None else Decimal("0")
    recommended = recommended_qty if recommended_qty is not None else Decimal("0")
    return holding < recommended


def hit_target(ltp, target) -> bool:
    if ltp is None or target is None or target <= 0:
        return False
    return ltp >= target


def hit_stop_loss(ltp, stop_loss) -> bool:
    if ltp is None or stop_loss is None or stop_loss <= 0:
        return False
    return ltp <= stop_loss


def evaluate_alerts(
    *,
    status: str,
    recommended_qty,
    holding_qty,
    ltp,
    buy_low,
    buy_high,
    target,
    stop_loss,
) -> list[str]:
    """Decide which Telegram alerts fire. Closed trades never alert."""
    if status == TradeStatus.CLOSED:
        return []
    alerts: list[str] = []
    if is_underweight(holding_qty, recommended_qty) and is_in_buy_zone(ltp, buy_low, buy_high):
        alerts.append(AlertType.UNDERWEIGHT_BUY_ZONE)
    holding = holding_qty if holding_qty is not None else Decimal("0")
    if holding > 0 and hit_target(ltp, target):
        alerts.append(AlertType.TARGET)
    if holding > 0 and hit_stop_loss(ltp, stop_loss):
        alerts.append(AlertType.STOP_LOSS)
    return alerts


def format_alert(trade: TradeIdea, alert_type: str, ltp) -> str:
    ltp_txt = "-" if ltp is None else str(ltp)
    if alert_type == AlertType.UNDERWEIGHT_BUY_ZONE:
        return (
            f"⚠️ Underweight: {trade.instrument} — hold {trade.holding_qty} / "
            f"plan {trade.recommended_qty}. LTP {ltp_txt} is in buy zone "
            f"{trade.buy_low}–{trade.buy_high}."
        )
    if alert_type == AlertType.TARGET:
        return (
            f"🎯 Target hit: {trade.instrument} LTP {ltp_txt} >= target {trade.target} "
            f"(holding {trade.holding_qty})."
        )
    return (
        f"🛑 Stop loss: {trade.instrument} LTP {ltp_txt} <= SL {trade.stop_loss} "
        f"(holding {trade.holding_qty})."
    )


def maybe_alert(trade: TradeIdea, alert_type: str, ltp, *, send=telegram_mod.send_message) -> AlertLog | None:
    # One Telegram ping per (trade, alert type, IST trading day).
    trading_date = ist_today()
    if AlertLog.objects.filter(
        trade=trade, alert_type=alert_type, trading_date=trading_date
    ).exists():
        return None
    message = format_alert(trade, alert_type, ltp)
    send(message)
    return AlertLog.objects.create(
        trade=trade,
        alert_type=alert_type,
        trading_date=trading_date,
        price=ltp,
        message=message,
    )


def refresh_holdings_and_prices(access_token: str | None = None, sheet_slug: str | None = None) -> dict[str, Decimal]:
    """Kite holdings (+ optional LTP) → DB. Sheet write is held-qty only."""
    token = access_token or kite_mod.latest_access_token()
    if not token:
        return {}

    client = kite_mod.KiteClient()
    prices: dict[str, Decimal] = {}
    # GET /portfolio/holdings
    parsed_holdings = kite_mod.parse_holdings(client.holdings(token))
    now = timezone.now()
    lookup = kite_mod.store_holding_snapshots(parsed_holdings, now)
    for row in parsed_holdings:
        if row["last_price"] is not None:
            prices[f"{row['exchange']}:{row['symbol']}"] = row["last_price"]

    trades_qs = TradeIdea.objects.all()
    if sheet_slug:
        trades_qs = trades_qs.filter(sheet_slug=sheet_slug)
    instruments = list(
        trades_qs.exclude(status=TradeStatus.CLOSED).values_list("exchange", "symbol")
    )
    keys = [f"{ex}:{sym}" for ex, sym in instruments]
    # GET /quote/ltp — Personal apps usually get {} from KiteClient.ltp.
    prices.update(kite_mod.parse_ltp_map(client.ltp(token, keys)))

    held_pairs = []
    for trade in trades_qs:
        holding = kite_mod.aggregate_holding(lookup, trade.symbol)
        if trade.status == TradeStatus.CLOSED:
            ltp = prices.get(trade.instrument)
            if ltp is not None:
                trade.last_ltp = ltp
                trade.save(update_fields=["last_ltp", "updated_at"])
            continue
        kite_qty = holding["quantity"] if holding else Decimal("0")
        trade.holding_qty = kite_qty
        trade.remaining_qty = kite_qty
        if holding:
            trade.holding_avg_price = holding["average_price"]
        else:
            trade.holding_avg_price = trade.holding_avg_price
        ltp = prices.get(trade.instrument)
        if ltp is not None:
            trade.last_ltp = ltp
        elif holding and holding["last_price"] is not None:
            trade.last_ltp = holding["last_price"]
        trade.save(
            update_fields=[
                "holding_qty",
                "holding_avg_price",
                "remaining_qty",
                "last_ltp",
                "updated_at",
            ]
        )
        held_pairs.append((trade, kite_qty))
    if held_pairs:
        try:
            from integrations.sheets import write_held_quantities_if_changed

            write_held_quantities_if_changed(held_pairs, slug=sheet_slug)
        except Exception:
            logger.exception("Failed to write Zerodha held qty back to the sheet")
    return prices


def evaluate_open_trades(*, send=telegram_mod.send_message, sheet_slug: str | None = None) -> list[AlertLog]:
    created: list[AlertLog] = []
    open_trades = TradeIdea.objects.exclude(status=TradeStatus.CLOSED)
    if sheet_slug:
        open_trades = open_trades.filter(sheet_slug=sheet_slug)
    for trade in open_trades:
        kinds = evaluate_alerts(
            status=trade.status,
            recommended_qty=trade.recommended_qty,
            holding_qty=trade.holding_qty,
            ltp=trade.last_ltp,
            buy_low=trade.buy_low,
            buy_high=trade.buy_high,
            target=trade.target,
            stop_loss=trade.stop_loss,
        )
        for kind in kinds:
            log = maybe_alert(trade, kind, trade.last_ltp, send=send)
            if log:
                created.append(log)
    return created


def run_checks(*, sync_sheet: bool = True, send=telegram_mod.send_message, force: bool = False) -> dict:
    """Cron / webhook entry: primary sheet → Kite refresh → alerts."""
    from trades.sheet_config import primary_slug

    if not force and not within_market_hours():
        logger.info("Outside market hours; skipping checks")
        return {"synced": 0, "alerts": 0, "skipped": "outside_market_hours"}
    slug = primary_slug()
    synced = []
    if sync_sheet:
        try:
            synced = sheets_mod.sync_from_sheet(slug=slug)
        except Exception:
            logger.exception("Sheet sync failed")
    try:
        refresh_holdings_and_prices(sheet_slug=slug)
    except Exception:
        logger.exception("Kite refresh failed")
    alerts = evaluate_open_trades(send=send, sheet_slug=slug)
    return {"synced": len(synced), "alerts": len(alerts), "sheet": slug}
