"""Shared fixtures: isolated sheets.json, market hours, sample TradeIdea."""

import json
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from trades.models import TradeIdea, TradeStatus


@pytest.fixture(autouse=True)
def sheets_config_file(tmp_path, settings):
    path = tmp_path / "sheets.json"
    settings.SHEETS_CONFIG_PATH = str(path)
    path.write_text(
        json.dumps(
            {
                "primary": "aug24-27",
                "sheets": [
                    {
                        "slug": "aug24-27",
                        "label": "Aug24-27",
                        "worksheet": "Aug24-27",
                        "spreadsheet_id": "",
                        "column_map": {"symbol": "Share"},
                        "summary_map": {"corpus": "A5"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def market_open(monkeypatch):
    monkeypatch.setattr("integrations.checker.within_market_hours", lambda now=None: True)


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
        sheet_slug="aug24-27",
    )
