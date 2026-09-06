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

from trades.models import HoldingSnapshot, TradeIdea, TradeStatus

# Closed-block rows are stored with this offset so they do not collide with
# an open trade on the same Excel row (same symbol can appear in both tables).
COMPLETED_ROW_OFFSET = 1_000_000

OPEN_BLOCK_FIRST_ROW = 5
OPEN_BLOCK_SCAN_LAST = 80
OPEN_SYMBOL_COL = 11  # L
CLOSED_SYMBOL_COL = 29  # AD

OPEN_PLAN_CLEAR_LETTERS = (
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
    "AA",
)
CLOSED_PLAN_CLEAR_LETTERS = ("AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK", "AL")

SHEET_ERRORS = {"#div/0!", "#n/a", "#value!", "#ref!", "#name?", "n/a"}

# Canonical field -> accepted header spellings after normalize_header()
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "share", "ticker"),
    "qty": (
        "qty",
        "recommended_qty",
        "minimum_shares_recom",
        "maximum_shares_recom",
        "min_shares_recom",
        "max_shares_recom",
        "shares_recommended",
    ),
    "current_qty": ("current_quantity", "current_qty"),
    "entry_price": ("entry_price", "recommended_price"),
    "buy_low": ("buy_low",),
    "buy_high": ("buy_high",),
    "buy_range": ("buy_range",),
    "risk_pct": ("risk_percentage", "risk_percent"),
    "target": ("first_target", "target"),
    "target_2": ("second_target",),
    "target_3": ("third_target", "thrid_target"),
    "tcp": (
        "tcp",
        "total_capital_percentage",
        "total_captial_percentage",
        "total_capital_percentage_tcp",
    ),
    "max_investment": (
        "max_investment",
        "maximum_investment_suggested",
        "max_investment_suggested",
        "max_investment_in_share",
    ),
    "stop_loss": ("stop_loss", "sl"),
    "status": ("status",),
    "closed_qty": ("closed_qty", "completed_quantity"),
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


def ltp_from_sheet_pnl(entry, current_pnl, qty=None) -> Decimal | None:
    """Turn sheet Current P/L into LTP. Column U is GOOGLEFINANCE(L)-N (per share)."""
    if entry is None or current_pnl is None:
        return None
    if abs(current_pnl) < entry:
        return entry + current_pnl
    if qty is not None and qty > 0:
        per_share = current_pnl / qty
        if abs(per_share) < entry:
            return entry + per_share
    return None


