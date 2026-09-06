"""Parse advisor WhatsApp dumps and map them onto the Aug24-27 sheet contract.

Fill rules: skills/google-sheet/SKILL.md
"""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from django.conf import settings

from integrations.sheets import (
    fetch_sheet_values,
    parse_buy_range,
    parse_decimal,
    _block_starts,
    _complete_indexes,
    _worksheet,
    header_index_map,
)
from trades.models import DEFAULT_COLUMN_MAP

MESSAGE_SPLIT = re.compile(
    r"36 Months Equity Trades 1st August 2024 to 1st August 2027:\s*",
    re.IGNORECASE,
)

SKIP_RE = re.compile(
    r"\b(ipo|gmp|lot size|listing gains|nifty|index|gold|silver|sip only|"
    r"watch video|zoom session|disclaimer and disclosures|"
    r"ratio chart|apply both ipos|apply for)\b",
    re.IGNORECASE,
)
BUY_RE = re.compile(r"\bbuy at\b", re.IGNORECASE)
UPDATE_RE = re.compile(
    r"\b(hit\s+\d+(st|nd|rd|th)\s+target|trade closed|book\s+\d+%|"
    r"book whole|book profit|trail sl|exit at cmp)\b",
    re.IGNORECASE,
)

TICKER_MAP = {
    "amber": "AMBER",
    "iol chemical": "IOLCP",
    "iol chemical & pharma": "IOLCP",
    "iolcp": "IOLCP",
    "pricol": "PRICOL",
    "zen tech": "ZENTEC",
    "zentech": "ZENTEC",
    "grse": "GRSE",
    "bajaj auto": "BAJAJ-AUTO",
    "interglobe aviation": "INDIGO",
    "interglobe aviation (indigo)": "INDIGO",
    "indigo": "INDIGO",
    "nlc india": "NLCINDIA",
    "biocon": "BIOCON",
    "astra microwave": "ASTRAMICRO",
    "phoenix mills": "PHOENIXLTD",
    "gabriel india": "GABRIEL",
    "anthem bio": "ANTHEM",
    "360one wam limited": "360ONE",
    "360one wam": "360ONE",
    "360one": "360ONE",
    "ask automotive": "ASKAUTOLTD",
    "uno minda": "UNOMINDA",
    "endurance technologies": "ENDURANCE",
    "northern arc": "NORTHARC",
    "india glycol": "INDIAGLYCO",
    "lt foods": "LTFOODS",
    "canara bank": "CANBK",
    "anantraj": "ANANTRAJ",
    "anant raj": "ANANTRAJ",
    "caplin point": "CAPLIPOINT",
    "jtekt india": "JTEKTINDIA",
    "tilak nagar": "TI",
    "tilak nagar industries": "TI",
    "azad engineering": "AZAD",
    "aeroflex": "AEROFLEX",
    "imfa": "IMFA",
    "kirloskar pneumatic": "KIRLPNU",
    "kirlosker pneumatic": "KIRLPNU",
    "larsen & toubro": "LT",
    "larsen and toubro": "LT",
    "l&t": "LT",
    "nmdc": "NMDC",
    "sbcl": "SBCL",
    "samhi": "SAMHI",
    "samhi hotels": "SAMHI",
    "himatsingka": "HIMATSEIDE",
    "stylam": "STYLAMIND",
    "stylam industries": "STYLAMIND",
    "texmaco rail": "TEXRAIL",
    "waaree energies": "WAAREEENER",
    "waaree": "WAAREEENER",
    "td power": "TDPOWERSYS",
    "tvs motors": "TVSMOTOR",
    "tvs motor": "TVSMOTOR",
    "star cements": "STARCEMENT",
    "star cement": "STARCEMENT",
    "igil": "IGIL",
}

_TICKER_TOKEN = re.compile(r"^[A-Z][A-Z0-9.&-]{1,20}$")
_NAME_NOISE = re.compile(
    r"\s+(hit\b|book\b|trade closed|stop loss|stoploss|target of).*$",
    re.I,
)

_EMOJI = re.compile(r"[\U00010000-\U0010ffff]|🖼|📢|📎|🟢|🔁")


def split_messages(text: str) -> list[str]:
    parts = MESSAGE_SPLIT.split(text or "")
    return [p.strip() for p in parts if p.strip()]


