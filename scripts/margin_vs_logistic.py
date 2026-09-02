#!/usr/bin/env python3
"""
Two ways to get P(home win) out of the same Elo ratings — which is better?

  LOGISTIC   p = 1 / (1 + 10^(-gap/400))          what the pages ship
  MARGIN     p = P(gap/eloPerPoint + residual > 0) implied by the simulation

They disagree by a point or two. The pages currently resolve that by shifting
the margin view onto the logistic, on the grounds that the logistic is the
validated one — but "validated" was never checked against this alternative, so
that was an assumption, not a result. This tests it.

Also tests a BLEND, since two estimators of the same quantity that disagree can
between them beat either alone. The blend weight is fitted on the tuning era
only and scored on the holdout.

No leakage: the residual distribution used to score a game is built only from
games played before it, accumulated as the walk-forward proceeds.

Usage:
    python3 scripts/margin_vs_logistic.py            # single holdout
    python3 scripts/margin_vs_logistic.py --rolling  # every season, pooled

The rolling mode exists because the single holdout misled: it showed the margin
view significantly better for the NBA, that was shipped, and evaluating across
all seasons withdrew it. The holdout had landed on the two seasons where the
margin view happened to lead.
"""
import bisect, csv, io, json, math, sys, urllib.request
from collections import defaultdict

import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))

EPS = 1e-15
MIN_RESID = 400          # residuals needed before the margin view is trusted

CONST = {
    'nba': dict(K=16, home=45, regress=0.50, epp=20.1, holdout=2025,
                mov=lambda m, wd: ((abs(m) + 3) ** 0.8) / (7.5 + 0.006 * wd)),
    'nfl': dict(K=20, home=48, regress=0.60, epp=22.8, holdout=2023,
                mov=lambda m, wd: math.log(abs(m) + 1) * (2.2 / (wd * 0.001 + 2.2))),
}


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


def logit(p):
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + math.exp(-z))


def walk(league, games):
    """Emit per-game (pLogistic, pMargin, won, season) with no leakage."""
    c = CONST[league]
    r = defaultdict(lambda: 1500.0)
    resid = []                      # sorted list of past margin residuals
    season = None
    rows = []
    for g in games:
        if season is not None and g['season'] != season:
            for t in r:
                r[t] = 1500.0 + (r[t] - 1500.0) * c['regress']
        season = g['season']

        h, a = g['home'], g['away']
        dr = r[h] - r[a] + c['home']
        margin = g['hs'] - g['as']
        p_log = 1 / (1 + 10 ** (-dr / 400.0))

        p_mar = None
        if len(resid) >= MIN_RESID:
            # P(pred + residual > 0) = share of residuals above -pred
            pred = dr / c['epp']
            i = bisect.bisect_right(resid, -pred)
            p_mar = 1 - i / len(resid)
            p_mar = min(max(p_mar, 0.001), 0.999)

        if margin != 0 and p_mar is not None:
            rows.append({'log': p_log, 'mar': p_mar,
                         'won': 1 if margin > 0 else 0, 'season': g['season']})

        # update: ratings, then the residual pool (order matters for leakage)
        p_elo = p_log
        won = 1 if margin > 0 else (0 if margin < 0 else 0.5)
        mult = 1.0 if margin == 0 else c['mov'](margin, dr if margin > 0 else -dr)
        d = c['K'] * mult * (won - p_elo)
        r[h] += d
        r[a] -= d
        bisect.insort(resid, margin - dr / c['epp'])
    return rows


def ll(rows, f):
    return -sum(math.log(max(f(x) if x['won'] else 1 - f(x), EPS)) for x in rows) / len(rows)


def acc(rows, f):
    return sum((f(x) >= 0.5) == (x['won'] == 1) for x in rows) / len(rows)


