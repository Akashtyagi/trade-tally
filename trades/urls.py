"""Public UI routes. Kite's default redirect is /callback, not /kite/callback/."""

from django.urls import path

from trades import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("s/<slug:sheet_slug>/", views.dashboard, name="sheet_dashboard"),
    path("config/", views.config_view, name="app_config"),
    path("sheets/<slug:sheet_slug>/primary/", views.set_primary_view, name="set_primary"),
    path("sheets/<slug:sheet_slug>/delete/", views.delete_sheet_view, name="delete_sheet"),
    path("trades/<int:pk>/", views.trade_detail, name="trade_detail"),
    path("trades/<int:pk>/close/", views.close_trade_view, name="close_trade"),
    path("trades/<int:pk>/delete/", views.delete_trade_view, name="delete_trade"),
    path("sync/", views.sync_sheet_view, name="sync_sheet"),
    path("s/<slug:sheet_slug>/sync/", views.sync_sheet_view, name="sync_sheet_for"),
    path("zerodha-sync/", views.zerodha_sync_view, name="zerodha_sync"),
    path("s/<slug:sheet_slug>/zerodha-sync/", views.zerodha_sync_view, name="zerodha_sync_for"),
    path("kite/login/", views.kite_login, name="kite_login"),
    path("kite/callback/", views.kite_callback, name="kite_callback"),
    # Kite Connect apps default the redirect URL to /callback (no kite/ prefix).
    path("callback/", views.kite_callback, name="kite_callback_compat"),
    path("callback", views.kite_callback),
]
