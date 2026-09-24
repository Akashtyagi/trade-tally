"""Import Zerodha tradebook worksheets, keep a consolidated ledger, match rounds."""

from __future__ import annotations

import csv
import hashlib
from collections import deque
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from django.utils import timezone

from integrations.sheets import (
    format_qty,
    get_or_create_worksheet,
    normalize_header,
    open_spreadsheet,
    parse_date,
    parse_decimal,
)
from trades.models import (
    CloseEvent,
    CloseSource,
    HoldingSnapshot,
    TradebookFill,
    TradeIdea,
    TradeStatus,
)
from trades.sheet_config import DEFAULT_SHEET_SLUG, sheet_period

IST = ZoneInfo("Asia/Kolkata")

LEDGER_TITLE = "Tradebook - Ledger"
MATCHED_TITLE = "Tradebook - Matched"
RESERVED_TITLES = {LEDGER_TITLE.lower(), MATCHED_TITLE.lower(), "tradebook - consolidated"}

LEDGER_HEADERS = [
    "symbol",
    "isin",
    "trade_date",
    "exchange",
    "segment",
    "series",
    "trade_type",
    "auction",
    "quantity",
    "price",
    "trade_id",
    "order_id",
    "order_execution_time",
    "source_sheet",
    "tracked",
]

MATCHED_HEADERS = [
    "symbol",
    "exchange",
    "dashboard",
    "sheet_row",
    "status",
    "buy_qty",
    "sell_qty",
    "held_qty",
    "avg_buy",
    "avg_sell",
    "realized_pnl",
    "first_buy",
    "last_sell",
    "pattern",
    "closed",
    "source_sheets",
]

FILL_ALIASES = {
    "symbol": ("symbol", "tradingsymbol", "share"),
    "isin": ("isin",),
    "trade_date": ("trade_date", "date"),
    "exchange": ("exchange",),
    "segment": ("segment",),
    "series": ("series",),
    "trade_type": ("trade_type", "type", "side", "transaction_type"),
    "auction": ("auction",),
    "quantity": ("quantity", "qty"),
    "price": ("price", "avg_price", "average_price"),
    "trade_id": ("trade_id",),
    "order_id": ("order_id",),
    "order_execution_time": ("order_execution_time", "fill_timestamp", "trade_time"),
    "source_sheet": ("source_sheet", "source"),
    "tracked": ("tracked",),
}


def is_source_tradebook(title: str) -> bool:
    """Tabs named 'Tradebook - …' except the generated Ledger/Matched sheets."""
    name = (title or "").strip()
    if not name.lower().startswith("tradebook"):
        return False
    return name.lower() not in RESERVED_TITLES


def fill_uid(row: dict) -> str:
    """Stable id: Zerodha trade_id+symbol, or a hash if the CSV omitted trade_id."""
    trade_id = str(row.get("trade_id") or "").strip()
    symbol = str(row.get("symbol") or "").strip().upper()
    if trade_id and symbol:
        return f"{trade_id}:{symbol}"[:128]
    raw = "|".join(
        [
            symbol,
            str(row.get("order_id") or ""),
            str(row.get("quantity") or ""),
            str(row.get("price") or ""),
            str(row.get("filled_at") or row.get("trade_date") or ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:40]


def parse_side(value) -> str:
    text = str(value or "").strip().upper()
    if text in {"B", "BUY"}:
        return "BUY"
    if text in {"S", "SELL"}:
        return "SELL"
    return text


def parse_datetime(value):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, IST)
        return dt.astimezone(IST)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            d = parse_date(text)
            if d is None:
                return None
            dt = datetime(d.year, d.month, d.day)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, IST)
    return dt.astimezone(IST)


def _header_map(headers: list[str]) -> dict[str, int]:
    lookup: dict[str, str] = {}
    for field, names in FILL_ALIASES.items():
        for name in names:
            lookup[name] = field
    indexes: dict[str, int] = {}
    for idx, header in enumerate(headers):
        key = normalize_header(header)
        field = lookup.get(key)
        if field and field not in indexes:
            indexes[field] = idx
    return indexes


def find_tradebook_header_row(values: list[list]) -> int | None:
    needed = {"symbol", "quantity", "price"}
    side_names = {"trade_type", "type", "side", "transaction_type"}
    for idx, row in enumerate(values[:30]):
        norms = {normalize_header(c) for c in row if str(c).strip()}
        if needed <= norms and (norms & side_names or "trade_id" in norms):
            return idx
    return None


