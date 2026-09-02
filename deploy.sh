#!/bin/bash
# Deploy Fulltime to Vercel.
#
# The Obsidian changelog step is personal to one machine, so it only runs when
# OBSIDIAN_HUB points at a checkout of that vault. Everyone else just deploys.
set -e

# Optional machine-local settings (gitignored), e.g. OBSIDIAN_HUB=...
[ -f "$(dirname "$0")/.deployrc" ] && . "$(dirname "$0")/.deployrc"

if [ -n "$OBSIDIAN_HUB" ] && [ -f "$OBSIDIAN_HUB/_scripts/log_change.py" ]; then
  echo "Logging to Obsidian..."
  python3 "$OBSIDIAN_HUB/_scripts/log_change.py" \
    "$(cd "$(dirname "$0")" && pwd)" \
    "$OBSIDIAN_HUB/Site_04_Fulltime/Changelog.md" || true
fi

echo "Deploying..."
vercel --prod
echo "Deployed successfully"
