from decimal import Decimal
from datetime import date

from django.db.models import QuerySet, Sum
from django.utils import timezone

from trades.models import CloseEvent, TradeIdea, TradeStatus


def close_writeback_payload(trade: TradeIdea) -> dict:
    """Cells written back to Google Sheets after a close."""
    return {
        "status": trade.status,
        "closed_qty": str(trade.closed_qty),
        "closed_price": "" if trade.closed_price is None else str(trade.closed_price),
        "current_qty": str(trade.remaining_qty),
    }


def close_trade(trade: TradeIdea, quantity: Decimal, price: Decimal, *, writeback=True) -> CloseEvent:
    if quantity <= 0:
        raise ValueError("Close quantity must be positive.")
    if price <= 0:
        raise ValueError("Close price must be positive.")
    if quantity > trade.remaining_qty:
        raise ValueError("Cannot close more than the remaining quantity.")

    avg_buy = trade.avg_buy()
    realized = (price - avg_buy) * quantity
    event = CloseEvent.objects.create(
        trade=trade,
        quantity=quantity,
        price=price,
        realized_pnl=realized,
    )
    trade.remaining_qty = trade.remaining_qty - quantity
    trade.closed_qty = trade.closed_qty + quantity
    trade.closed_price = price
    if trade.remaining_qty <= 0:
        trade.remaining_qty = Decimal("0")
        trade.status = TradeStatus.CLOSED
    else:
        trade.status = TradeStatus.PARTIAL
    trade.save(
        update_fields=[
            "remaining_qty",
            "closed_qty",
            "closed_price",
            "status",
            "updated_at",
        ]
    )
    if writeback:
        from integrations.sheets import write_close

        write_close(trade)
    return event


def dashboard_stats(trades: QuerySet[TradeIdea] | list[TradeIdea]) -> dict:
    trade_list = list(trades)
    realized = CloseEvent.objects.filter(trade__in=trade_list).aggregate(s=Sum("realized_pnl"))["s"]
    realized = realized if realized is not None else Decimal("0")
    invested = sum((t.invested() for t in trade_list), Decimal("0"))
    unrealized = sum((t.unrealized_pnl() for t in trade_list), Decimal("0"))
    return {
        "total_trades": len(trade_list),
        "total_invested": invested,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "net_pnl": realized + unrealized,
    }


def format_holding_age(start: date | None, today: date | None = None) -> str:
    if start is None:
        return "—"
    today = today or timezone.localdate()
    days = (today - start).days
    if days < 0:
        return "—"
    if days == 0:
        return "today"
    years, rest = divmod(days, 365)
    months, rest = divmod(rest, 30)
    weeks, rest = divmod(rest, 7)
    parts = []
    if years:
        parts.append(f"{years} year" + ("s" if years != 1 else ""))
    if months:
        parts.append(f"{months} month" + ("s" if months != 1 else ""))
    if not years and weeks:
        parts.append(f"{weeks} week" + ("s" if weeks != 1 else ""))
    if not parts:
        parts.append(f"{days} day" + ("s" if days != 1 else ""))
    return " ".join(parts[:2])
