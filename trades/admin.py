"""Django admin list views. Access tokens are stored but not shown in list_display."""

from django.contrib import admin

from trades.models import (
    AlertLog,
    AppSettings,
    CloseEvent,
    HoldingSnapshot,
    KiteFill,
    KiteSession,
    TradebookFill,
    TradeIdea,
)


@admin.register(TradeIdea)
class TradeIdeaAdmin(admin.ModelAdmin):
    list_display = (
        "symbol",
        "sheet_slug",
        "exchange",
        "status",
        "recommended_qty",
        "remaining_qty",
        "holding_qty",
        "last_ltp",
        "opened_on",
        "target",
        "target_2",
        "tcp_percent",
        "stop_loss",
    )
    list_filter = ("status", "exchange", "sheet_slug")
    search_fields = ("symbol",)


@admin.register(CloseEvent)
class CloseEventAdmin(admin.ModelAdmin):
    list_display = ("trade", "quantity", "price", "realized_pnl", "source", "created_at")
    list_filter = ("source", "created_at")


@admin.register(HoldingSnapshot)
class HoldingSnapshotAdmin(admin.ModelAdmin):
    list_display = ("exchange", "symbol", "quantity", "average_price", "last_price", "fetched_at")


@admin.register(AlertLog)
class AlertLogAdmin(admin.ModelAdmin):
    list_display = ("trade", "alert_type", "trading_date", "price")
    list_filter = ("alert_type", "trading_date")


@admin.register(KiteSession)
class KiteSessionAdmin(admin.ModelAdmin):
    list_display = ("login_time", "updated_at")


@admin.register(KiteFill)
class KiteFillAdmin(admin.ModelAdmin):
    list_display = ("symbol", "side", "quantity", "price", "filled_at", "fetched_at")
    list_filter = ("side", "exchange")


@admin.register(TradebookFill)
class TradebookFillAdmin(admin.ModelAdmin):
    list_display = ("symbol", "side", "quantity", "price", "trade_date", "source_sheet", "tracked")
    list_filter = ("side", "tracked", "source_sheet")
    search_fields = ("symbol", "trade_id", "order_id")


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "google_spreadsheet_id",
        "google_worksheet",
        "telegram_chat_id",
        "telegram_alerts_enabled",
        "updated_at",
    )
