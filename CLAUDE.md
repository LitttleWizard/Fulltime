# Fulltime

Live EPL match predictor — Elo ratings computed client-side from ten seasons of match
history fetched live from `openfootball/football.json` on GitHub (no backend, no API
key). Adjusted by each team's recent goals and shots-on-target form. Model constants
were fit (not guessed) by walk-forward backtesting — see `calibrate_elo.py` and
`calibration-report.json`.

Single static page (`index.html`), no build step. `epl-shots.json` is a periodic
snapshot from football-data.co.uk (that domain has no CORS, so it can't be fetched
live) — regenerate it with `python3 build_shots.py` when you want fresher shot data.

Deployed to Vercel via `./deploy.sh` (wraps `vercel --prod`).

This directory lives inside `~/ui:ux` but is its own git repo and its own Vercel
project, separate from the personal site — it's gitignored in the parent repo.

## Obsidian memory

This project's history and reasoning live in Obsidian at
`~/Content/00_Web_Network_Hub/Site_04_Fulltime/`:

- **Changelog.md** — auto-written by `deploy.sh` on every deploy. Don't hand-edit.
- **Devlog.md** — the *why*: design decisions, rationale, ideas, things to revisit.
  After making a meaningful change in a session, append a short dated entry here
  describing what changed and why (not just what — the mechanical diff is already
  in Changelog.md).
