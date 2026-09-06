"""Indian rupee grouping (lakhs) and one-decimal display."""

from decimal import Decimal

from trades.money import format_inr


def test_indian_grouping_and_one_decimal():
    assert format_inr(Decimal("1200000")) == "₹12,00,000.0"
    assert format_inr("1200000.00") == "₹12,00,000.0"
    assert format_inr(Decimal("12345678.56")) == "₹1,23,45,678.6"
    assert format_inr(Decimal("16672.5")) == "₹16,672.5"
    assert format_inr(Decimal("820")) == "₹820.0"
    assert format_inr(Decimal("-9.54")) == "₹-9.5"
    assert format_inr(None) == ""
    assert format_inr("") == ""
