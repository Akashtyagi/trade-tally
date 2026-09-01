from decimal import Decimal

from django.db import models
from django.utils import timezone


class TradeStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    PARTIAL = "PARTIAL", "Partial"
    CLOSED = "CLOSED", "Closed"


class AlertType(models.TextChoices):
    UNDERWEIGHT_BUY_ZONE = "UNDERWEIGHT_BUY_ZONE", "Underweight in buy zone"
    TARGET = "TARGET", "Target hit"
    STOP_LOSS = "STOP_LOSS", "Stop loss hit"


class TradeIdea(models.Model):
    sheet_row = models.PositiveIntegerField()
    symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=8, default="NSE")
    recommended_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    remaining_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    buy_low = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    buy_high = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    target = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    stop_loss = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    status = models.CharField(
        max_length=16, choices=TradeStatus.choices, default=TradeStatus.OPEN
    )
    closed_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    closed_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    notes = models.TextField(blank=True)
    last_ltp = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    holding_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    holding_avg_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    opened_on = models.DateField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "symbol", "sheet_row"],
                name="uniq_trade_sheet_row",
            )
        ]
        ordering = ["status", "symbol"]

    def __str__(self):
        return f"{self.exchange}:{self.symbol} (row {self.sheet_row})"

    @property
    def instrument(self) -> str:
        return f"{self.exchange}:{self.symbol}"

    def avg_buy(self) -> Decimal:
        if self.holding_avg_price is not None:
            return self.holding_avg_price
        return (self.buy_low + self.buy_high) / Decimal("2")

    def invested(self) -> Decimal:
        if self.remaining_qty <= 0:
            return Decimal("0")
        return self.remaining_qty * self.avg_buy()

    def unrealized_pnl(self) -> Decimal:
        if self.last_ltp is None or self.remaining_qty <= 0:
            return Decimal("0")
        return (self.last_ltp - self.avg_buy()) * self.remaining_qty

    def realized_pnl(self) -> Decimal:
        events = self.close_events.all()
        return sum((event.realized_pnl for event in events), Decimal("0"))

    def row_tone(self) -> str:
        if self.status != TradeStatus.CLOSED:
            return "open"
        return "profit" if self.realized_pnl() >= 0 else "loss"

    def holding_age(self, today=None) -> str:
        from trades.services import format_holding_age

        start = self.opened_on
        if start is None and self.created_at:
            start = timezone.localdate(self.created_at)
        end = today
        if end is None and self.status == TradeStatus.CLOSED:
            last = self.close_events.all()
            last = last[0] if last else None
            if last is not None:
                end = timezone.localdate(last.created_at)
        return format_holding_age(start, today=end)


class CloseEvent(models.Model):
    trade = models.ForeignKey(TradeIdea, related_name="close_events", on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    price = models.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Close {self.quantity} {self.trade.symbol} @ {self.price}"


class HoldingSnapshot(models.Model):
    exchange = models.CharField(max_length=8)
    symbol = models.CharField(max_length=32)
    quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    average_price = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    last_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["exchange", "symbol"], name="uniq_holding_symbol")
        ]

    def __str__(self):
        return f"{self.exchange}:{self.symbol} x {self.quantity}"


class AlertLog(models.Model):
    trade = models.ForeignKey(TradeIdea, related_name="alerts", on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=32, choices=AlertType.choices)
    trading_date = models.DateField()
    price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["trade", "alert_type", "trading_date"],
                name="uniq_alert_per_day",
            )
        ]

    def __str__(self):
        return f"{self.alert_type} {self.trade.symbol} {self.trading_date}"


class KiteSession(models.Model):
    access_token = models.CharField(max_length=512)
    request_token = models.CharField(max_length=256, blank=True)
    login_time = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Kite session {self.login_time}"