def _cell(row: list, indexes: dict[str, int], field: str, default=""):
    idx = indexes.get(field)
    if idx is None or idx >= len(row):
        return default
    return row[idx]


def parse_tradebook_values(values: list[list], *, source_sheet: str = "") -> list[dict]:
    if not values:
        return []
    header_idx = find_tradebook_header_row(values)
    if header_idx is None:
        return []
    indexes = _header_map(values[header_idx])
    if "symbol" not in indexes or "quantity" not in indexes:
        return []
    fills = []
    for row in values[header_idx + 1 :]:
        symbol = str(_cell(row, indexes, "symbol")).strip().upper()
        if not symbol:
            continue
        qty = parse_decimal(_cell(row, indexes, "quantity"), None)
        price = parse_decimal(_cell(row, indexes, "price"), None)
        if qty is None or price is None or qty <= 0:
            continue
        side = parse_side(_cell(row, indexes, "trade_type"))
        if side not in {"BUY", "SELL"}:
            continue
        filled_at = parse_datetime(_cell(row, indexes, "order_execution_time"))
        trade_date = parse_date(_cell(row, indexes, "trade_date"))
        if trade_date is None and filled_at is not None:
            trade_date = filled_at.astimezone(IST).date()
        if trade_date is None:
            continue
        auction_raw = str(_cell(row, indexes, "auction")).strip().lower()
        fill = {
            "symbol": symbol,
            "isin": str(_cell(row, indexes, "isin")).strip(),
            "exchange": str(_cell(row, indexes, "exchange") or "NSE").strip().upper() or "NSE",
            "segment": str(_cell(row, indexes, "segment")).strip().upper(),
            "series": str(_cell(row, indexes, "series")).strip(),
            "side": side,
            "quantity": qty,
            "price": price,
            "trade_date": trade_date,
            "filled_at": filled_at,
            "trade_id": str(_cell(row, indexes, "trade_id")).strip(),
            "order_id": str(_cell(row, indexes, "order_id")).strip(),
            "auction": auction_raw in {"true", "1", "yes"},
            "source_sheet": str(_cell(row, indexes, "source_sheet") or source_sheet).strip()
            or source_sheet,
            "tracked": False,
        }
        fill["uid"] = fill_uid(fill)
        fills.append(fill)
    return fills


def parse_tradebook_csv(path: str | Path, *, source_sheet: str = "") -> list[dict]:
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    return parse_tradebook_values(rows, source_sheet=source_sheet or path.name)


def _stamp(fill: dict) -> datetime:
    filled_at = fill.get("filled_at")
    if isinstance(filled_at, datetime):
        return filled_at
    d = fill["trade_date"]
    return datetime(d.year, d.month, d.day, tzinfo=IST)


def period_of(fills: list[dict]) -> tuple | None:
    dates = [f["trade_date"] for f in fills if f.get("trade_date")]
    if not dates:
        return None
    return min(dates), max(dates)


def fills_in_period(fills: list[dict], period: tuple | None) -> list[dict]:
    """Every fill a dashboard owns. A tab like Aug24-27 spans Aug 2024 to Aug 2027,
    so earlier lots of the same ticker still count against later sells."""
    if period is None:
        return list(fills)
    start, end = period
    return [f for f in fills if start <= f["trade_date"] <= end]


def merge_fills(*groups: list[dict]) -> list[dict]:
    by_uid: dict[str, dict] = {}
    for group in groups:
        for fill in group:
            by_uid[fill["uid"]] = fill
    return sorted(
        by_uid.values(),
        key=lambda f: (_stamp(f), f["uid"]),
    )


