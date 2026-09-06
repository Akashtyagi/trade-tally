"""Manual close math, remaining qty, and sheet writeback payload."""

from decimal import Decimal

import pytest

from trades.models import TradeStatus
from trades.services import close_trade, close_writeback_payload, dashboard_stats


@pytest.mark.django_db
def test_full_close_profit(trade, monkeypatch):
    written = {}

    def fake_write(closed_trade):
        written.update(close_writeback_payload(closed_trade))

    monkeypatch.setattr("integrations.sheets.write_close", fake_write)
    event = close_trade(trade, Decimal("50"), Decimal("1600"))
    trade.refresh_from_db()
    assert event.realized_pnl == Decimal("7500")  # midpoint 1450 -> 1600 * 50
    assert trade.status == TradeStatus.CLOSED
    assert trade.remaining_qty == Decimal("0")
    assert trade.closed_qty == Decimal("50")
    assert written["status"] == "CLOSED"
    assert written["closed_qty"] == "50.0000" or written["closed_qty"].startswith("50")


@pytest.mark.django_db
def test_partial_close_then_full(trade, monkeypatch):
    monkeypatch.setattr("integrations.sheets.write_close", lambda *a, **k: None)
    close_trade(trade, Decimal("20"), Decimal("1550"))
    trade.refresh_from_db()
    assert trade.status == TradeStatus.PARTIAL
    assert trade.remaining_qty == Decimal("30")
    close_trade(trade, Decimal("30"), Decimal("1400"))
    trade.refresh_from_db()
    assert trade.status == TradeStatus.CLOSED
    assert trade.remaining_qty == 0
    # first: (1550-1450)*20 = 2000; second: (1400-1450)*30 = -1500; net 500
    assert trade.realized_pnl() == Decimal("500")


@pytest.mark.django_db
def test_cannot_close_more_than_remaining(trade, monkeypatch):
    monkeypatch.setattr("integrations.sheets.write_close", lambda *a, **k: None)
    with pytest.raises(ValueError):
        close_trade(trade, Decimal("80"), Decimal("1500"))


@pytest.mark.django_db
def test_uses_kite_average_price_for_pnl(trade, monkeypatch):
    monkeypatch.setattr("integrations.sheets.write_close", lambda *a, **k: None)
    trade.holding_avg_price = Decimal("1500")
    trade.save()
    event = close_trade(trade, Decimal("10"), Decimal("1600"))
    assert event.realized_pnl == Decimal("1000")


@pytest.mark.django_db
def test_dashboard_totals(trade, monkeypatch):
    monkeypatch.setattr("integrations.sheets.write_close", lambda *a, **k: None)
    trade.last_ltp = Decimal("1460")
    trade.save()
    close_trade(trade, Decimal("10"), Decimal("1500"))
    trade.refresh_from_db()
    stats = dashboard_stats([trade])
    assert stats["total_trades"] == 1
    # remaining 40 * avg 1450
    assert stats["total_invested"] == Decimal("58000")
    assert stats["realized_pnl"] == Decimal("500")
    assert stats["net_pnl"] == stats["realized_pnl"] + stats["unrealized_pnl"]