def classify_message(text: str) -> str:
    """new_buy | update | skip. IPO / index / metal chatter is skipped."""
    body = text.strip()
    if not body:
        return "skip"
    if BUY_RE.search(body):
        if re.search(r"\b(gold|silver|nifty)\b", body, re.I) and not _company_line(body):
            return "skip"
        return "new_buy"
    if UPDATE_RE.search(body):
        return "update"
    if SKIP_RE.search(body):
        return "skip"
    return "skip"


def _company_line(text: str) -> str:
    for raw in text.splitlines():
        line = _EMOJI.sub("", raw).strip()
        line = line.lstrip(": ").strip()
        if not line or line.lower().startswith("disclaimer"):
            continue
        return line
    return ""


def _clean_name(name: str) -> str:
    key = _EMOJI.sub("", name or "").strip().lower()
    key = re.sub(r"\s+", " ", key)
    key = key.split(":")[0].strip()
    key = re.sub(r"\s+buy at.*$", "", key, flags=re.I).strip()
    key = _NAME_NOISE.sub("", key).strip(" .")
    return key


def resolve_ticker(name: str) -> str | None:
    """Map a company line to an NSE ticker via TICKER_MAP, or accept a bare symbol."""
    key = _clean_name(name)
    if not key:
        return None
    if key in TICKER_MAP:
        return TICKER_MAP[key]
    for label, ticker in sorted(TICKER_MAP.items(), key=lambda kv: -len(kv[0])):
        if key == label or key.startswith(label + " ") or label in key:
            return ticker
    # Advisor sometimes uses the NSE ticker as the name (SBCL, IMFA, NMDC).
    token = key.split()[0].upper().replace("\xa0", "")
    if token in {"GOLD", "SILVER", "NIFTY", "AUTO", "IPO"}:
        return None
    if _TICKER_TOKEN.match(token) and " " not in key:
        return token
    return None


def parse_risk_pct(text: str) -> Decimal | None:
    ranged = re.search(
        r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*%",
        text,
    )
    if ranged:
        a = Decimal(ranged.group(1))
        b = Decimal(ranged.group(2))
        return min(a, b)
    single = re.search(
        r"(?:allocation(?: of)?|max allocation)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%",
        text,
        re.I,
    )
    if single:
        return Decimal(single.group(1))
    fallback = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:allocation|max)", text, re.I)
    if fallback:
        return Decimal(fallback.group(1))
    return None


def _money_parts(fragment: str) -> list[Decimal]:
    nums = []
    for raw in re.findall(r"\d[\d,]*", fragment.replace("₹", "")):
        val = parse_decimal(raw)
        if val is not None:
            nums.append(val)
    return nums


_BUY_AT_RE = re.compile(
    r"buy at\s+(?:rs\.?)?\s*([\d,]+(?:\s*[-–&,]\s*(?:rs\.?)?\s*[\d,]+)*)",
    re.I,
)
_DIP_RE = re.compile(
    r"(?:some\s+in\s+)?dips?\s+upto\s+(?:rs\.?)?\s*([\d,]+)",
    re.I,
)


def _buy_at_prices(text: str) -> list[Decimal]:
    match = _BUY_AT_RE.search(text)
    if not match:
        return []
    return _money_parts(match.group(1))


def parse_buy_entry(text: str) -> Decimal | None:
    """Primary 'Buy at' price. Dips are the range floor, not the plan entry."""
    nums = _buy_at_prices(text)
    if not nums:
        return None
    return min(nums)


def parse_buy_levels(text: str) -> tuple[Decimal | None, Decimal | None]:
    nums = _buy_at_prices(text)
    if not nums:
        return None, None
    low, high = min(nums), max(nums)
    dip = _DIP_RE.search(text)
    if dip:
        dip_px = parse_decimal(dip.group(1))
        if dip_px is not None:
            low = min(low, dip_px)
    return low, high


def parse_stop_loss(text: str) -> Decimal | None:
    match = re.search(
        r"(?:stop\s*loss|s\.?l\.?)\s+(?:of\s+)?(?:rs\.?)?\s*([\d,]+)",
        text,
        re.I,
    )
    if not match:
        return None
    return parse_decimal(match.group(1))