def parse_tcp(value) -> Decimal | None:
    """Parse '1.39%', '6', or '72000 : 6.0%' into a percent number."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in SHEET_ERRORS:
        return None
    if ":" in text:
        text = text.split(":")[-1].strip()
    return parse_decimal(text)


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
    qty_names = {
        "qty",
        "recommended_qty",
        "minimum_shares_recom",
        "maximum_shares_recom",
        "min_shares_recom",
        "max_shares_recom",
        "shares_recommended",
        "current_quantity",
        "quantity",
    }
    for idx, row in enumerate(values[:40]):
        norms = {normalize_header(c) for c in row if str(c).strip()}
        has_symbol = bool(norms & {"share", "symbol", "ticker"})
        has_qty = bool(norms & qty_names)
        has_block = "s_no" in norms
        if has_symbol and (has_qty or has_block):
            return idx
    return 0


def _scan_header(headers: list[str], start: int, end: int | None, names: set[str]) -> int | None:
    stop = end if end is not None else len(headers)
    for idx in range(start, min(stop, len(headers))):
        if normalize_header(headers[idx]) in names:
            return idx
    return None


def _complete_indexes(
    headers: list[str],
    indexes: dict[str, int],
    *,
    start: int = 0,
    end: int | None = None,
    completed: bool = False,
) -> dict[str, int]:
    """Fill qty / current qty / closed qty from common workbook spellings."""
    if "qty" not in indexes:
        hit = _scan_header(
            headers,
            start,
            end,
            {
                "qty",
                "recommended_qty",
                "minimum_shares_recom",
                "maximum_shares_recom",
                "min_shares_recom",
                "max_shares_recom",
                "shares_recommended",
            },
        )
        if hit is not None:
            indexes["qty"] = hit
    if completed:
        if "closed_qty" not in indexes:
            hit = _scan_header(headers, start, end, {"quantity", "closed_qty", "completed_quantity"})
            if hit is not None:
                indexes["closed_qty"] = hit
    else:
        if "current_qty" not in indexes:
            hit = _scan_header(headers, start, end, {"current_quantity", "current_qty", "quantity"})
            if hit is not None:
                indexes["current_qty"] = hit
    return indexes


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
    return bool(re.match(r"^[A-Z0-9][A-Z0-9.&-]{0,31}$", text))


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
    current_pnl = parse_decimal(_cell(raw, indexes, "current_pnl"))
    last_ltp = ltp_from_sheet_pnl(entry, current_pnl, held if held else qty)
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
        "target_2": parse_decimal(_cell(raw, indexes, "target_2"), Decimal("0")) or Decimal("0"),
        "target_3": parse_decimal(_cell(raw, indexes, "target_3"), Decimal("0")) or Decimal("0"),
        "tcp": parse_tcp(_cell(raw, indexes, "tcp")),
        "stop_loss": parse_decimal(_cell(raw, indexes, "stop_loss"), Decimal("0")) or Decimal("0"),
        "status": parse_status(_cell(raw, indexes, "status")),
        "closed_qty": Decimal("0"),
        "closed_price": None,
        "notes": _cell(raw, indexes, "notes").strip(),
        "opened_on": parse_date(_cell(raw, indexes, "date")),
        "last_ltp": last_ltp,
    }


def _trade_from_completed(raw: list[str], indexes: dict[str, int], excel_row: int) -> dict | None:
    """Right-hand 'trade completed' block. sheet_row += COMPLETED_ROW_OFFSET so it cannot clash."""
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
        "target_2": Decimal("0"),
        "target_3": Decimal("0"),
        "tcp": None,
        "stop_loss": Decimal("0"),
        "status": TradeStatus.CLOSED,
        "closed_qty": closed_qty,
        "closed_price": closed_price,
        "notes": _cell(raw, indexes, "notes").strip(),
        "opened_on": None,
        "last_ltp": None,
    }


def parse_rows(values: list[list], column_map: dict[str, str] | None = None) -> list[dict]:
    """Parse sheet values into trade dicts. Header row is detected, not assumed row 1."""
    if not values:
        return []
    header_idx = find_header_row(values)
    headers = values[header_idx]
    active_start, completed_at = _block_starts(headers)
    active_indexes = header_index_map(headers, column_map, start=active_start, end=completed_at)
    active_indexes = _complete_indexes(
        headers, active_indexes, start=active_start, end=completed_at, completed=False
    )
    if "symbol" not in active_indexes:
        active_indexes = header_index_map(headers, column_map)
        active_indexes = _complete_indexes(headers, active_indexes, completed=False)
    if "symbol" not in active_indexes:
        raise ValueError("Sheet is missing a symbol column.")

    completed_indexes = (
        header_index_map(headers, column_map, start=completed_at) if completed_at else {}
    )
    if completed_indexes:
        completed_indexes = _complete_indexes(
            headers, completed_indexes, start=completed_at, completed=True
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


def open_spreadsheet(slug: str | None = None):
    """Google Sheets API via the service-account JSON (not Kite)."""
    import gspread
    from trades import runtime_config

    sid = runtime_config.spreadsheet_id(slug)
    if not sid:
        raise RuntimeError("Google spreadsheet ID is not configured.")
    gc = gspread.service_account(filename=settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    return gc.open_by_key(sid)


def get_or_create_worksheet(spreadsheet, title: str, *, rows: int = 2000, cols: int = 20):
    import gspread

    try:
        return spreadsheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def _worksheet(slug: str | None = None):
    from trades import runtime_config

    spreadsheet = open_spreadsheet(slug)
    name = runtime_config.worksheet_name(slug)
    if not name or name in {"*", "0"}:
        return spreadsheet.get_worksheet(0)
    return spreadsheet.worksheet(name)


def fetch_sheet_values(slug: str | None = None) -> list[list]:
    """Read the whole worksheet. Empty spreadsheet id → [] (tests / dry config)."""
    from trades import runtime_config

    if not runtime_config.spreadsheet_id(slug):
        return []
    return _worksheet(slug).get_all_values()


def column_letter(index_zero_based: int) -> str:
    index = index_zero_based + 1
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _excel_row(sheet_row: int) -> int:
    return sheet_row if sheet_row < COMPLETED_ROW_OFFSET else sheet_row - COMPLETED_ROW_OFFSET


def header_indexes_for_row(headers: list[str], sheet_row: int, column_map=None) -> dict[str, int]:
    """Column indexes for one trade row (open block vs completed block)."""
    active_start, completed_at = _block_starts(headers)
    if sheet_row >= COMPLETED_ROW_OFFSET and completed_at:
        indexes = header_index_map(headers, column_map, start=completed_at)
        return _complete_indexes(headers, indexes, start=completed_at, completed=True)
    indexes = header_index_map(headers, column_map, start=active_start, end=completed_at)
    indexes = _complete_indexes(
        headers, indexes, start=active_start, end=completed_at, completed=False
    )
    if "symbol" not in indexes:
        indexes = header_index_map(headers, column_map)
        indexes = _complete_indexes(headers, indexes, completed=False)
    return indexes


def writeback_updates(headers: list[str], sheet_row: int, payload: dict, column_map=None) -> list[dict]:
    """Build gspread batch_update entries. Completed-block rows subtract COMPLETED_ROW_OFFSET."""
    excel_row = _excel_row(sheet_row)
    indexes = header_indexes_for_row(headers, sheet_row, column_map)
    updates = []
    for field, value in payload.items():
        if field not in indexes:
            continue
        cell = f"{column_letter(indexes[field])}{excel_row}"
        updates.append({"range": cell, "values": [[value]]})
    return updates


def format_qty(qty) -> str:
    value = Decimal(str(qty or 0))
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def held_qty_differs(sheet_value, kite_qty) -> bool:
    """True when the sheet's held/Quantity cell does not match Kite."""
    kite = Decimal(str(kite_qty or 0))
    parsed = parse_decimal(sheet_value, None)
    if parsed is None:
        return kite != 0
    return parsed != kite


