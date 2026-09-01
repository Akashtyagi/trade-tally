"""Core-feature tests: periodic fetch, net P/L, notifications.

These assert stable behaviour, not copy, CSS, or exact alert enums.
Adding columns or UI chrome should not require changes here.
"""

from __future__ import annotations

import json
from decimal import Decimal
from io import StringIO

import pytest
import responses
from django.core.management import call_command

from integrations.checker import evaluate_open_trades, run_checks
from integrations.scheduler import scheduled_check
from integrations.telegram import send_message
from trades.models import TradeStatus
from trades.services import close_trade, dashboard_stats

PNL_KEYS = {"total_trades", "total_invested", "realized_pnl", "unrealized_pnl", "net_pnl"}


@pytest.fixture
def market_open(monkeypatch):
    monkeypatch.setattr("integrations.checker.within_market_hours", lambda now=None: True)


@pytest.fixture
def market_closed(monkeypatch):
    monkeypatch.setattr("integrations.checker.within_market_hours", lambda now=None: False)


def _stub_fetch(monkeypatch, calls):
    monkeypatch.setattr(
        "integrations.checker.sheets_mod.sync_from_sheet",
        lambda: calls.append("sheet") or [],
    )
    monkeypatch.setattr(
        "integrations.checker.refresh_holdings_and_prices",
        lambda: calls.append("prices") or {},
    )


# --- Periodic data fetch -------------------------------------------------


@pytest.mark.django_db
def test_periodic_check_loads_sheet_and_prices_in_session(market_open, monkeypatch):
    calls = []
    _stub_fetch(monkeypatch, calls)
    result = run_checks()
    assert "sheet" in calls
    assert "prices" in calls
    assert "skipped" not in result
    assert "synced" in result
    assert "alerts" in result


@pytest.mark.django_db
def test_periodic_check_does_not_fetch_off_session(market_closed, monkeypatch):
    calls = []
    _stub_fetch(monkeypatch, calls)
    result = run_checks()
    assert calls == []
    assert result.get("skipped")


@pytest.mark.django_db
def test_periodic_check_can_be_forced_off_session(market_closed, monkeypatch):
    calls = []
    _stub_fetch(monkeypatch, calls)
    result = run_checks(force=True)
    assert "sheet" in calls
    assert "skipped" not in result


@pytest.mark.django_db
def test_management_command_is_the_cron_entry(market_closed, monkeypatch):
    """Host cron / podman exec call this command."""
    monkeypatch.setattr(
        "integrations.management.commands.run_checks.run_checks",
        lambda **kwargs: {"synced": 0, "alerts": 0, "skipped": "outside_market_hours"},
    )
    buf = StringIO()
    call_command("run_checks", stdout=buf)
    assert "skip" in buf.getvalue().lower()


@pytest.mark.django_db
def test_cron_webhook_triggers_the_same_check(client, settings, market_closed):
    settings.CRON_SECRET = "cron-secret"
    response = client.post("/internal/run-checks", HTTP_X_CRON_SECRET="cron-secret")
    assert response.status_code == 200
    body = response.json()
    assert body.get("ok") is True
    assert body.get("skipped")


def test_in_process_scheduler_does_not_run_off_hours(monkeypatch):
    ran = []
    monkeypatch.setattr("integrations.scheduler.within_market_hours", lambda: False)
    monkeypatch.setattr("integrations.scheduler.run_checks", lambda: ran.append(True))
    scheduled_check()
    assert ran == []


def test_in_process_scheduler_runs_in_session(monkeypatch):
    ran = []
    monkeypatch.setattr("integrations.scheduler.within_market_hours", lambda: True)
    monkeypatch.setattr("integrations.scheduler.run_checks", lambda: ran.append(True))
    scheduled_check()
    assert ran == [True]


# --- Net profit / loss ---------------------------------------------------


@pytest.mark.django_db
def test_pnl_stats_have_stable_keys_and_identity(trade):
    trade.last_ltp = Decimal("1460")
    trade.save()
    stats = dashboard_stats([trade])
    assert PNL_KEYS <= stats.keys()
    assert stats["total_trades"] >= 1
    assert stats["net_pnl"] == stats["realized_pnl"] + stats["unrealized_pnl"]


@pytest.mark.django_db
def test_empty_book_has_zero_net_pnl():
    stats = dashboard_stats([])
    assert stats["total_trades"] == 0
    assert stats["net_pnl"] == 0
    assert stats["realized_pnl"] == 0


