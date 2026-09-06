"""Button-only Zerodha sync: holdings qty and last_price → DB and sheet."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from integrations.kite import (
    KiteClient,
    KiteNotConfigured,
    aggregate_holding,
    latest_access_token,
    parse_holdings,
    store_holding_snapshots,
)
from integrations.sheets import write_zerodha_holdings
from trades.models import TradeIdea, TradeStatus
from trades.sheet_config import primary_slug, update_sheet_state


def sync_zerodha(*, write_sheet: bool = True, sheet_slug: str | None = None) -> dict:
    # Daily access token from KiteSession — no HTTP call.
    token = latest_access_token()
    if not token:
        raise KiteNotConfigured("Connect Kite from the dashboard first (daily token).")

    slug = sheet_slug or primary_slug()
    client = KiteClient()
    # Sole Kite HTTP call in this function: GET /portfolio/holdings.
    holdings = parse_holdings(client.holdings(token))
    now = timezone.now()
    # Persist snapshots and return {(exchange, symbol): row} for in-memory lookup.
    lookup = store_holding_snapshots(holdings, now)

    open_trades = list(
        TradeIdea.objects.filter(sheet_slug=slug).exclude(status=TradeStatus.CLOSED)
    )

    updated = 0
    sheet_writes = 0
    held_pairs: list[tuple[TradeIdea, Decimal]] = []
    for trade in open_trades:
        # In-memory only: sum NSE+BSE legs for this ticker from `lookup`. Not a Kite call.
        holding = aggregate_holding(lookup, trade.symbol)
        kite_qty = holding["quantity"] if holding else Decimal("0")
        trade.holding_qty = kite_qty
        trade.remaining_qty = kite_qty
        if holding:
            trade.holding_avg_price = holding["average_price"]
            if holding["last_price"] is not None:
                # last_price here is whatever holdings() already returned, not a quote/LTP call.
                trade.last_ltp = holding["last_price"]
        trade.save()
        updated += 1
        held_pairs.append((trade, kite_qty))

    if write_sheet:
        # One get_all_values + one batch_update for O (qty) and R (investment).
        sheet_writes = len(write_zerodha_holdings(held_pairs, slug=slug))

    try:
        update_sheet_state(slug, last_zerodha_sync_at=now.isoformat())
    except Exception:
        pass
    return {
        "holdings": len(holdings),
        "trades_updated": updated,
        "sheet_cells": sheet_writes,
        "sheet": slug,
        "held_from_zerodha": True,
    }
