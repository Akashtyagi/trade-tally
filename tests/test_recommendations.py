"""Advisor dump parse, ticker map, and open-block row placement."""

from decimal import Decimal
from pathlib import Path

from integrations.recommendations import (
    buy_range_patches_from_comments,
    classify_message,
    last_open_share_row,
    open_share_rows,
    parse_buy_levels,
    parse_dump,
    parse_new_buy,
    parse_risk_pct,
    qty_formula,
    resolve_ticker,
    suggested_qty,
)


AMBER = """
🖼 Amber : Clean Technical Breakout on weekly charts.

Buy at Rs 8320, Stop loss Rs 6700 on weekly closing.

Target Rs 9999.
Allocation of 2-3% good to start. Moderate Trade.
"""

IOL = """
🖼 IOL Chemical & Pharma : Buy at Rs 180

Stop loss Rs 140 on Daily Closing Basis.

Target 220 - 240

Short Term Trade as per Chart Breakout.

Holding Period 2-4 Months. Max Allocation 2%.
"""


def test_classify_and_parse_amber():
    assert classify_message(AMBER) == "new_buy"
    row = parse_new_buy(AMBER)
    assert row["ticker"] == "AMBER"
    assert row["buy_low"] == Decimal("8320")
    assert row["buy_high"] == Decimal("8320")
    assert row["stop_loss"] == Decimal("6700")
    assert row["target"] == Decimal("9999")
    assert row["risk_pct"] == Decimal("2")


def test_iol_target_band_and_risk():
    row = parse_new_buy(IOL)
    assert row["ticker"] == "IOLCP"
    assert row["target"] == Decimal("220")
    assert row["target_2"] == Decimal("240")
    assert row["risk_pct"] == Decimal("2")


def test_risk_range_takes_lower():
    assert parse_risk_pct("Allocation of 2-3% good") == Decimal("2")
    assert parse_risk_pct("2.5-3%") == Decimal("2.5")
    assert parse_risk_pct("2.5% Allocation Max") == Decimal("2.5")


def test_qty_is_min_of_risk_and_b2_cap():
    qty = suggested_qty(
        corpus=Decimal("1200000"),
        risk_pct=Decimal("2"),
        entry=Decimal("180"),
        stop_loss=Decimal("140"),
        max_alloc_pct=Decimal("8"),
    )
    # risk: 1200000*0.02/40 = 600; cap: 1200000*0.08/180 = 533 → 533
    assert qty == Decimal("533")


def test_open_block_helpers():
    grid = [[""] * 12 for _ in range(50)]
    grid[4][11] = "PENIND"
    grid[41][11] = "CANBK"
    assert last_open_share_row(grid) == 42
    assert "PRICOL" not in open_share_rows(grid)
    assert open_share_rows(grid)["CANBK"] == 42


def test_qty_formula_matches_skill():
    assert qty_formula(12) == (
        "=MIN(ROUNDDOWN(($A$5*M12)/(N12-V12),0),ROUNDDOWN(($A$5*$B$2)/N12,0))"
    )


def test_resolve_ticker_company_and_direct_symbol():
    assert resolve_ticker("Aeroflex : Target of Rs 550 Hit") == "AEROFLEX"
    assert resolve_ticker("IMFA : Trade Update") == "IMFA"
    assert resolve_ticker("Kirlosker Pneumatic : Hit 2nd Target") == "KIRLPNU"
    assert resolve_ticker("Larsen & Toubro Hit 2nd Target of Rs 3850") == "LT"
    assert resolve_ticker("NMDC : Book profit") == "NMDC"
    assert resolve_ticker("SBCL : Hit 1st Target") == "SBCL"
    assert resolve_ticker("Samhi Hotels") == "SAMHI"
    assert resolve_ticker("TVS Motors : Hit 2nd Target") == "TVSMOTOR"
    assert resolve_ticker("Himatsingka") == "HIMATSEIDE"


def test_parse_dump_skips_ipo_and_keeps_buys():
    text = Path("zerodha_files/trades.txt").read_text(encoding="utf-8")
    parsed = parse_dump(text)
    tickers = {r["ticker"] for r in parsed["new_buys"] if r["ticker"]}
    assert "AMBER" in tickers
    assert "IOLCP" in tickers
    assert "PRICOL" in tickers
    assert parsed["skipped"] > 0
    kinds = [classify_message(b) for b in ["IPO Update : Foo\nAPPLY for listing", AMBER]]
    assert kinds[0] == "skip"
    assert kinds[1] == "new_buy"


PHOENIX = """
Phoenix Mills : Buy at Rs 2000, Some in Dips upto Rs 1800.
Stop loss Rs 1500 on Weekly Closing basis.
Target Rs 2400 - 2800.
"""

PRICOL = """
Pricol : Buy at 550 - 555 Range, Some in dips upto Rs 500.
Stop loss Rs 400 on weekly closing basis.
Target 645 - 750.
"""


def test_dips_widen_buy_range_but_keep_buy_at_as_entry():
    row = parse_new_buy(PHOENIX)
    assert parse_buy_levels(PHOENIX) == (Decimal("1800"), Decimal("2000"))
    assert row["buy_low"] == Decimal("1800")
    assert row["buy_high"] == Decimal("2000")
    assert row["entry"] == Decimal("2000")
    assert row["target"] == Decimal("2400")
    assert row["target_2"] == Decimal("2800")

    pricol = parse_new_buy(PRICOL)
    assert pricol["buy_low"] == Decimal("500")
    assert pricol["buy_high"] == Decimal("555")
    assert pricol["entry"] == Decimal("550")

    band = "Buy at Rs 4900-4950, Some in dips upto Rs 4600."
    assert parse_buy_levels(band) == (Decimal("4600"), Decimal("4950"))


def test_buy_range_patches_from_sheet_comments():
    grid = [[""] * 27 for _ in range(50)]
    grid[48][11] = "PHOENIXLTD"
    grid[48][19] = "2000-2000"
    grid[48][26] = PHOENIX
    grid[10][11] = "AMBER"
    grid[10][19] = "8320-8320"
    grid[10][26] = AMBER
    patches = buy_range_patches_from_comments(grid)
    assert len(patches) == 1
    assert patches[0]["sheet_row"] == 49
    assert patches[0]["buy_range"] == "1800-2000"
    assert patches[0]["was"] == "2000-2000"

