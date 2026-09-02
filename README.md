# Fulltime

Sports match prediction for the Premier League, NFL and NBA, live at
**[fulltime.beer](https://fulltime.beer)**. Built with [Claude Code](https://claude.com/claude-code).

Static HTML, CSS and vanilla JavaScript. No backend, no API keys, no build step —
every model is fitted in the browser on page load. The only compiled artefacts are
JSON data files baked offline by the Python scripts in this repo.

## The models

| Tab | Model | Held-out accuracy | Baseline |
|---|---|---|---|
| **EPL** | Dixon-Coles (Poisson goals + low-score correction) | 50.4% | 51.9% (betting market) |
| **NFL** | Elo + margin of victory, QB / rest / divisional adjustments | 64.6% | 67.9% (betting market) |
| **NBA** | Elo + margin of victory, back-to-back + player availability | 67.6% | 55.0% (always pick home) |

Every figure above is **held out** — scored on seasons the tuning never saw. In-sample
numbers on a rating model are always flattering and always wrong, so they aren't quoted.

## Measure before building

The recurring discipline here is that candidate signals get tested and are dropped when
they don't pay, even when they're intuitive. Things that were tried and **rejected**:

- **EA FC squad ratings on the EPL** (`epl_squad.py`, `epl_players.py`) — worth +0.0003
  log-loss, with cross-fitted betas of opposite sign in the general case. Dixon-Coles
  already infers team strength from results, and results beat a video-game rating as
  soon as you have any.
- **NFL weather** (`nfl_features.py`) — temperature and wind are recorded *after* a game,
  so every upcoming fixture has those fields empty. They can't inform a prediction
  whatever they score in backtest.
- **NBA rest days** (`nba_features.py`) — scored *worse* than Elo alone. Only the
  narrower back-to-back flag survived.

And what **worked**:

- **NBA player availability** (`nba_players.py`) — the share of a team's usual scoring
  that's unavailable tonight. 0.6068 → 0.5995 log-loss, 67.0% → 67.6%, cross-fitted
  betas +1.70/+1.80. That's 24× the EPL squad-rating effect: one basketball starter is
  a fifth of the floor.

The difference between the last two isn't really the sport — it's data timing. NBA injury
reports are published days ahead; football lineups land an hour before kickoff. One can
inform a prediction, the other can only explain afterwards.

## Layout

```
index.html epl.html nfl.html nba.html logs.html   pages (root: the URLs depend on it)
assets/    terminal.css, elo.js, terminal-ui.js, live.js, trend-chart.js,
           dixon-coles.js, players.js, theme.js, mobile-nav.js
data/      the baked JSON the pages fetch, plus analysis outputs
scripts/   every Python build + evaluation script
test/      test_parity.py — asserts elo.js and nba_model.py agree
```

Pages stay at the root because `fulltime.beer/epl` resolves to `epl.html`; moving
them would break every URL. The Python scripts stay in one directory because they
import each other, and each resolves paths from its own location, so they run from
any working directory.

Only the constants and the margin-of-victory multiplier differ per league
(`Elo.mov.football` / `.nfl` / `.nba`) — the loop is shared. A few render helpers
*look* duplicated but genuinely differ (football reports draws and counts five
head-to-head meetings; the others count six), so those stay local rather than
being forced together.

**Baking data** (offline, writes the JSON the pages fetch):

```bash
python3 build_shots.py         # epl-shots.json
python3 fetch_lineups.py       # lineups.json      (one ESPN request per match)
python3 build_players.py       # epl-players.json
python3 build_nba.py           # nba-games.json
python3 fetch_nba_box.py       # nba-box.json      (~2,800 requests, ~20 min)
python3 build_nba_players.py   # nba-players.json
```

**Re-tuning** — the ratings adapt to every result on their own; the constants
don't. This re-fits them on an expanding window and adopts new values only if
they beat the shipped ones on seasons neither was tuned on:

```bash
python3 scripts/retune.py           # report
python3 scripts/retune.py --write   # adopt improvements
```

**Testing** — the browser and the Python scripts must agree, since every accuracy
figure comes from Python while visitors see numbers from `elo.js`:

```bash
python3 test/test_parity.py
```

**Evaluating models** (prints held-out scores; changes nothing):

```bash
python3 evaluate.py      # EPL: Dixon-Coles vs baselines and the betting market
python3 diagnose.py      # EPL: tests candidate signals before building them
python3 nfl_model.py     # NFL: Elo calibration + held-out evaluation
python3 nfl_features.py  # NFL: QB / rest / divisional / weather signals
python3 nba_model.py     # NBA: Elo grid search + held-out evaluation
python3 nba_features.py  # NBA: back-to-back and rest-day signals
python3 nba_players.py   # NBA: player availability (needs fetch_nba_box.py first)
```

## Data sources

All CORS-open and key-free, which is the binding constraint on a static site:

- [openfootball/football.json](https://github.com/openfootball/football.json) — EPL results
- [nflverse/nfldata](https://github.com/nflverse/nfldata) — NFL schedule and results, 1999–
- [ESPN's public endpoints](https://site.api.espn.com/apis/site/v2/sports) — live scores,
  schedules, lineups, box scores and injuries for all three leagues
- [EAFC26-DataHub](https://github.com/ismailoksuz/EAFC26-DataHub) — player ratings
- football-data.co.uk — shots and closing odds (no CORS, so baked offline only)

Gotchas worth knowing before touching data loading are documented in `CLAUDE.md`.

## Deploying

```bash
./deploy.sh
```

Wraps `vercel --prod`. Copy `.deployrc.example` to `.deployrc` for optional machine-local
settings; that file is gitignored.

## Licence

**All rights reserved.** The source is public for reference and review; no
licence is granted to reuse it. See `LICENSE`.

Predictions are statistical estimates, not advice, and the accuracy figures
above are historical measurements on held-out data rather than a forecast. Not
affiliated with any league or data provider.