def fifo_match(fills: list[dict], *, fallback_avg_buy: Decimal | None = None) -> dict:
    """Walk BUY then SELL in time order to get held qty and realized PnL."""
    ordered = sorted(
        fills,
        key=lambda f: (_stamp(f), f["uid"]),
    )
    lots: deque[list] = deque()
    sell_legs = []
    buy_qty = Decimal("0")
    sell_qty = Decimal("0")
    buy_value = Decimal("0")
    sell_value = Decimal("0")
    first_buy = None
    last_sell = None
    for fill in ordered:
        if fill["side"] == "BUY":
            lots.append([fill["quantity"], fill["price"]])
            buy_qty += fill["quantity"]
            buy_value += fill["quantity"] * fill["price"]
            stamp = _stamp(fill)
            if first_buy is None or stamp < first_buy:
                first_buy = stamp
            continue
        remaining = fill["quantity"]
        realized = Decimal("0")
        matched = Decimal("0")
        while remaining > 0 and lots:
            lot_qty, lot_price = lots[0]
            take = min(lot_qty, remaining)
            realized += (fill["price"] - lot_price) * take
            matched += take
            remaining -= take
            lot_qty -= take
            if lot_qty == 0:
                lots.popleft()
            else:
                lots[0][0] = lot_qty
        if remaining > 0 and fallback_avg_buy is not None:
            realized += (fill["price"] - fallback_avg_buy) * remaining
            matched += remaining
            remaining = Decimal("0")
        sell_qty += fill["quantity"]
        sell_value += fill["quantity"] * fill["price"]
        stamp = _stamp(fill)
        if last_sell is None or stamp > last_sell:
            last_sell = stamp
        sell_legs.append(
            {
                "fill": fill,
                "quantity": fill["quantity"],
                "matched_qty": matched,
                "unmatched_qty": remaining,
                "realized_pnl": realized,
                "price": fill["price"],
            }
        )
    open_qty = sum((lot[0] for lot in lots), Decimal("0"))
    buy_then_sell = bool(first_buy and last_sell and last_sell > first_buy and buy_qty > 0 and sell_qty > 0)
    return {
        "buy_qty": buy_qty,
        "sell_qty": sell_qty,
        "open_qty": open_qty,
        "buy_value": buy_value,
        "sell_value": sell_value,
        "avg_buy": (buy_value / buy_qty) if buy_qty else None,
        "avg_sell": (sell_value / sell_qty) if sell_qty else None,
        "realized_pnl": sum((leg["realized_pnl"] for leg in sell_legs), Decimal("0")),
        "sell_legs": sell_legs,
        "first_buy": first_buy,
        "last_sell": last_sell,
        "buy_then_sell": buy_then_sell,
        "source_sheets": sorted({f.get("source_sheet") or "" for f in ordered if f.get("source_sheet")}),
    }


def _as_date(value):
    if value is None:
        return None
    if hasattr(value, "date") and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.astimezone(IST).date()
    return value


def _replace_tradebook_closes(trade: TradeIdea, match: dict) -> None:
    trade.close_events.filter(source=CloseSource.TRADEBOOK).delete()
    for leg in match["sell_legs"]:
        fill = leg["fill"]
        CloseEvent.objects.create(
            trade=trade,
            quantity=leg["quantity"],
            price=leg["price"],
            realized_pnl=leg["realized_pnl"],
            source=CloseSource.TRADEBOOK,
            fill_key=fill["uid"],
        )


def _kite_held_for_symbol(symbol: str) -> Decimal | None:
    """Sum NSE+BSE snapshot qty. None means Kite has never seen this ticker."""
    from integrations.kite import aggregate_holding

    snaps = list(HoldingSnapshot.objects.filter(symbol=symbol))
    if not snaps:
        return None
    lookup = {
        (row.exchange, row.symbol): {
            "quantity": row.quantity,
            "average_price": row.average_price,
            "last_price": row.last_price,
        }
        for row in snaps
    }
    holding = aggregate_holding(lookup, symbol)
    if holding is None:
        return Decimal("0")
    return Decimal(str(holding.get("quantity") or 0))


def _position_is_flat(trade: TradeIdea, match: dict) -> bool:
    kite_qty = _kite_held_for_symbol(trade.symbol)
    if kite_qty is not None:
        return kite_qty == 0
    return match["open_qty"] == 0


def apply_match_to_trade(trade: TradeIdea, match: dict, *, writeback: bool = True) -> str:
    """Update close events / status from a FIFO match. Returns an action label."""
    if trade.close_events.exclude(source=CloseSource.TRADEBOOK).exists():
        return "skipped_manual"

    kite_qty = _kite_held_for_symbol(trade.symbol)
    held = kite_qty if kite_qty is not None else match["open_qty"]
    first_buy = _as_date(match["first_buy"])
    if trade.opened_on is None and first_buy is not None:
        trade.opened_on = first_buy
    can_settle = trade.opened_on is not None
    flat = _position_is_flat(trade, match)

    if can_settle and match["buy_then_sell"] and flat:
        _replace_tradebook_closes(trade, match)
        trade.status = TradeStatus.CLOSED
        trade.remaining_qty = Decimal("0")
        trade.holding_qty = Decimal("0")
        trade.closed_qty = match["sell_qty"]
        trade.closed_price = match["avg_sell"]
        if trade.opened_on is None and first_buy is not None:
            trade.opened_on = first_buy
        trade.save()
        if writeback:
            from integrations.sheets import write_close

            write_close(trade)
        return "closed"

    if can_settle and match["buy_then_sell"] and match["sell_qty"] > 0 and not flat:
        _replace_tradebook_closes(trade, match)
        trade.status = TradeStatus.PARTIAL
        trade.remaining_qty = held if held > 0 else match["open_qty"]
        trade.holding_qty = trade.remaining_qty
        trade.closed_qty = match["sell_qty"]
        trade.closed_price = match["avg_sell"]
        if trade.opened_on is None and first_buy is not None:
            trade.opened_on = first_buy
        trade.save()
        if writeback:
            from integrations.sheets import write_close

            write_close(trade)
        return "partial"

    trade.save()
    return "fills_only"