class KiteFill(models.Model):
    """One execution from the last Zerodha sync (Kite day's trades + holdings context)."""

    symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=8, default="NSE")
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    price = models.DecimalField(max_digits=18, decimal_places=4)
    side = models.CharField(max_length=8, blank=True)
    filled_at = models.DateTimeField(null=True, blank=True)
    order_id = models.CharField(max_length=64, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-filled_at", "-id"]

    def __str__(self):
        return f"{self.side} {self.quantity} {self.symbol} @ {self.price}"


TRADE_COLUMN_FIELDS = [
    ("symbol", "Symbol / Share"),
    ("date", "Opened on (Date)"),
    ("qty", "Recommended qty (Minimum Shares Recom.)"),
    ("current_qty", "Current quantity"),
    ("entry_price", "Entry price"),
    ("buy_range", "Buy range"),
    ("stop_loss", "Stop loss"),
    ("target", "First target"),
    ("target_2", "Second target"),
    ("target_3", "Third target"),
    ("current_pnl", "Current P/L"),
    ("total_investment", "Total investment"),
    ("notes", "Comments"),
    ("closed_qty", "Completed quantity"),
    ("closed_price", "Exit price"),
]

SUMMARY_CELL_FIELDS = [
    ("corpus", "Corpus / total portfolio size"),
    ("risk_percentage", "Risk % / max allocation"),
    ("current_value", "Current value / active investment"),
    ("remaining_balance", "Remaining balance"),
]

# Defaults match the live Aug24-27 workbook headers / sizer cells.
DEFAULT_COLUMN_MAP = {
    "symbol": "Share",
    "date": "Date",
    "qty": "Minimum Shares Recom.",
    "current_qty": "Current Quantity",
    "entry_price": "Entry Price",
    "buy_range": "Buy Range",
    "stop_loss": "STOP LOSS",
    "target": "FIRST TARGET",
    "target_2": "SECOND TARGET",
    "target_3": "THRID TARGET",
    "current_pnl": "Current P/L",
    "total_investment": "Total Investment",
    "notes": "Comments",
    "closed_qty": "Quantity",
    "closed_price": "Exit Price",
}

DEFAULT_SUMMARY_MAP = {
    "corpus": "A5",
    "risk_percentage": "B2",
    "current_value": "N2",
    "remaining_balance": "K2",
}


class AppSettings(models.Model):
    """UI-driven config. Secrets (tokens, service account file) stay in .env."""

    telegram_chat_id = models.CharField(max_length=64, blank=True)
    telegram_alerts_enabled = models.BooleanField(default=True)
    google_spreadsheet_id = models.CharField(max_length=128, blank=True)
    google_worksheet = models.CharField(max_length=128, blank=True, default="Aug24-27")
    column_map = models.JSONField(default=dict, blank=True)
    summary_map = models.JSONField(default=dict, blank=True)
    last_sheet_sync_at = models.DateTimeField(null=True, blank=True)
    last_zerodha_sync_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App settings"

    def __str__(self):
        return "App settings"

    @classmethod
    def load(cls) -> "AppSettings":
        from django.conf import settings as django_settings

        obj, created = cls.objects.get_or_create(pk=1)
        dirty_fields = []
        if created or not obj.google_spreadsheet_id:
            env_id = (django_settings.GOOGLE_SHEETS_SPREADSHEET_ID or "").strip()
            if env_id and not obj.google_spreadsheet_id:
                obj.google_spreadsheet_id = env_id
                dirty_fields.append("google_spreadsheet_id")
        if created and not obj.google_worksheet:
            obj.google_worksheet = django_settings.GOOGLE_SHEETS_WORKSHEET or "Aug24-27"
            dirty_fields.append("google_worksheet")
        if created and not obj.telegram_chat_id:
            obj.telegram_chat_id = django_settings.TELEGRAM_CHAT_ID or ""
            dirty_fields.append("telegram_chat_id")
        if not obj.column_map:
            obj.column_map = dict(DEFAULT_COLUMN_MAP)
            dirty_fields.append("column_map")
        if not obj.summary_map:
            obj.summary_map = dict(DEFAULT_SUMMARY_MAP)
            dirty_fields.append("summary_map")
        if dirty_fields:
            obj.save(update_fields=[*dirty_fields, "updated_at"])
        return obj

