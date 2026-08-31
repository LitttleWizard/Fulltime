#!/usr/bin/env python3
"""
Does splitting NFL team strength into separate OFFENCE and DEFENCE ratings beat
a single Elo number?

Elo compresses a team into one value, so a 30-points-for / 28-allowed team and a
17-for / 15-allowed team look identical. This models them separately, the way the
EPL tab's Dixon-Coles does with attack/defence:

    expected home points = base + off_home + def_away + hfa
    expected away points = base + off_away + def_home
    margin               = difference of the two

Ratings are in points and update online from actual scoring. Win probability
comes from the predicted margin against the residual spread.

Same protocol as everything else: fitted on 2001-2022, scored on 2023+.
"""
import math
import sys

sys.path.insert(0, '/Users/aaronho1880/ui:ux/fulltime')
import nfl_model as nm

HOLDOUT_FROM = nm.HOLDOUT_FROM
WARMUP = nm.WARMUP_SEASONS
FIRST = nm.FIRST_SEASON


def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def run(games, lr, hfa, regress, sigma, base):
    off, dfn = {}, {}
    prev_season = None
    rows = []

    for g in games:
        if not g['played']:
            continue
        h, a = g['home'], g['away']
        for t in (h, a):
            off.setdefault(t, 0.0)
            dfn.setdefault(t, 0.0)

        if prev_season is not None and g['season'] != prev_season:
            for t in off:
                off[t] *= regress
                dfn[t] *= regress
        prev_season = g['season']

        # predict each side's points, then the margin
        eh = base + off[h] + dfn[a] + hfa
        ea = base + off[a] + dfn[h]
        margin_pred = eh - ea
        p_home = norm_cdf(margin_pred / sigma)

        margin = g['hs'] - g['as']
        if g['season'] >= FIRST + WARMUP and margin != 0:
            rows.append({'season': g['season'], 'p': p_home,
                         'actual': 1 if margin > 0 else 0,
                         'home_ml': g['home_ml'], 'away_ml': g['away_ml']})

        # update: credit the surprise in each side's scoring to that offence
        # and the opposing defence, split evenly
        rh = g['hs'] - eh
        ra = g['as'] - ea
        off[h] += lr * rh
        dfn[a] += lr * rh
        off[a] += lr * ra
        dfn[h] += lr * ra

    return rows, off, dfn


def main():
    print('Fetching nflverse games…')
    games = [g for g in nm.fetch_games() if g['played']]
    print(f'{len(games)} played games\n')

    best, best_p = None, None
    for lr in (0.03, 0.06, 0.10, 0.15):
        for hfa in (1.2, 1.8, 2.4):
            for regress in (0.55, 0.70, 0.85):
                for sigma in (12.5, 13.5, 14.5):
                    rows, _, _ = run(games, lr, hfa, regress, sigma, 22.0)
                    tr = [r for r in rows if r['season'] < HOLDOUT_FROM]
                    s = nm.score(tr)
                    if s and (best is None or s['logloss'] < best['logloss']):
                        best, best_p = s, (lr, hfa, regress, sigma)

    lr, hfa, regress, sigma = best_p
    print(f'fitted on 2001-{HOLDOUT_FROM-1}: lr={lr} hfa={hfa} '
          f'regress={regress} sigma={sigma}')

    rows, off, dfn = run(games, lr, hfa, regress, sigma, 22.0)
    train = [r for r in rows if r['season'] < HOLDOUT_FROM]
    hold = [r for r in rows if r['season'] >= HOLDOUT_FROM]

    print('\n' + '=' * 88)
    print(f'HELD-OUT ERA ({HOLDOUT_FROM}+) — same games as every other model here')
    print('=' * 88)
    print(nm.fmt('Offence/defence split', nm.score(hold)))
    print(f"{'Elo (current model)':<34} n=854   acc= 64.3%   logloss=0.6334   brier=0.2214")
    print(f"{'Kalman (rejected)':<34} n=854   acc= 64.1%   logloss=0.6373   brier=0.2234")
    print(f"{'betting market':<34} n=854   acc= 67.9%   logloss=0.6077   brier=0.2102")

    print('\nTRAINING ERA')
    print(nm.fmt('Offence/defence split', nm.score(train)))
    print(f"{'Elo (current model)':<34} n=5889  acc= 64.3%   logloss=0.6300")

    print('\nMost lopsided teams (where a single rating loses information):')
    spread = sorted(off, key=lambda t: -(off[t] - dfn[t]))
    print(f"   {'team':<6}{'offence':>9}{'defence':>9}   (points vs average; "
          "defence negative = allows fewer)")
    for t in spread[:5] + spread[-3:]:
        print(f'   {t:<6}{off[t]:>+9.2f}{dfn[t]:>+9.2f}')


if __name__ == '__main__':
    main()
