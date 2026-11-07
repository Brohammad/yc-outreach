#!/usr/bin/env bash
# Run every minute (cron or launchd). Sends only messages past send_at.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec /usr/bin/env python3 outreach_mailer.py run --queue outreach_queue.json "$@"
