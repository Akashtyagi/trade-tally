"""Zerodha Kite Connect client with env placeholders."""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db.models import Q

from trades.models import HoldingSnapshot, KiteSession

logger = logging.getLogger(__name__)

# .env.example value — treated as "not configured" so local runs skip Kite.
PLACEHOLDER_API_KEY = "your_api_key_here"


class KiteNotConfigured(RuntimeError):
    pass


def is_permission_error(exc: BaseException) -> bool:
    """Personal Kite apps often deny LTP/trades; treat that as empty data, not a crash."""
    name = type(exc).__name__
    text = str(exc)
    return name in {"PermissionException", "ForbiddenException"} or "Insufficient permission" in text


class KiteClient:
    """Thin wrapper around kiteconnect. Methods here are the HTTP calls to api.kite.trade."""
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key if api_key is not None else settings.KITE_API_KEY
        self.api_secret = api_secret if api_secret is not None else settings.KITE_API_SECRET
        self.base_url = base_url if base_url is not None else settings.KITE_API_BASE_URL

    def is_configured(self) -> bool:
        return bool(self.api_key) and self.api_key != PLACEHOLDER_API_KEY

    def login_url(self) -> str:
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={self.api_key}"

    def _connect(self, access_token: str | None = None):
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=self.api_key, root=self.base_url)
        if access_token:
            kite.set_access_token(access_token)
        return kite

    def exchange_request_token(self, request_token: str) -> dict:
        """POST /session/token — one-shot request_token → access_token."""
        if not self.is_configured():
            raise KiteNotConfigured("Set KITE_API_KEY and KITE_API_SECRET in .env")
        kite = self._connect()
        data = kite.generate_session(request_token, api_secret=self.api_secret)
        return data

    def holdings(self, access_token: str) -> list[dict]:
        """GET /portfolio/holdings. The daily token must already be on the session."""
        if not self.is_configured():
            return []
        return self._connect(access_token).holdings() or []

    def ltp(self, access_token: str, instruments: list[str]) -> dict:
        """Live LTP. Personal (free) Kite apps do not allow this; returns {} instead of failing."""
        if not self.is_configured() or not instruments:
            return {}
        try:
            return self._connect(access_token).ltp(instruments) or {}
        except Exception as exc:
            if is_permission_error(exc):
                logger.warning(
                    "Kite LTP/quote is not allowed on this app (Personal apps have no market data). %s",
                    exc,
                )
                return {}
            raise

    def trades(self, access_token: str) -> list[dict]:
        if not self.is_configured():
            return []
        try:
            return self._connect(access_token).trades() or []
        except Exception as exc:
            if is_permission_error(exc):
                logger.warning("Kite trades() not permitted: %s", exc)
                return []
            raise

    def orders(self, access_token: str) -> list[dict]:
        if not self.is_configured():
            return []
        return self._connect(access_token).orders() or []


def latest_access_token() -> str | None:
    """Latest KiteSession row — local DB only, not a Kite call."""
    session = KiteSession.objects.order_by("-login_time").first()
    return session.access_token if session else None


def parse_holdings(raw: list[dict]) -> list[dict]:
    """Normalize a holdings() payload. No HTTP."""
    parsed = []
    for row in raw:
        symbol = str(row.get("tradingsymbol") or row.get("symbol") or "").upper()
        exchange = str(row.get("exchange") or "NSE").upper()
        if not symbol:
            continue
        parsed.append(
            {
                "exchange": exchange,
                "symbol": symbol,
                "quantity": Decimal(str(row.get("quantity") or 0)),
                "average_price": Decimal(str(row.get("average_price") or 0)),
                "last_price": (
                    Decimal(str(row["last_price"])) if row.get("last_price") is not None else None
                ),
            }
        )
    return parsed


def store_holding_snapshots(parsed: list[dict], fetched_at) -> dict[tuple[str, str], dict]:
    """Persist Kite holdings. Symbols missing from Kite are held qty 0."""
    lookup = {(row["exchange"], row["symbol"]): row for row in parsed}
    for row in parsed:
        HoldingSnapshot.objects.update_or_create(
            exchange=row["exchange"],
            symbol=row["symbol"],
            defaults={
                "quantity": row["quantity"],
                "average_price": row["average_price"],
                "last_price": row["last_price"],
                "fetched_at": fetched_at,
            },
        )
    if lookup:
        keep = Q()
        for exchange, symbol in lookup:
            keep |= Q(exchange=exchange, symbol=symbol)
        # Sold-out names stay in the table at qty 0 so sheet sync does not revive them.
        HoldingSnapshot.objects.exclude(keep).update(quantity=0, fetched_at=fetched_at)
    else:
        HoldingSnapshot.objects.update(quantity=0, fetched_at=fetched_at)
    return lookup


def aggregate_holding(lookup: dict, symbol: str) -> dict | None:
    """In-memory NSE+BSE sum for one ticker. Does not call Kite."""
    rows = [row for key, row in lookup.items() if key[1] == symbol]
    if not rows:
        return None
    quantities = [Decimal(str(row.get("quantity") or 0)) for row in rows]
    quantity = sum(quantities, Decimal("0"))
    if quantity > 0:
        cost = sum(
            (
                qty * Decimal(str(row.get("average_price") or 0))
                for qty, row in zip(quantities, rows)
            ),
            Decimal("0"),
        )
        average_price = cost / quantity
    else:
        average_price = next(
            (Decimal(str(row["average_price"])) for row in rows if row.get("average_price")),
            Decimal("0"),
        )
    priced = [
        row["last_price"]
        for qty, row in zip(quantities, rows)
        if row.get("last_price") is not None and qty > 0
    ] or [row["last_price"] for row in rows if row.get("last_price") is not None]
    return {
        "quantity": quantity,
        "average_price": average_price,
        "last_price": priced[0] if priced else None,
    }


def parse_fills(raw: list[dict]) -> list[dict]:
    fills = []
    for row in raw or []:
        symbol = str(row.get("tradingsymbol") or row.get("symbol") or "").upper()
        if not symbol:
            continue
        fills.append(
            {
                "symbol": symbol,
                "exchange": str(row.get("exchange") or "NSE").upper(),
                "quantity": Decimal(str(row.get("quantity") or 0)),
                "price": Decimal(str(row.get("average_price") or row.get("price") or 0)),
                "side": str(row.get("transaction_type") or row.get("trade_type") or "").upper(),
                "filled_at": row.get("fill_timestamp") or row.get("order_timestamp"),
                "order_id": str(row.get("order_id") or ""),
            }
        )
    return fills


def parse_ltp_map(raw: dict) -> dict[str, Decimal]:
    """Map 'NSE:INFY' -> last price from Kite ltp() payload."""
    prices: dict[str, Decimal] = {}
    for key, payload in (raw or {}).items():
        last = None
        if isinstance(payload, dict):
            last = payload.get("last_price")
        elif payload is not None:
            last = payload
        if last is None:
            continue
        prices[str(key).upper()] = Decimal(str(last))
    return prices