def kite_held_qty(lookup: dict, trade: TradeIdea) -> Decimal:
    """Zerodha is source of truth: missing from holdings means held qty is 0."""
    from integrations.kite import aggregate_holding

    row = aggregate_holding(lookup, trade.symbol)
    if not row:
        return Decimal("0")
    return Decimal(str(row.get("quantity") or 0))


def mapped_cell_value(
    values: list[list], headers: list, trade: TradeIdea, field: str, column_map
) -> str | None:
    """Sheet cell for a mapped field. None means the column is not on this tab."""
    indexes = header_indexes_for_row(headers, trade.sheet_row, column_map)
    col = indexes.get(field)
    if col is None:
        return None
    row_i = _excel_row(trade.sheet_row) - 1
    if row_i < 0 or row_i >= len(values):
        return ""
    row = values[row_i]
    if col >= len(row):
        return ""
    return row[col]


def _current_qty_from_values(values: list[list], headers: list, trade: TradeIdea, column_map) -> str | None:
    return mapped_cell_value(values, headers, trade, "current_qty", column_map)


def _numeric_differs(sheet_value, new_value) -> bool:
    parsed_old = parse_decimal(sheet_value, None)
    parsed_new = parse_decimal(new_value, None)
    if parsed_old is None:
        return parsed_new is not None and parsed_new != 0
    if parsed_new is None:
        return True
    return parsed_old != parsed_new


def write_sheet_payloads_bulk(
    items: list[tuple[TradeIdea, dict]],
    slug: str | None = None,
    *,
    skip_unchanged: bool = False,
) -> list[dict]:
    """One worksheet open, one get_all_values, one batch_update."""
    from trades import runtime_config

    if not items:
        return []
    slug = slug or getattr(items[0][0], "sheet_slug", None)
    cmap = runtime_config.column_map(slug)
    ws = None
    values: list[list] = []
    headers: list[str] = []
    if runtime_config.spreadsheet_id(slug):
        ws = _worksheet(slug)
        values = ws.get_all_values()
        headers = values[find_header_row(values)] if values else []

    updates = []
    for trade, payload in items:
        to_write = payload
        if skip_unchanged and headers:
            to_write = {}
            for field, value in payload.items():
                existing = mapped_cell_value(values, headers, trade, field, cmap)
                if existing is None:
                    continue
                differs = (
                    held_qty_differs(existing, value)
                    if field == "current_qty"
                    else _numeric_differs(existing, value)
                )
                if differs:
                    to_write[field] = value
        if to_write:
            updates.extend(writeback_updates(headers, trade.sheet_row, to_write, cmap))
    if ws is not None and updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    return updates


