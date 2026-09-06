"""Market hours, buy-zone / target / SL rules, and run_checks skip paths."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from integrations.checker import (
    evaluate_alerts,
    hit_stop_loss,
    hit_target,
    is_in_buy_zone,
    is_near_buy_zone,
    is_underweight,
    within_market_hours,
)
from trades.models import AlertType, TradeStatus

IST = ZoneInfo("Asia/Kolkata")


def test_underweight_and_buy_zone():
    assert is_underweight(Decimal("10"), Decimal("50"))
    assert not is_underweight(Decimal("50"), Decimal("50"))
    assert is_in_buy_zone(Decimal("1450"), Decimal("1400"), Decimal("1500"))
    assert not is_in_buy_zone(Decimal("1510"), Decimal("1400"), Decimal("1500"))
    assert is_near_buy_zone(Decimal("1650"), Decimal("1400"), Decimal("1500"))
    assert not is_near_buy_zone(Decimal("1800"), Decimal("1400"), Decimal("1500"))


def test_target_and_stop_loss():
    assert hit_target(Decimal("1700"), Decimal("1700"))
    assert hit_target(Decimal("1710"), Decimal("1700"))
    assert not hit_target(Decimal("1699"), Decimal("1700"))
    assert not hit_target(Decimal("100"), Decimal("0"))
    assert hit_stop_loss(Decimal("1300"), Decimal("1300"))
    assert hit_stop_loss(Decimal("1290"), Decimal("1300"))
    assert not hit_stop_loss(Decimal("1301"), Decimal("1300"))
    assert not hit_stop_loss(Decimal("100"), Decimal("0"))


def test_evaluate_underweight_only_in_buy_zone():
    kinds = evaluate_alerts(
        status=TradeStatus.OPEN,
        recommended_qty=Decimal("50"),
        holding_qty=Decimal("10"),
        ltp=Decimal("1450"),
        buy_low=Decimal("1400"),
        buy_high=Decimal("1500"),
        target=Decimal("1700"),
        stop_loss=Decimal("1300"),
    )
    assert kinds == [AlertType.UNDERWEIGHT_BUY_ZONE]


def test_evaluate_skips_underweight_outside_buy_zone():
    kinds = evaluate_alerts(
        status=TradeStatus.OPEN,
        recommended_qty=Decimal("50"),
        holding_qty=Decimal("10"),
        ltp=Decimal("1600"),
        buy_low=Decimal("1400"),
        buy_high=Decimal("1500"),
        target=Decimal("1700"),
        stop_loss=Decimal("1300"),
    )
    assert kinds == []


def test_evaluate_target_requires_holding():
    with_holding = evaluate_alerts(
        status=TradeStatus.OPEN,
        recommended_qty=Decimal("50"),
        holding_qty=Decimal("50"),
        ltp=Decimal("1750"),
        buy_low=Decimal("1400"),
        buy_high=Decimal("1500"),
        target=Decimal("1700"),
        stop_loss=Decimal("1300"),
    )
    without_holding = evaluate_alerts(
        status=TradeStatus.OPEN,
        recommended_qty=Decimal("50"),
        holding_qty=Decimal("0"),
        ltp=Decimal("1750"),
        buy_low=Decimal("1400"),
        buy_high=Decimal("1500"),
        target=Decimal("1700"),
        stop_loss=Decimal("1300"),
    )
    assert AlertType.TARGET in with_holding
    assert without_holding == []


def test_evaluate_stop_loss_and_ignores_closed():
    sl = evaluate_alerts(
        status=TradeStatus.OPEN,
        recommended_qty=Decimal("50"),
        holding_qty=Decimal("40"),
        ltp=Decimal("1200"),
        buy_low=Decimal("1400"),
        buy_high=Decimal("1500"),
        target=Decimal("1700"),
        stop_loss=Decimal("1300"),
    )
    closed = evaluate_alerts(
        status=TradeStatus.CLOSED,
        recommended_qty=Decimal("50"),
        holding_qty=Decimal("40"),
        ltp=Decimal("1200"),
        buy_low=Decimal("1400"),
        buy_high=Decimal("1500"),
        target=Decimal("1700"),
        stop_loss=Decimal("1300"),
    )
    assert sl == [AlertType.STOP_LOSS]
    assert closed == []


def test_market_hours_weekdays_only():
    friday_open = datetime(2026, 8, 21, 10, 0, tzinfo=IST)
    friday_early = datetime(2026, 8, 21, 8, 0, tzinfo=IST)
    saturday = datetime(2026, 8, 22, 11, 0, tzinfo=IST)
    assert within_market_hours(friday_open)
    assert not within_market_hours(friday_early)
    assert not within_market_hours(saturday)


def test_run_checks_skips_outside_market_hours(monkeypatch):
    from integrations.checker import run_checks

    monkeypatch.setattr("integrations.checker.within_market_hours", lambda: False)
    result = run_checks()
    assert result["skipped"] == "outside_market_hours"
    assert result["alerts"] == 0
    assert result["synced"] == 0


def test_run_checks_force_ignores_market_hours(monkeypatch):
    from integrations.checker import run_checks

    monkeypatch.setattr("integrations.checker.within_market_hours", lambda: False)
    monkeypatch.setattr("integrations.checker.sheets_mod.sync_from_sheet", lambda *a, **k: [])
    monkeypatch.setattr("integrations.checker.refresh_holdings_and_prices", lambda *a, **k: {})
    monkeypatch.setattr("integrations.checker.evaluate_open_trades", lambda *a, **k: [])
    result = run_checks(force=True)
    assert "skipped" not in result
    assert result["alerts"] == 0

