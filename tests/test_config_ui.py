from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from integrations.kite import parse_fills
from integrations.sheets import parse_date, parse_portfolio_config, parse_rows
from trades.models import (
    AppSettings,
    KiteFill,
    KiteSession,
    TRADE_COLUMN_FIELDS,
    SUMMARY_CELL_FIELDS,
)
from trades.services import format_holding_age


def test_format_holding_age_units():
    today = date(2026, 8, 31)
    assert format_holding_age(None, today=today) == "—"
    assert format_holding_age(today, today=today) == "today"
    assert format_holding_age(today - timedelta(days=3), today=today) == "3 days"
    assert "week" in format_holding_age(today - timedelta(days=10), today=today)
    assert "month" in format_holding_age(today - timedelta(days=40), today=today)
    assert "year" in format_holding_age(today - timedelta(days=400), today=today)


def test_parse_date_and_opened_on():
    assert parse_date("7-Aug-2024") == date(2024, 8, 7)
    assert parse_date("4-Sept-2024") == date(2024, 9, 4)
    rows = parse_rows(
        [
            ["Share", "Date", "Minimum Shares Recom.", "Current Quantity"],
            ["ABDL", "6-Aug-2024", "59", "15"],
        ]
    )
    assert rows[0]["opened_on"] == date(2024, 8, 6)


def test_summary_map_cells():
    values = [
        ["", ""],
        ["max allocation", "8%"],
        ["", ""],
        ["", ""],
        ["1200000", ""],
    ]
    cfg = parse_portfolio_config(values, {"corpus": "A5", "risk_percentage": "B2"})
    assert cfg["total_budget"] == Decimal("1200000")
    assert cfg["risk_percentage"] == Decimal("8")


def test_parse_fills():
    fills = parse_fills(
        [
            {
                "tradingsymbol": "infy",
                "exchange": "NSE",
                "quantity": 10,
                "average_price": 1500,
                "transaction_type": "BUY",
                "order_id": "1",
            }
        ]
    )
    assert fills[0]["symbol"] == "INFY"
    assert fills[0]["quantity"] == Decimal("10")
    assert fills[0]["side"] == "BUY"


@pytest.mark.django_db
def test_config_get_is_separate_view(client):
    response = client.get(reverse("app_config"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Telegram" in html
    assert "Google Sheet" in html
    assert "Column mapping" in html
    assert "Current quantity" in html


@pytest.mark.django_db
def test_config_post_saves_telegram_and_sheet_mapping(client):
    AppSettings.load()
    payload = {
        "telegram_chat_id": "4242",
        "telegram_alerts_enabled": "on",
        "google_spreadsheet_id": "sheet-abc",
        "google_worksheet": "Aug24-27",
        "col_symbol": "Share",
        "col_current_qty": "Current Quantity",
        "col_current_pnl": "Current P/L",
        "sum_corpus": "A5",
        "sum_risk_percentage": "B2",
        "sum_current_value": "N2",
        "sum_remaining_balance": "K2",
    }
    for key, _label in TRADE_COLUMN_FIELDS:
        payload.setdefault(f"col_{key}", "")
    for key, _label in SUMMARY_CELL_FIELDS:
        payload.setdefault(f"sum_{key}", "")
    response = client.post(reverse("app_config"), payload)
    assert response.status_code == 302
    cfg = AppSettings.load()
    assert cfg.telegram_chat_id == "4242"
    assert cfg.google_spreadsheet_id == "sheet-abc"
    assert cfg.google_worksheet == "Aug24-27"
    assert cfg.column_map["symbol"] == "Share"
    assert cfg.column_map["current_qty"] == "Current Quantity"
    assert cfg.summary_map["corpus"] == "A5"


@pytest.mark.django_db
def test_dashboard_shows_holding_duration(client, trade):
    trade.opened_on = timezone.localdate() - timedelta(days=400)
    trade.save()
    response = client.get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "Active for" in html
    assert "year" in html
    assert reverse("trade_detail", args=[trade.pk]) in html


@pytest.mark.django_db
def test_trade_detail_view(client, trade):
    response = client.get(reverse("trade_detail", args=[trade.pk]))
    assert response.status_code == 200
    html = response.content.decode()
    assert "INFY" in html
    assert "Plan" in html
    assert trade.holding_age() in html


@pytest.mark.django_db
def test_sheet_sync_button_does_not_run_alerts(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "integrations.sheets.sync_from_sheet",
        lambda: calls.append("sheet") or [],
    )
    monkeypatch.setattr(
        "integrations.checker.run_checks",
        lambda **kwargs: calls.append("checks") or {"synced": 0, "alerts": 0},
    )
    response = client.post(reverse("sync_sheet"))
    assert response.status_code == 302
    assert calls == ["sheet"]


@pytest.mark.django_db
def test_zerodha_sync_updates_trade_and_sheet(trade, monkeypatch):
    KiteSession.objects.create(access_token="tok")
    writes = []

    class FakeClient:
        def holdings(self, token):
            return [
                {
                    "tradingsymbol": "INFY",
                    "exchange": "NSE",
                    "quantity": 40,
                    "average_price": 1450,
                    "last_price": 1500,
                }
            ]

        def trades(self, token):
            return [
                {
                    "tradingsymbol": "INFY",
                    "exchange": "NSE",
                    "quantity": 10,
                    "average_price": 1500,
                    "transaction_type": "BUY",
                    "order_id": "99",
                }
            ]

        def ltp(self, token, instruments):
            return {"NSE:INFY": {"last_price": 1510}}

    monkeypatch.setattr("integrations.zerodha_sync.KiteClient", FakeClient)
    monkeypatch.setattr(
        "integrations.zerodha_sync.write_mapped_payload",
        lambda synced_trade, payload: writes.append(payload) or [{"range": "P7"}],
    )
    from integrations.zerodha_sync import sync_zerodha

    result = sync_zerodha()
    trade.refresh_from_db()
    assert result["trades_updated"] == 1
    assert result["fills"] == 1
    assert trade.holding_qty == Decimal("40")
    assert trade.last_ltp == Decimal("1510")
    assert writes[0]["current_qty"] == "40"
    assert "current_pnl" in writes[0]
    assert KiteFill.objects.filter(symbol="INFY").count() == 1
    assert AppSettings.load().last_zerodha_sync_at is not None


@pytest.mark.django_db
def test_zerodha_sync_view_is_button_only(client, monkeypatch):
    monkeypatch.setattr(
        "integrations.zerodha_sync.sync_zerodha",
        lambda: {"trades_updated": 1, "fills": 2, "sheet_cells": 3, "holdings": 1},
    )
    with patch("integrations.checker.run_checks") as checks:
        response = client.post(reverse("zerodha_sync"))
    assert response.status_code == 302
    checks.assert_not_called()
