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
from trades.models import AlertLog, AlertType, HoldingSnapshot, TradeIdea, TradeStatus

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def within_market_hours(now: datetime | None = None) -> bool:
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


def is_in_buy_zone(ltp, buy_low, buy_high) -> bool:
    if ltp is None or buy_low is None or buy_high is None:
        return False
    return buy_low <= ltp <= buy_high


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


def _holding_lookup(parsed: list[dict]) -> dict[tuple[str, str], dict]:
    return {(row["exchange"], row["symbol"]): row for row in parsed}


def refresh_holdings_and_prices(access_token: str | None = None) -> dict[str, Decimal]:
    token = access_token or kite_mod.latest_access_token()
    if not token:
        return {}

    client = kite_mod.KiteClient()
    prices: dict[str, Decimal] = {}
    parsed_holdings = kite_mod.parse_holdings(client.holdings(token))
    now = timezone.now()
    for row in parsed_holdings:
        HoldingSnapshot.objects.update_or_create(
            exchange=row["exchange"],
            symbol=row["symbol"],
            defaults={
                "quantity": row["quantity"],
                "average_price": row["average_price"],
                "last_price": row["last_price"],
                "fetched_at": now,
            },
        )
        if row["last_price"] is not None:
            prices[f"{row['exchange']}:{row['symbol']}"] = row["last_price"]

    instruments = list(
        TradeIdea.objects.exclude(status=TradeStatus.CLOSED).values_list("exchange", "symbol")
    )
    keys = [f"{ex}:{sym}" for ex, sym in instruments]
    prices.update(kite_mod.parse_ltp_map(client.ltp(token, keys)))

    lookup = _holding_lookup(parsed_holdings)
    for trade in TradeIdea.objects.all():
        holding = lookup.get((trade.exchange, trade.symbol))
        if holding:
            trade.holding_qty = holding["quantity"]
            trade.holding_avg_price = holding["average_price"]
        else:
            trade.holding_qty = Decimal("0")
            trade.holding_avg_price = None
        ltp = prices.get(trade.instrument)
        if ltp is not None:
            trade.last_ltp = ltp
        trade.save(
            update_fields=[
                "holding_qty",
                "holding_avg_price",
                "last_ltp",
                "updated_at",
            ]
        )
    return prices


def evaluate_open_trades(*, send=telegram_mod.send_message) -> list[AlertLog]:
    created: list[AlertLog] = []
    open_trades = TradeIdea.objects.exclude(status=TradeStatus.CLOSED)
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
    if not force and not within_market_hours():
        logger.info("Outside market hours; skipping checks")
        return {"synced": 0, "alerts": 0, "skipped": "outside_market_hours"}
    synced = []
    if sync_sheet:
        try:
            synced = sheets_mod.sync_from_sheet()
        except Exception:
            logger.exception("Sheet sync failed")
    try:
        refresh_holdings_and_prices()
    except Exception:
        logger.exception("Kite refresh failed")
    alerts = evaluate_open_trades(send=send)
    return {"synced": len(synced), "alerts": len(alerts)}
