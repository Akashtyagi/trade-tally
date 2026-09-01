"""Google Sheets read/write.

Supports:
- A simple header row (symbol, qty, buy_low, ...)
- The live portfolio workbook (sizer | open trades | trade completed)
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

from trades.models import TradeIdea, TradeStatus

# Closed-block rows are stored with this offset so they do not collide with
# an open trade on the same Excel row (same symbol can appear in both tables).
COMPLETED_ROW_OFFSET = 1_000_000

SHEET_ERRORS = {"#div/0!", "#n/a", "#value!", "#ref!", "#name?", "n/a"}

# Canonical field -> accepted header spellings after normalize_header()
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "share", "ticker"),
    "qty": ("qty", "recommended_qty", "minimum_shares_recom", "min_shares_recom"),
    "current_qty": ("current_quantity", "current_qty"),
    "entry_price": ("entry_price", "recommended_price"),
    "buy_low": ("buy_low",),
    "buy_high": ("buy_high",),
    "buy_range": ("buy_range",),
    "target": ("first_target", "target"),
    "target_2": ("second_target",),
    "target_3": ("third_target", "thrid_target"),
    "stop_loss": ("stop_loss", "sl"),
    "status": ("status",),
    "closed_qty": ("closed_qty", "quantity"),
    "closed_price": ("closed_price", "exit_price"),
    "notes": ("notes", "comments"),
    "exchange": ("exchange",),
    "date": ("date", "opened_on"),
    "current_pnl": ("current_pl", "current_pnl"),
    "total_investment": ("total_investment",),
}


def normalize_header(value: str) -> str:
    text = " ".join(str(value).strip().lower().replace("\n", " ").split())
    text = re.sub(r"[.#%/]+", "", text)
    return text.replace(" ", "_")


def parse_decimal(value, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    text = str(value).strip()
    if text == "" or text.lower() in SHEET_ERRORS:
        return default
    compact = (
        text.replace("₹", "")
        .replace(",", "")
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace("−", "-")
        .replace("%", "")
    )
    if compact in {"", "-", "+", "--"}:
        return default
    try:
        return Decimal(compact)
    except InvalidOperation:
        return default


def parse_buy_range(value) -> tuple[Decimal | None, Decimal | None]:
    """Parse '155-180', '445--4500', or a single price like '₹820.00'."""
    if value is None:
        return None, None
    text = str(value).replace("₹", "").replace(",", "").strip()
    if not text or text.lower() in SHEET_ERRORS:
        return None, None
    parts = [p.strip() for p in re.split(r"-{1,2}", text) if p.strip()]
    if len(parts) >= 2:
        return parse_decimal(parts[0]), parse_decimal(parts[1])
    one = parse_decimal(text)
    return one, one


def parse_date(value):
    """Parse sheet dates like 7-Aug-2024, 4-Sept-2024, 30-04-2025."""
    from datetime import datetime

    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in SHEET_ERRORS:
        return None
    text = text.replace("Sept", "Sep")
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def a1_to_rc(a1: str) -> tuple[int, int] | None:
    text = str(a1 or "").strip().upper()
    match = re.match(r"^([A-Z]+)(\d+)$", text)
    if not match:
        return None
    col = 0
    for char in match.group(1):
        col = col * 26 + (ord(char) - 64)
    return int(match.group(2)) - 1, col - 1


def parse_status(value) -> str:
    text = str(value or "").strip().upper()
    if text in TradeStatus.values:
        return text
    return TradeStatus.OPEN


def _alias_lookup(column_map: dict[str, str] | None) -> dict[str, str]:
    """Normalized header -> canonical field."""
    lookup: dict[str, str] = {}
    for field, names in HEADER_ALIASES.items():
        for name in names:
            lookup.setdefault(name, field)
    column_map = column_map or getattr(settings, "SHEET_COLUMN_MAP", {})
    for field, sheet_name in column_map.items():
        lookup[normalize_header(sheet_name)] = field
        lookup[normalize_header(field)] = field
    return lookup


def header_index_map(
    headers: list[str],
    column_map: dict[str, str] | None = None,
    *,
    start: int = 0,
    end: int | None = None,
) -> dict[str, int]:
    lookup = _alias_lookup(column_map)
    indexes: dict[str, int] = {}
    stop = end if end is not None else len(headers)
    for idx in range(start, min(stop, len(headers))):
        key = normalize_header(headers[idx])
        if not key:
            continue
        field = lookup.get(key)
        if field and field not in indexes:
            indexes[field] = idx
    return indexes


def find_header_row(values: list[list]) -> int:
    for idx, row in enumerate(values[:15]):
        norms = {normalize_header(c) for c in row if str(c).strip()}
        has_symbol = bool(norms & {"share", "symbol", "ticker"})
        has_qty = bool(
            norms
            & {
                "qty",
                "recommended_qty",
                "minimum_shares_recom",
                "current_quantity",
                "quantity",
            }
        )
        if has_symbol and has_qty:
            return idx
    return 0


def _block_starts(headers: list[str]) -> tuple[int, int | None]:
    """Return (active_start, completed_start) using the two 'S No' columns."""
    hits = [i for i, h in enumerate(headers) if normalize_header(h) == "s_no"]
    if len(hits) >= 2:
        return hits[0], hits[1]
    if len(hits) == 1:
        exit_hits = [i for i, h in enumerate(headers) if normalize_header(h) == "exit_price"]
        return hits[0], (exit_hits[0] if exit_hits else None)
    return 0, None


def _cell(row: list[str], indexes: dict[str, int], field: str, default: str = "") -> str:
    idx = indexes.get(field)
    if idx is None or idx >= len(row):
        return default
    return row[idx]


def _is_symbol(value: str) -> bool:
    text = value.strip().upper()
    if not text or text.lower() in SHEET_ERRORS:
        return False
    return bool(re.match(r"^[A-Z][A-Z0-9.&-]{0,31}$", text))


def _trade_from_active(raw: list[str], indexes: dict[str, int], excel_row: int) -> dict | None:
    symbol = _cell(raw, indexes, "symbol").strip().upper()
    if not _is_symbol(symbol):
        return None
    qty = parse_decimal(_cell(raw, indexes, "qty"), Decimal("0")) or Decimal("0")
    has_current = "current_qty" in indexes
    current_qty = (
        parse_decimal(_cell(raw, indexes, "current_qty"), Decimal("0")) or Decimal("0")
        if has_current
        else None
    )
    entry = parse_decimal(_cell(raw, indexes, "entry_price"))
    buy_low = parse_decimal(_cell(raw, indexes, "buy_low"))
    buy_high = parse_decimal(_cell(raw, indexes, "buy_high"))
    range_low, range_high = parse_buy_range(_cell(raw, indexes, "buy_range"))
    held = current_qty if current_qty is not None else Decimal("0")
    if qty == 0 and held == 0 and entry is None and range_low is None:
        return None
    buy_low = buy_low or range_low or entry or Decimal("0")
    buy_high = buy_high or range_high or entry or buy_low
    return {
        "sheet_row": excel_row,
        "symbol": symbol,
        "exchange": (_cell(raw, indexes, "exchange", "NSE") or "NSE").strip().upper() or "NSE",
        "qty": qty,
        "current_qty": current_qty,
        "entry_price": entry,
        "buy_low": buy_low,
        "buy_high": buy_high,
        "target": parse_decimal(_cell(raw, indexes, "target"), Decimal("0")) or Decimal("0"),
        "stop_loss": parse_decimal(_cell(raw, indexes, "stop_loss"), Decimal("0")) or Decimal("0"),
        "status": parse_status(_cell(raw, indexes, "status")),
        "closed_qty": Decimal("0"),
        "closed_price": None,
        "notes": _cell(raw, indexes, "notes").strip(),
        "opened_on": parse_date(_cell(raw, indexes, "date")),
    }


def _trade_from_completed(raw: list[str], indexes: dict[str, int], excel_row: int) -> dict | None:
    symbol = _cell(raw, indexes, "symbol").strip().upper()
    if not _is_symbol(symbol):
        return None
    closed_qty = parse_decimal(_cell(raw, indexes, "closed_qty"), Decimal("0")) or Decimal("0")
    closed_price = parse_decimal(_cell(raw, indexes, "closed_price"))
    entry = parse_decimal(_cell(raw, indexes, "entry_price"))
    if closed_qty <= 0 and closed_price is None:
        return None
    return {
        "sheet_row": excel_row + COMPLETED_ROW_OFFSET,
        "symbol": symbol,
        "exchange": "NSE",
        "qty": closed_qty,
        "current_qty": Decimal("0"),
        "entry_price": entry,
        "buy_low": entry or Decimal("0"),
        "buy_high": entry or Decimal("0"),
        "target": Decimal("0"),
        "stop_loss": Decimal("0"),
        "status": TradeStatus.CLOSED,
        "closed_qty": closed_qty,
        "closed_price": closed_price,
        "notes": _cell(raw, indexes, "notes").strip(),
        "opened_on": None,
    }


def parse_rows(values: list[list], column_map: dict[str, str] | None = None) -> list[dict]:
    """Parse sheet values into trade dicts. Header row is detected, not assumed row 1."""
    if not values:
        return []
    header_idx = find_header_row(values)
    headers = values[header_idx]
    active_start, completed_at = _block_starts(headers)
    active_indexes = header_index_map(headers, column_map, start=active_start, end=completed_at)
    if "symbol" not in active_indexes:
        active_indexes = header_index_map(headers, column_map)
    if "symbol" not in active_indexes:
        raise ValueError("Sheet is missing a symbol column.")

    completed_indexes = (
        header_index_map(headers, column_map, start=completed_at) if completed_at else {}
    )

    rows: list[dict] = []
    for i, raw in enumerate(values):
        if i <= header_idx:
            continue
        excel_row = i + 1
        active = _trade_from_active(raw, active_indexes, excel_row)
        if active:
            rows.append(active)
        if completed_indexes:
            closed = _trade_from_completed(raw, completed_indexes, excel_row)
            if closed:
                rows.append(closed)
    return rows


def parse_portfolio_config(values: list[list], summary_map: dict | None = None) -> dict:
    """Read corpus / risk / current value from mapped A1 cells, with workbook fallbacks."""
    from trades import runtime_config

    config = {
        "total_budget": None,
        "risk_percentage": None,
        "current_value": None,
        "remaining_balance": None,
    }
    mapping = summary_map if summary_map is not None else runtime_config.summary_map()
    for key, cell in mapping.items():
        rc = a1_to_rc(cell)
        if not rc:
            continue
        row_i, col_i = rc
        if row_i < len(values) and col_i < len(values[row_i]):
            parsed = parse_decimal(values[row_i][col_i])
            if key == "corpus":
                config["total_budget"] = parsed
            else:
                config[key] = parsed
    if config["risk_percentage"] is None and len(values) > 1:
        config["risk_percentage"] = parse_decimal(values[1][1] if len(values[1]) > 1 else None)
    if config["total_budget"] is None and len(values) > 4:
        config["total_budget"] = parse_decimal(values[4][0] if values[4] else None)
    for row in values[:30]:
        joined = " ".join(str(c).lower() for c in row[:3])
        if "total amount" in joined and len(row) > 2:
            config["total_budget"] = parse_decimal(row[2]) or config["total_budget"]
        if "max allocation" in joined and len(row) > 1:
            config["risk_percentage"] = parse_decimal(row[1]) or config["risk_percentage"]
    return config


def _worksheet():
    import gspread
    from trades import runtime_config

    gc = gspread.service_account(filename=settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    spreadsheet = gc.open_by_key(runtime_config.spreadsheet_id())
    name = runtime_config.worksheet_name()
    if not name or name in {"*", "0"}:
        return spreadsheet.get_worksheet(0)
    return spreadsheet.worksheet(name)


def fetch_sheet_values() -> list[list]:
    from trades import runtime_config

    if not runtime_config.spreadsheet_id():
        return []
    return _worksheet().get_all_values()


def column_letter(index_zero_based: int) -> str:
    index = index_zero_based + 1
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def writeback_updates(headers: list[str], sheet_row: int, payload: dict, column_map=None) -> list[dict]:
    """Build gspread batch_update entries for tests and the writer."""
    excel_row = sheet_row if sheet_row < COMPLETED_ROW_OFFSET else sheet_row - COMPLETED_ROW_OFFSET
    active_start, completed_at = _block_starts(headers)
    if sheet_row >= COMPLETED_ROW_OFFSET and completed_at:
        indexes = header_index_map(headers, column_map, start=completed_at)
    else:
        indexes = header_index_map(headers, column_map, start=active_start, end=completed_at)
        if "symbol" not in indexes:
            indexes = header_index_map(headers, column_map)
    updates = []
    for field, value in payload.items():
        if field not in indexes:
            continue
        cell = f"{column_letter(indexes[field])}{excel_row}"
        updates.append({"range": cell, "values": [[value]]})
    return updates


def write_close(trade: TradeIdea) -> list[dict]:
    from trades.services import close_writeback_payload

    payload = close_writeback_payload(trade)
    from trades import runtime_config

    cmap = runtime_config.column_map()
    if not runtime_config.spreadsheet_id():
        return writeback_updates([], trade.sheet_row, payload, cmap)

    ws = _worksheet()
    values = ws.get_all_values()
    header_idx = find_header_row(values)
    headers = values[header_idx] if values else []
    updates = writeback_updates(headers, trade.sheet_row, payload, cmap)
    if (
        trade.status == TradeStatus.CLOSED
        and trade.sheet_row < COMPLETED_ROW_OFFSET
        and _block_starts(headers)[1]
    ):
        updates.extend(
            writeback_updates(headers, trade.sheet_row + COMPLETED_ROW_OFFSET, payload, cmap)
        )
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    return updates


def apply_sheet_row(row: dict) -> TradeIdea:
    defaults = {
        "recommended_qty": row["qty"],
        "buy_low": row["buy_low"],
        "buy_high": row["buy_high"],
        "target": row["target"],
        "stop_loss": row["stop_loss"],
        "notes": row.get("notes") or "",
        "last_synced_at": timezone.now(),
    }
    if row.get("entry_price") is not None:
        defaults["holding_avg_price"] = row["entry_price"]
    if row.get("current_qty") is not None:
        defaults["holding_qty"] = row["current_qty"]
    if row.get("opened_on") is not None:
        defaults["opened_on"] = row["opened_on"]

    trade, _created = TradeIdea.objects.update_or_create(
        exchange=row["exchange"],
        symbol=row["symbol"],
        sheet_row=row["sheet_row"],
        defaults=defaults,
    )
    closed_from_events = sum((e.quantity for e in trade.close_events.all()), Decimal("0"))
    if closed_from_events > 0:
        last_event = trade.close_events.order_by("-created_at").first()
        trade.closed_qty = closed_from_events
        trade.closed_price = last_event.price if last_event else row.get("closed_price")
        held = row.get("current_qty")
        if held is not None:
            trade.remaining_qty = max(held, Decimal("0"))
        else:
            trade.remaining_qty = max(trade.recommended_qty - closed_from_events, Decimal("0"))
        trade.status = (
            TradeStatus.CLOSED if trade.remaining_qty == 0 else TradeStatus.PARTIAL
        )
    else:
        trade.closed_qty = row.get("closed_qty") or Decimal("0")
        trade.closed_price = row.get("closed_price")
        current = row.get("current_qty")
        if row.get("status") == TradeStatus.CLOSED:
            trade.remaining_qty = Decimal("0")
            trade.status = TradeStatus.CLOSED
        elif current is not None:
            trade.remaining_qty = current
            if current > 0 and current < trade.recommended_qty:
                trade.status = TradeStatus.PARTIAL
            elif current == 0 and trade.closed_qty > 0:
                trade.status = TradeStatus.CLOSED
            else:
                trade.status = row.get("status") or TradeStatus.OPEN
        else:
            trade.remaining_qty = max(trade.recommended_qty - trade.closed_qty, Decimal("0"))
            if trade.remaining_qty == 0 and trade.closed_qty > 0:
                trade.status = TradeStatus.CLOSED
            else:
                trade.status = row.get("status") or TradeStatus.OPEN
    trade.save()
    return trade


def write_mapped_payload(trade: TradeIdea, payload: dict) -> list[dict]:
    """Write arbitrary mapped fields for a trade row (used by Zerodha sync)."""
    from trades import runtime_config

    cmap = runtime_config.column_map()
    if not runtime_config.spreadsheet_id():
        return writeback_updates([], trade.sheet_row, payload, cmap)
    ws = _worksheet()
    values = ws.get_all_values()
    header_idx = find_header_row(values)
    headers = values[header_idx] if values else []
    updates = writeback_updates(headers, trade.sheet_row, payload, cmap)
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    return updates


def sync_from_sheet(values: list[list] | None = None) -> list[TradeIdea]:
    from trades import runtime_config
    from trades.models import AppSettings

    if values is None:
        values = fetch_sheet_values()
    cmap = runtime_config.column_map() or None
    trades = [apply_sheet_row(row) for row in parse_rows(values, column_map=cmap)]
    try:
        cfg = AppSettings.load()
        cfg.last_sheet_sync_at = timezone.now()
        cfg.save(update_fields=["last_sheet_sync_at", "updated_at"])
    except Exception:
        pass
    return trades
