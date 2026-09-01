from django.urls import path

from trades import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("config/", views.config_view, name="app_config"),
    path("trades/<int:pk>/", views.trade_detail, name="trade_detail"),
    path("trades/<int:pk>/close/", views.close_trade_view, name="close_trade"),
    path("sync/", views.sync_sheet_view, name="sync_sheet"),
    path("zerodha-sync/", views.zerodha_sync_view, name="zerodha_sync"),
    path("kite/login/", views.kite_login, name="kite_login"),
    path("kite/callback/", views.kite_callback, name="kite_callback"),
]
