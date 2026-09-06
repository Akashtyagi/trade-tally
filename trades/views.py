"""Browser UI: dashboards, config, Kite login, sheet / Zerodha sync buttons."""

from django.db.models import Case, IntegerField, Value, When
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from integrations.kite import KiteClient, KiteNotConfigured, is_permission_error
from trades.forms import (
    AddSheetForm,
    AppConfigForm,
    CloseTradeForm,
    sheets_from_post,
    telegram_token_configured,
)
from trades.models import (
    SUMMARY_CELL_FIELDS,
    TRADE_COLUMN_FIELDS,
    AppSettings,
    KiteFill,
    KiteSession,
    TradebookFill,
    TradeIdea,
    TradeStatus,
)
from trades.services import close_trade, dashboard_stats, delete_trade, unique_dashboard_trades, apply_snapshot_ltp
from trades.sheet_config import (
    delete_sheet,
    get_primary,
    get_sheet,
    list_sheets,
    primary_slug,
    replace_sheets,
    set_primary,
    unique_slug,
    upsert_sheet,
)


def _sheet_or_404(slug: str | None):
    sheet = get_primary() if not slug else get_sheet(slug)
    if sheet is None:
        raise Http404("Unknown sheet")
    return sheet


def _home(slug: str | None = None):
    """Primary tab lives at /; other tabs at /s/<slug>/."""
    want = slug or primary_slug()
    if want == primary_slug():
        return redirect("dashboard")
    return redirect("sheet_dashboard", sheet_slug=want)


