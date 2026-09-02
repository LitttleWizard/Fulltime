# Fulltime — Development Log

Sports match prediction for the Premier League, NFL and NBA. Static site, no
backend, no API keys; every model is fitted in the browser on page load.

This log records **why** things are the way they are — particularly the ideas
that were tested and thrown away, since those are invisible in the code and are
the expensive lessons. `Changelog.md` in Obsidian records the mechanical diff;
this is the reasoning.

**Live:** [fulltime.beer](https://fulltime.beer) · **Repo:** LitttleWizard/Fulltime
· 41 commits, 30 Aug – 2 Sep 2026

---

## Where it stands

| Tab | Model | Held-out accuracy | Benchmark |
|---|---|---|---|
| EPL | Dixon-Coles (Poisson goals + low-score correction) | 50.4% | 51.9% betting market |
| NFL | Elo + margin of victory, QB / rest / divisional | 64.6% | 67.9% betting market |
| NBA | Elo + margin, back-to-back, player availability | 67.6% | 55.0% always-pick-home |

Every figure is **held out** — scored on seasons the tuning never saw. In-sample
numbers on a rating model flatter and mislead, so they are not quoted anywhere.

---

## The through-line: measure before building

The recurring discipline is that a candidate signal has to earn its place on
held-out data, and most did not. What was **rejected**:

| Idea | Result | Why it failed |
|---|---|---|
| EA FC squad ratings (EPL) | +0.0003 log-loss, betas of opposite sign | Dixon-Coles already infers team strength from results; results beat a video-game rating as soon as you have any |
| NFL weather (temp, wind) | Looked useful in backtest | Recorded *after* a game — every upcoming fixture has the field empty, so it can never inform a prediction |
| NFL offence/defence split | 0.6347 vs 0.6334 for single-rating Elo | More parameters, less signal |
| NFL roster moves / trades | No measurable effect | Kept on the page as context, explicitly labelled "not a model input" |
| NBA rest-day difference | 0.6101 vs 0.6099 — worse than Elo alone | Only the narrower back-to-back flag survived |
| Sky/fuchsia chart colours | CVD ΔE 1.5 | Indistinguishable to a deuteranope despite looking fine |

What **worked**:

| Idea | Gain | Note |
|---|---|---|
| NBA player availability | 0.6068 → 0.5995, 67.0% → 67.6% | 24× the EPL squad effect — one starter is a fifth of the floor |
| NBA back-to-backs | 0.6099 → 0.6078 | β=0.28, both folds agreeing |
| NFL QB / rest / divisional | 0.6334 → 0.6293 | Fitted jointly, not one at a time |
| Dixon-Coles over Elo (EPL) | Scoreline distribution | Elo can't produce one |
| Margin-based win probability (NBA) | 0.6083 → 0.6075, 66.7% → 67.1% | Bootstrap CI excludes zero |

---

## Timeline

### 30 Aug — the EPL predictor, spun out
Started as a match-outcome model on the personal site, then separated into its
own repo and Vercel project. Elo first, then **switched to Dixon-Coles**: Poisson
goals with the low-score correction, weighted MLE with a 200-day half-life,
fitted in-browser by hand-rolled gradient ascent (no numpy in a browser). Elo
stayed for the watchlist and trend chart, where a single number is what's wanted.

NFL added the same day — Elo with a margin-of-victory multiplier, using
FiveThirtyEight's autocorrelation correction so strong teams can't inflate their
rating by beating weak ones badly.

### 31 Aug — the day most of the testing happened
The QB adjustment was **fitted from data rather than assumed**, and weather was
rejected on the timing argument above. The offence/defence split was built,
measured, and deleted.

The **prediction log** went in — every call replayed walk-forward against what
actually happened. This is the tab that keeps the rest honest.

**Live scores** from ESPN, and in-play win probability for the EPL. That one was
almost free: Dixon-Coles already yields expected goals, so remaining goals over
remaining time are Poisson at a pro-rated rate. NFL and NBA have no equivalent —
points arrive in 7s and 3s and possession dominates late.

Measuring in-play calibration showed the model **overconfident**: the 0–10% band
lands 7.0%, the 80–90% band 70.3%. Surfaced on the page rather than buried.

EA FC player ratings were tested twice — squad-level, then with real lineups —
and both times came back near zero. The lineup work stayed anyway, because
seeing who is missing is useful to a reader even when it doesn't move the number.

### 1 Sep — NBA, and mobile
The **NBA tab**. Sourcing was the hard part: hoopR's schedules stop at 2023 and
FiveThirtyEight pulled their `nba_elo` files, leaving ESPN as the only current
CORS-open source. It answers one date range per request, so five seasons is ~90
of them — hence baking `nba-games.json` offline.

That feed is not only NBA. It carries preseason exhibitions against Real Madrid,
Flamengo and Australian NBL clubs, plus All-Star squads — 22 phantom teams, and
those results were **moving real franchises' Elo**. Filtering to the 30 franchises
changed the fitted offseason regression from 0.35 to 0.50, so everything was
refit rather than left quoting numbers from dirty data.

### 2 Sep — availability, publishing, and the estimator question
**Player availability** turned out to be the largest signal on the site. The
reason it works here and failed on the EPL tab isn't the sport — it's data
timing. NBA injury reports publish days ahead; football lineups land an hour
before kickoff. One can inform a prediction, the other can only explain
afterwards.

Deliberately conservative: only players listed **Out** count. 67 of 76 current
listings are Day-To-Day and most of those play.

Then a cleanup pass — `elo.js` and `terminal-ui.js` extracted (Elo had been
implemented three times), a **parity test** asserting the browser and the Python
analysis produce identical ratings, and the repo reorganised into
`assets/ data/ scripts/ test/`.

Two things worth recording from that refactor. Snapshotting every rating and
prediction *before* touching anything caught a real break mid-way — NBA stores
scores as `hs`/`as` while `Elo.run` expects `hg`/`ag`, producing NaN ratings. And
`formPills` / `renderWatchlist` / `h2hSummary` *look* duplicated but genuinely
differ per league, so they were deliberately left alone. A real difference is
not duplication.

**Simulation.** Season projection first — Monte Carlo over remaining fixtures for
title, top-four and relegation odds. Then match simulation, which I initially
argued against on the grounds that sampling from a closed form just reproduces
it. That was half right: it's true of the win probability, and wrong about
everything else. The Elo tabs had no score distribution at all.

That panel then earned its keep immediately by exposing a **disagreement**: the
margin view said 59.4% where the headline said 61%. I first resolved it by
shifting the simulation onto the headline — assuming the logistic was the
validated one. Challenged on that, I measured properly, and the assumption was
wrong: for the NBA the margin view is significantly better (CI [+0.00008,
+0.00152]). For the NFL there's no distinguishable difference. The answer was
league-specific, which is exactly why it needed measuring.

---

## Things that will need attention

- **`data/epl-players.json` goes stale.** The EA FC snapshot is dated
  2025-09-19 and upstream publishes no history. Three current clubs appear only
  in its Championship slice.
- **`build_nba_players.py` needs re-running** every month or two or the scoring
  averages drift out of date.
- **`scripts/retune.py`** should run once or twice a season. It only adopts
  constants that beat the incumbent on held-out seasons — reporting KEEP and
  changing nothing is the normal, correct outcome.
- **The in-play model is EPL-only** and measurably overconfident. A possession-
  level model for NBA/NFL needs play-by-play data the site doesn't ship.
- **NBA `nba-box.json` is gitignored** — 1.4 MB and ~2,800 requests to rebuild.
  `nba_players.py` can't run without regenerating it first.

---

*Maintained alongside `Changelog.md` (auto-written on deploy) and the Obsidian
devlog at `~/Content/00_Web_Network_Hub/Site_04_Fulltime/`.*
