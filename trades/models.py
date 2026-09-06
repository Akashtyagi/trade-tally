"""Local DB models. Google Sheet is the plan; Kite holdings are the position."""

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
    # Which dashboard tab this row belongs to (see trades.sheet_config).
    sheet_slug = models.CharField(max_length=64, default="aug24-27", db_index=True)
    # Excel row for the open block; completed-block rows add COMPLETED_ROW_OFFSET.
    sheet_row = models.PositiveIntegerField()
    symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=8, default="NSE")
    recommended_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    remaining_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    buy_low = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    buy_high = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    target = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    target_2 = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    target_3 = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    stop_loss = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    tcp_percent = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=TradeStatus.choices, default=TradeStatus.OPEN
    )
    closed_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    closed_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    notes = models.TextField(blank=True)
    last_ltp = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    # From Kite holdings when a snapshot exists; otherwise from the sheet Quantity cell.
    holding_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    holding_avg_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    opened_on = models.DateField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sheet_slug", "exchange", "symbol", "sheet_row"],
                name="uniq_trade_per_sheet_row",
            )
        ]
        ordering = ["status", "symbol"]

    def __str__(self):
        return f"{self.sheet_slug} {self.exchange}:{self.symbol} (row {self.sheet_row})"

    @property
    def instrument(self) -> str:
        return f"{self.exchange}:{self.symbol}"

    def avg_buy(self) -> Decimal:
        """Kite average when held; otherwise midpoint of the sheet buy range."""
        if self.holding_avg_price is not None:
            return self.holding_avg_price
        return (self.buy_low + self.buy_high) / Decimal("2")

    def tcp_display(self, corpus=None) -> Decimal | None:
        if self.tcp_percent is not None:
            return self.tcp_percent
        if corpus is None:
            return None
        try:
            total = Decimal(str(corpus))
        except Exception:
            return None
        if total <= 0:
            return None
        notional = self.recommended_qty * self.avg_buy()
        return (notional / total) * Decimal("100")

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

    def buy_gap_ready(self) -> bool:
        from integrations.checker import is_in_buy_zone, is_underweight

        return is_underweight(self.holding_qty, self.recommended_qty) and is_in_buy_zone(
            self.last_ltp, self.buy_low, self.buy_high
        )

    def ltp_in_buy_range(self) -> bool:
        from integrations.checker import is_in_buy_zone

        return is_in_buy_zone(self.last_ltp, self.buy_low, self.buy_high)

    def ltp_near_buy_range(self) -> bool:
        from integrations.checker import is_near_buy_zone

        return is_near_buy_zone(self.last_ltp, self.buy_low, self.buy_high)

    def dashboard_visible(self) -> bool:
        held = self.holding_qty if self.holding_qty is not None else Decimal("0")
        return held > 0 or self.ltp_in_buy_range()

    def dashboard_active(self) -> bool:
        """Live list: still open and either held or LTP in the buy range."""
        if self.status == TradeStatus.CLOSED:
            return False
        return self.dashboard_visible()

    def holding_age(self, today=None) -> str:
        # Prefer first tradebook BUY date; fall back to sheet opened_on / created_at.
        from trades.services import format_holding_age

        first_buy = (
            TradebookFill.objects.filter(symbol__iexact=self.symbol, side__iexact="BUY")
            .order_by("trade_date", "id")
            .values_list("trade_date", flat=True)
            .first()
        )
        start = first_buy or self.opened_on
        if start is None and self.created_at:
            start = timezone.localdate(self.created_at)
        end = today
        if end is None and self.status == TradeStatus.CLOSED:
            last = self.close_events.all()
            last = last[0] if last else None
            if last is not None:
                end = timezone.localdate(last.created_at)
        return format_holding_age(start, today=end)


class CloseSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    TRADEBOOK = "tradebook", "Tradebook"


class CloseEvent(models.Model):
    """One partial or full exit — manual UI or tradebook FIFO match."""
    trade = models.ForeignKey(TradeIdea, related_name="close_events", on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    price = models.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=4)
    source = models.CharField(max_length=16, choices=CloseSource.choices, default=CloseSource.MANUAL)
    fill_key = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Close {self.quantity} {self.trade.symbol} @ {self.price}"


class HoldingSnapshot(models.Model):
    """Last Kite holdings() row per exchange+symbol. Missing names are qty 0."""
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
    """Dedupes Telegram: unique on (trade, alert_type, trading_date)."""
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
    """Daily Kite login. request_token is one-shot; access_token is what API calls use."""
    access_token = models.CharField(max_length=512)
    request_token = models.CharField(max_length=256, blank=True)
    login_time = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Kite session {self.login_time}"


class TradebookFill(models.Model):
    """One execution imported from a Zerodha tradebook worksheet."""

    uid = models.CharField(max_length=128, unique=True)
    symbol = models.CharField(max_length=32, db_index=True)
    isin = models.CharField(max_length=16, blank=True)
    exchange = models.CharField(max_length=8, default="NSE")
    segment = models.CharField(max_length=8, blank=True)
    series = models.CharField(max_length=8, blank=True)
    side = models.CharField(max_length=8)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    price = models.DecimalField(max_digits=18, decimal_places=4)
    trade_date = models.DateField()
    filled_at = models.DateTimeField(null=True, blank=True)
    trade_id = models.CharField(max_length=64, blank=True)
    order_id = models.CharField(max_length=64, blank=True)
    auction = models.BooleanField(default=False)
    source_sheet = models.CharField(max_length=128, blank=True)
    tracked = models.BooleanField(default=False)
    imported_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["filled_at", "id"]

    def __str__(self):
        return f"{self.side} {self.quantity} {self.symbol} @ {self.price}"


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
    ("risk_pct", "Risk percentage"),
    ("stop_loss", "Stop loss"),
    ("target", "First target"),
    ("target_2", "Second target"),
    ("target_3", "Third target"),
    ("tcp", "TCP / total capital %"),
    ("max_investment", "Maximum investment suggested"),
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
    "qty": "Maximum Shares Recom.",
    "current_qty": "Quantity",
    "entry_price": "Entry Price",
    "buy_range": "Buy Range",
    "risk_pct": "Risk Percentage",
    "stop_loss": "STOP LOSS",
    "target": "FIRST TARGET",
    "target_2": "SECOND TARGET",
    "target_3": "THRID TARGET",
    "tcp": "Total Captial Percentage",
    "max_investment": "Maximum Investment Suggested",
    "current_pnl": "Current P/L",
    "total_investment": "Total Investment",
    "notes": "Comments",
    "closed_qty": "Completed Quantity",
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
        """Singleton row pk=1. First load copies spreadsheet/chat IDs from .env."""
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