def parse_targets(text: str) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    match = re.search(
        r"target(?:s)?\s+(?:range of\s+)?(?:rs\.?)?\s*([\d,.\s\-–]+)",
        text,
        re.I,
    )
    if not match:
        return None, None, None
    nums = _money_parts(match.group(1).split("\n")[0])
    nums = nums[:3]
    while len(nums) < 3:
        nums.append(None)
    return nums[0], nums[1], nums[2]


def suggested_qty(
    *,
    corpus: Decimal,
    risk_pct: Decimal,
    entry: Decimal,
    stop_loss: Decimal,
    max_alloc_pct: Decimal,
) -> Decimal | None:
    if entry <= 0 or corpus <= 0:
        return None
    gap = entry - stop_loss
    if gap <= 0:
        return None
    risk_frac = risk_pct / Decimal("100")
    cap_frac = max_alloc_pct / Decimal("100")
    by_risk = (corpus * risk_frac) / gap
    by_cap = (corpus * cap_frac) / entry
    shares = min(by_risk, by_cap)
    return shares.to_integral_value(rounding=ROUND_DOWN)


def qty_formula(row: int) -> str:
    return (
        f"=MIN(ROUNDDOWN(($A$5*M{row})/(N{row}-V{row}),0),"
        f"ROUNDDOWN(($A$5*$B$2)/N{row},0))"
    )


def max_investment_formula(row: int) -> str:
    return f'=ROUND((P{row}*N{row}),0) & " : " & ROUND((P{row}*N{row})/$A$5*100,1) & "%"'


def tcp_formula(row: int) -> str:
    return f"=DIVIDE(R{row},$A$5)"


def pnl_formula(row: int) -> str:
    return f"=(GOOGLEFINANCE(L{row}) - N{row})"


def sell_ratio_formula(row: int) -> str:
    return f'=(O{row}*0.4)&" - "&(O{row}*0.3)&" - "&(O{row}*0.3)'


def closed_cash_formula(row: int) -> str:
    return f"=MULTIPLY(AF{row},AG{row})"


def closed_pnl_formula(row: int) -> str:
    return f"=PRODUCT(MINUS(AG{row},AE{row}),AF{row})"


def closed_pnl_pct_formula(row: int) -> str:
    return f"=ROUND((AI{row}/(AE{row}*AF{row})),2)"


OPEN_FIRST_ROW = 5
OPEN_SCAN_LAST = 80
STRAY_CLEAR_FROM = 190
CLOSED_FIRST_ROW = 5
CLOSED_SCAN_LAST = 80
_EMPTY = {"", "-", "#div/0!", "#n/a", "#value!", "#ref!", "#name?", "n/a"}


def _cell(values: list[list], excel_row: int, col: int) -> str:
    idx = excel_row - 1
    if idx < 0 or idx >= len(values) or col >= len(values[idx]):
        return ""
    return str(values[idx][col]).strip()


def _is_empty(value) -> bool:
    return str(value or "").strip().lower() in _EMPTY


def last_open_share_row(values: list[list], symbol_col: int = 11) -> int:
    """Last contiguous Share in the J5 open block (ignore stray rows ~199)."""
    last = OPEN_FIRST_ROW - 1
    for excel_row in range(OPEN_FIRST_ROW, min(OPEN_SCAN_LAST, len(values)) + 1):
        if _cell(values, excel_row, symbol_col):
            last = excel_row
    return last


def open_share_rows(values: list[list], symbol_col: int = 11) -> dict[str, int]:
    found = {}
    for excel_row in range(OPEN_FIRST_ROW, min(OPEN_SCAN_LAST, len(values)) + 1):
        symbol = _cell(values, excel_row, symbol_col).upper()
        if symbol:
            found[symbol] = excel_row
    return found


def completed_share_rows(values: list[list], symbol_col: int = 29) -> dict[str, int]:
    found = {}
    for excel_row in range(CLOSED_FIRST_ROW, min(CLOSED_SCAN_LAST, len(values)) + 1):
        symbol = _cell(values, excel_row, symbol_col).upper()
        if symbol:
            found[symbol] = excel_row
    return found


