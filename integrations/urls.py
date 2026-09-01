from django.urls import path

from integrations import views

urlpatterns = [
    path("run-checks", views.run_checks_webhook, name="run_checks_webhook"),
]
