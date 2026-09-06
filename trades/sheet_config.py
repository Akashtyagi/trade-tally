"""Sheet dashboards live in a JSON config file.

Each entry is one Google worksheet (a tab, or a tab in another spreadsheet).
Exactly one is primary: the landing dashboard and the only sheet cron touches.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from django.conf import settings

from trades.models import DEFAULT_COLUMN_MAP, DEFAULT_SUMMARY_MAP

DEFAULT_SHEET_SLUG = "aug24-27"


def config_path() -> Path:
    return Path(getattr(settings, "SHEETS_CONFIG_PATH", settings.BASE_DIR / "data" / "sheets.json"))


def slugify_worksheet(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
    return text.strip("-")[:64] or "sheet"


def _empty_sheet(*, slug: str, worksheet: str, label: str = "", spreadsheet_id: str = "") -> dict:
    return {
        "slug": slug,
        "label": (label or worksheet or slug).strip(),
        "spreadsheet_id": (spreadsheet_id or "").strip(),
        "worksheet": (worksheet or slug).strip(),
        "column_map": dict(DEFAULT_COLUMN_MAP),
        "summary_map": dict(DEFAULT_SUMMARY_MAP),
        "last_sheet_sync_at": None,
        "last_zerodha_sync_at": None,
        "portfolio": {},
    }


def _seed_catalog() -> dict:
    worksheet = "Aug24-27"
    spreadsheet_id = ""
    column_map = dict(DEFAULT_COLUMN_MAP)
    summary_map = dict(DEFAULT_SUMMARY_MAP)
    try:
        from trades.models import AppSettings

        cfg = AppSettings.load()
        worksheet = (cfg.google_worksheet or worksheet).strip()
        spreadsheet_id = (cfg.google_spreadsheet_id or "").strip()
        if cfg.column_map:
            column_map = dict(cfg.column_map)
        if cfg.summary_map:
            summary_map = dict(cfg.summary_map)
    except Exception:
        worksheet = (getattr(settings, "GOOGLE_SHEETS_WORKSHEET", None) or worksheet).strip()
        spreadsheet_id = (getattr(settings, "GOOGLE_SHEETS_SPREADSHEET_ID", "") or "").strip()
    slug = slugify_worksheet(worksheet) or DEFAULT_SHEET_SLUG
    sheet = _empty_sheet(slug=slug, worksheet=worksheet, label=worksheet, spreadsheet_id=spreadsheet_id)
    sheet["column_map"] = column_map
    sheet["summary_map"] = summary_map
    return {"primary": slug, "sheets": [sheet]}


def _normalize(data: dict) -> dict:
    sheets = []
    seen = set()
    for raw in data.get("sheets") or []:
        if not isinstance(raw, dict):
            continue
        worksheet = str(raw.get("worksheet") or raw.get("label") or "").strip()
        slug = slugify_worksheet(str(raw.get("slug") or worksheet))
        if not slug or slug in seen:
            continue
        seen.add(slug)
        sheet = _empty_sheet(
            slug=slug,
            worksheet=worksheet or slug,
            label=str(raw.get("label") or worksheet or slug),
            spreadsheet_id=str(raw.get("spreadsheet_id") or ""),
        )
        if isinstance(raw.get("column_map"), dict):
            sheet["column_map"] = {k: v for k, v in raw["column_map"].items() if v}
        if isinstance(raw.get("summary_map"), dict):
            sheet["summary_map"] = {k: v for k, v in raw["summary_map"].items() if v}
        sheet["last_sheet_sync_at"] = raw.get("last_sheet_sync_at")
        sheet["last_zerodha_sync_at"] = raw.get("last_zerodha_sync_at")
        sheet["portfolio"] = raw.get("portfolio") if isinstance(raw.get("portfolio"), dict) else {}
        sheets.append(sheet)
    if not sheets:
        return _seed_catalog()
    primary = slugify_worksheet(str(data.get("primary") or ""))
    if primary not in {s["slug"] for s in sheets}:
        primary = sheets[0]["slug"]
    return {"primary": primary, "sheets": sheets}


def load_catalog() -> dict:
    path = config_path()
    if not path.exists():
        catalog = _seed_catalog()
        save_catalog(catalog)
        return catalog
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    catalog = _normalize(data)
    return catalog


def save_catalog(catalog: dict) -> dict:
    normalized = _normalize(catalog)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-replace so a crashed save cannot leave half a JSON file.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return normalized


def list_sheets() -> list[dict]:
    return deepcopy(load_catalog()["sheets"])


def primary_slug() -> str:
    return load_catalog()["primary"]


def get_sheet(slug: str | None = None) -> dict | None:
    catalog = load_catalog()
    want = slugify_worksheet(slug) if slug else catalog["primary"]
    for sheet in catalog["sheets"]:
        if sheet["slug"] == want:
            return deepcopy(sheet)
    return None


def get_primary() -> dict:
    sheet = get_sheet(None)
    if sheet is None:
        catalog = save_catalog(_seed_catalog())
        return deepcopy(catalog["sheets"][0])
    return sheet


def set_primary(slug: str) -> dict:
    catalog = load_catalog()
    want = slugify_worksheet(slug)
    if want not in {s["slug"] for s in catalog["sheets"]}:
        raise KeyError(f"Unknown sheet '{slug}'")
    catalog["primary"] = want
    return save_catalog(catalog)


def upsert_sheet(sheet: dict) -> dict:
    catalog = load_catalog()
    worksheet = str(sheet.get("worksheet") or "").strip()
    slug = slugify_worksheet(str(sheet.get("slug") or worksheet))
    existing = {s["slug"]: i for i, s in enumerate(catalog["sheets"])}
    merged = _empty_sheet(
        slug=slug,
        worksheet=worksheet or slug,
        label=str(sheet.get("label") or worksheet or slug),
        spreadsheet_id=str(sheet.get("spreadsheet_id") or ""),
    )
    if slug in existing:
        prev = catalog["sheets"][existing[slug]]
        merged["column_map"] = prev["column_map"]
        merged["summary_map"] = prev["summary_map"]
        merged["last_sheet_sync_at"] = prev.get("last_sheet_sync_at")
        merged["last_zerodha_sync_at"] = prev.get("last_zerodha_sync_at")
        merged["portfolio"] = prev.get("portfolio") or {}
    if isinstance(sheet.get("column_map"), dict):
        merged["column_map"] = {k: v for k, v in sheet["column_map"].items() if v}
    if isinstance(sheet.get("summary_map"), dict):
        merged["summary_map"] = {k: v for k, v in sheet["summary_map"].items() if v}
    if slug in existing:
        catalog["sheets"][existing[slug]] = merged
    else:
        catalog["sheets"].append(merged)
        if not catalog.get("primary"):
            catalog["primary"] = slug
    return save_catalog(catalog)


def delete_sheet(slug: str) -> dict:
    catalog = load_catalog()
    want = slugify_worksheet(slug)
    remaining = [s for s in catalog["sheets"] if s["slug"] != want]
    if not remaining:
        raise ValueError("Cannot delete the last sheet.")
    catalog["sheets"] = remaining
    if catalog["primary"] == want:
        catalog["primary"] = remaining[0]["slug"]
    return save_catalog(catalog)


def replace_sheets(sheets: list[dict], primary: str | None = None) -> dict:
    catalog = {"primary": primary or "", "sheets": sheets}
    return save_catalog(catalog)


def update_sheet_state(slug: str, **fields) -> dict:
    """Patch last_*_sync_at / portfolio on one catalog entry."""
    catalog = load_catalog()
    want = slugify_worksheet(slug)
    for sheet in catalog["sheets"]:
        if sheet["slug"] == want:
            sheet.update(fields)
            return save_catalog(catalog)
    raise KeyError(f"Unknown sheet '{slug}'")


def unique_slug(worksheet: str, existing: set[str] | None = None) -> str:
    existing = existing or {s["slug"] for s in list_sheets()}
    base = slugify_worksheet(worksheet)
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"[:64]
        n += 1
    return slug
