# Fulltime

Sports match predictor with three league tabs, all computed client-side with no
backend and no API keys. Static pages; the only build steps are the offline
scripts that bake data files.

- **EPL** (`epl.html`; `index.html` is the landing page) — Dixon-Coles model (attack/defence strengths, Poisson goals
  with the low-score correction) fitted in-browser; produces win/draw/loss plus a
  scoreline distribution. Elo is kept alongside it purely for the watchlist rating and
  trend chart. Data: `openfootball/football.json`, fetched live.
- **NFL** (`nfl.html`) — Elo with a margin-of-victory multiplier. Data: nflverse
  `games.csv` (1999–present), fetched live. Constants calibrated by `nfl_model.py`.
- **NBA** (`nba.html`) — Elo with 538's NBA margin multiplier, plus back-to-back
  and player-availability adjustments. Data baked into `nba-games.json` by
  `build_nba.py` and `nba-players.json` by `build_nba_players.py`; schedule,
  live scores and injuries from ESPN at runtime. Calibrated by `nba_model.py`.

`terminal.css` holds the shared terminal-style layout used by both pages; keep page
files free of layout CSS so the two tabs can't drift apart.

`mobile-nav.js` injects the bottom tab bar and shows one column at a time below
1080px — without it every `.term-col` is `display:none` and the page renders
blank on a phone. Any new page built from `.term-col` must load it. Columns can
override the tab label with `data-mtab` / `data-mtab-icon` (the log tab does).

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
- **ESPN's NBA scoreboard is not only NBA.** It carries preseason exhibitions
  against European and Australian clubs (Real Madrid, Flamengo, Hapoel, the NBL
  sides) and All-Star squads (EAST/WEST/STARS/STRIPES), plus the odd `null`
  abbreviation. `build_nba.py` keeps only games between two of the 30 franchises
  it resolves from `/teams` — without that filter, beating Real Madrid in
  October moves a team's Elo, and the team picker shows 52 teams.
- **NBA injuries are usable, football lineups are not.** ESPN posts NBA injury
  status days ahead (one league-wide `/injuries` request), so it can inform a
  prediction. Football lineups only appear ~1h before kickoff, which is why the
  EPL team sheet falls back to each club's last XI. Count only players listed
  `Out`: most listings are `Day-To-Day` and most of those play.
- **The injuries feed carries no athlete id** and keys teams by display name, so
  joining it to `nba-players.json` is name matching against the abbreviation map.
- **hoopR-data stops at 2023 and FiveThirtyEight's `nba_elo` files are gone**, so
  ESPN is currently the only NBA source that is both current and CORS-open.
- **`nflreadpy` needs Python ≥3.10** and isn't used here — it's a wrapper over the same
  nflverse file the page reads directly. If you ever want its richer play-by-play data,
  write a build script that emits JSON (the `build_shots.py` pattern).

## Player ratings (`players.js`, `epl-players.json`)

EA FC 26 overalls, snapshot **2025-09-19**, trimmed from an upstream 9MB CSV by
`build_players.py`. Shown as a team sheet on `epl.html` once ESPN publishes a
lineup, which it only does near kickoff — a fixture days out has empty rosters.

What was measured (`epl_players.py`, 340 matches, betas cross-fitted):

| model | logloss |
|---|---|
| Dixon-Coles alone | 1.0350 |
| + absolute XI quality gap | 1.0450 — **worse** |
| + XI vs that club's recent norm | 1.0347 — +0.0003 |

The absolute gap fails because Dixon-Coles already infers team strength from
results, and results beat a video-game rating as soon as you have any. Only the
*deviation* from a club's own norm is new information, and it is worth almost
nothing — real in sign (positive betas in both folds and across four encodings)
but negligible in size. Don't talk it up; the page states the number.

