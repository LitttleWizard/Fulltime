#!/usr/bin/env python3
"""
NFL Elo model for the Fulltime predictor — calibrated and evaluated the same
honest way as the EPL side: constants are grid-searched on a training era, then
scored on a held-out era they never saw, against real baselines and the market.

Data: nflverse `games.csv` (1999-present). `nflreadpy` is the usual Python
front door to this, but it needs Python >= 3.10 and this machine has 3.9, so we
read the same underlying file directly — which is also what lets the browser
fetch it live, with no build step.

Why Elo here and not the Dixon-Coles model the EPL tab uses: NFL scoring is not
Poisson (points arrive in 7s and 3s, not 1s), and ties are ~0.2% of games, so
the three-outcome goals model has nothing to model. Elo on margin of victory is
the right shape for this sport.

Usage:  python3 nfl_model.py
"""
import csv
import io
import math
import urllib.request
from collections import defaultdict

GAMES_URL = 'https://github.com/nflverse/nfldata/raw/master/data/games.csv'
FIRST_SEASON = 1999
HOLDOUT_FROM = 2023          # never used for tuning
WARMUP_SEASONS = 2
EPS = 1e-15
DEFAULT_RATING = 1500.0


def fetch_games():
    req = urllib.request.Request(GAMES_URL, headers={'User-Agent': 'fulltime/1.0'})
    with urllib.request.urlopen(req) as r:
        text = r.read().decode('utf-8')
    rows = []
    for g in csv.DictReader(io.StringIO(text)):
        try:
            season = int(g['season'])
        except (TypeError, ValueError):
            continue
        if season < FIRST_SEASON:
            continue
        hs, as_ = g.get('home_score'), g.get('away_score')
        played = bool(hs) and bool(as_)
        rows.append({
            'season': season,
            'week': g.get('week'),
            'date': g.get('gameday') or '',
            'type': g.get('game_type') or 'REG',
            'home': g.get('home_team'), 'away': g.get('away_team'),
            'hs': int(hs) if played else None,
            'as': int(as_) if played else None,
            'played': played,
            'home_ml': g.get('home_moneyline'), 'away_ml': g.get('away_moneyline'),
        })
    rows.sort(key=lambda r: (r['date'], r['home'] or ''))
    return rows


def ml_to_prob(ml):
    """American moneyline -> implied probability."""
    try:
        m = float(ml)
    except (TypeError, ValueError):
        return None
    if m == 0:
        return None
    return (-m) / ((-m) + 100) if m < 0 else 100 / (m + 100)


def mov_multiplier(margin, elo_diff_winner):
    """FiveThirtyEight's NFL margin multiplier, with the autocorrelation
    correction that stops good teams running away with the rating."""
    return math.log(abs(margin) + 1) * (2.2 / (elo_diff_winner * 0.001 + 2.2))


def run(games, K, HOME_ADV, REGRESS):
    ratings = {}
    rows = []
    prev_season = None

    for g in games:
        if not g['played']:
            continue
        if prev_season is not None and g['season'] != prev_season:
            for t in ratings:
                ratings[t] = DEFAULT_RATING + (ratings[t] - DEFAULT_RATING) * REGRESS
        prev_season = g['season']

        h, a = g['home'], g['away']
        Rh = ratings.get(h, DEFAULT_RATING)
        Ra = ratings.get(a, DEFAULT_RATING)
        dr = Rh - Ra + HOME_ADV
        pHome = 1 / (1 + 10 ** (-dr / 400))

        margin = g['hs'] - g['as']
        if margin == 0:
            actual = 0.5
        else:
            actual = 1.0 if margin > 0 else 0.0

        if g['season'] >= FIRST_SEASON + WARMUP_SEASONS and margin != 0:
            rows.append({'season': g['season'], 'p': pHome,
                         'actual': 1 if margin > 0 else 0,
                         'home_ml': g['home_ml'], 'away_ml': g['away_ml']})

        # rating update
        if margin == 0:
            mult = 1.0
        else:
            winner_diff = dr if margin > 0 else -dr
            mult = mov_multiplier(margin, winner_diff)
        delta = K * mult * (actual - pHome)
        ratings[h] = Rh + delta
        ratings[a] = Ra - delta

    return rows, ratings


def score(rows, key='p'):
    n = len(rows)
    if not n:
        return None
    ll = br = 0.0
    correct = 0
    for r in rows:
        p = min(max(r[key], EPS), 1 - EPS)
        y = r['actual']
        ll += -(math.log(p) if y == 1 else math.log(1 - p))
        br += (p - y) ** 2
        if (p >= 0.5) == (y == 1):
            correct += 1
    return {'n': n, 'logloss': ll / n, 'brier': br / n, 'acc': correct / n}


def fmt(label, s):
    if not s:
        return f'{label:<34} —'
    return (f"{label:<34} n={s['n']:<5} acc={s['acc']*100:5.1f}%   "
            f"logloss={s['logloss']:.4f}   brier={s['brier']:.4f}")


def main():
    print('Fetching nflverse games…')
    games = fetch_games()
    played = [g for g in games if g['played']]
    print(f"{len(games)} games ({len(played)} played), "
          f"seasons {games[0]['season']}–{games[-1]['season']}")

    # ---- grid search on the training era only ----------------------------
    best, best_params = None, None
    for K in (12, 16, 20, 24, 28):
        for HA in (30, 40, 48, 55, 65, 80):
            for REG in (0.5, 0.6, 0.67, 0.75, 0.85, 1.0):
                rows, _ = run(played, K, HA, REG)
                tr = [r for r in rows if r['season'] < HOLDOUT_FROM]
                s = score(tr)
                if s and (best is None or s['logloss'] < best['logloss']):
                    best, best_params = s, (K, HA, REG)
    K, HA, REG = best_params
    print(f'\nCalibrated on {FIRST_SEASON + WARMUP_SEASONS}–{HOLDOUT_FROM - 1}: '
          f'K={K}  home_adv={HA}  season_regress={REG}')

    rows, final_ratings = run(played, K, HA, REG)
    train = [r for r in rows if r['season'] < HOLDOUT_FROM]
    hold = [r for r in rows if r['season'] >= HOLDOUT_FROM]

    base = sum(r['actual'] for r in train) / len(train)
    for r in rows:
        r['baserate'] = base
        mh, ma = ml_to_prob(r['home_ml']), ml_to_prob(r['away_ml'])
        r['market'] = (mh / (mh + ma)) if (mh and ma) else None

    print(f'Home team wins {base*100:.1f}% of the time (training era)')

    print('\n' + '=' * 92)
    print(f'HELD-OUT ERA ({HOLDOUT_FROM}+ — constants never tuned on these)')
    print('=' * 92)
    print(fmt('Fulltime NFL Elo', score(hold)))
    print(fmt('  baseline: always pick home', score(hold, 'baserate')))
    mk = [r for r in hold if r['market']]
    if mk:
        print(fmt('  betting market (moneyline)', score(mk, 'market')))
        print(fmt('  our model, same games', score(mk)))

    print('\nTRAINING ERA (tuned on — optimistically biased)')
    print(fmt('Fulltime NFL Elo', score(train)))

    print('\nPer season (holdout)')
    for s in range(HOLDOUT_FROM, games[-1]['season'] + 1):
        rs = [r for r in rows if r['season'] == s]
        if rs:
            print('  ', fmt(str(s), score(rs)))

    print('\nTop 10 current ratings:')
    for t, r in sorted(final_ratings.items(), key=lambda kv: -kv[1])[:10]:
        print(f'   {t:<5} {r:7.0f}')


if __name__ == '__main__':
    main()
