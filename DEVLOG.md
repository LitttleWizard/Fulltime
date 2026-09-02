# Fulltime — Development Log

Sports match prediction for the EPL, NFL and NBA. Static site, no backend, no
API keys; every model is fitted in the browser on page load.

This records **why** things are as they are — above all the ideas that were
tested and thrown out, since those are invisible in the code. `Changelog.md`
(Obsidian, auto-written on deploy) has the mechanical diff.

**Live:** [fulltime.beer](https://fulltime.beer) · 41 commits, 30 Aug – 2 Sep 2026

---

## Where it stands

| Tab | Model | Held out | Benchmark |
|---|---|---|---|
| EPL | Dixon-Coles (Poisson goals + low-score correction) | 50.4% · 1.022 | 51.9% market |
| NFL | Elo + MOV, QB / rest / divisional | 64.6% · 0.6293 | 67.9% market |
| NBA | Elo + MOV, back-to-back, availability | 67.6% · 0.5995 | 55.0% pick-home |

All figures are **held out** — scored on seasons the tuning never saw. In-sample
numbers on a rating model flatter and mislead, so they aren't quoted.

---

## Results

### EPL

| Test | Result | Verdict |
|---|---|---|
| EA FC squad rating, all 380 matches | 1.0276 → 1.0314, betas −0.30 / +0.36 | **Rejected** — worse, betas disagree |
| Squad rating, promoted sides (n=108) | 1.0061 → 1.0015, betas +0.59 / +0.81 | Directional, too thin to ship |
| Real lineups, XI quality gap (n=340) | 1.0350 → 1.0450, betas −0.51 / +0.57 | **Rejected** |
| Real lineups, XI vs own recent norm | 1.0350 → 1.0347, betas +0.61 / +1.50 | Real but negligible |
| — across four encodings | +0.0003 / −0.0012 / +0.0002 / +0.0002 | Softmax betas steadiest (+0.53/+0.54) |
| ESPN → EA FC name matching | 97.3% of 8,360 starters | Misses are post-snapshot signings |
| In-play calibration | 0–10% band lands 7.0%; 80–90% lands 70.3% | **Overconfident** — said so on the page |

Dixon-Coles already infers team strength from results, so a video-game rating
adds nothing. Only the *disruption* variant — is today's XI weaker than this
club's normal XI — carries new information, and even that is worth ~nothing in
football. Shipped as display, not as a model input.

### NFL

| Test | Result | Verdict |
|---|---|---|
| Elo + MOV (854 games, 2023+) | 64.3% · 0.6334 | Baseline |
| QB change alone | 0.6304 | Helps |
| QB + rest + divisional, fitted jointly | 0.6293 · 64.6% | **Shipped** |
| Temperature / wind | — | **Rejected**: recorded post-game, so never available pre-kickoff |
| Roof / indoor | ≈0 alongside other signals | **Rejected** |
| Offence/defence split | 0.6347 vs 0.6334 | **Rejected** — more parameters, less signal |
| Roster moves / trades | No measurable effect | Kept as labelled context only |
| Elo per point of spread | 22.8 measured, not the conventional 25 | Corrected |
| Residual SD of margin | 13.5 pts over 6,758 games | Shown as ± on the spread |
| Margin vs logistic win prob | +0.00039, CI spans zero | **No difference** — kept logistic |

### NBA

| Test | Result | Verdict |
|---|---|---|
| Grid search | K=16, home +45, regress 0.50 | Shipped |
| Elo holdout (2,777 games, 2025+) | 66.5% · 0.6099 | Baseline (pick-home 55.0%) |
| Without margin multiplier | 66.1% · 0.6171 | MOV worth ~0.4pt |
| Back-to-back (β 0.28) | 0.6099 → 0.6078 · 67.0% | **Shipped** |
| Rest-day difference | 0.6101 — worse than Elo alone | **Rejected** |
| Player availability (β 1.75) | 0.6068 → 0.5995 · 67.0% → 67.6%, betas +1.70 / +1.80 | **Shipped** — largest signal here |
| Margin vs logistic, b2b applied | 0.6083 → 0.6075 · 66.7% → 67.1%, CI [+0.00008, +0.00152] | **Adopted** |
| Elo per point / residual SD | 20.1 · 14.2 pts over 8,150 games | Shown as ± |
| Calibration | 65% calls land 65.5%; 75% land 77.0% | Well calibrated |

Availability is worth **24× the equivalent EPL squad effect**. Partly structural
— one basketball starter is a fifth of the floor — but the deciding factor is
*data timing*: NBA injury reports publish days ahead, football lineups an hour
before kickoff. One can inform a prediction; the other only explains afterwards.

### Cross-cutting

| Check | Result |
|---|---|
| JS ↔ Python parity (`test_parity.py`) | 30 teams agree to 0.000000 |
| Browser log replay vs Python holdout | 67.0% · 0.608 — reproduces `nba_features.py` exactly |
| Re-tune (`retune.py`), NBA / NFL | Incumbent wins both → **KEEP**, nothing changed |
| Chart colours: blue + orange | CVD ΔE 31.3, contrast ≥3:1 both themes → pass |
| Chart colours: sky + fuchsia | CVD ΔE 1.5 → **rejected**, invisible to a deuteranope |

Re-tune reporting KEEP is the guard working: a grid search always finds
something that looks better in-sample, and requiring a holdout win is what stops
the model overfitting itself slightly worse each season.

---

## Method notes

- **Cross-fitting** is used where a single season is too short to hold out an
  era: fit the beta on one half, score the other, swap. **Agreement between the
  two betas is the signal** — opposite signs mean noise, which is exactly what
  separated EA FC squad ratings (−0.30 / +0.36) from availability (+1.70 / +1.80).
- **Paired bootstrap** (4,000 resamples) settles small differences. It gave
  opposite answers for NBA and NFL on the same question.
- **Leakage discipline**: the EA FC snapshot is dated 2025-09-19 so only later
  matches are scored against it; the residual pool scoring a game holds only
  games played before it.

---

## What testing caught

1. **ESPN's NBA feed is not only NBA.** Preseason exhibitions against Real
   Madrid, Flamengo and Australian NBL clubs, plus All-Star squads — 22 phantom
   teams whose results were moving real franchises' Elo. Filtering them moved
   the fitted offseason regression 0.35 → 0.50, so everything was refit.
2. **openfootball renamed every club in 2020-21.** 13 clubs existed as both
   "Manchester City" and "Manchester City FC", resetting ratings mid-history.
   Fixing it improved 2020-21 log-loss 1.0424 → 1.0223.
3. **A silent NaN in the Elo refactor.** NBA stores scores as `hs`/`as`; the
   extracted `Elo.run` expects `hg`/`ag`. Caught only because every rating and
   prediction was snapshotted before the refactor and diffed after.
4. **An assumption shipped without test.** The match simulation disagreed with
   the headline; I suppressed the disagreement instead of measuring it. When
   measured, the margin view was significantly better for NBA — and no better
   for NFL.
5. **An accuracy figure from the wrong era.** An early version reported 53.6%
   for EPL, which was tuning-era. The honest held-out figure is 50.4%.

---

## Known decay

- **`data/epl-players.json`** — EA FC snapshot dated 2025-09-19, no upstream
  history. Three current clubs appear only in its Championship slice.
- **`build_nba_players.py`** — re-run every month or two or scoring averages drift.
- **`scripts/retune.py`** — once or twice a season.
- **In-play model is EPL-only** and measurably overconfident. NBA/NFL would need
  possession-level play-by-play the site doesn't ship.
- **`nba-box.json` is gitignored** — 1.4 MB, ~2,800 requests to rebuild;
  `nba_players.py` can't run without it.

---

## Timeline

**30 Aug** — EPL predictor spun out of the personal site. Elo first, then
switched to Dixon-Coles for the scoreline distribution Elo can't produce. NFL
tab same day.

**31 Aug** — the heavy testing day: QB/rest/divisional fitted, weather and the
offence/defence split rejected. Prediction log added (walk-forward replay of
every call). ESPN live scores and EPL in-play probability. EA FC ratings tested
twice and both times came back ~zero.

**1 Sep** — NBA tab. hoopR stops at 2023 and FiveThirtyEight pulled their
`nba_elo` files, leaving ESPN as the only current CORS-open source — hence
baking `nba-games.json` offline.

**2 Sep** — availability shipped; published to GitHub; `elo.js` and
`terminal-ui.js` extracted (Elo had been written three times); parity test added;
repo reorganised; UI density pass; re-tune loop; season and match simulation;
and the margin-vs-logistic correction.

---

*Kept alongside `Changelog.md` and the Obsidian devlog at
`~/Content/00_Web_Network_Hub/Site_04_Fulltime/`.*
