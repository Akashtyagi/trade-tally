"""Runtime config: per-sheet catalog overlays env. Secrets stay in .env."""

from __future__ import annotations

from django.conf import settings


def _app_settings():
    try:
        from trades.models import AppSettings

        return AppSettings.load()
    except Exception:
        return None


def _sheet(slug: str | None = None) -> dict | None:
    try:
        from trades.sheet_config import get_primary, get_sheet

        return get_sheet(slug) if slug else get_primary()
    except Exception:
        return None


def spreadsheet_id(slug: str | None = None) -> str:
    # Per-sheet catalog → AppSettings → .env.
    sheet = _sheet(slug)
    if sheet and sheet.get("spreadsheet_id"):
        return str(sheet["spreadsheet_id"]).strip()
    cfg = _app_settings()
    if cfg and cfg.google_spreadsheet_id:
        return cfg.google_spreadsheet_id.strip()
    return (settings.GOOGLE_SHEETS_SPREADSHEET_ID or "").strip()


def worksheet_name(slug: str | None = None) -> str:
    sheet = _sheet(slug)
    if sheet and sheet.get("worksheet"):
        return str(sheet["worksheet"]).strip()
    cfg = _app_settings()
    if cfg and cfg.google_worksheet:
        return cfg.google_worksheet.strip()
    return (settings.GOOGLE_SHEETS_WORKSHEET or "").strip()


def column_map(slug: str | None = None) -> dict:
    merged = dict(getattr(settings, "SHEET_COLUMN_MAP", {}) or {})
    sheet = _sheet(slug)
    if sheet:
        merged.update(sheet.get("column_map") or {})
    else:
        cfg = _app_settings()
        if cfg:
            merged.update(cfg.column_map or {})
    return {k: v for k, v in merged.items() if v}


def summary_map(slug: str | None = None) -> dict:
    sheet = _sheet(slug)
    if sheet:
        return dict(sheet.get("summary_map") or {})
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
