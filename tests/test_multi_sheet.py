"""Primary vs secondary sheet isolation for cron and dashboards."""

from decimal import Decimal

import pytest
from django.urls import reverse

from integrations.checker import evaluate_open_trades, run_checks
from trades.models import TradeIdea, TradeStatus
from trades.sheet_config import list_sheets, primary_slug, upsert_sheet


def _other_trade():
    return TradeIdea.objects.create(
        sheet_row=2,
        symbol="RELIANCE",
        exchange="NSE",
        recommended_qty=Decimal("10"),
        remaining_qty=Decimal("10"),
        buy_low=Decimal("2800"),
        buy_high=Decimal("2900"),
        target=Decimal("3100"),
        stop_loss=Decimal("2700"),
        status=TradeStatus.OPEN,
        sheet_slug="fy26",
        last_ltp=Decimal("3200"),
        holding_qty=Decimal("10"),
    )


@pytest.mark.django_db
def test_landing_shows_only_primary_trades(client, trade):
    trade.holding_qty = Decimal("10")
    trade.save()
    upsert_sheet({"slug": "fy26", "worksheet": "FY26", "label": "FY26"})
    other = _other_trade()
    response = client.get("/")
    html = response.content.decode()
    assert b"INFY" in response.content
    assert "RELIANCE" not in html
    assert "Aug24-27" in html
    assert "Primary" in html
    assert reverse("sheet_dashboard", args=["fy26"]) in html or "/s/fy26/" in html
    assert other.symbol not in html


@pytest.mark.django_db
def test_other_sheet_dashboard_is_isolated(client, trade):
    upsert_sheet({"slug": "fy26", "worksheet": "FY26", "label": "FY26"})
    _other_trade()
    response = client.get(reverse("sheet_dashboard", args=["fy26"]))
    html = response.content.decode()
    assert response.status_code == 200
    assert "RELIANCE" in html
    assert "INFY" not in html
    assert "FY26" in html


@pytest.mark.django_db
def test_primary_sheet_url_redirects_to_landing(client):
    response = client.get(reverse("sheet_dashboard", args=["aug24-27"]))
    assert response.status_code == 302
    assert response.url == "/"


@pytest.mark.django_db
def test_set_primary_toggle_changes_landing(client, trade):
    upsert_sheet({"slug": "fy26", "worksheet": "FY26", "label": "FY26"})
    _other_trade()
    response = client.post(reverse("set_primary", args=["fy26"]))
    assert response.status_code == 302
    assert primary_slug() == "fy26"
    landing = client.get("/")
    html = landing.content.decode()
    assert "RELIANCE" in html
    assert "INFY" not in html
    assert landing.context["is_primary_sheet"] is True


@pytest.mark.django_db
def test_add_sheet_from_config(client):
    response = client.post(
        reverse("app_config"),
        {
            "action": "add_sheet",
            "worksheet": "FY26",
            "label": "Year 26",
            "spreadsheet_id": "",
        },
    )
    assert response.status_code == 302
    slugs = {s["slug"] for s in list_sheets()}
    assert "fy26" in slugs
    assert primary_slug() == "aug24-27"


@pytest.mark.django_db
def test_same_symbol_can_exist_on_two_sheets(trade):
    other = TradeIdea.objects.create(
        sheet_row=2,
        symbol="INFY",
        exchange="NSE",
        recommended_qty=Decimal("5"),
        remaining_qty=Decimal("5"),
        buy_low=Decimal("1400"),
        buy_high=Decimal("1500"),
        target=Decimal("1700"),
        stop_loss=Decimal("1300"),
        status=TradeStatus.OPEN,
        sheet_slug="fy26",
    )
    assert TradeIdea.objects.filter(symbol="INFY").count() == 2
    assert other.pk != trade.pk


@pytest.mark.django_db
def test_cron_syncs_only_primary_sheet(market_open, monkeypatch, trade):
    upsert_sheet({"slug": "fy26", "worksheet": "FY26", "label": "FY26"})
    _other_trade()
    synced = []
    monkeypatch.setattr(
        "integrations.checker.sheets_mod.sync_from_sheet",
        lambda *a, **k: synced.append(k.get("slug")) or [],
    )
    monkeypatch.setattr("integrations.checker.refresh_holdings_and_prices", lambda **k: {})
    inbox = []
    run_checks(send=inbox.append)
    assert synced == ["aug24-27"]
    assert inbox == []


@pytest.mark.django_db
def test_cron_does_not_alert_non_primary_trades(trade):
    trade.holding_qty = Decimal("5")
    trade.last_ltp = Decimal("1450")
    trade.save()
    upsert_sheet({"slug": "fy26", "worksheet": "FY26", "label": "FY26"})
    other = _other_trade()
    inbox = []
    created = evaluate_open_trades(send=inbox.append, sheet_slug=primary_slug())
    assert created
    assert all(log.trade_id == trade.id for log in created)
    assert other.symbol not in "".join(inbox)


@pytest.mark.django_db
def test_sheet_sync_posts_to_named_sheet(client, monkeypatch):
    upsert_sheet({"slug": "fy26", "worksheet": "FY26", "label": "FY26"})
    slugs = []
    monkeypatch.setattr(
        "integrations.sheets.sync_from_sheet",
        lambda *a, **k: slugs.append(k.get("slug")) or [],
    )
    response = client.post(reverse("sync_sheet_for", args=["fy26"]))
    assert response.status_code == 302
    assert slugs == ["fy26"]
    assert response.url == "/s/fy26/"
