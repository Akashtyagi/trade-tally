import os
import sys

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"

    def ready(self):
        from django.conf import settings

        if not settings.ENABLE_SCHEDULER:
            return
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return
        from integrations.scheduler import start_scheduler

        start_scheduler()