def write_held_quantities_if_changed(
    items: list[tuple[TradeIdea, Decimal]],
    slug: str | None = None,
) -> list[dict]:
    """Update the sheet Quantity/current_qty cells only when they differ from Kite."""
    return write_sheet_payloads_bulk(
        [(trade, {"current_qty": format_qty(qty)}) for trade, qty in items],
        slug=slug,
        skip_unchanged=True,
    )


def write_zerodha_holdings(
    items: list[tuple[TradeIdea, Decimal]],
    slug: str | None = None,
) -> list[dict]:
    """Write held qty (O) and total investment (R) in one read and one write."""
    payloads = []
    for trade, qty in items:
        payloads.append(
            (
                trade,
                {
                    "current_qty": format_qty(qty),
                    "total_investment": str(qty * trade.avg_buy()),
                },
            )
        )
    return write_sheet_payloads_bulk(payloads, slug=slug, skip_unchanged=True)


def write_close(trade: TradeIdea) -> list[dict]:
    from trades.services import close_writeback_payload

    payload = close_writeback_payload(trade)
    from trades import runtime_config

    slug = getattr(trade, "sheet_slug", None)
    cmap = runtime_config.column_map(slug)
    if not runtime_config.spreadsheet_id(slug):
        return writeback_updates([], trade.sheet_row, payload, cmap)

    ws = _worksheet(slug)
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


def write_closes_bulk(trades: list[TradeIdea], slug: str | None = None) -> list[dict]:
    """One read + one write for every close/partial writeback on a tab."""
    from trades.services import close_writeback_payload
    from trades import runtime_config

    if not trades:
        return []
    slug = slug or getattr(trades[0], "sheet_slug", None)
    cmap = runtime_config.column_map(slug)
    if not runtime_config.spreadsheet_id(slug):
        updates = []
        for trade in trades:
            updates.extend(writeback_updates([], trade.sheet_row, close_writeback_payload(trade), cmap))
        return updates

    ws = _worksheet(slug)
    values = ws.get_all_values()
    headers = values[find_header_row(values)] if values else []
    updates = []
    completed_at = _block_starts(headers)[1]
    for trade in trades:
        payload = close_writeback_payload(trade)
        updates.extend(writeback_updates(headers, trade.sheet_row, payload, cmap))
        if (
            trade.status == TradeStatus.CLOSED
            and trade.sheet_row < COMPLETED_ROW_OFFSET
            and completed_at
        ):
            updates.extend(
                writeback_updates(headers, trade.sheet_row + COMPLETED_ROW_OFFSET, payload, cmap)
            )
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    return updates


def _grid_symbol(values: list[list], excel_row: int, col: int) -> str:
    idx = excel_row - 1
    if idx < 0 or idx >= len(values) or col >= len(values[idx]):
        return ""
    return str(values[idx][col]).strip().upper()


def _clear_row_updates(excel_row: int, letters: tuple[str, ...]) -> list[dict]:
    return [{"range": f"{letter}{excel_row}", "values": [[""]]} for letter in letters]


