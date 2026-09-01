#!/usr/bin/env python3
"""
Do rest days and back-to-backs add anything to NBA Elo?

Rest is the signal every NBA fan will expect, and unlike the weather features
rejected on the NFL tab it is knowable before tip-off, so it is fair game. This
fits it in log-odds on top of Elo, tuned on seasons <= 2024 and scored on the
2025+ holdout the tuning never saw.

Also measures the Elo-per-point conversion used for the projected spread, by
regressing actual margin on the pre-game rating gap, rather than borrowing the
NFL's ~25 constant.

Usage:  python3 nba_features.py
"""
import json, math, sys
from collections import defaultdict
from datetime import date

import nba_model as M

TUNE_MAX = 2024
EPS = 1e-15


def dnum(s):
    y, m, d = map(int, s.split('-')); return date(y, m, d).toordinal()


def build(games, K, HOME, REG):
    """Walk forward, emitting a row per game with Elo prob and rest context."""
    r = defaultdict(lambda: M.BASE)
    last = {}
    season = None
    rows = []
    for g in games:
        if season != g['season']:
            if season is not None:
                for t in r:
                    r[t] = M.BASE + (r[t] - M.BASE) * (1 - REG)
            last.clear()
            season = g['season']
        h, a, day = g['home'], g['away'], dnum(g['date'])
        adv = 0 if g.get('neutral') else HOME
        diff = (r[h] + adv) - r[a]
        p = 1.0 / (1 + 10 ** (-diff / 400.0))
        won = 1 if g['hs'] > g['as'] else 0
        rh = day - last[h] if h in last else None
        ra = day - last[a] if a in last else None
        rows.append({'p': p, 'won': won, 'season': g['season'], 'diff': diff,
                     'margin': g['hs'] - g['as'],
                     'restH': rh, 'restA': ra,
                     'b2bH': 1 if rh == 1 else 0, 'b2bA': 1 if ra == 1 else 0})
        margin = abs(g['hs'] - g['as'])
        wdiff = diff if won else -diff
        mult = ((margin + 3) ** 0.8) / (7.5 + 0.006 * wdiff)
        d = K * mult * (won - p)
        r[h] += d; r[a] -= d
        last[h] = last[a] = day
    return rows


def logloss(rows, feat=None, beta=0.0):
    t = 0.0
    for x in rows:
        p = x['p']
        if feat and beta:
            z = math.log(max(p, EPS) / max(1 - p, EPS)) + beta * feat(x)
            p = 1 / (1 + math.exp(-z))
        t += -math.log(max(p if x['won'] else 1 - p, EPS))
    return t / len(rows)


def acc(rows, feat=None, beta=0.0):
    ok = 0
    for x in rows:
        p = x['p']
        if feat and beta:
            z = math.log(max(p, EPS) / max(1 - p, EPS)) + beta * feat(x)
            p = 1 / (1 + math.exp(-z))
        ok += (p >= 0.5) == (x['won'] == 1)
    return ok / len(rows)


def fit(rows, feat, lo=-1.0, hi=1.0):
    best, bb, b = logloss(rows), 0.0, lo
    while b <= hi + 1e-9:
        v = logloss(rows, feat, b)
        if v < best: best, bb = v, b
        b += 0.01
    return bb


def main():
    games, teams = M.load()
    cal = json.load(open('nba-calibration.json'))
    K, HOME, REG = cal['K'], cal['home'], cal['regress']
    print(f'Elo constants from nba_model.py: K={K} HOME={HOME} REGRESS={REG}')

    rows = build(games, K, HOME, REG)
    tune = [x for x in rows if x['season'] <= TUNE_MAX]
    hold = [x for x in rows if x['season'] > TUNE_MAX]
    print(f'{len(tune)} tuning rows, {len(hold)} holdout rows\n')

    FEATS = {
        'back-to-back (either side)': lambda x: x['b2bA'] - x['b2bH'],
        'rest-day difference / 3':    lambda x: 0 if x['restH'] is None or x['restA'] is None
                                      else max(-3, min(3, x['restH'] - x['restA'])) / 3,
    }
    base_ll, base_acc = logloss(hold), acc(hold)
    print(f"{'feature':<32}{'beta':>8}{'holdout ll':>13}{'vs base':>10}{'acc':>9}")
    print('-' * 72)
    print(f"{'Elo alone':<32}{'':>8}{base_ll:>13.4f}{'':>10}{base_acc*100:>8.1f}%")
    keep = {}
    for name, f in FEATS.items():
        b = fit(tune, f)
        ll, a2 = logloss(hold, f, b), acc(hold, f, b)
        flag = '  <-- helps' if ll < base_ll else ''
        keep[name] = (b, ll)
        print(f"{name:<32}{b:>+8.2f}{ll:>13.4f}{base_ll-ll:>+10.4f}{a2*100:>8.1f}%{flag}")

    # Elo points per point of margin. Regress margin ON the rating gap (the
    # near-noiseless side) and invert: regressing the other way attenuates the
    # slope toward zero, because margin carries most of the variance.
    slope = sum(x['diff'] * x['margin'] for x in rows) / sum(x['diff'] ** 2 for x in rows)
    per_point = 1 / slope
    resid = sum((x['margin'] - slope * x['diff']) ** 2 for x in rows) / len(rows)
    print(f'\nElo gap per point of margin: {per_point:.1f}'
          f'   (margin ~= gap / {per_point:.1f}; NFL uses ~25)')
    print(f'residual SD of margin: {resid ** 0.5:.1f} points over {len(rows)} games')
    return 0


if __name__ == '__main__':
    sys.exit(main())
