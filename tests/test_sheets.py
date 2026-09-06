"""Google Sheet header/block parsing and writeback cell ranges."""

from decimal import Decimal

import pytest

from integrations.sheets import (
    COMPLETED_ROW_OFFSET,
    find_header_row,
    format_qty,
    header_index_map,
    held_qty_differs,
    ltp_from_sheet_pnl,
    parse_buy_range,
    parse_decimal,
    parse_portfolio_config,
    parse_rows,
    parse_tcp,
    write_held_quantities_if_changed,
    write_zerodha_holdings,
    writeback_updates,
)


SAMPLE_SHEET = [
    [
        "symbol",
        "exchange",
        "qty",
        "buy_low",
        "buy_high",
        "target",
        "stop_loss",
        "status",
        "closed_qty",
        "closed_price",
        "notes",
    ],
    ["INFY", "NSE", "50", "1,400", "1500", "1700", "1300", "OPEN", "", "", "it"],
    ["", "NSE", "10", "100", "110", "120", "90", "OPEN", "", "", "skip blank symbol"],
    ["RELIANCE", "", "20", "2800", "2900", "3100", "2700", "", "0", "", ""],
]


def test_parse_rows_skips_blank_and_defaults_exchange():
    rows = parse_rows(SAMPLE_SHEET)
    assert len(rows) == 2
    infy = rows[0]
    assert infy["sheet_row"] == 2
    assert infy["symbol"] == "INFY"
    assert infy["qty"] == Decimal("50")
    assert infy["buy_low"] == Decimal("1400")
    assert infy["status"] == "OPEN"
    reliance = rows[1]
    assert reliance["sheet_row"] == 4
    assert reliance["exchange"] == "NSE"
    assert reliance["symbol"] == "RELIANCE"


def test_header_remap():
    headers = ["Ticker", "Quantity", "SL"]
    column_map = {
        "symbol": "ticker",
        "qty": "quantity",
        "stop_loss": "sl",
        "exchange": "exchange",
        "buy_low": "buy_low",
        "buy_high": "buy_high",
        "target": "target",
        "status": "status",
        "closed_qty": "closed_qty",
        "closed_price": "closed_price",
        "notes": "notes",
    }
    indexes = header_index_map(headers, column_map)
    assert indexes["symbol"] == 0
    assert indexes["qty"] == 1
    assert indexes["stop_loss"] == 2


def test_writeback_updates_target_status_qty_price_cells():
    headers = ["symbol", "status", "closed_qty", "closed_price"]
    payload = {"status": "CLOSED", "closed_qty": "50", "closed_price": "1680"}
    updates = writeback_updates(headers, 2, payload)
    cells = {u["range"]: u["values"][0][0] for u in updates}
    assert cells["B2"] == "CLOSED"
    assert cells["C2"] == "50"
    assert cells["D2"] == "1680"


def test_parse_rows_requires_symbol_column():
    try:
        parse_rows([["qty"], ["10"]])
    except ValueError as exc:
        assert "symbol" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_parse_rupee_and_formula_errors():
    assert parse_decimal("₹   16,672.50") == Decimal("16672.50")
    assert parse_decimal("-₹   9.50") == Decimal("-9.50")
    assert parse_decimal("#DIV/0!") is None
    assert parse_decimal("#N/A") is None
    assert parse_buy_range("155-180") == (Decimal("155"), Decimal("180"))
    assert parse_buy_range("445--4500") == (Decimal("445"), Decimal("4500"))
    assert parse_buy_range("₹820.00") == (Decimal("820.00"), Decimal("820.00"))


def test_parse_live_workbook_layout():
    import csv
    from pathlib import Path

    values = list(csv.reader(Path("tests/fixtures/shares_workbook.csv").open(encoding="utf-8")))
    assert find_header_row(values) == 2
    parsed = parse_rows(values)
    by_key = {(r["symbol"], r["status"]): r for r in parsed}

    penind_open = by_key[("PENIND", "OPEN")]
    assert penind_open["qty"] == Decimal("137")
    assert penind_open["current_qty"] == Decimal("95")
    assert penind_open["buy_low"] == Decimal("155")
    assert penind_open["buy_high"] == Decimal("180")
    assert penind_open["stop_loss"] == Decimal("100")
    assert penind_open["entry_price"] == Decimal("175.50")
    assert penind_open["sheet_row"] < COMPLETED_ROW_OFFSET

    penind_closed = by_key[("PENIND", "CLOSED")]
    assert penind_closed["closed_qty"] == Decimal("30")
    assert penind_closed["closed_price"] == Decimal("213.78")
    assert penind_closed["sheet_row"] >= COMPLETED_ROW_OFFSET

    # Placeholder names with no plan/holding are skipped
    assert "CENTRALBK" not in {r["symbol"] for r in parsed if r["status"] == "OPEN"}

    abdl = by_key[("ABDL", "OPEN")]
    assert abdl["current_qty"] < abdl["qty"]
    assert abdl["opened_on"].year == 2024

    config = parse_portfolio_config(values)
    assert config["total_budget"] == Decimal("1200000.00")
    assert config["risk_percentage"] == Decimal("8")
    assert penind_open["tcp"] == Decimal("1.39")


