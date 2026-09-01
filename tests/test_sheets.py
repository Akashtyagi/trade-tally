from decimal import Decimal

from integrations.sheets import (
    COMPLETED_ROW_OFFSET,
    find_header_row,
    header_index_map,
    parse_buy_range,
    parse_decimal,
    parse_portfolio_config,
    parse_rows,
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

