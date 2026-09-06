#!/bin/sh
# Occasional Zerodha tradebook import. Prefer the running container so the
# dashboard DB and Google Sheet stay in sync.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if command -v podman >/dev/null 2>&1 && podman ps --format '{{.Names}}' | grep -qx 'trade-tally'; then
  exec podman exec trade-tally uv run --no-dev python manage.py ingest_tradebook "$@"
fi
exec uv run python manage.py ingest_tradebook "$@"
