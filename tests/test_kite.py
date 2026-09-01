from decimal import Decimal

from integrations.kite import KiteClient, parse_holdings, parse_ltp_map


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
