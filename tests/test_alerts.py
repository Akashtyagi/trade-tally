from decimal import Decimal

import pytest

from integrations.checker import evaluate_open_trades, maybe_alert
from trades.models import AlertLog, AlertType


@pytest.mark.django_db
def test_maybe_alert_dedupes_same_day(trade):
    sent = []
    first = maybe_alert(trade, AlertType.TARGET, Decimal("1710"), send=sent.append)
    second = maybe_alert(trade, AlertType.TARGET, Decimal("1720"), send=sent.append)
    assert first is not None
    assert second is None
    assert len(sent) == 1
    assert AlertLog.objects.filter(trade=trade, alert_type=AlertType.TARGET).count() == 1


@pytest.mark.django_db
def test_evaluate_open_trades_sends_underweight(trade):
    trade.holding_qty = Decimal("5")
    trade.last_ltp = Decimal("1450")
    trade.save()
    sent = []
    created = evaluate_open_trades(send=sent.append)
    assert len(created) == 1
    assert created[0].alert_type == AlertType.UNDERWEIGHT_BUY_ZONE
    assert sent
