#!/bin/sh
# Called from the host crontab. Talks to the running Podman container.
set -e

CONTAINER="${TRADE_TALLY_CONTAINER:-trade-tally}"
LOG="${TRADE_TALLY_CRON_LOG:-/tmp/trade-tally-cron.log}"

{
  echo "---- $(date) ----"
  if ! podman inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
    echo "ERROR: container $CONTAINER is not running"
    exit 1
  fi
  podman exec "$CONTAINER" uv run --no-dev python manage.py run_checks
} >>"$LOG" 2>&1
