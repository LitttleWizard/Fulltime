#!/bin/bash
set -e

echo "Logging to Obsidian..."
python3 "/Users/aaronho1880/Content/00_Web_Network_Hub/_scripts/log_change.py" \
  "/Users/aaronho1880/ui:ux/fulltime" \
  "/Users/aaronho1880/Content/00_Web_Network_Hub/Site_04_Fulltime/Changelog.md" || true

echo "Deploying..."
vercel --prod
echo "Deployed successfully"
