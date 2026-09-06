"""Dashboard listing, unique-symbol rows, and LTP snapshot fill."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from trades.models import TradeStatus


@pytest.mark.django_db
def test_dashboard_hides_removed_stat_cards(client, trade):
    response = client.get("/")
    html = response.content.decode()
    assert "Risk %" not in html
    assert "Remaining balance" not in html
    assert "Current value" not in html
    assert "Net P/L" not in html
    assert "NSE · row" not in html
    assert "Realized P/L" in html
    assert "Manage sheets" in html
    assert "display: none !important" in html
    assert "pnl-pos" in html
    assert ">Status<" not in html
    assert ">Close<" not in html
    assert "closeModal" not in html


@pytest.mark.django_db
def test_dashboard_dedupes_open_and_completed_rows(client, db):
    from integrations.sheets import COMPLETED_ROW_OFFSET
    from trades.models import TradeIdea, TradeStatus

    TradeIdea.objects.create(
        sheet_row=10,
        symbol="PENIND",
        recommended_qty=100,
        remaining_qty=50,
        holding_qty=50,
        status=TradeStatus.OPEN,
        sheet_slug="aug24-27",
    )
    TradeIdea.objects.create(
        sheet_row=10 + COMPLETED_ROW_OFFSET,
        symbol="PENIND",
        recommended_qty=30,
        remaining_qty=0,
        status=TradeStatus.CLOSED,
        sheet_slug="aug24-27",
    )
    html = client.get("/").content.decode()
    assert html.count(">PENIND<") == 1


@pytest.mark.django_db
def test_dashboard_keeps_one_row_when_two_open_copies_exist(client, db):
    from trades.models import TradeIdea, TradeStatus

    TradeIdea.objects.create(
        sheet_row=12,
        symbol="GENESYS",
        recommended_qty=40,
        remaining_qty=0,
        holding_qty=0,
        status=TradeStatus.OPEN,
        sheet_slug="aug24-27",
    )
    TradeIdea.objects.create(
        sheet_row=40,
        symbol="GENESYS",
        recommended_qty=40,
        remaining_qty=11,
        holding_qty=11,
        status=TradeStatus.OPEN,
        sheet_slug="aug24-27",
    )
    html = client.get("/").content.decode()
    assert html.count(">GENESYS<") == 1
    assert "11" in html


@pytest.mark.django_db
def test_holding_age_uses_first_tradebook_buy(trade):
    from datetime import date, timedelta

    from trades.models import TradebookFill

    TradebookFill.objects.create(
        uid="buy-1",
        symbol="INFY",
        side="BUY",
        quantity=10,
        price=1400,
        trade_date=date.today() - timedelta(days=10),
    )
    trade.opened_on = date.today()
    trade.save()
    assert "week" in trade.holding_age()


@pytest.mark.django_db
def test_plan_held_is_green_when_underweight_in_buy_zone(client, trade):
    trade.holding_qty = Decimal("10")
    trade.recommended_qty = Decimal("50")
    trade.last_ltp = Decimal("1450")
    trade.buy_low = Decimal("1400")
    trade.buy_high = Decimal("1500")
    trade.save()
    html = client.get("/").content.decode()
    assert "buy-ready" in html
    assert "in-buy-range" in html


@pytest.mark.django_db
def test_plan_held_in_buy_range_gets_yellow_cell_class(client, trade):
    trade.holding_qty = Decimal("7")
    trade.recommended_qty = Decimal("103")
    trade.last_ltp = Decimal("1450")
    trade.buy_low = Decimal("1400")
    trade.buy_high = Decimal("1500")
    trade.save()
    html = client.get("/").content.decode()
    assert 'class="in-buy-range buy-ready"' in html


@pytest.mark.django_db
def test_plan_held_is_yellow_when_ltp_within_200_of_buy_range(client, trade):
    trade.holding_qty = Decimal("10")
    trade.last_ltp = Decimal("1650")
    trade.buy_low = Decimal("1400")
    trade.buy_high = Decimal("1500")
    trade.save()
    html = client.get("/").content.decode()
    assert "near-buy" in html
    assert 'class="near-buy "' in html or 'class="near-buy"' in html
    assert "buy-ready" not in html.split("Plan / held", 1)[-1].split("</tbody>", 1)[0]


@pytest.mark.django_db
def test_dashboard_hides_unheld_names_outside_buy_range(client, trade):
    trade.holding_qty = Decimal("0")
    trade.last_ltp = Decimal("2000")
    trade.buy_low = Decimal("1400")
    trade.buy_high = Decimal("1500")
    trade.save()
    response = client.get("/")
    assert trade not in response.context["trades"]
    assert trade in response.context["idle_trades"]
    html = response.content.decode()
    assert "Closed &amp; unheld" in html
    assert ">INFY<" in html
    live = html.split('id="active-trades"', 1)[1].split('id="idle-trades"', 1)[0]
    assert ">INFY<" not in live


@pytest.mark.django_db
def test_dashboard_shows_unheld_name_when_ltp_in_buy_range(client, trade):
    trade.holding_qty = Decimal("0")
    trade.last_ltp = Decimal("1450")
    trade.save()
    response = client.get("/")
    assert trade in response.context["trades"]
    assert trade not in response.context["idle_trades"]
    html = response.content.decode()
    assert ">INFY<" in html


@pytest.mark.django_db
def test_dashboard_lists_closed_trades_in_collapsed_section(client, trade):
    trade.status = TradeStatus.CLOSED
    trade.holding_qty = Decimal("0")
    trade.last_ltp = Decimal("1450")
    trade.save()
    response = client.get("/")
    assert trade not in response.context["trades"]
    assert trade in response.context["idle_trades"]
    html = response.content.decode()
    assert 'id="idle-trades"' in html
    assert ">INFY<" in html
    live = html.split('id="active-trades"', 1)[1].split('id="idle-trades"', 1)[0]
    assert ">INFY<" not in live


@pytest.mark.django_db
def test_zero_stop_and_target_render_as_dash(client, trade):
    trade.stop_loss = Decimal("0")
    trade.target = Decimal("0")
    trade.last_ltp = Decimal("1450")
    trade.save()
    html = client.get("/").content.decode()
    assert "₹1,400.0" in html
    assert html.count("—") >= 2


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