def persist_fills(fills: list[dict], tracked_symbols: set[str]) -> int:
    """Upsert TradebookFill rows. tracked=True when the symbol is on a dashboard."""
    now = timezone.now()
    known = {row.uid: row for row in TradebookFill.objects.all()}
    upserted = 0
    for fill in fills:
        tracked = fill["symbol"] in tracked_symbols
        fill["tracked"] = tracked
        defaults = {
            "symbol": fill["symbol"],
            "isin": fill.get("isin") or "",
            "exchange": fill.get("exchange") or "NSE",
            "segment": fill.get("segment") or "",
            "series": fill.get("series") or "",
            "side": fill["side"],
            "quantity": fill["quantity"],
            "price": fill["price"],
            "trade_date": fill["trade_date"],
            "filled_at": fill.get("filled_at"),
            "trade_id": fill.get("trade_id") or "",
            "order_id": fill.get("order_id") or "",
            "auction": bool(fill.get("auction")),
            "source_sheet": fill.get("source_sheet") or "",
            "tracked": tracked,
            "imported_at": now,
        }
        obj = known.get(fill["uid"])
        if obj is None:
            TradebookFill.objects.create(uid=fill["uid"], **defaults)
            upserted += 1
            continue
        dirty = False
        for field, value in defaults.items():
            if getattr(obj, field) != value:
                setattr(obj, field, value)
                dirty = True
        if dirty:
            obj.save()
            upserted += 1
    stale = set(known) - {f["uid"] for f in fills}
    if stale:
        TradebookFill.objects.filter(uid__in=stale).delete()
    return upserted


def _fmt_dt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(IST).replace(tzinfo=None).isoformat(timespec="seconds")
    return str(value)


def fills_to_ledger_rows(fills: list[dict]) -> list[list]:
    rows = [LEDGER_HEADERS]
    for fill in fills:
        rows.append(
            [
                fill["symbol"],
                fill.get("isin") or "",
                fill["trade_date"].isoformat(),
                fill.get("exchange") or "",
                fill.get("segment") or "",
                fill.get("series") or "",
                fill["side"].lower(),
                str(bool(fill.get("auction"))).lower(),
                format_qty(fill["quantity"]),
                format(fill["price"].normalize(), "f"),
                fill.get("trade_id") or "",
                fill.get("order_id") or "",
                _fmt_dt(fill.get("filled_at")),
                fill.get("source_sheet") or "",
                "YES" if fill.get("tracked") else "NO",
            ]
        )
    return rows


def matches_to_rows(matches: list[dict]) -> list[list]:
    rows = [MATCHED_HEADERS]
    for item in matches:
        match = item["match"]
        trade = item["trade"]
        rows.append(
            [
                trade.symbol,
                trade.exchange,
                trade.sheet_slug,
                str(trade.sheet_row),
                trade.status,
                format_qty(match["buy_qty"]),
                format_qty(match["sell_qty"]),
                format_qty(trade.holding_qty),
                "" if match["avg_buy"] is None else format(match["avg_buy"].normalize(), "f"),
                "" if match["avg_sell"] is None else format(match["avg_sell"].normalize(), "f"),
                format(match["realized_pnl"].normalize(), "f"),
                _fmt_dt(match["first_buy"]),
                _fmt_dt(match["last_sell"]),
                "BUY_THEN_SELL" if match["buy_then_sell"] else "",
                "YES" if trade.status == TradeStatus.CLOSED else "NO",
                ", ".join(match["source_sheets"]),
            ]
        )
    return rows


