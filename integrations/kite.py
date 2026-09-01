"""Zerodha Kite Connect client with env placeholders."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from trades.models import KiteSession

PLACEHOLDER_API_KEY = "your_api_key_here"


class KiteNotConfigured(RuntimeError):
    pass


class KiteClient:
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
        if not self.is_configured():
            raise KiteNotConfigured("Set KITE_API_KEY and KITE_API_SECRET in .env")
        kite = self._connect()
        data = kite.generate_session(request_token, api_secret=self.api_secret)
        return data

    def holdings(self, access_token: str) -> list[dict]:
        if not self.is_configured():
            return []
        return self._connect(access_token).holdings() or []

    def ltp(self, access_token: str, instruments: list[str]) -> dict:
        if not self.is_configured() or not instruments:
            return {}
        return self._connect(access_token).ltp(instruments) or {}

    def trades(self, access_token: str) -> list[dict]:
        if not self.is_configured():
            return []
        return self._connect(access_token).trades() or []

    def orders(self, access_token: str) -> list[dict]:
        if not self.is_configured():
            return []
        return self._connect(access_token).orders() or []


def latest_access_token() -> str | None:
    session = KiteSession.objects.order_by("-login_time").first()
    return session.access_token if session else None


def parse_holdings(raw: list[dict]) -> list[dict]:
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
