from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from integrations.kite import KiteClient, KiteNotConfigured
from trades.forms import AppConfigForm, CloseTradeForm, telegram_token_configured
from trades.models import AppSettings, KiteFill, KiteSession, TradeIdea, TradeStatus
from trades.services import close_trade, dashboard_stats


def dashboard(request):
    trades = list(TradeIdea.objects.all().prefetch_related("close_events"))
    session = KiteSession.objects.order_by("-login_time").first()
    kite = KiteClient()
    cfg = AppSettings.load()
    context = {
        "trades": trades,
        "stats": dashboard_stats(trades),
        "close_form": CloseTradeForm(),
        "kite_configured": kite.is_configured(),
        "kite_session": session,
        "open_count": sum(1 for t in trades if t.status != TradeStatus.CLOSED),
        "app_settings": cfg,
    }
    return render(request, "trades/dashboard.html", context)


def trade_detail(request, pk: int):
    trade = get_object_or_404(
        TradeIdea.objects.prefetch_related("close_events", "alerts"),
        pk=pk,
    )
    fills = KiteFill.objects.filter(symbol=trade.symbol)
    return render(
        request,
        "trades/detail.html",
        {
            "trade": trade,
            "fills": fills,
            "close_form": CloseTradeForm(trade=trade),
        },
    )


def config_view(request):
    cfg = AppSettings.load()
    if request.method == "POST":
        form = AppConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            form.save()
            messages.success(request, "Config saved. Secrets (bot token, Kite keys, Google credentials) stay in .env.")
            return redirect("app_config")
        messages.error(request, "Could not save config. Check the fields below.")
    else:
        form = AppConfigForm(instance=cfg)
    return render(
        request,
        "trades/config.html",
        {
            "form": form,
            "telegram_token_ok": telegram_token_configured(),
            "app_settings": cfg,
        },
    )


@require_http_methods(["POST"])
def close_trade_view(request, pk: int):
    trade = get_object_or_404(TradeIdea, pk=pk)
    form = CloseTradeForm(request.POST, trade=trade)
    go_detail = request.POST.get("next") == "detail"

    def bounce():
        if go_detail:
            return redirect("trade_detail", pk=trade.pk)
        return redirect("dashboard")

    if trade.status == TradeStatus.CLOSED:
        messages.error(request, f"{trade.symbol} is already closed.")
        return bounce()
    if not form.is_valid():
        messages.error(request, "; ".join(form.errors.as_text().splitlines()))
        return bounce()
    try:
        close_trade(trade, form.cleaned_data["quantity"], form.cleaned_data["price"])
    except Exception as exc:
        messages.error(request, f"Could not close {trade.symbol}: {exc}")
        return bounce()
    messages.success(
        request,
        f"Closed {form.cleaned_data['quantity']} {trade.symbol} @ {form.cleaned_data['price']}.",
    )
    return bounce()


@require_POST
def sync_sheet_view(request):
    """Manual sheet pull only — does not run Kite or send Telegram alerts."""
    from integrations.sheets import sync_from_sheet

    try:
        trades = sync_from_sheet()
        messages.success(request, f"Synced {len(trades)} sheet rows.")
    except Exception as exc:
        messages.error(request, f"Sheet sync failed: {exc}")
    nxt = request.POST.get("next")
    if nxt == "config":
        return redirect("app_config")
    return redirect("dashboard")


@require_POST
def zerodha_sync_view(request):
    """Button-only: pull Kite holdings / today's fills and write latest values to the sheet."""
    from integrations.zerodha_sync import sync_zerodha

    try:
        result = sync_zerodha()
        messages.success(
            request,
            "Zerodha sync updated "
            f"{result['trades_updated']} trades "
            f"({result['fills']} fills, {result['sheet_cells']} sheet cells). "
            "Kite only returns today's executed trades; holdings still refresh latest qty and P/L.",
        )
    except KiteNotConfigured as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        messages.error(request, f"Zerodha sync failed: {exc}")
    return redirect("dashboard")


def kite_login(request):
    client = KiteClient()
    if not client.is_configured():
        messages.error(request, "Set KITE_API_KEY in .env before connecting Kite.")
        return redirect("dashboard")
    return redirect(client.login_url())


def kite_callback(request):
    request_token = request.GET.get("request_token")
    status = request.GET.get("status")
    if status and status != "success":
        messages.error(request, "Kite login was not successful.")
        return redirect("dashboard")
    if not request_token:
        messages.error(request, "Kite callback is missing request_token.")
        return redirect("dashboard")
    try:
        data = KiteClient().exchange_request_token(request_token)
    except KiteNotConfigured as exc:
        messages.error(request, str(exc))
        return redirect("dashboard")
    except Exception as exc:
        messages.error(request, f"Could not exchange Kite token: {exc}")
        return redirect("dashboard")
    access_token = data.get("access_token") if isinstance(data, dict) else data
    KiteSession.objects.create(
        access_token=access_token,
        request_token=request_token,
        login_time=timezone.now(),
    )
    messages.success(request, "Kite connected. Use Zerodha sync to refresh holdings into the sheet.")
    return redirect("dashboard")