def write_consolidated(spreadsheet, fills: list[dict], matches: list[dict]) -> None:
    ledger = get_or_create_worksheet(spreadsheet, LEDGER_TITLE, rows=max(2000, len(fills) + 10), cols=len(LEDGER_HEADERS))
    matched = get_or_create_worksheet(spreadsheet, MATCHED_TITLE, rows=max(200, len(matches) + 10), cols=len(MATCHED_HEADERS))
    ledger.clear()
    matched.clear()
    ledger_rows = fills_to_ledger_rows(fills)
    matched_rows = matches_to_rows(matches)
    meta = [
        [
            "Last run (IST)",
            timezone.now().astimezone(IST).strftime("%Y-%m-%d %H:%M"),
            "fills",
            str(len(fills)),
            "tracked matches",
            str(len(matches)),
        ]
    ]
    ledger.update("A1", meta + [[]] + ledger_rows, value_input_option="USER_ENTERED")
    matched.update("A1", meta + [[]] + matched_rows, value_input_option="USER_ENTERED")


def list_source_worksheets(spreadsheet) -> list:
    return [ws for ws in spreadsheet.worksheets() if is_source_tradebook(ws.title)]


def ingest_tradebook(
    *,
    write_sheet: bool = True,
    writeback_closes: bool = True,
    csv_paths: list[str] | None = None,
    slug: str | None = None,
    dry_run: bool = False,
    apply_closes: bool = True,
) -> dict:
    """Merge source tabs/CSVs into Ledger + Matched, persist fills, optionally close rounds."""
    tracked_trades = list(TradeIdea.objects.all())
    tracked_symbols = {t.symbol.upper() for t in tracked_trades}

    source_fills: list[dict] = []
    source_names: list[str] = []
    spreadsheet = None
    if csv_paths:
        for path in csv_paths:
            parsed = parse_tradebook_csv(path)
            source_fills.extend(parsed)
            source_names.append(Path(path).name)
    else:
        from trades import runtime_config

        if not runtime_config.spreadsheet_id(slug):
            raise RuntimeError("Google spreadsheet ID is not configured.")
        spreadsheet = open_spreadsheet(slug)
        try:
            ledger_ws = spreadsheet.worksheet(LEDGER_TITLE)
            source_fills.extend(parse_tradebook_values(ledger_ws.get_all_values(), source_sheet=LEDGER_TITLE))
        except Exception:
            pass
        for ws in list_source_worksheets(spreadsheet):
            parsed = parse_tradebook_values(ws.get_all_values(), source_sheet=ws.title)
            period = period_of(parsed)
            source_names.append(ws.title)
            for fill in parsed:
                fill["period"] = period
                source_fills.append(fill)

    merged = merge_fills(source_fills)
    for fill in merged:
        fill["tracked"] = fill["symbol"] in tracked_symbols

    if not dry_run:
        persist_fills(merged, tracked_symbols)

    matches = []
    closed = 0
    partial = 0
    skipped = 0
    sheet_closes: list[TradeIdea] = []
    periods: dict[str, tuple | None] = {}
    for trade in tracked_trades:
        symbol_fills = [f for f in merged if f["symbol"] == trade.symbol.upper()]
        if not symbol_fills:
            continue
        sheet_slug = trade.sheet_slug or DEFAULT_SHEET_SLUG
        if sheet_slug not in periods:
            periods[sheet_slug] = sheet_period(sheet_slug)
        window = fills_in_period(symbol_fills, periods[sheet_slug])
        match = fifo_match(window, fallback_avg_buy=trade.avg_buy())
        if dry_run or not apply_closes:
            matches.append(
                {
                    "trade": trade,
                    "match": match,
                    "action": "dry_run" if dry_run else "fills_only",
                }
            )
            continue
        action = apply_match_to_trade(trade, match, writeback=False)
        trade.refresh_from_db()
        matches.append({"trade": trade, "match": match, "action": action})
        if action == "closed":
            closed += 1
            sheet_closes.append(trade)
        elif action == "partial":
            partial += 1
            sheet_closes.append(trade)
        elif action == "skipped_manual":
            skipped += 1

    if writeback_closes and sheet_closes:
        from collections import defaultdict
        from integrations.sheets import write_closes_bulk

        by_slug: dict[str, list[TradeIdea]] = defaultdict(list)
        for trade in sheet_closes:
            by_slug[trade.sheet_slug or "aug24-27"].append(trade)
        for sheet_slug, group in by_slug.items():
            write_closes_bulk(group, slug=sheet_slug)

    if write_sheet:
        if spreadsheet is None:
            spreadsheet = open_spreadsheet(slug)
        write_consolidated(spreadsheet, merged, matches)

    return {
        "sources": source_names,
        "fills": len(merged),
        "tracked_fills": sum(1 for f in merged if f.get("tracked")),
        "matched_symbols": len(matches),
        "closed": closed,
        "partial": partial,
        "skipped_manual": skipped,
        "ledger": LEDGER_TITLE,
        "matched_sheet": MATCHED_TITLE,
    }
