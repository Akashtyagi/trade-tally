"""Delete trade from app and Google Sheet."""

from decimal import Decimal

import pytest
from django.urls import reverse

from integrations.sheets import (
    COMPLETED_ROW_OFFSET,
    clear_trade_from_sheet,
    trade_plan_clear_updates,
)
from trades.models import TradeIdea, TradeStatus
from trades.services import delete_trade


def _grid(rows: dict[int, dict[int, str]]) -> list[list[str]]:
    width = max((col for cols in rows.values() for col in cols), default=30) + 1
    height = max(rows) if rows else 5
    grid = [[""] * width for _ in range(height)]
    for row_n, cols in rows.items():
        for col, value in cols.items():
            grid[row_n - 1][col] = value
    return grid


@pytest.mark.django_db
def test_trade_plan_clear_updates_open_and_completed_rows(trade):
    trade.sheet_row = 10
    open_row = trade.sheet_row
    closed_row = 12
    values = _grid(
        {
            open_row: {11: trade.symbol, 19: "1400-1500"},
            closed_row: {29: trade.symbol, 30: "1600"},
        }
    )
    closed_trade = TradeIdea(
        sheet_row=closed_row + COMPLETED_ROW_OFFSET,
        symbol=trade.symbol,
        sheet_slug=trade.sheet_slug,
    )
    updates = trade_plan_clear_updates(values, closed_trade)
    ranges = {item["range"] for item in updates}
    assert f"L{open_row}" in ranges
    assert f"T{open_row}" in ranges
    assert f"AA{open_row}" in ranges
    assert f"AD{closed_row}" in ranges
    assert f"AL{closed_row}" in ranges
    assert all(item["values"] == [[""]] for item in updates)


@pytest.mark.django_db
def test_delete_trade_removes_all_rows_for_symbol(trade, monkeypatch):
    from integrations.sheets import COMPLETED_ROW_OFFSET

    TradeIdea.objects.create(
        sheet_row=trade.sheet_row + COMPLETED_ROW_OFFSET,
        symbol=trade.symbol,
        exchange="NSE",
        recommended_qty=Decimal("10"),
        remaining_qty=Decimal("0"),
        status=TradeStatus.CLOSED,
        sheet_slug=trade.sheet_slug,
    )
    monkeypatch.setattr("integrations.sheets.clear_trade_from_sheet", lambda t: [])
    slug, symbol = delete_trade(trade)
    assert slug == "aug24-27"
    assert symbol == "INFY"
    assert TradeIdea.objects.filter(symbol="INFY", sheet_slug="aug24-27").count() == 0


@pytest.mark.django_db
def test_delete_trade_view(client, trade, monkeypatch):
    monkeypatch.setattr("integrations.sheets.clear_trade_from_sheet", lambda t: [])
    response = client.post(reverse("delete_trade", args=[trade.pk]))
    assert response.status_code == 302
    assert response.url == "/"
    assert not TradeIdea.objects.filter(pk=trade.pk).exists()


@pytest.mark.django_db
def test_delete_trade_view_writes_sheet(client, trade, monkeypatch):
    cleared = []

    def fake_clear(t):
        cleared.append(t.pk)
        return [{"range": "L5", "values": [[""]]}]

    monkeypatch.setattr("integrations.sheets.clear_trade_from_sheet", fake_clear)
    client.post(reverse("delete_trade", args=[trade.pk]))
    assert cleared == [trade.pk]


@pytest.mark.django_db
def test_trade_detail_shows_delete_button(client, trade):
    html = client.get(reverse("trade_detail", args=[trade.pk])).content.decode()
    assert "Delete trade" in html
    assert reverse("delete_trade", args=[trade.pk]) in html


@pytest.mark.django_db
def test_clear_trade_from_sheet_batches_blank_cells(trade, monkeypatch):
    values = _grid({trade.sheet_row: {11: trade.symbol, 26: "Buy at 100"}})
    captured = []

    class FakeWs:
        def get_all_values(self):
            return values

        def batch_update(self, updates, value_input_option=None):
            captured.extend(updates)

    monkeypatch.setattr("trades.runtime_config.spreadsheet_id", lambda slug=None: "sheet")
    monkeypatch.setattr("integrations.sheets._worksheet", lambda slug=None: FakeWs())
    updates = clear_trade_from_sheet(trade)
    assert updates
    assert captured
    assert all(item["values"] == [[""]] for item in captured)