def test_parse_tcp_and_extra_targets():
    assert parse_tcp("1.39%") == Decimal("1.39")
    assert parse_tcp("72000 : 6.0%") == Decimal("6.0")
    header = [
        "S No",
        "Share",
        "Entry Price",
        "Quantity",
        "Maximum Shares Recom.",
        "Buy Range",
        "STOP LOSS",
        "FIRST TARGET",
        "SECOND TARGET",
        "THRID TARGET",
        "Total Captial Percentage",
        "S No",
        "Share",
        "Quantity",
        "Exit Price",
    ]
    data = [
        "1",
        "AMBER",
        "8320",
        "0",
        "10",
        "8320-8320",
        "6700",
        "9999",
        "11000",
        "12000",
        "6.0%",
        "",
        "",
        "",
        "",
    ]
    parsed = parse_rows([header, data])
    open_row = next(r for r in parsed if r["status"] == "OPEN")
    assert open_row["target"] == Decimal("9999")
    assert open_row["target_2"] == Decimal("11000")
    assert open_row["target_3"] == Decimal("12000")
    assert open_row["tcp"] == Decimal("6.0")


def test_parse_maximum_shares_and_quantity_headers():
    """Live Aug24-27 tab uses Quantity + Maximum Shares Recom., not Current Quantity."""
    header = (
        [""] * 9
        + [
            "S No",
            "Date",
            "Share",
            "Entry Price",
            "Quantity",
            "Maximum Shares Recom.",
            "Buy Range",
            "STOP LOSS",
            "FIRST TARGET",
            "Comments",
            "S No",
            "Share",
            "Quantity",
            "Exit Price",
        ]
    )
    data = (
        [""] * 9
        + [
            "1",
            "7-Aug-2024",
            "PENIND",
            "175.50",
            "95",
            "137",
            "155-180",
            "100",
            "200",
            "held",
            "1",
            "PENIND",
            "30",
            "213.78",
        ]
    )
    parsed = parse_rows([header, data])
    open_row = next(r for r in parsed if r["status"] == "OPEN")
    assert open_row["qty"] == Decimal("137")
    assert open_row["current_qty"] == Decimal("95")
    closed_row = next(r for r in parsed if r["status"] == "CLOSED")
    assert closed_row["closed_qty"] == Decimal("30")
    assert closed_row["closed_price"] == Decimal("213.78")


def test_ltp_from_googlefinance_current_pnl():
    assert ltp_from_sheet_pnl(Decimal("1202"), Decimal("15.5")) == Decimal("1217.5")
    assert ltp_from_sheet_pnl(Decimal("820"), Decimal("0")) == Decimal("820")
    assert ltp_from_sheet_pnl(Decimal("820"), Decimal("24054"), Decimal("211")) == Decimal("934")
    rows = parse_rows(
        [
            ["Share", "Entry Price", "Maximum Shares Recom.", "Current P/L"],
            ["AGARIND", "1202", "40", "12.5"],
        ]
    )
    assert rows[0]["last_ltp"] == Decimal("1214.5")


def test_held_qty_differs_compares_decimals():
    assert not held_qty_differs("95.0", Decimal("95"))
    assert not held_qty_differs("", Decimal("0"))
    assert held_qty_differs("95", Decimal("40"))
    assert held_qty_differs("", Decimal("40"))
    assert format_qty(Decimal("40.0000")) == "40"


@pytest.mark.django_db
def test_write_held_qty_only_when_sheet_differs(trade, monkeypatch):
    values = [
        ["S No", "Share", "Quantity"],
        ["1", "INFY", "50"],
    ]
    captured = []

    class FakeWs:
        def get_all_values(self):
            return values

        def batch_update(self, updates, value_input_option=None):
            captured.extend(updates)

    monkeypatch.setattr("trades.runtime_config.spreadsheet_id", lambda slug=None: "sheet")
    monkeypatch.setattr("integrations.sheets._worksheet", lambda slug=None: FakeWs())

    same = write_held_quantities_if_changed([(trade, Decimal("50"))])
    assert same == []
    assert captured == []

    changed = write_held_quantities_if_changed([(trade, Decimal("40"))])
    assert changed
    assert captured[0]["values"][0][0] == "40"


@pytest.mark.django_db
def test_write_zerodha_holdings_is_one_read_and_one_write(trade, monkeypatch):
    from trades.models import TradeIdea, TradeStatus

    other = TradeIdea.objects.create(
        sheet_row=3,
        symbol="BIOCON",
        recommended_qty=Decimal("209"),
        remaining_qty=Decimal("0"),
        buy_low=Decimal("340"),
        buy_high=Decimal("340"),
        status=TradeStatus.OPEN,
        sheet_slug="aug24-27",
    )
    values = [
        ["Share", "Quantity", "Total Investment"],
        ["INFY", "50", "72500"],
        ["BIOCON", "0", "0"],
    ]
    reads = []
    writes = []

    class FakeWs:
        def get_all_values(self):
            reads.append(1)
            return values

        def batch_update(self, updates, value_input_option=None):
            writes.append(list(updates))

    monkeypatch.setattr("trades.runtime_config.spreadsheet_id", lambda slug=None: "sheet")
    monkeypatch.setattr("integrations.sheets._worksheet", lambda slug=None: FakeWs())

    updates = write_zerodha_holdings([(trade, Decimal("40")), (other, Decimal("28"))])
    assert len(reads) == 1
    assert len(writes) == 1
    cells = {item["range"]: item["values"][0][0] for item in writes[0]}
    assert cells["B2"] == "40"
    assert cells["B3"] == "28"
    assert Decimal(cells["C2"]) == Decimal("58000")
    assert Decimal(cells["C3"]) == Decimal("9520")
    assert len(updates) == 4

