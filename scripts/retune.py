#!/usr/bin/env python3
"""
Re-fit the model constants as seasons accumulate, and adopt them only if they
actually beat the ones currently shipped.

The ratings already adapt on their own — every result moves them. What does NOT
adapt is the constants (K, home advantage, offseason regression, the feature
betas), which were grid-searched once and hardcoded. This is the loop that
updates those.

Method, and why it is shaped this way:

  * EXPANDING WINDOW. Tune on everything up to a cutoff, score on the seasons
    after it. As years accumulate the tuning window grows, so the constants are
    fitted on more evidence each time rather than on a fixed old slice.

  * ADOPT ONLY ON IMPROVEMENT. New constants have to beat the incumbent ones on
    the same held-out games, by more than a noise margin. A grid search will
    always find something that looks better in-sample; requiring it to win on
    data neither set has seen is what stops the model drifting into overfit.

  * WRITE TO DATA, NOT CODE. Results go to data/model-config.json, which the
    pages read at load. Re-tuning therefore never needs a code change, and the
    file records when it was fitted and on how many games so the page can say so.

Usage:
    python3 scripts/retune.py              # report only, changes nothing
    python3 scripts/retune.py --write      # adopt any improvement and save
    python3 scripts/retune.py --margin 0   # adopt any improvement at all
"""
import argparse, json, math, os, sys
from collections import defaultdict

import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))

CONFIG = 'data/model-config.json'
EPS = 1e-15

# Shipped constants, used as the incumbent when no config file exists yet.
FALLBACK = {
    'nba': {'K': 16, 'homeAdv': 45, 'regress': 0.50, 'b2b': 0.28,
            'eloPerPoint': 20.1, 'spreadSd': 14.2},
    'nfl': {'K': 20, 'homeAdv': 48, 'regress': 0.60,
            'eloPerPoint': 22.8, 'spreadSd': 13.5},
}


# ── shared Elo machinery ─────────────────────────────────────────────────
def elo_pass(games, K, home_adv, regress, mov, b2b=0.0, score_from=None):
    """Walk forward; return (rows, ratings). Rows are scored games only."""
    r = defaultdict(lambda: 1500.0)
    last = {}
    season = None
    rows = []
    for g in games:
        if season is not None and g['season'] != season:
            for t in r:
                r[t] = 1500.0 + (r[t] - 1500.0) * regress
            last.clear()
        season = g['season']

        h, a = g['home'], g['away']
        dr = r[h] - r[a] + (0 if g.get('neutral') else home_adv)
        day = g.get('day')
        z = math.log(10) * dr / 400.0
        if b2b and day is not None:
            bh = 1 if last.get(h) is not None and day - last[h] == 1 else 0
            ba = 1 if last.get(a) is not None and day - last[a] == 1 else 0
            z += b2b * (ba - bh)
        p = 1 / (1 + math.exp(-z))
        margin = g['hs'] - g['as']

        if margin != 0 and (score_from is None or g['season'] >= score_from):
            rows.append({'p': p, 'won': 1 if margin > 0 else 0, 'season': g['season']})

        p_elo = 1 / (1 + 10 ** (-dr / 400.0))
        won = 1 if margin > 0 else (0 if margin < 0 else 0.5)
        mult = 1.0 if margin == 0 else mov(margin, dr if margin > 0 else -dr)
        d = K * mult * (won - p_elo)
        r[h] += d
        r[a] -= d
        if day is not None:
            last[h] = last[a] = day
    return rows, r


def logloss(rows):
    return -sum(math.log(max(x['p'] if x['won'] else 1 - x['p'], EPS))
                for x in rows) / len(rows)


def accuracy(rows):
    return sum((x['p'] >= 0.5) == (x['won'] == 1) for x in rows) / len(rows)


MOV = {
    'nba': lambda m, wd: ((abs(m) + 3) ** 0.8) / (7.5 + 0.006 * wd),
    'nfl': lambda m, wd: math.log(abs(m) + 1) * (2.2 / (wd * 0.001 + 2.2)),
}


# ── loaders ──────────────────────────────────────────────────────────────
def day_num(ds):
    from datetime import date
    try:
        y, m, d = map(int, ds.split('-'))
        return date(y, m, d).toordinal()
    except Exception:
        return None


def load_nba():
    doc = json.load(open('data/nba-games.json'))
    out = []
    for g in doc['games']:
        out.append({'season': g['season'], 'home': g['home'], 'away': g['away'],
                    'hs': g['hs'], 'as': g['as'], 'neutral': g.get('neutral'),
                    'day': day_num(g['date'])})
    out.sort(key=lambda g: (g['day'] or 0))
    return out


def load_nfl():
    import csv, io, urllib.request
    url = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
    txt = urllib.request.urlopen(url, timeout=120).read().decode('utf-8', 'replace')
    out = []
    for g in csv.DictReader(io.StringIO(txt)):
        try:
            s = int(g['season'])
        except (ValueError, TypeError):
            continue
        if s < 2001 or not g['home_score'] or not g['away_score']:
            continue
        out.append({'season': s, 'home': g['home_team'], 'away': g['away_team'],
                    'hs': int(g['home_score']), 'as': int(g['away_score']),
                    'day': day_num(g.get('gameday') or '')})
    out.sort(key=lambda g: (g['day'] or 0))
    return out


