"""Button-only Zerodha sync: holdings, LTP, today's fills → DB and sheet."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from integrations.kite import (
    KiteClient,
    KiteNotConfigured,
    latest_access_token,
    parse_fills,
    parse_holdings,
    parse_ltp_map,
)
from integrations.sheets import write_mapped_payload
from trades.models import AppSettings, HoldingSnapshot, KiteFill, TradeIdea, TradeStatus


def _as_datetime(value):
    if value is None:
        return None
    if hasattr(value, "year") and hasattr(value, "hour"):
        return value
    if isinstance(value, str):
        return parse_datetime(value.replace("Z", "+00:00"))
    return None


def sync_zerodha(*, write_sheet: bool = True) -> dict:
    token = latest_access_token()
    if not token:
        raise KiteNotConfigured("Connect Kite from the dashboard first (daily token).")

    client = KiteClient()
    holdings = parse_holdings(client.holdings(token))
    fills = parse_fills(client.trades(token))
    now = timezone.now()

    KiteFill.objects.all().delete()
    for fill in fills:
        KiteFill.objects.create(
            symbol=fill["symbol"],
            exchange=fill["exchange"],
            quantity=fill["quantity"],
            price=fill["price"],
            side=fill["side"],
            filled_at=_as_datetime(fill["filled_at"]),
            order_id=fill["order_id"],
            fetched_at=now,
        )

    lookup = {(row["exchange"], row["symbol"]): row for row in holdings}
    for row in holdings:
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

    open_trades = list(TradeIdea.objects.exclude(status=TradeStatus.CLOSED))
    instruments = [trade.instrument for trade in open_trades]
    prices = parse_ltp_map(client.ltp(token, instruments)) if instruments else {}

    updated = 0
    sheet_writes = 0
    for trade in open_trades:
        holding = lookup.get((trade.exchange, trade.symbol))
        ltp = prices.get(trade.instrument)
        if holding:
            trade.holding_qty = holding["quantity"]
            trade.holding_avg_price = holding["average_price"]
            trade.remaining_qty = holding["quantity"]
            if holding["last_price"] is not None:
                ltp = ltp or holding["last_price"]
        if ltp is not None:
            trade.last_ltp = ltp
        trade.save()
        updated += 1

        qty = trade.holding_qty or Decimal("0")
        avg = trade.avg_buy()
        pnl = (ltp - avg) * qty if ltp is not None else None
        payload = {
            "current_qty": str(qty),
            "total_investment": str(qty * avg),
        }
        if pnl is not None:
            payload["current_pnl"] = str(pnl)
        if write_sheet:
            writes = write_mapped_payload(trade, payload)
            sheet_writes += len(writes)

    cfg = AppSettings.load()
    cfg.last_zerodha_sync_at = now
    cfg.save(update_fields=["last_zerodha_sync_at", "updated_at"])
    return {
        "holdings": len(holdings),
        "fills": len(fills),
        "trades_updated": updated,
        "sheet_cells": sheet_writes,
    }
