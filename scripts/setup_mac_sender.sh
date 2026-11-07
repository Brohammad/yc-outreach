#!/usr/bin/env bash
# Install launchd job on macOS to run outreach_mailer every 60s.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

for f in .env outreach_queue.json outreach_template.json; do
  if [[ ! -f "$f" ]]; then
    echo "Missing $f in $ROOT" >&2
    exit 1
  fi
done

chmod +x "$ROOT/scripts/outreach_run_if_due.sh"
PLIST_DST="$HOME/Library/LaunchAgents/com.brohammad.yc-outreach.plist"
sed "s|REPO_ROOT|$ROOT|g" "$ROOT/scripts/com.brohammad.yc-outreach.plist" > "$PLIST_DST"
launchctl bootout "gui/$(id -u)/com.brohammad.yc-outreach" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
launchctl enable "gui/$(id -u)/com.brohammad.yc-outreach"
echo "Installed $PLIST_DST — runs every 60s. Log: $ROOT/outreach_run.log"
echo "Test now: $ROOT/scripts/outreach_run_if_due.sh --dry-run"