# ── the tuning loop ──────────────────────────────────────────────────────
def tune(league, games, incumbent, margin):
    seasons = sorted({g['season'] for g in games})
    if len(seasons) < 4:
        return None, 'not enough seasons to hold any out'

    # hold out the most recent two seasons; tune on everything before them
    holdout_from = seasons[-2]
    tune_games = [g for g in games if g['season'] < holdout_from]
    mov = MOV[league]

    grids = {
        'nba': ([12, 14, 16, 18, 20, 24], [35, 40, 45, 50, 55, 60], [0.35, 0.45, 0.5, 0.6, 0.7]),
        'nfl': ([14, 16, 18, 20, 22, 26], [40, 44, 48, 52, 56], [0.4, 0.5, 0.6, 0.7, 0.8]),
    }[league]
    b2b = incumbent.get('b2b', 0.0)

    best = None
    inner_from = sorted({g['season'] for g in tune_games})[-2]
    for K in grids[0]:
        for HA in grids[1]:
            for RG in grids[2]:
                rows, _ = elo_pass(tune_games, K, HA, RG, mov, b2b, score_from=inner_from)
                if not rows:
                    continue
                ll = logloss(rows)
                if best is None or ll < best[0]:
                    best = (ll, K, HA, RG)
    if best is None:
        return None, 'grid produced no scorable rows'

    _, K, HA, RG = best

    # score both candidate and incumbent on the same untouched holdout
    def on_holdout(k, ha, rg):
        rows, _ = elo_pass(games, k, ha, rg, mov, b2b, score_from=holdout_from)
        return logloss(rows), accuracy(rows), len(rows)

    cand = on_holdout(K, HA, RG)
    inc = on_holdout(incumbent['K'], incumbent['homeAdv'], incumbent['regress'])
    gain = inc[0] - cand[0]

    return {
        'league': league, 'holdoutFrom': holdout_from,
        'tunedOn': len(tune_games), 'scoredOn': cand[2],
        'candidate': {'K': K, 'homeAdv': HA, 'regress': RG},
        'candidateLL': cand[0], 'candidateAcc': cand[1],
        'incumbentLL': inc[0], 'incumbentAcc': inc[1],
        'gain': gain, 'adopt': gain > margin,
    }, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true', help='save adopted constants')
    ap.add_argument('--margin', type=float, default=0.0005,
                    help='minimum holdout log-loss gain required to adopt')
    args = ap.parse_args()

    cfg = json.load(open(CONFIG)) if os.path.exists(CONFIG) else {}
    changed = False

    for league, loader in [('nba', load_nba), ('nfl', load_nfl)]:
        print(f'\n── {league.upper()} ' + '─' * 52)
        try:
            games = loader()
        except Exception as e:
            print(f'  could not load games: {e}')
            continue
        incumbent = dict(FALLBACK[league])
        incumbent.update(cfg.get(league, {}))

        res, err = tune(league, games, incumbent, args.margin)
        if err:
            print(f'  {err}')
            continue

        print(f"  tuned on {res['tunedOn']} games, scored on {res['scoredOn']} "
              f"from season {res['holdoutFrom']}+")
        print(f"  incumbent  K={incumbent['K']} home={incumbent['homeAdv']} "
              f"regress={incumbent['regress']}   ll {res['incumbentLL']:.4f}  "
              f"acc {res['incumbentAcc']*100:.1f}%")
        c = res['candidate']
        print(f"  candidate  K={c['K']} home={c['homeAdv']} "
              f"regress={c['regress']}   ll {res['candidateLL']:.4f}  "
              f"acc {res['candidateAcc']*100:.1f}%")
        print(f"  holdout gain {res['gain']:+.4f} log-loss "
              f"(need > {args.margin:+.4f} to adopt)")

        if res['adopt']:
            print('  ADOPT — candidate wins on games neither set was tuned on')
            entry = dict(incumbent)
            entry.update(c)
            entry['fittedOn'] = res['tunedOn']
            entry['scoredOn'] = res['scoredOn']
            entry['holdoutLogloss'] = round(res['candidateLL'], 4)
            entry['holdoutAcc'] = round(res['candidateAcc'], 4)
            cfg[league] = entry
            changed = True
        else:
            print('  KEEP — the shipped constants are not beaten; nothing changes')
            entry = dict(incumbent)
            entry.setdefault('holdoutLogloss', round(res['incumbentLL'], 4))
            entry.setdefault('holdoutAcc', round(res['incumbentAcc'], 4))
            cfg.setdefault(league, entry)

    import time
    cfg['generated'] = time.strftime('%Y-%m-%d')
    if args.write:
        os.makedirs('data', exist_ok=True)
        json.dump(cfg, open(CONFIG, 'w'), indent=2, sort_keys=True)
        open(CONFIG, 'a').write('\n')
        print(f'\nwrote {CONFIG}' + (' (constants changed)' if changed else ' (no change)'))
    else:
        print('\nreport only — pass --write to save')
    return 0


if __name__ == '__main__':
    sys.exit(main())
