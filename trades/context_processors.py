"""Nav sheets for the collapsible sidebar."""

from trades.sheet_config import get_sheet, list_sheets, primary_slug


def sheets_nav(request):
    try:
        sheets = list_sheets()
        primary = primary_slug()
    except Exception:
        return {}
    current = None
    match = getattr(request, "resolver_match", None)
    kwargs = getattr(match, "kwargs", None) or {}
    slug = kwargs.get("sheet_slug")
    if slug:
        current = get_sheet(slug)
    if current is None:
        current = get_sheet(primary)
    return {
        "nav_sheets": sheets,
        "primary_slug": primary,
        "current_sheet": current,
    }
