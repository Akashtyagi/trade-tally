"""Indian rupee display: lakh grouping, one decimal place."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_ONE_PLACE = Decimal("0.1")


def format_inr(value) -> str:
    """Format a number as ₹12,00,000.0 (Indian grouping, 1 decimal)."""
    amount = _to_decimal(value)
    if amount is None:
        return ""
    quantized = amount.quantize(_ONE_PLACE, rounding=ROUND_HALF_UP)
    negative = quantized < 0
    quantized = abs(quantized)
    integer, frac = f"{quantized:.1f}".split(".")
    grouped = _indian_group(integer)
    sign = "-" if negative else ""
    return f"₹{sign}{grouped}.{frac}"


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    text = (
        str(value)
        .strip()
        .replace("₹", "")
        .replace(",", "")
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace("−", "-")
    )
    if text in {"", "-", "+", "--"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _indian_group(digits: str) -> str:
    """Last 3 digits, then groups of 2 (12,34,56,789)."""
    if len(digits) <= 3:
        return digits
    last3 = digits[-3:]
    rest = digits[:-3]
    parts: list[str] = []
    while rest:
        parts.append(rest[-2:])
        rest = rest[:-2]
    return ",".join([*reversed(parts), last3])
