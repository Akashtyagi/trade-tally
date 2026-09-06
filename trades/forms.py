"""Dashboard and config forms. Secrets stay in .env, not these fields."""

from decimal import Decimal

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from trades.models import (
    SUMMARY_CELL_FIELDS,
    TRADE_COLUMN_FIELDS,
    AppSettings,
    TradeIdea,
)
from trades.sheet_config import list_sheets, slugify_worksheet, unique_slug


class CloseTradeForm(forms.Form):
    quantity = forms.DecimalField(
        min_value=Decimal("0.0001"),
        max_digits=18,
        decimal_places=4,
        label="Quantity to close",
    )
    price = forms.DecimalField(
        min_value=Decimal("0.0001"),
        max_digits=18,
        decimal_places=4,
        label="Close price",
    )

    def __init__(self, *args, trade: TradeIdea | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.trade = trade
        if trade is not None:
            self.fields["quantity"].initial = trade.remaining_qty

    def clean_quantity(self) -> Decimal:
        qty = self.cleaned_data["quantity"]
        if self.trade is not None and qty > self.trade.remaining_qty:
            raise ValidationError("Cannot close more than the remaining quantity.")
        return qty


class AppConfigForm(forms.ModelForm):
    class Meta:
        model = AppSettings
        fields = [
            "telegram_chat_id",
            "telegram_alerts_enabled",
            "google_spreadsheet_id",
        ]
        widgets = {
            "telegram_chat_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "123456789"}),
            "google_spreadsheet_id": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "from the sheet URL /d/ID/edit"}
            ),
        }
        labels = {
            "telegram_chat_id": "Telegram chat ID",
            "telegram_alerts_enabled": "Send Telegram alerts",
            "google_spreadsheet_id": "Default Google spreadsheet ID",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["telegram_alerts_enabled"].widget.attrs["class"] = "form-check-input"


class AddSheetForm(forms.Form):
    worksheet = forms.CharField(
        label="Tab / worksheet name",
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Aug24-27"}),
    )
    label = forms.CharField(
        label="Dashboard label",
        max_length=128,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Same as tab name if blank"}),
    )
    spreadsheet_id = forms.CharField(
        label="Spreadsheet ID override",
        max_length=128,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Leave blank to use the default workbook"}
        ),
    )


def sheets_from_post(post) -> tuple[list[dict], str]:
    """Rebuild the sheet catalog from the config form POST."""
    existing = list_sheets()
    count = int(post.get("sheet_count") or 0)
    sheets = []
    used_slugs: set[str] = set()
    for i in range(count):
        if post.get(f"delete_{i}"):
            continue
        worksheet = (post.get(f"sheet_worksheet_{i}") or "").strip()
        if not worksheet:
            continue
        slug = slugify_worksheet(post.get(f"sheet_slug_{i}") or worksheet)
        if slug in used_slugs:
            slug = unique_slug(worksheet, used_slugs)
        used_slugs.add(slug)
        prev = next((s for s in existing if s["slug"] == slug), {})
        column_map = {
            key: (post.get(f"sheet_{i}_col_{key}") or "").strip()
            for key, _label in TRADE_COLUMN_FIELDS
            if (post.get(f"sheet_{i}_col_{key}") or "").strip()
        }
        summary_map = {
            key: (post.get(f"sheet_{i}_sum_{key}") or "").strip()
            for key, _label in SUMMARY_CELL_FIELDS
            if (post.get(f"sheet_{i}_sum_{key}") or "").strip()
        }
        sheets.append(
            {
                "slug": slug,
                "label": (post.get(f"sheet_label_{i}") or worksheet).strip(),
                "worksheet": worksheet,
                "spreadsheet_id": (post.get(f"sheet_spreadsheet_{i}") or "").strip(),
                "column_map": column_map,
                "summary_map": summary_map,
                "last_sheet_sync_at": prev.get("last_sheet_sync_at"),
                "last_zerodha_sync_at": prev.get("last_zerodha_sync_at"),
                "portfolio": prev.get("portfolio") or {},
            }
        )
    primary = slugify_worksheet(post.get("primary") or "")
    return sheets, primary


def telegram_token_configured() -> bool:
    token = settings.TELEGRAM_BOT_TOKEN
    return bool(token) and token != "your_telegram_bot_token_here"
