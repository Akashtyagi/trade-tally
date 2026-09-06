"""ASGI entrypoint. The container uses WSGI/gunicorn, not this file."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_asgi_application()
