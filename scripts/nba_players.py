#!/usr/bin/env python3
"""
Does knowing who is unavailable improve the NBA prediction?

On the EPL tab this failed: Dixon-Coles already infers team strength from
results, so a squad rating told it nothing new. Basketball should be different —
one starter is a fifth of the floor, and a rating built from past results cannot
know that tonight's best player is out.

The feature is availability, not talent:

    availability = (recent scoring of the players who suited up)
                 / (recent scoring of the team's usual rotation)

Weights come only from a team's PRIOR games, so the measure of who matters is
never taken from the game being predicted. Who actually appeared is
contemporaneous — which is exactly what an injury report tells you before
tip-off, and ESPN publishes those for scheduled games.

Betas are cross-fitted: fitted on one half of the window, scored on the other,
then swapped, so no game is scored by a beta that saw it.

Usage:  python3 nba_players.py
"""
import json, math, sys
from collections import defaultdict, deque

import nba_model as M

# Paths below are relative to the repo root, so the script works from any
# working directory. The join is absolute, so re-running it (a script that
# imports another that also does this) is a no-op rather than climbing up.
import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))


BOX = 'data/nba-box.json'
FORM_N = 10        # prior games defining a player's recent value
MIN_MIN = 8        # a rotation player, not a garbage-time cameo
EPS = 1e-15


def build_rows(games, box, K, HOME, REG):
    """Walk forward, emitting Elo probability + availability per game."""
    r = defaultdict(lambda: M.BASE)
    recent = defaultdict(lambda: defaultdict(lambda: deque(maxlen=FORM_N)))
    season = None
    rows = []

    for g in games:
        if season != g['season']:
            if season is not None:
                for t in r:
                    r[t] = M.BASE + (r[t] - M.BASE) * (1 - REG)
            recent.clear()
            season = g['season']

        h, a = g['home'], g['away']
        adv = 0 if g.get('neutral') else HOME
        diff = (r[h] + adv) - r[a]
        p = 1.0 / (1 + 10 ** (-diff / 400.0))
        won = 1 if g['hs'] > g['as'] else 0

        bx = box.get(g['id'])
        avail = {}
        if bx:
            for team in (h, a):
                rows_t = bx.get(team)
                if not rows_t:
                    continue
                # a player's value = mean points across their recent appearances
                def val(pid):
                    d = recent[team][pid]
                    return sum(d) / len(d) if d else 0.0
                rotation = [pid for pid in recent[team]
                            if len(recent[team][pid]) >= 3 and val(pid) > 0]
                if len(rotation) < 6:
                    continue
                played_now = {row[0] for row in rows_t if row[3] and row[1] >= MIN_MIN}
                total = sum(val(pid) for pid in rotation)
                here = sum(val(pid) for pid in rotation if pid in played_now)
                if total > 0:
                    avail[team] = here / total

        if len(avail) == 2:
            rows.append({'p': p, 'won': won, 'season': g['season'], 'date': g['date'],
                         'home': h, 'away': a,
                         'availH': avail[h], 'availA': avail[a],
                         'feat': avail[h] - avail[a]})

        # update Elo
        margin = abs(g['hs'] - g['as'])
        wdiff = diff if won else -diff
        mult = ((margin + 3) ** 0.8) / (7.5 + 0.006 * wdiff)
        d = K * mult * (won - p)
        r[h] += d
        r[a] -= d

        # update player recent scoring from tonight's box
        if bx:
            for team in (h, a):
                for pid, mn, pts, played in bx.get(team, []):
                    if played and mn >= MIN_MIN:
                        recent[team][pid].append(pts)
    return rows


def apply_beta(p, feat, beta):
    z = math.log(max(p, EPS) / max(1 - p, EPS)) + beta * feat
    return 1 / (1 + math.exp(-z))


def logloss(rows, beta=0.0):
    t = 0.0
    for x in rows:
        p = apply_beta(x['p'], x['feat'], beta) if beta else x['p']
        t += -math.log(max(p if x['won'] else 1 - p, EPS))
    return t / len(rows)


def acc(rows, beta=0.0):
    ok = 0
    for x in rows:
        p = apply_beta(x['p'], x['feat'], beta) if beta else x['p']
        ok += (p >= 0.5) == (x['won'] == 1)
    return ok / len(rows)


def fit_beta(rows, lo=-4.0, hi=4.0):
    best, bb, b = logloss(rows), 0.0, lo
    while b <= hi + 1e-9:
        v = logloss(rows, b)
        if v < best:
            best, bb = v, b
        b += 0.02
    return bb


def main():
    try:
        box = json.load(open(BOX))
    except FileNotFoundError:
        print(f'{BOX} missing — run: python3 fetch_nba_box.py'); return 1
    games, teams = M.load()
    cal = json.load(open('data/nba-calibration.json'))
    K, HOME, REG = cal['K'], cal['home'], cal['regress']
    print(f'{len(box)} games with box scores; Elo K={K} HOME={HOME} REGRESS={REG}')

    rows = build_rows(games, box, K, HOME, REG)
    if len(rows) < 200:
        print(f'only {len(rows)} scorable rows — not enough'); return 1
    print(f'{len(rows)} games scored ({rows[0]["date"]} .. {rows[-1]["date"]})\n')

    mid = len(rows) // 2
    first, second = rows[:mid], rows[mid:]
    b1, b2 = fit_beta(second), fit_beta(first)
    xf_ll = (logloss(first, b1) * len(first) + logloss(second, b2) * len(second)) / len(rows)
    xf_acc = (acc(first, b1) * len(first) + acc(second, b2) * len(second)) / len(rows)
    base_ll, base_acc = logloss(rows), acc(rows)

    print(f"{'model':<40}{'logloss':>10}{'acc':>9}{'betas':>16}")
    print('-' * 75)
    print(f"{'Elo + back-to-back (as shipped)':<40}{base_ll:>10.4f}{base_acc*100:>8.1f}%")
    flag = '  <-- helps' if xf_ll < base_ll else ''
    print(f"{'+ availability (cross-fitted)':<40}{xf_ll:>10.4f}{xf_acc*100:>8.1f}%"
          f"{f'{b1:+.2f}/{b2:+.2f}':>16}{flag}")
    print(f'\nimprovement: {base_ll - xf_ll:+.4f} log-loss, '
          f'{(xf_acc - base_acc)*100:+.1f} points of accuracy')

    # how often does availability actually differ enough to matter?
    big = [x for x in rows if abs(x['feat']) > 0.10]
    print(f'\ngames where availability differs by >10pp: {len(big)} '
          f'({len(big)/len(rows)*100:.0f}%)')
    if big:
        bb = fit_beta(big)
        print(f'  on those alone: {logloss(big):.4f} -> {logloss(big, bb):.4f} '
              f'(beta {bb:+.2f}, in-sample — directional only)')
    worst = sorted(rows, key=lambda x: min(x['availH'], x['availA']))[:5]
    print('\nlargest measured absences')
    for x in worst:
        side, v = ((x['home'], x['availH']) if x['availH'] < x['availA']
                   else (x['away'], x['availA']))
        print(f"  {x['date']}  {side:<5} had {v*100:4.0f}% of its usual scoring available")

    json.dump({'beta': round((b1 + b2) / 2, 3), 'n': len(rows),
               'base': base_ll, 'withAvail': xf_ll,
               'accBase': base_acc, 'accAvail': xf_acc},
              open('data/nba-availability.json', 'w'), separators=(',', ':'))
    print('\nwrote nba-availability.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
