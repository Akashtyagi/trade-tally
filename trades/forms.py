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
            "google_worksheet",
        ]
        widgets = {
            "telegram_chat_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "123456789"}),
            "google_spreadsheet_id": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "from the sheet URL /d/ID/edit"}
            ),
            "google_worksheet": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Aug24-27 or * for first tab"}
            ),
        }
        labels = {
            "telegram_chat_id": "Telegram chat ID",
            "telegram_alerts_enabled": "Send Telegram alerts",
            "google_spreadsheet_id": "Google spreadsheet ID",
            "google_worksheet": "Worksheet / tab name",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["telegram_alerts_enabled"].widget.attrs["class"] = "form-check-input"
        instance: AppSettings | None = kwargs.get("instance")
        col = (instance.column_map if instance else {}) or {}
        summary = (instance.summary_map if instance else {}) or {}
        for key, label in TRADE_COLUMN_FIELDS:
            self.fields[f"col_{key}"] = forms.CharField(
                label=label,
                required=False,
                initial=col.get(key, ""),
                widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Sheet column header"}),
            )
        for key, label in SUMMARY_CELL_FIELDS:
            self.fields[f"sum_{key}"] = forms.CharField(
                label=label,
                required=False,
                initial=summary.get(key, ""),
                widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "A1 cell e.g. A5 or B2"}),
            )

    def save(self, commit=True):
        obj: AppSettings = super().save(commit=False)
        obj.column_map = {
            key: (self.cleaned_data.get(f"col_{key}") or "").strip()
            for key, _label in TRADE_COLUMN_FIELDS
            if (self.cleaned_data.get(f"col_{key}") or "").strip()
        }
        obj.summary_map = {
            key: (self.cleaned_data.get(f"sum_{key}") or "").strip()
            for key, _label in SUMMARY_CELL_FIELDS
            if (self.cleaned_data.get(f"sum_{key}") or "").strip()
        }
        if commit:
            obj.save()
        return obj


def telegram_token_configured() -> bool:
    token = settings.TELEGRAM_BOT_TOKEN
    return bool(token) and token != "your_telegram_bot_token_here"
