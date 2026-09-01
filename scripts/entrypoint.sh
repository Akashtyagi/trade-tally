#!/bin/sh
set -e

mkdir -p /data

uv run --no-dev python manage.py migrate --noinput
uv run --no-dev python manage.py collectstatic --noinput || true

exec uv run --no-dev gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2
