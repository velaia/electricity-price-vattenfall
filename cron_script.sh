#!/bin/zsh
# Daily electricity-price chart refresh.
#
# Driven by ~/Library/LaunchAgents/de.lang.energiepreis.plist, not cron: this is
# a laptop, and launchd re-fires a StartCalendarInterval job shortly after the
# Mac wakes, whereas cron silently skips any run that fell while it was asleep.
set -euo pipefail

REPO=/Users/daniel/git/energiepreis-vattenfall-api
cd "$REPO"

echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# set -e aborts here on a failed fetch, so `open` below is never reached with a
# stale chart still on disk — a day-old price curve looks exactly like a fresh
# one on screen, which is the one failure this script must not produce silently.
/opt/homebrew/bin/uv run main.py

open -gj dual_timeline_plot.png
echo "ok — opened dual_timeline_plot.png"