def last_completed_share_row(values: list[list], symbol_col: int = 29) -> int:
    last = CLOSED_FIRST_ROW - 1
    for excel_row in range(CLOSED_FIRST_ROW, min(CLOSED_SCAN_LAST, len(values)) + 1):
        if _cell(values, excel_row, symbol_col):
            last = excel_row
    return last


def open_row_incomplete(values: list[list], excel_row: int) -> bool:
    """True when an existing L row is missing plan fields (range/SL/target/risk)."""
    risk = _cell(values, excel_row, 12)
    entry = _cell(values, excel_row, 13)
    buy = _cell(values, excel_row, 19)
    sl = _cell(values, excel_row, 21)
    t1 = _cell(values, excel_row, 23)
    if _is_empty(entry):
        return True
    if _is_empty(risk):
        return True
    if _is_empty(buy) and _is_empty(sl) and _is_empty(t1):
        return True
    return False


def parse_close_levels(text: str) -> dict:
    entry = None
    bought = re.search(r"bought at\s+(?:rs\.?)?\s*([\d,]+)", text, re.I)
    if bought:
        entry = parse_decimal(bought.group(1))
    exit_price = None
    for pat in (
        r"exit at cmp\s+([\d,]+)",
        r"close(?:e)?(?: balance)?(?: \d+% qty)? at\s+(?:rs\.?)?\s*([\d,]+)",
        r"book profit in rs\.?\s*([\d,]+)",
        r"hit\s+\d+(?:st|nd|rd|th)\s+target(?: of)?(?: rs\.?)?\s*([\d,]+)",
        r"target of rs\.?\s*([\d,]+)\s+hit",
    ):
        hit = re.search(pat, text, re.I)
        if hit:
            exit_price = parse_decimal(hit.group(1))
            break
    qty = None
    qhit = re.search(r"(?:book(?:ed)?|close)\s+(\d+)%\s+qty", text, re.I)
    if qhit:
        qty = None  # percent of holding — do not invent share count
    return {"entry": entry, "exit": exit_price, "qty": qty}


def _risk_cell(pct: Decimal | None) -> str:
    if pct is None:
        return ""
    return str((pct / Decimal("100")).normalize())


def _a1(col_letter: str, row: int, value) -> dict:
    return {"range": f"{col_letter}{row}", "values": [[value]]}


def parse_new_buy(text: str) -> dict | None:
    company = _company_line(text)
    ticker = resolve_ticker(company)
    buy_low, buy_high = parse_buy_levels(text)
    if buy_low is None:
        return None
    entry = parse_buy_entry(text) or buy_low
    sl = parse_stop_loss(text)
    t1, t2, t3 = parse_targets(text)
    risk = parse_risk_pct(text)
    comments = " ".join(
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lower().startswith("disclaimer")
    )
    return {
        "company": company,
        "ticker": ticker,
        "buy_low": buy_low,
        "buy_high": buy_high,
        "entry": entry,
        "stop_loss": sl,
        "target": t1,
        "target_2": t2,
        "target_3": t3,
        "risk_pct": risk,
        "comments": comments[:2000],
        "kind": "new_buy",
        "raw": text,
    }


def parse_update(text: str) -> dict:
    company = _company_line(text)
    levels = parse_close_levels(text)
    closed = bool(
        re.search(r"\b(trade closed|exit at cmp|book whole|book profit)\b", text, re.I)
    )
    return {
        "company": company,
        "ticker": resolve_ticker(company),
        "kind": "update",
        "closed": closed,
        "entry": levels["entry"],
        "exit": levels["exit"],
        "comments": text.strip()[:2000],
        "raw": text,
    }


def parse_dump(text: str) -> dict:
    new_buys = []
    updates = []
    skipped = 0
    unknown = []
    for block in split_messages(text):
        kind = classify_message(block)
        if kind == "skip":
            skipped += 1
            continue
        if kind == "new_buy":
            row = parse_new_buy(block)
            if not row:
                skipped += 1
                continue
            if not row["ticker"]:
                unknown.append(row["company"])
            new_buys.append(row)
            continue
        upd = parse_update(block)
        if not upd["ticker"]:
            unknown.append(upd["company"])
        updates.append(upd)
    return {
        "new_buys": new_buys,
        "updates": updates,
        "skipped": skipped,
        "unknown_names": sorted({n for n in unknown if n}),
    }