def dashboard(request, sheet_slug: str | None = None):
    if sheet_slug and sheet_slug == primary_slug():
        return redirect("dashboard")
    sheet = _sheet_or_404(sheet_slug)
    sort = request.GET.get("sort") or "position"
    if sort not in {"symbol", "position"}:
        sort = "position"
    position = (request.GET.get("position") or "").upper()
    trades_qs = TradeIdea.objects.filter(sheet_slug=sheet["slug"]).prefetch_related("close_events")
    if position in TradeStatus.values:
        trades_qs = trades_qs.filter(status=position)
    if sort == "symbol":
        trades_qs = trades_qs.order_by("symbol")
    else:
        trades_qs = trades_qs.annotate(
            _pos=Case(
                When(status=TradeStatus.OPEN, then=Value(0)),
                When(status=TradeStatus.PARTIAL, then=Value(1)),
                When(status=TradeStatus.CLOSED, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        ).order_by("_pos", "symbol")
    # Same ticker can appear on the open block and completed block — keep one row.
    trades = unique_dashboard_trades(list(trades_qs))
    apply_snapshot_ltp(trades)
    stats = dashboard_stats(trades)
    visible = [t for t in trades if t.dashboard_active()]
    idle = [t for t in trades if not t.dashboard_active()]
    session = KiteSession.objects.order_by("-login_time").first()
    kite = KiteClient()
    cfg = AppSettings.load()
    context = {
        "trades": visible,
        "idle_trades": idle,
        "stats": stats,
        "close_form": CloseTradeForm(),
        "kite_configured": kite.is_configured(),
        "kite_session": session,
        "app_settings": cfg,
        "sheet": sheet,
        "is_primary_sheet": sheet["slug"] == primary_slug(),
        "portfolio": sheet.get("portfolio") or {},
        "sort": sort,
        "position_filter": position if position in TradeStatus.values else "",
    }
    return render(request, "trades/dashboard.html", context)


def trade_detail(request, pk: int):
    trade = get_object_or_404(
        TradeIdea.objects.prefetch_related("close_events", "alerts"),
        pk=pk,
    )
    fills = KiteFill.objects.filter(symbol=trade.symbol)
    tradebook_fills = TradebookFill.objects.filter(symbol__iexact=trade.symbol)
    sheet = get_sheet(trade.sheet_slug)
    corpus = None
    if sheet:
        corpus = (sheet.get("portfolio") or {}).get("total_budget")
    tcp_percent = trade.tcp_display(corpus)
    return render(
        request,
        "trades/detail.html",
        {
            "trade": trade,
            "fills": fills,
            "tradebook_fills": tradebook_fills,
            "close_form": CloseTradeForm(trade=trade),
            "sheet": sheet,
            "tcp_percent": tcp_percent,
        },
    )


def config_view(request):
    cfg = AppSettings.load()
    if request.method == "POST":
        action = request.POST.get("action") or "save"
        if action == "add_sheet":
            add_form = AddSheetForm(request.POST)
            form = AppConfigForm(instance=cfg)
            if add_form.is_valid():
                worksheet = add_form.cleaned_data["worksheet"]
                slug = unique_slug(worksheet)
                upsert_sheet(
                    {
                        "slug": slug,
                        "worksheet": worksheet,
                        "label": add_form.cleaned_data["label"] or worksheet,
                        "spreadsheet_id": add_form.cleaned_data["spreadsheet_id"],
                    }
                )
                messages.success(request, f"Added dashboard for tab {worksheet}.")
                return redirect("app_config")
            messages.error(request, "Could not add that sheet. Check the tab name.")
        else:
            form = AppConfigForm(request.POST, instance=cfg)
            add_form = AddSheetForm()
            if form.is_valid():
                form.save()
                sheets, primary = sheets_from_post(request.POST)
                if not sheets:
                    messages.error(request, "Keep at least one sheet dashboard.")
                else:
                    if primary not in {s["slug"] for s in sheets}:
                        primary = sheets[0]["slug"]
                    replace_sheets(sheets, primary=primary)
                    messages.success(
                        request,
                        "Config saved. Secrets (bot token, Kite keys, Google credentials) stay in .env.",
                    )
                    return redirect("app_config")
            else:
                messages.error(request, "Could not save config. Check the fields below.")
    else:
        form = AppConfigForm(instance=cfg)
        add_form = AddSheetForm()
    sheets = list_sheets()
    return render(
        request,
        "trades/config.html",
        {
            "form": form,
            "add_form": add_form,
            "telegram_token_ok": telegram_token_configured(),
            "app_settings": cfg,
            "sheets": sheets,
            "primary_slug": primary_slug(),
            "column_fields": TRADE_COLUMN_FIELDS,
            "summary_fields": SUMMARY_CELL_FIELDS,
        },
    )


@require_POST
def set_primary_view(request, sheet_slug: str):
    try:
        set_primary(sheet_slug)
    except KeyError:
        messages.error(request, "Unknown sheet.")
        return redirect("dashboard")
    messages.success(request, f"{get_sheet(sheet_slug)['label']} is now the primary sheet. Cron uses this tab.")
    return redirect("dashboard")


@require_POST
def delete_sheet_view(request, sheet_slug: str):
    try:
        delete_sheet(sheet_slug)
        messages.success(request, "Sheet dashboard removed. Trades already synced for it stay in the database.")
    except (KeyError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("app_config")


@require_http_methods(["POST"])
def close_trade_view(request, pk: int):
    trade = get_object_or_404(TradeIdea, pk=pk)
    form = CloseTradeForm(request.POST, trade=trade)
    go_detail = request.POST.get("next") == "detail"

    def bounce():
        if go_detail:
            return redirect("trade_detail", pk=trade.pk)
        return _home(trade.sheet_slug)

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
def delete_trade_view(request, pk: int):
    trade = get_object_or_404(TradeIdea, pk=pk)
    slug = trade.sheet_slug
    symbol = trade.symbol
    try:
        delete_trade(trade)
    except Exception as exc:
        messages.error(request, f"Could not delete {symbol}: {exc}")
        return redirect("trade_detail", pk=pk)
    messages.success(request, f"Deleted {symbol} from the app and Google Sheet.")
    return _home(slug)


@require_POST
def sync_sheet_view(request, sheet_slug: str | None = None):
    """Manual sheet pull only — does not run Kite or send Telegram alerts."""
    from integrations.sheets import sync_from_sheet

    sheet = _sheet_or_404(sheet_slug)
    try:
        trades = sync_from_sheet(slug=sheet["slug"])
        messages.success(request, f"Synced {len(trades)} rows from {sheet['label']}.")
    except Exception as exc:
        messages.error(request, f"Sheet sync failed: {exc}")
    nxt = request.POST.get("next")
    if nxt == "config":
        return redirect("app_config")
    return _home(sheet["slug"])


@require_POST
def zerodha_sync_view(request, sheet_slug: str | None = None):
    """Button-only: pull Kite holdings and write qty / last_price to this sheet."""
    from integrations.zerodha_sync import sync_zerodha

    sheet = _sheet_or_404(sheet_slug)
    try:
        result = sync_zerodha(sheet_slug=sheet["slug"])
        messages.success(
            request,
            "Zerodha sync updated "
            f"{result['trades_updated']} trades on {sheet['label']} "
            f"({result['holdings']} holdings, {result['sheet_cells']} sheet cells). "
            "Qty and LTP come from Kite holdings last_price. Fills come from the tradebook worksheet.",
        )
    except KiteNotConfigured as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        if is_permission_error(exc):
            messages.error(
                request,
                "Zerodha sync failed: this Kite app is not allowed holdings(). "
                "Reconnect Kite if you just changed the API key. Original: "
                f"{exc}",
            )
        else:
            messages.error(request, f"Zerodha sync failed: {exc}")
    return _home(sheet["slug"])


def kite_login(request):
    client = KiteClient()
    if not client.is_configured():
        messages.error(request, "Set KITE_API_KEY in .env before connecting Kite.")
        return redirect("dashboard")
    return redirect(client.login_url())


def kite_callback(request):
    """Kite redirects here with request_token; we exchange it and store both on KiteSession."""
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
