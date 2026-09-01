"""Runtime config: UI AppSettings overlays env, secrets stay in .env."""

from __future__ import annotations

from django.conf import settings


def _app_settings():
    try:
        from trades.models import AppSettings

        return AppSettings.load()
    except Exception:
        return None


def spreadsheet_id() -> str:
    cfg = _app_settings()
    if cfg and cfg.google_spreadsheet_id:
        return cfg.google_spreadsheet_id.strip()
    return (settings.GOOGLE_SHEETS_SPREADSHEET_ID or "").strip()


def worksheet_name() -> str:
    cfg = _app_settings()
    if cfg and cfg.google_worksheet:
        return cfg.google_worksheet.strip()
    return (settings.GOOGLE_SHEETS_WORKSHEET or "").strip()


def column_map() -> dict:
    merged = dict(getattr(settings, "SHEET_COLUMN_MAP", {}) or {})
    cfg = _app_settings()
    if cfg:
        merged.update(cfg.column_map or {})
    return {k: v for k, v in merged.items() if v}


def summary_map() -> dict:
    cfg = _app_settings()
    if cfg:
        return dict(cfg.summary_map or {})
    return {}


def telegram_chat_id() -> str:
    cfg = _app_settings()
    if cfg and cfg.telegram_chat_id:
        return cfg.telegram_chat_id.strip()
    return (settings.TELEGRAM_CHAT_ID or "").strip()


def telegram_alerts_enabled() -> bool:
    cfg = _app_settings()
    if cfg is None:
        return True
    return bool(cfg.telegram_alerts_enabled)