def main():
    if '--rolling' in sys.argv:
        return rolling_main()
    for league, loader in [('nba', load_nba), ('nfl', load_nfl)]:
        print(f'\n── {league.upper()} ' + '─' * 56)
        rows = walk(league, loader())
        cut = CONST[league]['holdout']
        tune = [x for x in rows if x['season'] < cut]
        hold = [x for x in rows if x['season'] >= cut]
        if not tune or not hold:
            print('  not enough data'); continue
        print(f'  {len(tune)} tuning games, {len(hold)} holdout (season {cut}+)')

        f_log = lambda x: x['log']
        f_mar = lambda x: x['mar']

        # blend weight fitted on the tuning era only
        best_w, best = 1.0, None
        w = 0.0
        while w <= 1.0001:
            ww = w
            f = lambda x, ww=ww: sigmoid(ww * logit(x['log']) + (1 - ww) * logit(x['mar']))
            v = ll(tune, f)
            if best is None or v < best:
                best, best_w = v, ww
            w += 0.02
        f_bl = lambda x: sigmoid(best_w * logit(x['log']) + (1 - best_w) * logit(x['mar']))

        print(f"\n  {'estimator':<34}{'holdout ll':>12}{'acc':>9}")
        print('  ' + '-' * 55)
        for name, f in [('logistic on the rating gap', f_log),
                        ('margin + empirical residuals', f_mar),
                        (f'blend (w={best_w:.2f} logistic)', f_bl)]:
            print(f'  {name:<34}{ll(hold, f):>12.4f}{acc(hold, f)*100:>8.1f}%')

        base = ll(hold, f_log)
        gain_m = base - ll(hold, f_mar)
        gain_b = base - ll(hold, f_bl)
        print(f'\n  margin vs logistic : {gain_m:+.4f} log-loss')
        print(f'  blend  vs logistic : {gain_b:+.4f} log-loss'
              f'   (weight fitted on tuning only)')
        mean_gap = sum(abs(x['log'] - x['mar']) for x in hold) / len(hold)
        print(f'  they disagree by {mean_gap*100:.1f} points on average')
    return 0




# ── rolling-origin evaluation ────────────────────────────────────────────
def rolling(league, rows):
    """
    Score the two estimators season by season instead of on one holdout.

    The single-holdout test left the NFL underpowered: 854 games could not
    separate the two, which is 'not proven' rather than 'shown equal'. Neither
    estimator has parameters fitted per game — the margin view is a causal
    transform of a residual pool built only from earlier games — so every season
    with a mature pool is a fair paired comparison, and pooling them recovers
    the power the single cutoff threw away.

    The Elo constants were tuned on early seasons, but BOTH estimators share
    them, so that bias cancels in a paired difference.
    """
    import random
    random.seed(19)
    by_season = defaultdict(list)
    for x in rows:
        by_season[x['season']].append(x)

    print(f"\n  {'season':>8}{'n':>7}{'logistic':>11}{'margin':>10}{'diff':>10}")
    print('  ' + '-' * 46)
    wins = 0
    seasons = sorted(by_season)
    for s in seasons:
        r = by_season[s]
        a, b = ll(r, lambda x: x['log']), ll(r, lambda x: x['mar'])
        if a > b:
            wins += 1
        print(f"  {s:>8}{len(r):>7}{a:>11.4f}{b:>10.4f}{a-b:>+10.4f}")

    allrows = [x for s in seasons for x in by_season[s]]
    d = [(-math.log(max(x['log'] if x['won'] else 1 - x['log'], EPS)))
         - (-math.log(max(x['mar'] if x['won'] else 1 - x['mar'], EPS)))
         for x in allrows]
    n = len(d)
    obs = sum(d) / n
    B = 4000
    boot = []
    for _ in range(B):
        t = 0.0
        for _ in range(n):
            t += d[random.randrange(n)]
        boot.append(t / n)
    boot.sort()
    lo95, hi95 = boot[int(0.025 * B)], boot[int(0.975 * B)]
    print(f"\n  pooled over {len(seasons)} seasons, n={n}")
    print(f"  margin advantage {obs:+.5f}  95% CI [{lo95:+.5f}, {hi95:+.5f}]")
    print(f"  margin better in {wins}/{len(seasons)} seasons  "
          f"P(better) = {sum(1 for x in boot if x > 0)/B:.3f}")
    print(f"  -> {'SIGNIFICANT' if lo95 > 0 else 'not distinguishable from noise'}")


def rolling_main():
    for league, loader in [('nba', load_nba), ('nfl', load_nfl)]:
        print(f'\n── {league.upper()} rolling-origin ' + '─' * 40)
        rows = walk(league, loader())
        rolling(league, rows)
    return 0


if __name__ == '__main__':
    sys.exit(main())
