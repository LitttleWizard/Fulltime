#!/usr/bin/env python3
"""
Calibrate and honestly evaluate the NBA Elo model.

Same discipline as `nfl_model.py`: tune on early seasons, report on a holdout
the tuning never touched. In-sample numbers on a rating model are always
flattering and always wrong.

Elo with three knobs worth tuning:
  K        how fast ratings move
  HOME     home-court advantage, in rating points
  REGRESS  fraction pulled back to the mean between seasons

plus a margin-of-victory multiplier. The MOV term carries FiveThirtyEight's
autocorrelation correction: without the `/ (denom)` factor, good teams keep
running up the score against bad ones and their ratings inflate without bound.

Usage:  python3 nba_model.py
"""
import json, math, sys
from collections import defaultdict

SRC = 'nba-games.json'
TUNE_MAX = 2024          # seasons <= this are for tuning
BASE = 1500.0


def load():
    d = json.load(open(SRC))
    return d['games'], d.get('teams', {})


def elo_run(games, K, HOME, REGRESS, mov=True, upto=None, collect=None):
    """Walk forward; return (n, logloss, correct, brier) over scored games."""
    r = defaultdict(lambda: BASE)
    season = None
    n = ll = brier = 0
    correct = 0
    for g in games:
        if season != g['season']:
            if season is not None:
                for t in r:
                    r[t] = BASE + (r[t] - BASE) * (1 - REGRESS)
            season = g['season']
        h, a = g['home'], g['away']
        adv = 0 if g.get('neutral') else HOME
        diff = (r[h] + adv) - r[a]
        p = 1.0 / (1 + 10 ** (-diff / 400.0))
        won = 1 if g['hs'] > g['as'] else 0

        scored = (upto is None) or (g['season'] > upto)
        if scored:
            n += 1
            ll += -math.log(max(p if won else 1 - p, 1e-15))
            brier += (p - won) ** 2
            correct += (p >= 0.5) == (won == 1)
            if collect is not None:
                collect.append({'p': p, 'won': won, 'season': g['season'],
                                'date': g['date'], 'home': h, 'away': a})

        margin = abs(g['hs'] - g['as'])
        if mov:
            # 538's correction: the winner's rating edge damps the multiplier,
            # otherwise blowouts by strong teams compound without limit.
            wdiff = diff if won else -diff
            mult = ((margin + 3) ** 0.8) / (7.5 + 0.006 * wdiff)
        else:
            mult = 1.0
        delta = K * mult * (won - p)
        r[h] += delta
        r[a] -= delta
    return n, (ll / n if n else 0), (correct / n if n else 0), (brier / n if n else 0), r


def main():
    games, teams = load()
    print(f'{len(games)} games, {len(teams)} teams, '
          f'{games[0]["date"]} .. {games[-1]["date"]}')
    tune = [g for g in games if g['season'] <= TUNE_MAX]
    hold = [g for g in games if g['season'] > TUNE_MAX]
    print(f'tuning on seasons <= {TUNE_MAX} ({len(tune)} games); '
          f'holdout {sorted({g["season"] for g in hold})} ({len(hold)} games)\n')

    best = None
    for K in [12, 16, 20, 24, 28, 32]:
        for HOME in [30, 45, 60, 75, 90]:
            for REG in [0.15, 0.25, 0.35, 0.50]:
                n, ll, acc, br, _ = elo_run(tune, K, HOME, REG, upto=2021)
                if best is None or ll < best[0]:
                    best = (ll, K, HOME, REG, acc)
    ll, K, HOME, REG, acc = best
    print(f'best on tuning seasons:  K={K}  HOME={HOME}  REGRESS={REG:.2f}'
          f'   logloss {ll:.4f}  acc {acc*100:.1f}%')

    # honest holdout — parameters above never saw these seasons
    rows = []
    n, hll, hacc, hbr, ratings = elo_run(games, K, HOME, REG, upto=TUNE_MAX, collect=rows)
    print(f'\nHOLDOUT ({n} games)')
    print(f'  accuracy   {hacc*100:.1f}%')
    print(f'  log-loss   {hll:.4f}')
    print(f'  Brier      {hbr:.4f}')

    # baselines worth beating
    base_home = sum(1 for r in rows if r['won'] == 1) / len(rows)
    print(f'\nbaselines on the same games')
    print(f'  always pick home   {base_home*100:.1f}%   '
          f'logloss {-(math.log(base_home)*base_home + math.log(1-base_home)*(1-base_home)):.4f}')
    n2, ll2, acc2, br2, _ = elo_run(games, K, HOME, REG, mov=False, upto=TUNE_MAX)
    print(f'  Elo without MOV    {acc2*100:.1f}%   logloss {ll2:.4f}')

    # calibration
    bins = defaultdict(lambda: [0, 0.0, 0])
    for r in rows:
        b = min(int(r['p'] * 10), 9)
        bins[b][0] += 1; bins[b][1] += r['p']; bins[b][2] += r['won']
    print('\ncalibration — predicted vs actual (home win)')
    for b in sorted(bins):
        c, ps, w = bins[b]
        if c < 40: continue
        print(f'  {b*10:>3}-{b*10+10:<3} n={c:<5} predicted {ps/c*100:5.1f}%   actual {w/c*100:5.1f}%')

    top = sorted(ratings.items(), key=lambda kv: -kv[1])[:8]
    print('\nfinal ratings (top 8)')
    for t, v in top:
        print(f'  {teams.get(t, t):<26}{v:7.0f}')

    json.dump({'K': K, 'home': HOME, 'regress': REG,
               'holdout': {'n': n, 'acc': hacc, 'logloss': hll, 'brier': hbr},
               'baselineHome': base_home},
              open('nba-calibration.json', 'w'), separators=(',', ':'))
    print('\nwrote nba-calibration.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
