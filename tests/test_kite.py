"""Kite holdings aggregation, LTP permission fallback, and login callbacks."""

from decimal import Decimal

import pytest

from integrations.kite import aggregate_holding, KiteClient, parse_holdings, parse_ltp_map
from trades.models import KiteSession


def test_aggregate_holding_sums_nse_and_bse_legs():
    """The sheet calls everything NSE, but Kite can hold the same ticker on BSE."""
    lookup = {
        ("NSE", "BIOCON"): {
            "quantity": Decimal("0"),
            "average_price": Decimal("340"),
            "last_price": Decimal("352"),
        },
        ("BSE", "BIOCON"): {
            "quantity": Decimal("28"),
            "average_price": Decimal("300"),
            "last_price": Decimal("351.5"),
        },
    }
    holding = aggregate_holding(lookup, "BIOCON")
    assert holding["quantity"] == Decimal("28")
    assert holding["average_price"] == Decimal("300")
    assert holding["last_price"] == Decimal("351.5")
    assert aggregate_holding(lookup, "PRICOL") is None


def test_aggregate_holding_weights_average_price_across_exchanges():
    lookup = {
        ("NSE", "TI"): {"quantity": Decimal("40"), "average_price": Decimal("100")},
        ("BSE", "TI"): {"quantity": Decimal("10"), "average_price": Decimal("150")},
    }
    holding = aggregate_holding(lookup, "TI")
    assert holding["quantity"] == Decimal("50")
    assert holding["average_price"] == Decimal("110")
    assert holding["last_price"] is None


def test_ltp_permission_error_returns_empty(settings):
    settings.KITE_API_KEY = "real-looking-key"

    class Denied:
        def ltp(self, instruments):
            raise RuntimeError("Insufficient permission for that call.")

    client = KiteClient()
    client._connect = lambda access_token=None: Denied()
    assert client.ltp("token", ["NSE:INFY"]) == {}


def test_placeholder_key_is_not_configured(settings):
    settings.KITE_API_KEY = "your_api_key_here"
    assert KiteClient().is_configured() is False
    assert KiteClient().holdings("token") == []
    assert KiteClient().ltp("token", ["NSE:INFY"]) == {}


def test_parse_holdings_and_ltp():
    holdings = parse_holdings(
        [
            {
                "tradingsymbol": "infy",
                "exchange": "NSE",
                "quantity": 10,
                "average_price": 1450.5,
                "last_price": 1460,
            },
            {"tradingsymbol": "", "quantity": 1},
        ]
    )
    assert holdings == [
        {
            "exchange": "NSE",
            "symbol": "INFY",
            "quantity": Decimal("10"),
            "average_price": Decimal("1450.5"),
            "last_price": Decimal("1460"),
        }
    ]
    prices = parse_ltp_map({"NSE:INFY": {"last_price": 1461.25}})
    assert prices["NSE:INFY"] == Decimal("1461.25")


@pytest.mark.django_db
def test_zerodha_default_callback_path(client, monkeypatch):
    monkeypatch.setattr(
        "trades.views.KiteClient.exchange_request_token",
        lambda self, token: {"access_token": f"acc-{token}"},
    )
    response = client.get(
        "/callback?request_token=rt-1&action=login&type=login&status=success"
    )
    assert response.status_code == 302
    assert KiteSession.objects.filter(access_token="acc-rt-1").exists()


@pytest.mark.django_db
def test_kite_prefixed_callback_path_still_works(client, monkeypatch):
    monkeypatch.setattr(
        "trades.views.KiteClient.exchange_request_token",
        lambda self, token: {"access_token": "acc-prefixed"},
    )
    response = client.get("/kite/callback/?request_token=rt-2&status=success")
    assert response.status_code == 302
    assert KiteSession.objects.filter(access_token="acc-prefixed").exists()