def load_dump(path: str | Path | None = None) -> str:
    path = Path(path or (settings.BASE_DIR / "zerodha_files" / "trades.txt"))
    return path.read_text(encoding="utf-8")


def _open_indexes(headers, column_map):
    active_start, completed_at = _block_starts(headers)
    indexes = header_index_map(headers, column_map, start=active_start, end=completed_at)
    indexes = _complete_indexes(
        headers, indexes, start=active_start, end=completed_at, completed=False
    )
    # Live qty formula uses column M as risk % even when that header still says Share.
    if "risk_pct" not in indexes:
        indexes["risk_pct"] = 12
    return indexes


def _format_pct(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value}%"


def _format_range(low, high) -> str:
    if low is None:
        return ""
    lo = _format_num(low)
    if high is None or high == low:
        return f"{lo}-{lo}"
    return f"{lo}-{_format_num(high)}"


def _format_num(value) -> str:
    if value is None:
        return ""
    as_int = value.to_integral_value()
    if as_int == value:
        return str(int(as_int))
    return format(value, "f")


def buy_range_patches_from_comments(values: list[list]) -> list[dict]:
    """Open rows whose Comments imply a wider Buy Range than column T."""
    patches = []
    for excel_row in range(OPEN_FIRST_ROW, min(OPEN_SCAN_LAST, len(values)) + 1):
        symbol = _cell(values, excel_row, 11)
        if not symbol:
            continue
        comments = _cell(values, excel_row, 26)
        low, high = parse_buy_levels(comments)
        if low is None or high is None:
            continue
        current_low, current_high = parse_buy_range(_cell(values, excel_row, 19))
        if current_low == low and current_high == high:
            continue
        patches.append(
            {
                "sheet_row": excel_row,
                "ticker": symbol,
                "buy_low": low,
                "buy_high": high,
                "buy_range": _format_range(low, high),
                "was": _cell(values, excel_row, 19),
            }
        )
    return patches


def repair_buy_ranges_from_comments(
    *, slug: str | None = None, dry_run: bool = False
) -> dict:
    from trades.sheet_config import primary_slug

    sheet_slug = slug or primary_slug()
    values = fetch_sheet_values(sheet_slug)
    patches = buy_range_patches_from_comments(values)
    if dry_run or not patches:
        return {"patches": patches, "cells": 0, "dry_run": True if dry_run or not values else False}
    updates = [_a1("T", item["sheet_row"], item["buy_range"]) for item in patches]
    _worksheet(sheet_slug).batch_update(updates, value_input_option="USER_ENTERED")
    return {"patches": patches, "cells": len(updates), "dry_run": False}


def _open_plan_updates(row_n: int, rec: dict, *, only_empty: bool, values: list[list]) -> list[dict]:
    """Write J–Z plan cells. When only_empty, skip cells that already have values."""
    sl = rec.get("stop_loss")
    entry = rec.get("entry")
    can_qty = entry and sl and entry > sl
    cells = {
        "L": rec["ticker"],
        "M": _risk_cell(rec.get("risk_pct")),
        "N": _format_num(entry),
        "P": qty_formula(row_n) if can_qty else "",
        "Q": max_investment_formula(row_n),
        "S": tcp_formula(row_n),
        "T": _format_range(rec.get("buy_low"), rec.get("buy_high")),
        "U": pnl_formula(row_n),
        "V": _format_num(sl),
        "W": sell_ratio_formula(row_n),
        "X": _format_num(rec.get("target")),
        "Y": _format_num(rec.get("target_2")),
        "Z": _format_num(rec.get("target_3")),
        "AA": rec.get("comments") or "",
    }
    col_index = {
        "L": 11,
        "M": 12,
        "N": 13,
        "P": 15,
        "Q": 16,
        "S": 18,
        "T": 19,
        "U": 20,
        "V": 21,
        "W": 22,
        "X": 23,
        "Y": 24,
        "Z": 25,
        "AA": 26,
    }
    out = []
    for letter, value in cells.items():
        if value == "":
            continue
        if only_empty and not _is_empty(_cell(values, row_n, col_index[letter])):
            continue
        out.append(_a1(letter, row_n, value))
    return out


