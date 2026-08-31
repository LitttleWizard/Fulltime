# Fulltime

Sports match predictor with two tabs, both computed client-side with no backend and
no API keys. Static pages, no build step.

- **EPL** (`index.html`) — Dixon-Coles model (attack/defence strengths, Poisson goals
  with the low-score correction) fitted in-browser; produces win/draw/loss plus a
  scoreline distribution. Elo is kept alongside it purely for the watchlist rating and
  trend chart. Data: `openfootball/football.json`, fetched live.
- **NFL** (`nfl.html`) — Elo with a margin-of-victory multiplier. Data: nflverse
  `games.csv` (1999–present), fetched live. Constants calibrated by `nfl_model.py`.

`terminal.css` holds the shared terminal-style layout used by both pages; keep page
files free of layout CSS so the two tabs can't drift apart.

## Data source gotchas — read before touching data loading

- **openfootball renamed every club in 2020-21** ("Manchester City" → "Manchester City
  FC"). `canonicalTeam()` strips the trailing FC/AFC. Without it 13 clubs become two
  separate teams and their ratings reset mid-history.
- **openfootball score shape is inconsistent**: usually `score.ft`, but some 2025-26
  rows are `score: [h, a]` directly. `finalScore()` handles both.
- **Use `raw.githubusercontent.com`, never `github.com/…/raw/…`** — the latter
  302-redirects and the redirect hop has no CORS header, so browsers refuse it even
  though `curl -L` follows it happily.
- **football-data.co.uk has no CORS**, so it can't be fetched at runtime. Its shots
  data is baked into `epl-shots.json` via `python3 build_shots.py`; its odds are used
  only for offline benchmarking in `evaluate.py`.
- **`nflreadpy` needs Python ≥3.10** and isn't used here — it's a wrapper over the same
  nflverse file the page reads directly. If you ever want its richer play-by-play data,
  write a build script that emits JSON (the `build_shots.py` pattern).

## Measuring accuracy

Report **held-out** numbers, never the tuning-era ones — they differ materially. Current
honest figures: EPL 50.4% (market 51.9%), NFL 64.3% (market 67.9%).

- `evaluate.py` — EPL honest evaluation vs baselines and the betting market
- `dixon_coles.py` — EPL Dixon-Coles backtest
- `nfl_model.py` — NFL calibration + evaluation
- `diagnose.py` — tests candidate signals before building them

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
