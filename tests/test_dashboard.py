from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from trades.models import TradeStatus


@pytest.mark.django_db
def test_dashboard_is_public(client, trade):
    response = client.get("/")
    assert response.status_code == 200
    assert b"INFY" in response.content


@pytest.mark.django_db
def test_dashboard_shows_stats(client, trade):
    trade.last_ltp = Decimal("1460")
    trade.save()
    response = client.get("/")
    assert response.status_code == 200
    stats = response.context["stats"]
    assert stats["total_trades"] >= 1
    assert "net_pnl" in stats


@pytest.mark.django_db
def test_close_trade_view_partial(client, trade):
    with patch("trades.views.close_trade") as mocked:
        from trades.services import close_trade as real_close

        def wrapper(*args, **kwargs):
            return real_close(*args, writeback=False)

        mocked.side_effect = wrapper
        response = client.post(
            reverse("close_trade", args=[trade.pk]),
            {"quantity": "20", "price": "1550"},
        )
    assert response.status_code == 302
    trade.refresh_from_db()
    assert trade.status == TradeStatus.PARTIAL
    assert trade.remaining_qty == Decimal("30")


@pytest.mark.django_db
def test_webhook_rejects_bad_secret(client, settings):
    settings.CRON_SECRET = "expected-secret"
    response = client.post("/internal/run-checks", HTTP_X_CRON_SECRET="nope")
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_runs_checks(client, settings):
    settings.CRON_SECRET = "expected-secret"
    with patch("integrations.views.run_checks", return_value={"synced": 2, "alerts": 1}):
        response = client.post("/internal/run-checks", HTTP_X_CRON_SECRET="expected-secret")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["synced"] == 2
