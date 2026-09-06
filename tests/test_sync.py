"""Sheet sync must not overwrite Kite held qty; Zerodha sync writes BSE-only names."""

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


@pytest.mark.django_db
def test_sheet_sync_does_not_override_kite_held_qty():
    from trades.models import HoldingSnapshot

    HoldingSnapshot.objects.create(
        exchange="NSE",
        symbol="INFY",
        quantity=Decimal("40"),
        average_price=Decimal("1450"),
    )
    row = parse_rows(
        [
            ["symbol", "qty", "current_qty"],
            ["INFY", "50", "95"],
        ]
    )[0]
    trade = apply_sheet_row(row)
    assert trade.holding_qty == Decimal("40")
    assert trade.remaining_qty == Decimal("40")


@pytest.mark.django_db
def test_sheet_sync_sees_holdings_kept_on_the_other_exchange():
    """Sheet rows are all NSE; a BSE-only holding must still count as held."""
    from trades.models import HoldingSnapshot

    HoldingSnapshot.objects.create(
        exchange="NSE", symbol="BIOCON", quantity=Decimal("0"), average_price=Decimal("340")
    )
    HoldingSnapshot.objects.create(
        exchange="BSE", symbol="BIOCON", quantity=Decimal("28"), average_price=Decimal("300")
    )
    row = parse_rows([["symbol", "qty", "current_qty"], ["BIOCON", "209", "0"]])[0]
    trade = apply_sheet_row(row)
    assert trade.holding_qty == Decimal("28")


@pytest.mark.django_db
def test_zerodha_sync_writes_col_o_for_bse_only_holding(trade, monkeypatch):
    from trades.models import KiteSession

    KiteSession.objects.create(access_token="tok")
    trade.symbol = "BIOCON"
    trade.exchange = "NSE"
    trade.save()

    class FakeClient:
        def is_configured(self):
            return True

        def holdings(self, token):
            return [
                {
                    "tradingsymbol": "BIOCON",
                    "exchange": "BSE",
                    "quantity": 28,
                    "average_price": 300,
                    "last_price": 351.5,
                }
            ]

    monkeypatch.setattr("integrations.zerodha_sync.KiteClient", FakeClient)
    held = []
    monkeypatch.setattr(
        "integrations.zerodha_sync.write_zerodha_holdings",
        lambda items, slug=None: held.extend(items) or [],
    )
    from integrations.zerodha_sync import sync_zerodha

    sync_zerodha()
    trade.refresh_from_db()
    assert trade.holding_qty == Decimal("28")
    assert trade.last_ltp == Decimal("351.5")
    assert held[0][1] == Decimal("28")
