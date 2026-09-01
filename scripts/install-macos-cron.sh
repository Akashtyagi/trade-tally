#!/bin/sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRAGMENT="$ROOT/scripts/crontab.fragment"
chmod +x "$ROOT/scripts/cron-run-checks.sh"

existing="$(crontab -l 2>/dev/null || true)"
cleaned="$(printf "%s\n" "$existing" | grep -v 'trade-tally-podman\|trade-tally/scripts/cron-run-checks' || true)"
{
  printf "%s\n" "$cleaned"
  cat "$FRAGMENT"
} | crontab -

echo "Installed Trade Tally crontab (weekdays 09:15 and 10:00–15:00)."
crontab -l | grep trade-tally || true
