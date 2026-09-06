"""Close math, dashboard stats, and display helpers. No Kite HTTP here."""

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
    """Record an exit, update remaining/status, optionally write the sheet."""
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


def delete_trade(trade: TradeIdea, *, writeback: bool = True) -> tuple[str, str]:
    """Remove a symbol from the app and clear its rows on the Google Sheet."""
    slug = trade.sheet_slug
    symbol = trade.symbol
    if writeback:
        from integrations.sheets import clear_trade_from_sheet

        clear_trade_from_sheet(trade)
    TradeIdea.objects.filter(sheet_slug=slug, symbol=symbol).delete()
    return slug, symbol


def _prefer_dashboard_trade(current: TradeIdea, candidate: TradeIdea) -> TradeIdea:
    """Prefer the live open-block row, then any still-open row, then the larger holding."""
    from integrations.sheets import COMPLETED_ROW_OFFSET

    current_live = current.sheet_row < COMPLETED_ROW_OFFSET
    candidate_live = candidate.sheet_row < COMPLETED_ROW_OFFSET
    if candidate_live != current_live:
        return candidate if candidate_live else current
    current_open = current.status != TradeStatus.CLOSED
    candidate_open = candidate.status != TradeStatus.CLOSED
    if candidate_open != current_open:
        return candidate if candidate_open else current
    if candidate.holding_qty != current.holding_qty:
        return candidate if candidate.holding_qty > current.holding_qty else current
    if candidate.remaining_qty != current.remaining_qty:
        return candidate if candidate.remaining_qty > current.remaining_qty else current
    return current if current.sheet_row <= candidate.sheet_row else candidate


def unique_dashboard_trades(trades: list[TradeIdea]) -> list[TradeIdea]:
    """One row per symbol. Same ticker can exist on the open block and the completed block."""
    chosen: dict[str, TradeIdea] = {}
    order: list[str] = []
    for trade in trades:
        key = trade.symbol
        prev = chosen.get(key)
        if prev is None:
            chosen[key] = trade
            order.append(key)
            continue
        chosen[key] = _prefer_dashboard_trade(prev, trade)
    return [chosen[key] for key in order]


def apply_snapshot_ltp(trades: list[TradeIdea]) -> None:
    """Fill missing LTP from the last Kite holding price (personal apps cannot quote)."""
    from trades.models import HoldingSnapshot

    snaps: dict[str, HoldingSnapshot] = {}
    for row in HoldingSnapshot.objects.filter(symbol__in={t.symbol for t in trades}):
        prev = snaps.get(row.symbol)
        if prev is None or (row.quantity > prev.quantity):
            snaps[row.symbol] = row
    for trade in trades:
        snap = snaps.get(trade.symbol)
        if not snap or snap.last_price is None:
            continue
        if trade.last_ltp is None or snap.quantity > 0:
            trade.last_ltp = snap.last_price


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
    """Human age using 365-day years and 30-day months (display only)."""
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
