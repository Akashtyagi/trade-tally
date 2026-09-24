"""Tradebook CSV/sheet parse, FIFO match, and close-from-fills."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from integrations.tradebook import (
    apply_match_to_trade,
    fifo_match,
    fill_uid,
    ingest_tradebook,
    is_source_tradebook,
    merge_fills,
    parse_tradebook_values,
)
from trades.models import CloseSource, TradeStatus, TradebookFill


SAMPLE_BOOK = [
    [
        "symbol",
        "isin",
        "trade_date",
        "exchange",
        "segment",
        "series",
        "trade_type",
        "auction",
        "quantity",
        "price",
        "trade_id",
        "order_id",
        "order_execution_time",
    ],
    [
        "INFY",
        "INE009A01021",
        "2025-09-02",
        "NSE",
        "EQ",
        "EQ",
        "buy",
        "false",
        "50",
        "1450",
        "t-buy",
        "o-1",
        "2025-09-02T11:19:40",
    ],
    [
        "INFY",
        "INE009A01021",
        "2025-10-15",
        "NSE",
        "EQ",
        "EQ",
        "sell",
        "false",
        "50",
        "1600",
        "t-sell",
        "o-2",
        "2025-10-15T09:15:03",
    ],
    [
        "RELIANCE",
        "",
        "2025-09-16",
        "BSE",
        "EQ",
        "A",
        "sell",
        "false",
        "10",
        "1400",
        "t-rel",
        "o-3",
        "2025-09-16T14:15:41",
    ],
]


def _book_row(symbol, trade_date, side, qty, price, trade_id, exchange="NSE"):
    return [
        symbol,
        "INE009A01021",
        trade_date,
        exchange,
        "EQ",
        "EQ",
        side,
        "false",
        qty,
        price,
        trade_id,
        f"o-{trade_id}",
        f"{trade_date}T11:00:00",
    ]


# CENTUM on the live Aug24-27 tab: 6 shares bought in 2025, then 7 bought and
# 7 sold in 2026. The row's Date cell says 2026-04-16.
SPLIT_YEAR_BOOK = [
    SAMPLE_BOOK[0],
    _book_row("INFY", "2025-05-30", "buy", "3", "2505", "t1"),
    _book_row("INFY", "2025-06-25", "buy", "3", "2195", "t2", exchange="BSE"),
    _book_row("INFY", "2026-04-16", "buy", "7", "2913", "t3"),
    _book_row("INFY", "2026-06-01", "sell", "7", "3670", "t4"),
]


def test_is_source_tradebook_skips_ledger():
    assert is_source_tradebook("Tradebook - Sep 2025")
    assert is_source_tradebook("tradebook-ZN6729-EQ")
    assert is_source_tradebook("tradebook-09/24: 08/25")
    assert not is_source_tradebook("Tradebook - Ledger")
    assert not is_source_tradebook("Tradebook - Matched")
    assert not is_source_tradebook("Aug24-27")


def test_parse_and_merge_tradebook_rows():
    fills = parse_tradebook_values(SAMPLE_BOOK, source_sheet="Tradebook - Sep")
    assert len(fills) == 3
    assert fills[0]["side"] == "BUY"
    assert fills[1]["side"] == "SELL"
    assert fills[0]["symbol"] == "INFY"
    merged = merge_fills(fills, fills)
    assert len(merged) == 3
    assert fill_uid(fills[0]).startswith("t-buy:")


def test_fifo_buy_then_sell_profit():
    fills = parse_tradebook_values(SAMPLE_BOOK)
    infy = [f for f in fills if f["symbol"] == "INFY"]
    match = fifo_match(infy)
    assert match["buy_then_sell"] is True
    assert match["open_qty"] == 0
    assert match["realized_pnl"] == Decimal("7500")
    assert match["buy_qty"] == Decimal("50")
    assert match["sell_qty"] == Decimal("50")


@pytest.mark.django_db
def test_ingest_closes_flat_tracked_share(trade):
    trade.opened_on = date(2025, 8, 1)
    trade.holding_qty = Decimal("0")
    trade.save()
    fills = parse_tradebook_values(SAMPLE_BOOK, source_sheet="Tradebook - Sep")
    match = fifo_match([f for f in fills if f["symbol"] == "INFY"], fallback_avg_buy=trade.avg_buy())
    action = apply_match_to_trade(trade, match, writeback=False)
    trade.refresh_from_db()
    assert action == "closed"
    assert trade.status == TradeStatus.CLOSED
    assert trade.realized_pnl() == Decimal("7500")
    assert trade.close_events.filter(source=CloseSource.TRADEBOOK).count() == 1


@pytest.mark.django_db
def test_ingest_partial_when_still_held(trade):
    trade.opened_on = date(2025, 8, 1)
    trade.holding_qty = Decimal("20")
    trade.save()
    fills = parse_tradebook_values(SAMPLE_BOOK)
    infy = [f for f in fills if f["symbol"] == "INFY"]
    infy[1]["quantity"] = Decimal("30")
    match = fifo_match(infy)
    action = apply_match_to_trade(trade, match, writeback=False)
    trade.refresh_from_db()
    assert match["open_qty"] == Decimal("20")
    assert action == "partial"
    assert trade.status == TradeStatus.PARTIAL
    assert trade.remaining_qty == Decimal("20")


@pytest.mark.django_db
def test_ingest_closes_when_fifo_flat_even_if_sheet_qty_stale(trade):
    trade.opened_on = date(2025, 8, 1)
    trade.holding_qty = Decimal("95")
    trade.save()
    fills = parse_tradebook_values(SAMPLE_BOOK)
    match = fifo_match([f for f in fills if f["symbol"] == "INFY"])
    action = apply_match_to_trade(trade, match, writeback=False)
    trade.refresh_from_db()
    assert action == "closed"
    assert trade.status == TradeStatus.CLOSED
    assert trade.holding_qty == Decimal("0")


@pytest.mark.django_db
def test_ingest_closes_using_first_tradebook_buy_when_opened_on_missing(trade, tmp_path):
    trade.holding_qty = Decimal("0")
    trade.opened_on = None
    trade.save()
    path = tmp_path / "book.csv"
    path.write_text("\n".join(",".join(row) for row in SAMPLE_BOOK) + "\n")
    ingest_tradebook(write_sheet=False, writeback_closes=False, csv_paths=[str(path)])
    trade.refresh_from_db()
    assert trade.status == TradeStatus.CLOSED
    assert trade.opened_on == date(2025, 9, 2)
    assert TradebookFill.objects.filter(symbol="INFY").count() == 2


@pytest.mark.django_db
def test_ingest_stays_open_when_kite_still_holds_on_other_exchange(trade):
    from trades.models import HoldingSnapshot

    trade.opened_on = date(2025, 8, 1)
    trade.holding_qty = Decimal("55")
    trade.exchange = "NSE"
    trade.save()
    HoldingSnapshot.objects.create(
        exchange="NSE", symbol="INFY", quantity=Decimal("0"), average_price=Decimal("1400")
    )
    HoldingSnapshot.objects.create(
        exchange="BSE", symbol="INFY", quantity=Decimal("55"), average_price=Decimal("1400")
    )
    fills = parse_tradebook_values(SAMPLE_BOOK)
    infy = [f for f in fills if f["symbol"] == "INFY"]
    infy[1]["quantity"] = Decimal("30")
    match = fifo_match(infy)
    action = apply_match_to_trade(trade, match, writeback=False)
    trade.refresh_from_db()
    assert action == "partial"
    assert trade.status == TradeStatus.PARTIAL
    assert trade.remaining_qty == Decimal("55")


@pytest.mark.django_db
def test_ingest_from_values_persists_tracked_fills(trade, tmp_path):
    trade.opened_on = date(2025, 8, 1)
    trade.holding_qty = Decimal("0")
    trade.save()
    path = tmp_path / "Tradebook - Sep.csv"
    lines = [",".join(row) for row in SAMPLE_BOOK]
    path.write_text("\n".join(lines) + "\n")
    result = ingest_tradebook(
        write_sheet=False,
        writeback_closes=False,
        csv_paths=[str(path)],
    )
    trade.refresh_from_db()
    assert result["tracked_fills"] == 2
    assert result["closed"] == 1
    assert TradebookFill.objects.filter(symbol="INFY").count() == 2
    assert TradebookFill.objects.filter(symbol="RELIANCE").count() == 1
    assert trade.status == TradeStatus.CLOSED


@pytest.mark.django_db
def test_ingest_counts_lots_bought_before_the_sheet_row_date(trade, tmp_path):
    trade.opened_on = date(2026, 4, 16)
    trade.holding_qty = Decimal("0")
    trade.remaining_qty = Decimal("0")
    trade.save()
    path = tmp_path / "book.csv"
    path.write_text("\n".join(",".join(row) for row in SPLIT_YEAR_BOOK) + "\n")
    ingest_tradebook(write_sheet=False, writeback_closes=False, csv_paths=[str(path)])
    trade.refresh_from_db()
    assert trade.status == TradeStatus.PARTIAL
    assert trade.remaining_qty == Decimal("6")
    assert trade.holding_qty == Decimal("6")
    assert trade.closed_qty == Decimal("7")


@pytest.mark.django_db
def test_ingest_ignores_fills_outside_the_sheet_period(trade, tmp_path):
    book = [SAMPLE_BOOK[0], _book_row("INFY", "2019-05-30", "buy", "3", "500", "t9")]
    book.extend(SAMPLE_BOOK[1:])
    trade.opened_on = None
    trade.holding_qty = Decimal("0")
    trade.save()
    path = tmp_path / "book.csv"
    path.write_text("\n".join(",".join(row) for row in book) + "\n")
    ingest_tradebook(write_sheet=False, writeback_closes=False, csv_paths=[str(path)])
    trade.refresh_from_db()
    assert trade.status == TradeStatus.CLOSED
    assert trade.opened_on == date(2025, 9, 2)


@pytest.mark.django_db
def test_detail_shows_tradebook_fills(client, trade, tmp_path):
    trade.opened_on = date(2025, 8, 1)
    trade.holding_qty = Decimal("0")
    trade.save()
    path = tmp_path / "book.csv"
    path.write_text("\n".join(",".join(row) for row in SAMPLE_BOOK) + "\n")
    ingest_tradebook(write_sheet=False, writeback_closes=False, csv_paths=[str(path)])
    response = client.get(reverse("trade_detail", args=[trade.pk]))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Tradebook fills" in html
    assert "BUY" in html
    assert "SELL" in html


@pytest.mark.django_db
def test_dashboard_filter_and_sort(client, trade):
    trade.status = TradeStatus.CLOSED
    trade.last_ltp = Decimal("1450")
    trade.save()
    from trades.models import TradeIdea

    TradeIdea.objects.create(
        sheet_row=3,
        symbol="ABB",
        exchange="NSE",
        recommended_qty=Decimal("1"),
        remaining_qty=Decimal("1"),
        holding_qty=Decimal("1"),
        buy_low=Decimal("1"),
        buy_high=Decimal("2"),
        target=Decimal("3"),
        stop_loss=Decimal("1"),
        status=TradeStatus.OPEN,
        sheet_slug="aug24-27",
    )
    closed_only = client.get("/?position=CLOSED&sort=symbol")
    assert closed_only.status_code == 200
    assert b"INFY" in closed_only.content
    assert b"ABB" not in closed_only.content
    by_name = client.get("/?sort=symbol")
    body = by_name.content.decode()
    assert body.index("ABB") < body.index("INFY")
