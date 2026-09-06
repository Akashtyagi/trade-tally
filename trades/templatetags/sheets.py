"""Template helpers: INR grouping and primary-vs-secondary sheet URLs."""

from django import template
from django.urls import reverse

from trades.money import format_inr
from trades.sheet_config import primary_slug

register = template.Library()


@register.filter(name="inr")
def inr(value) -> str:
    return format_inr(value)


@register.simple_tag
def sheet_home(slug=None):
    """Landing URL for a sheet: '/' for primary, '/s/<slug>/' otherwise."""
    want = slug or primary_slug()
    if want == primary_slug():
        return reverse("dashboard")
    return reverse("sheet_dashboard", args=[want])


@register.filter
def dict_get(mapping, key):
    if not mapping:
        return ""
    return mapping.get(key, "")
