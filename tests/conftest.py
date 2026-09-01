from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from trades.models import TradeIdea, TradeStatus


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="akash", password="pass12345")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def trade(db):
    return TradeIdea.objects.create(
        sheet_row=2,
        symbol="INFY",
        exchange="NSE",
        recommended_qty=Decimal("50"),
        remaining_qty=Decimal("50"),
        buy_low=Decimal("1400"),
        buy_high=Decimal("1500"),
        target=Decimal("1700"),
        stop_loss=Decimal("1300"),
        status=TradeStatus.OPEN,
    )
