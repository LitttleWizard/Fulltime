#!/usr/bin/env python3
"""
Bake the empirical error distributions a match simulation needs -> data/sim-dist.json

Why empirical rather than a normal: NFL margins pile up on the key numbers —
15.0% of games finish exactly 3 apart and 9.1% exactly 7, because of how
scoring works. A Gaussian smears those into nothing and misprices the most
common results in the sport. Sampling real residuals keeps the shape.

Two distributions per league:
  marginResid  actual margin  - margin the rating gap implied
  totalResid   actual total   - the two sides' recent scoring average

Both are stored as a plain list of integers, which the browser samples with a
uniform draw. A few thousand values captures the shape and costs a few KB.

Usage:  python3 scripts/build_sim.py
"""
import csv, io, json, math, os, sys, urllib.request
from collections import defaultdict, deque

import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))

OUT = 'data/sim-dist.json'
FORM_N = 12          # recent games defining a team's scoring level
CAP = 4000           # residuals kept per league


def thin(vals, cap=CAP):
    """Even stride through the sorted values, preserving the distribution."""
    vals = sorted(vals)
    if len(vals) <= cap:
        return vals
    step = len(vals) / cap
    return [vals[min(len(vals) - 1, int(i * step))] for i in range(cap)]


def residuals(games, K, home_adv, regress, mov, elo_per_point):
    """Walk forward; collect margin and total residuals against the model."""
    r = defaultdict(lambda: 1500.0)
    recent = defaultdict(lambda: deque(maxlen=FORM_N))
    season = None
    mres, tres = [], []
    for g in games:
        if season is not None and g['season'] != season:
            for t in r:
                r[t] = 1500.0 + (r[t] - 1500.0) * regress
        season = g['season']
        h, a = g['home'], g['away']
        dr = r[h] - r[a] + home_adv
        margin, total = g['hs'] - g['as'], g['hs'] + g['as']

        if len(recent[h]) >= 6 and len(recent[a]) >= 6:
            pred_margin = dr / elo_per_point
            pred_total = (sum(recent[h]) / len(recent[h])) + (sum(recent[a]) / len(recent[a]))
            mres.append(round(margin - pred_margin))
            tres.append(round(total - pred_total))

        p = 1 / (1 + 10 ** (-dr / 400.0))
        won = 1 if margin > 0 else (0 if margin < 0 else 0.5)
        mult = 1.0 if margin == 0 else mov(margin, dr if margin > 0 else -dr)
        d = K * mult * (won - p)
        r[h] += d
        r[a] -= d
        # a team's own scoring level, for the total
        recent[h].append(g['hs'])
        recent[a].append(g['as'])
    return mres, tres


def load_nba():
    doc = json.load(open('data/nba-games.json'))
    gs = [{'season': g['season'], 'home': g['home'], 'away': g['away'],
           'hs': g['hs'], 'as': g['as'], 'date': g['date']} for g in doc['games']]
    gs.sort(key=lambda g: g['date'])
    return gs


def load_nfl():
    url = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
    txt = urllib.request.urlopen(url, timeout=120).read().decode('utf-8', 'replace')
    gs = []
    for g in csv.DictReader(io.StringIO(txt)):
        try:
            s = int(g['season'])
        except (ValueError, TypeError):
            continue
        if s < 2001 or not g['home_score'] or not g['away_score']:
            continue
        gs.append({'season': s, 'home': g['home_team'], 'away': g['away_team'],
                   'hs': int(g['home_score']), 'as': int(g['away_score']),
                   'date': g.get('gameday') or ''})
    gs.sort(key=lambda g: g['date'])
    return gs


MOV = {
    'nba': lambda m, wd: ((abs(m) + 3) ** 0.8) / (7.5 + 0.006 * wd),
    'nfl': lambda m, wd: math.log(abs(m) + 1) * (2.2 / (wd * 0.001 + 2.2)),
}
CONST = {
    'nba': dict(K=16, home_adv=45, regress=0.50, elo_per_point=20.1),
    'nfl': dict(K=20, home_adv=48, regress=0.60, elo_per_point=22.8),
}


def main():
    out = {}
    for lg, loader in [('nba', load_nba), ('nfl', load_nfl)]:
        games = loader()
        c = CONST[lg]
        mres, tres = residuals(games, c['K'], c['home_adv'], c['regress'],
                               MOV[lg], c['elo_per_point'])
        if not mres:
            print(f'{lg}: no residuals'); continue
        import statistics as st
        out[lg] = {'marginResid': thin(mres), 'totalResid': thin(tres),
                   'n': len(mres),
                   'marginSd': round(st.pstdev(mres), 2),
                   'totalSd': round(st.pstdev(tres), 2)}
        # how much of the shape a normal would miss
        near = {k: round(sum(1 for m in mres if abs(m) == k) / len(mres) * 100, 1)
                for k in (3, 7)}
        print(f'{lg}: {len(mres)} residuals · margin SD {out[lg]["marginSd"]} · '
              f'total SD {out[lg]["totalSd"]} · |resid|=3 {near[3]}% =7 {near[7]}%')

    import time
    out['generated'] = time.strftime('%Y-%m-%d')
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print(f'\nwrote {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
