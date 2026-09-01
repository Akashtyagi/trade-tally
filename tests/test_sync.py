from decimal import Decimal

import pytest

from integrations.sheets import apply_sheet_row, parse_rows, sync_from_sheet
from trades.models import TradeIdea, TradeStatus
from trades.services import close_trade


SAMPLE = [
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
    ["INFY", "NSE", "50", "1400", "1500", "1700", "1300", "OPEN", "", "", ""],
]


@pytest.mark.django_db
def test_sync_upserts_from_sheet():
    trades = sync_from_sheet(SAMPLE)
    assert len(trades) == 1
    trade = TradeIdea.objects.get(symbol="INFY")
    assert trade.recommended_qty == Decimal("50")
    assert trade.remaining_qty == Decimal("50")
    assert trade.status == TradeStatus.OPEN

    again = SAMPLE.copy()
    again = [SAMPLE[0], ["INFY", "NSE", "60", "1400", "1500", "1700", "1300", "OPEN", "", "", ""]]
    sync_from_sheet(again)
    trade.refresh_from_db()
    assert trade.recommended_qty == Decimal("60")
    assert TradeIdea.objects.filter(symbol="INFY").count() == 1


@pytest.mark.django_db
def test_sync_preserves_local_closes(monkeypatch):
    trade = apply_sheet_row(parse_rows(SAMPLE)[0])
    monkeypatch.setattr("integrations.sheets.write_close", lambda *a, **k: None)
    close_trade(trade, Decimal("20"), Decimal("1550"), writeback=False)
    sync_from_sheet(SAMPLE)
    trade.refresh_from_db()
    assert trade.status == TradeStatus.PARTIAL
    assert trade.remaining_qty == Decimal("30")
    assert trade.closed_qty == Decimal("20")