def trade_plan_clear_updates(values: list[list], trade: TradeIdea) -> list[dict]:
    """Build batch_update entries that wipe open J:AA and completed AC:AL rows for a symbol."""
    symbol = trade.symbol.upper()
    open_rows: set[int] = set()
    closed_rows: set[int] = set()
    for excel_row in range(OPEN_BLOCK_FIRST_ROW, min(OPEN_BLOCK_SCAN_LAST, len(values)) + 1):
        if _grid_symbol(values, excel_row, OPEN_SYMBOL_COL) == symbol:
            open_rows.add(excel_row)
    for excel_row in range(OPEN_BLOCK_FIRST_ROW, min(OPEN_BLOCK_SCAN_LAST, len(values)) + 1):
        if _grid_symbol(values, excel_row, CLOSED_SYMBOL_COL) == symbol:
            closed_rows.add(excel_row)
    if trade.sheet_row < COMPLETED_ROW_OFFSET:
        open_rows.add(trade.sheet_row)
    else:
        closed_rows.add(_excel_row(trade.sheet_row))
    updates: list[dict] = []
    for row in sorted(open_rows):
        updates.extend(_clear_row_updates(row, OPEN_PLAN_CLEAR_LETTERS))
    for row in sorted(closed_rows):
        updates.extend(_clear_row_updates(row, CLOSED_PLAN_CLEAR_LETTERS))
    return updates


def clear_trade_from_sheet(trade: TradeIdea) -> list[dict]:
    """Clear every open/completed sheet row for this trade's symbol."""
    from trades import runtime_config

    slug = getattr(trade, "sheet_slug", None)
    if not runtime_config.spreadsheet_id(slug):
        return []
    ws = _worksheet(slug)
    values = ws.get_all_values()
    updates = trade_plan_clear_updates(values, trade)
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    return updates


def apply_sheet_row(row: dict) -> TradeIdea:
    defaults = {
        "recommended_qty": row["qty"],
        "buy_low": row["buy_low"],
        "buy_high": row["buy_high"],
        "target": row["target"],
        "target_2": row.get("target_2") or Decimal("0"),
        "target_3": row.get("target_3") or Decimal("0"),
        "tcp_percent": row.get("tcp"),
        "stop_loss": row["stop_loss"],
        "notes": row.get("notes") or "",
        "last_synced_at": timezone.now(),
    }
    if row.get("entry_price") is not None:
        defaults["holding_avg_price"] = row["entry_price"]
    if row.get("opened_on") is not None:
        defaults["opened_on"] = row["opened_on"]
    if row.get("last_ltp") is not None:
        defaults["last_ltp"] = row["last_ltp"]

    # A prior Zerodha sync wins over the sheet Quantity cell.
    kite_snap = (
        HoldingSnapshot.objects.filter(symbol=row["symbol"]).order_by("-quantity").first()
    )
    if kite_snap is None and row.get("current_qty") is not None:
        defaults["holding_qty"] = row["current_qty"]

    trade, _created = TradeIdea.objects.update_or_create(
        sheet_slug=row.get("sheet_slug") or "aug24-27",
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
    if kite_snap is not None and trade.status != TradeStatus.CLOSED:
        # Sheet sync must not overwrite live Kite qty with a stale Quantity cell.
        trade.holding_qty = kite_snap.quantity
        trade.remaining_qty = kite_snap.quantity
        trade.holding_avg_price = kite_snap.average_price or trade.holding_avg_price
    trade.save()
    return trade


def write_mapped_payload(trade: TradeIdea, payload: dict) -> list[dict]:
    """Write arbitrary mapped fields for one trade row (one read + one write)."""
    return write_sheet_payloads_bulk([(trade, payload)], slug=getattr(trade, "sheet_slug", None))


def sync_from_sheet(values: list[list] | None = None, slug: str | None = None) -> list[TradeIdea]:
    """Pull one worksheet into TradeIdea rows. Does not call Kite."""
    from trades import runtime_config
    from trades.sheet_config import primary_slug, update_sheet_state

    sheet_slug = slug or primary_slug()
    if values is None:
        values = fetch_sheet_values(sheet_slug)
    cmap = runtime_config.column_map(sheet_slug) or None
    rows = parse_rows(values, column_map=cmap)
    trades = []
    for row in rows:
        row["sheet_slug"] = sheet_slug
        trades.append(apply_sheet_row(row))
    portfolio = parse_portfolio_config(values, runtime_config.summary_map(sheet_slug))
    serializable = {
        key: (str(val) if val is not None else None) for key, val in portfolio.items()
    }
    try:
        update_sheet_state(
            sheet_slug,
            last_sheet_sync_at=timezone.now().isoformat(),
            portfolio=serializable,
        )
    except Exception:
        pass
    return trades