- Name matching ESPN → EA FC is 97.3% on 8,360 starters. The rest are players
  who joined after the snapshot; they fall back to club mean. Match on the SET
  of surname tokens, not the last one — Iberian double surnames ("Ezri Konsa
  Ngoyo" vs ESPN's "Ezri Konsa") break naive matching, and `ß` must become `ss`
  before the ASCII fold or "Groß" collapses to "gro".
- `fetch_lineups.py` caches historical lineups to `lineups.json` (one ESPN
  request per match, append-only). `build_players.py` reads it to compute each
  club's rolling baseline XI, so the shipped feature is identical to the tested
  one.

## Re-tuning as seasons accumulate

The ratings adapt on their own — every result moves them. The **constants** do
not, and `scripts/retune.py` is the loop that updates those:

```bash
python3 scripts/retune.py            # report only
python3 scripts/retune.py --write    # adopt improvements, save the config
```

It tunes on an expanding window (everything up to a cutoff) and scores both the
candidate and the incumbent on the two most recent seasons, which neither was
tuned on. It adopts **only** if the candidate wins by more than `--margin`
(default 0.0005 log-loss). A grid search always finds something that looks
better in-sample; requiring a holdout win is what stops the model drifting into
overfit. It is entirely normal — and the correct outcome — for it to report
KEEP and change nothing.

Results go to `data/model-config.json`, which `nba.html` and `nfl.html` read at
load and apply over their defaults. **Re-tuning needs no code change or deploy**
beyond publishing that file. If the file is missing or unreadable the pages
silently keep their built-in defaults.

Run it once or twice a season. `build_nba_players.py` should be re-run on a
similar cadence, or the scoring averages go stale.

## Two win probabilities, and which one to use

The same Elo ratings yield a probability two ways: the logistic on the rating
gap, or the share of historical margin errors that would still leave a side
ahead. They disagree by about a point. This was invisible until the match
simulation put both on screen.

`scripts/margin_vs_logistic.py` settles it per league on held-out games, with a
paired bootstrap:

- **NBA** — the margin view wins, and survives with the back-to-back term on
  top: 0.6083 → 0.6075 log-loss, 66.7% → 67.1%, CI [+0.00008, +0.00152].
  `nba.html` uses it.
- **NFL** — no distinguishable difference (CI spans zero). `nfl.html` keeps the
  logistic, and its simulation panel is shifted onto that base so the two views
  agree on screen.

The answer being league-specific is the reason to run the script rather than
pick one. Re-run it if the constants or `eloPerPoint` change, since the margin
view depends on that conversion.

## Measuring accuracy

Report **held-out** numbers, never the tuning-era ones — they differ materially. Current
honest figures: EPL 50.4% (market 51.9%), NFL 64.3% (market 67.9%), NBA 67.6%
(vs 55.0% for always picking the home side).

- `evaluate.py` — EPL honest evaluation vs baselines and the betting market
- `dixon_coles.py` — EPL Dixon-Coles backtest
- `nfl_model.py` — NFL calibration + evaluation
- `nba_model.py` — NBA Elo grid search + honest holdout evaluation
- `nba_features.py` — tests NBA rest signals; back-to-back kept, rest-days rejected
- `nba_players.py` — tests player availability; the largest measured signal on
  the site (0.6068 -> 0.5995 log-loss, 67.0% -> 67.6%). Needs `fetch_nba_box.py`
  to have cached box scores first (~2800 requests, several minutes).
- `epl_players.py` / `epl_squad.py` — tested EA FC ratings against Dixon-Coles
- `diagnose.py` — tests candidate signals before building them

## Caching (`vercel.json`)

JSON is comment-free, so the reasoning lives here:

- **HTML** revalidates every request, so a deploy is visible immediately.
- **Baked datasets** (`nba-games.json` and friends) change only when a build
  script is re-run — weekly at most — so they cache for an hour and then serve
  stale for a day while revalidating. A repeat visitor pays no round-trip for
  ~1 MB of history. Bump nothing when you rebuild; the hour covers it.
- **Shared JS modules** cache for 5 minutes and revalidate, since they change
  with a deploy.

## Layout

Pages live at the root (the deployed URLs depend on it); everything else is
sorted into `assets/` (JS + CSS), `data/` (baked JSON), `scripts/` (Python) and
`test/`. Python scripts `chdir` to the repo root on import, so their data paths
are `data/…` regardless of where you run them from. If you add a script that
reads a data file, copy that four-line header or it will only work from the root.

## Shared modules

`elo.js` holds the rating loop for all three tabs; only the constants and the
margin-of-victory multiplier are league-specific (`Elo.mov.football/nfl/nba`).
`terminal-ui.js` holds the handful of render helpers that were byte-identical
across pages. `formPills`, `renderWatchlist` and `h2hSummary` look duplicated
but genuinely differ per league (football reports draws and counts five
meetings; the others count six) — they are deliberately left local.

`test/test_parity.py` asserts elo.js and `nba_model.py` produce the same
ratings. Run it after touching either; every accuracy claim on the site depends
on the two agreeing.

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

## Live scores (`live.js`)

ESPN's public scoreboard endpoint, no key, `access-control-allow-origin: *` on the
first hop. Undocumented and unsupported, so every failure path is silent — if it
breaks the page shows no live badge rather than erroring.

- **Team naming**: ESPN's EPL `displayName` matches our canonical names once the
  trailing FC/AFC is stripped. NFL needs exactly two fixes: `LAR→LA`, `WSH→WAS`.
- **In-play win probability is EPL only.** Dixon-Coles already yields expected
  goals, so remaining goals over remaining time are Poisson at a pro-rated rate —
  the pre-match model extends to in-play with no new data. NFL has no equivalent:
  points come in 7s and 3s and possession dominates late, which needs an
  empirical play-by-play model (and nflverse play-by-play is CORS-blocked).
- It ignores game state effects (teams protect leads), red cards, and real
  stoppage time. Sound baseline, not a betting model.
- `Live.detail()` returns goals, the play-by-play feed and the lineup from a
  single `summary` request. Injuries have no event of their own — ESPN writes
  them into the substitution text ("… because of an injury"), which is what
  `classify()` keys on. Feed text is third-party and goes through `esc()`.