def ingest_recommendations(
    *,
    path: str | Path | None = None,
    slug: str | None = None,
    dry_run: bool = False,
    live_prices: dict[str, Decimal] | None = None,
    update_existing: bool = True,
) -> dict:
    """Parse trades.txt and write missing open-block rows using sheet formulas."""
    from trades import runtime_config
    from trades.sheet_config import primary_slug

    parsed = parse_dump(load_dump(path))
    sheet_slug = slug or primary_slug()
    values = fetch_sheet_values(sheet_slug) if runtime_config.spreadsheet_id(sheet_slug) else []
    skipped_unknown = []
    skipped_complete = []
    pending: dict[str, dict] = {}
    for rec in parsed["new_buys"]:
        ticker = rec["ticker"]
        if not ticker:
            skipped_unknown.append(rec["company"])
            continue
        entry = rec["entry"]
        if live_prices and ticker in live_prices and live_prices[ticker] < entry:
            entry = live_prices[ticker]
        pending[ticker] = {**rec, "entry": entry, "ticker": ticker}

    row_of = open_share_rows(values) if values else {}
    closed_of = completed_share_rows(values) if values else {}
    last_open = last_open_share_row(values) if values else OPEN_FIRST_ROW - 1
    last_closed = last_completed_share_row(values) if values else CLOSED_FIRST_ROW - 1
    next_open = last_open + 1
    next_closed = last_closed + 1

    planned_writes = []
    closed_writes = []
    updates = []

    if values:
        for excel_row in range(STRAY_CLEAR_FROM, min(len(values), 230) + 1):
            if _cell(values, excel_row, 11):
                for letter in ("J", "K", "L", "M", "N", "P", "Q", "S", "T", "V", "X", "Y", "Z", "AA"):
                    updates.append(_a1(letter, excel_row, ""))

    for rec in pending.values():
        ticker = rec["ticker"]
        if ticker in row_of:
            row_n = row_of[ticker]
            if not open_row_incomplete(values, row_n):
                skipped_complete.append(ticker)
                continue
            if not update_existing:
                skipped_complete.append(ticker)
                continue
            updates.extend(_open_plan_updates(row_n, rec, only_empty=True, values=values))
            planned_writes.append({**rec, "sheet_row": row_n, "action": "fill"})
            continue
        row_n = next_open
        next_open += 1
        updates.extend(_open_plan_updates(row_n, rec, only_empty=False, values=values))
        planned_writes.append({**rec, "sheet_row": row_n, "action": "append"})
        row_of[ticker] = row_n

    for upd in parsed["updates"]:
        ticker = upd.get("ticker")
        if not ticker:
            skipped_unknown.append(upd["company"])
            continue
        if not upd.get("closed"):
            continue
        if ticker in closed_of:
            continue
        row_n = next_closed
        next_closed += 1
        updates.extend(
            [
                _a1("AD", row_n, ticker),
                _a1("AH", row_n, closed_cash_formula(row_n)),
                _a1("AI", row_n, closed_pnl_formula(row_n)),
                _a1("AJ", row_n, closed_pnl_pct_formula(row_n)),
                _a1("AL", row_n, (upd.get("comments") or "")[:800]),
            ]
        )
        if upd.get("entry") is not None:
            updates.append(_a1("AE", row_n, _format_num(upd["entry"])))
        if upd.get("exit") is not None:
            updates.append(_a1("AG", row_n, _format_num(upd["exit"])))
        closed_of[ticker] = row_n
        closed_writes.append({"ticker": ticker, "sheet_row": row_n})

    if dry_run or not values:
        return {
            **parsed,
            "writes": planned_writes,
            "closed_writes": closed_writes,
            "patched": closed_writes,
            "skipped_unknown": skipped_unknown,
            "skipped_existing": skipped_complete,
            "cells": 0,
            "dry_run": True,
            "next_open": next_open,
            "next_closed": next_closed,
        }

    if updates:
        _worksheet(sheet_slug).batch_update(updates, value_input_option="USER_ENTERED")
    return {
        **parsed,
        "writes": planned_writes,
        "closed_writes": closed_writes,
        "patched": closed_writes,
        "skipped_unknown": skipped_unknown,
        "skipped_existing": skipped_complete,
        "cells": len(updates),
        "dry_run": False,
        "next_open": next_open,
        "next_closed": next_closed,
    }