@pytest.mark.django_db
def test_closing_a_trade_changes_realized_and_net(trade, monkeypatch):
    monkeypatch.setattr("integrations.sheets.write_close", lambda *a, **k: None)
    before = dashboard_stats([trade])
    close_trade(trade, Decimal("10"), Decimal("1600"), writeback=False)
    trade.refresh_from_db()
    after = dashboard_stats([trade])
    assert after["realized_pnl"] != before["realized_pnl"]
    assert after["net_pnl"] == after["realized_pnl"] + after["unrealized_pnl"]


@pytest.mark.django_db
def test_dashboard_exposes_net_pnl_to_the_ui(client, trade):
    trade.last_ltp = Decimal("1460")
    trade.holding_avg_price = Decimal("1450")
    trade.save()
    response = client.get("/")
    assert response.status_code == 200
    stats = response.context["stats"]
    assert PNL_KEYS <= stats.keys()
    assert stats["net_pnl"] == stats["realized_pnl"] + stats["unrealized_pnl"]
    html = response.content.decode()
    # Show the number somewhere; do not assert labels or CSS.
    assert f"{stats['net_pnl']:.2f}" in html or str(int(stats["net_pnl"])) in html


@pytest.mark.django_db
def test_closed_trade_is_marked_profit_or_loss(trade, monkeypatch):
    monkeypatch.setattr("integrations.sheets.write_close", lambda *a, **k: None)
    close_trade(trade, trade.remaining_qty, Decimal("1600"), writeback=False)
    trade.refresh_from_db()
    assert trade.status == TradeStatus.CLOSED
    assert trade.row_tone() in {"profit", "loss"}


# --- Notifications -------------------------------------------------------


@pytest.mark.django_db
def test_underheld_position_in_buy_range_notifies(trade):
    trade.holding_qty = Decimal("5")
    trade.last_ltp = Decimal("1450")
    trade.save()
    inbox = []
    created = evaluate_open_trades(send=inbox.append)
    assert created
    assert inbox
    assert all(isinstance(msg, str) and msg for msg in inbox)
    assert trade.symbol in inbox[0]


@pytest.mark.django_db
def test_price_at_or_above_target_notifies_when_held(trade):
    trade.holding_qty = Decimal("50")
    trade.last_ltp = Decimal("1750")
    trade.save()
    inbox = []
    created = evaluate_open_trades(send=inbox.append)
    assert created
    assert inbox
    assert trade.symbol in inbox[0]


@pytest.mark.django_db
def test_fully_held_mid_price_does_not_notify(trade):
    trade.holding_qty = Decimal("50")
    trade.last_ltp = Decimal("1600")
    trade.save()
    inbox = []
    assert evaluate_open_trades(send=inbox.append) == []
    assert inbox == []


@pytest.mark.django_db
def test_closed_trade_does_not_notify(trade):
    trade.status = TradeStatus.CLOSED
    trade.holding_qty = Decimal("50")
    trade.last_ltp = Decimal("1750")
    trade.save()
    inbox = []
    assert evaluate_open_trades(send=inbox.append) == []


@pytest.mark.django_db
def test_same_alert_is_not_sent_twice_in_one_day(trade):
    trade.holding_qty = Decimal("5")
    trade.last_ltp = Decimal("1450")
    trade.save()
    inbox = []
    first = evaluate_open_trades(send=inbox.append)
    second = evaluate_open_trades(send=inbox.append)
    assert first
    assert second == []
    assert len(inbox) == len(first)


def test_telegram_is_silent_without_credentials(settings):
    settings.TELEGRAM_BOT_TOKEN = "your_telegram_bot_token_here"
    settings.TELEGRAM_CHAT_ID = ""
    assert send_message("should not go out") is False


@responses.activate
def test_telegram_delivers_when_configured(settings):
    settings.TELEGRAM_BOT_TOKEN = "123:test-token"
    settings.TELEGRAM_CHAT_ID = "42"
    responses.add(
        responses.POST,
        "https://api.telegram.org/bot123:test-token/sendMessage",
        json={"ok": True},
        status=200,
    )
    assert send_message("buy INFY") is True
    assert len(responses.calls) == 1
    payload = json.loads(responses.calls[0].request.body)
    assert str(payload["chat_id"]) == "42"
    assert payload["text"]
