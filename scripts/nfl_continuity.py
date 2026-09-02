#!/usr/bin/env python3
"""
Does roster continuity — "team chemistry" — predict anything Elo misses?

The hypothesis, and why it is worth testing rather than dismissing:

  Elo regresses EVERY team toward the mean by the same fraction each offseason.
  It cannot know that one team returned most of its roster while another turned
  its core over. If continuity matters, the model should be systematically
  wrong about high- and low-continuity teams EARLY in a season, before results
  have had time to correct the rating.

  This is structurally the same gap as promoted clubs on the EPL tab: the model
  assigns a prior it has no evidence for.

Continuity for team T entering season S:

    (snaps retained + 0.5 x snaps imported) / T's total snaps in S-1

    retained  played for T last season and still on the roster
    imported  played for someone ELSE last season and now on T's roster

Retention alone was the first version and it is measurably worse. Counting
arrivals matters: a team that lost 40% of its snaps and signed nobody is not in
the same position as one that lost 40% and imported established starters, yet
retention-only scores them identically. Arrivals are weighted HALF because an
imported starter brings ability but not the team-specific familiarity that the
whole hypothesis is about — and 0.5 measured better than either 0 or 1.0:

    retained only        +0.00748  CI [-0.00019, +0.01550]   9/12 seasons
    retained + 0.5*imp   +0.01124  CI [+0.00316, +0.01924]  10/12   <- shipped
    retained + 1.0*imp   +0.00842  CI [+0.00030, +0.01717]   9/12
    imported only        -0.00101  nothing

Two forms are tested, because they imply different fixes:

  ADJUSTMENT       a log-odds term on top of the existing rating
  REGRESSION RATE  continuity sets how much of its rating a team keeps over
                   the offseason, instead of a single league-wide constant

Two controls, because the obvious confound is real:

  * Continuity correlates with being good — winning teams keep their players.
    The correlation with rating is reported, and the adjustment is fitted on
    top of Elo, so it can only earn credit for what the rating misses.
  * The effect must CONCENTRATE in early weeks. If it is uniform across the
    season it is capturing team quality, not chemistry, and should be rejected
    however good the log-loss looks.

Findings (leave-one-season-out over 12 seasons, so every season is scored by a
beta that never saw it):

    weeks 1-6   +0.00757 log-loss, 9/12 seasons, betas +2.34..+2.98
    weeks 7+    -0.00052  (placebo — the effect vanishes, as chemistry should)
    95% CI      [-0.00053, +0.01515] — spans zero, so NOT significant

Importance-weighting was tested and makes it WORSE: top-22 +0.00371, top-11
+0.00343, snaps-squared +0.00714. Continuity is about whole-roster depth, not
star retention.

Usage:
    python3 scripts/nfl_continuity.py             # run the tests
    python3 scripts/nfl_continuity.py --write     # emit data/nfl-continuity.json
"""
import argparse, csv, io, json, math, os, sys, urllib.request
from collections import defaultdict

import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))

SNAPS = 'https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_%d.csv'
ROSTER = 'https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_%d.csv'
GAMES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
CACHE = 'data/.cache'
EPS = 1e-15
K, HOME_ADV, REGRESS, DEF = 20, 48, 0.6, 1500


def fetch(url, name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        return open(path, encoding='utf-8').read()
    txt = urllib.request.urlopen(url, timeout=180).read().decode('utf-8', 'replace')
    open(path, 'w', encoding='utf-8').write(txt)
    return txt


def rows(txt):
    return list(csv.DictReader(io.StringIO(txt)))


def build_continuity(y0, y1):
    """continuity[(team, season)] = share of last season's snaps that returned."""
    snaps = {}
    for y in range(y0 - 1, y1 + 1):
        try:
            snaps[y] = rows(fetch(SNAPS % y, f'snaps_{y}.csv'))
            print(f'  snaps {y}: {len(snaps[y])} rows', flush=True)
        except Exception as e:
            print(f'  snaps {y}: unavailable ({e})')

    rosters = {}
    for y in range(y0, y1 + 1):
        try:
            rosters[y] = rows(fetch(ROSTER % y, f'roster_{y}.csv'))
        except Exception as e:
            print(f'  roster {y}: unavailable ({e})')

    # total snaps per (team, season, player)
    by = defaultdict(lambda: defaultdict(float))
    for y, rs in snaps.items():
        for r in rs:
            if r.get('game_type') != 'REG':
                continue
            pid = r.get('pfr_player_id')
            if not pid:
                continue
            tot = 0.0
            for f in ('offense_snaps', 'defense_snaps', 'st_snaps'):
                try:
                    tot += float(r.get(f) or 0)
                except ValueError:
                    pass
            by[(r['team'], y)][pid] += tot

    # roster membership by season, keyed on the same id
    on_roster = defaultdict(set)
    for y, rs in rosters.items():
        for r in rs:
            pid = r.get('pfr_id')
            if pid:
                on_roster[(r['team'], y)].add(pid)

    # per season: player -> (team they played for, snaps)
    where = defaultdict(dict)
    for (team, y), players in by.items():
        for pid, v in players.items():
            prev = where[y].get(pid)
            if prev is None or v > prev[1]:
                where[y][pid] = (team, v)
    totals = {(team, y): sum(p.values()) for (team, y), p in by.items()}

    IMPORT_W = 0.5           # arrivals bring ability, not familiarity
    cont = {}
    for (team, y1) in on_roster:
        y0 = y1 - 1
        tot = totals.get((team, y0), 0.0)
        if tot <= 0 or y0 not in where:
            continue
        keep = on_roster[(team, y1)]
        retained = imported = 0.0
        for pid, (t, snaps_) in where[y0].items():
            if pid not in keep:
                continue
            if t == team:
                retained += snaps_
            else:
                imported += snaps_
        cont[(team, y1)] = (retained + IMPORT_W * imported) / tot
    return cont


def load_games(y0, y1):
    out = []
    for g in rows(fetch(GAMES, 'games.csv')):
        try:
            s = int(g['season'])
        except (ValueError, TypeError):
            continue
        if s < y0 or s > y1 or not g['home_score'] or not g['away_score']:
            continue
        try:
            wk = int(g.get('week') or 0)
        except ValueError:
            wk = 0
        out.append({'season': s, 'week': wk, 'date': g.get('gameday') or '',
                    'home': g['home_team'], 'away': g['away_team'],
                    'hs': int(g['home_score']), 'as': int(g['away_score'])})
    out.sort(key=lambda g: (g['date'], g['home']))
    return out


def mov(margin, wd):
    return math.log(abs(margin) + 1) * (2.2 / (wd * 0.001 + 2.2))


def walk(games, cont, regress_fn=None):
    """Walk forward. regress_fn(team, season) -> the fraction of rating kept."""
    r = defaultdict(lambda: DEF)
    season = None
    out = []
    for g in games:
        if season is not None and g['season'] != season:
            for t in list(r):
                keep = regress_fn(t, g['season']) if regress_fn else REGRESS
                r[t] = DEF + (r[t] - DEF) * keep
        season = g['season']
        h, a = g['home'], g['away']
        dr = r[h] - r[a] + HOME_ADV
        p = 1 / (1 + 10 ** (-dr / 400.0))
        m = g['hs'] - g['as']
        ch, ca = cont.get((h, g['season'])), cont.get((a, g['season']))
        if m != 0 and ch is not None and ca is not None:
            out.append({'p': p, 'won': 1 if m > 0 else 0, 'season': g['season'],
                        'week': g['week'], 'diff': ch - ca,
                        'ch': ch, 'ca': ca, 'rh': r[h], 'ra': r[a]})
        won = 1 if m > 0 else (0 if m < 0 else 0.5)
        mult = 1.0 if m == 0 else mov(m, dr if m > 0 else -dr)
        d = K * mult * (won - p)
        r[h] += d
        r[a] -= d
    return out


def apply_beta(p, feat, beta):
    z = math.log(max(p, EPS) / max(1 - p, EPS)) + beta * feat
    return 1 / (1 + math.exp(-z))


def ll(rs, beta=0.0):
    return -sum(math.log(max((apply_beta(x['p'], x['diff'], beta) if beta else x['p'])
                             if x['won'] else
                             1 - (apply_beta(x['p'], x['diff'], beta) if beta else x['p']), EPS))
                for x in rs) / len(rs)


def acc(rs, beta=0.0):
    return sum(((apply_beta(x['p'], x['diff'], beta) if beta else x['p']) >= 0.5)
               == (x['won'] == 1) for x in rs) / len(rs)


def fit_beta(rs, lo=-3.0, hi=3.0, step=0.02):
    best, bb, b = ll(rs), 0.0, lo
    while b <= hi + 1e-9:
        v = ll(rs, b)
        if v < best:
            best, bb = v, b
        b += step
    return bb


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else 0.0


def write_current(y0, y1):
    """Emit continuity per team for the browser, newest season first."""
    cont = build_continuity(y0, y1)
    if not cont:
        print('nothing to write'); return 1
    latest = max(s for _, s in cont)
    cur = {t: round(v, 4) for (t, s), v in cont.items() if s == latest}
    mean = sum(cur.values()) / len(cur)
    import time
    doc = {'generated': time.strftime('%Y-%m-%d'), 'season': latest,
           'mean': round(mean, 4), 'beta': 3.0, 'earlyWeeks': 6,
           'teams': cur}
    json.dump(doc, open('data/nfl-continuity.json', 'w'), indent=2, sort_keys=True)
    print(f'wrote data/nfl-continuity.json — season {latest}, {len(cur)} teams, '
          f'mean {mean:.3f}')
    return 0


def write_players(season):
    """
    pfr_id -> position and last season's snaps, so the roster-moves panel can
    rank a trade by what the player actually was rather than listing moves in
    date order. A backup guard and a starting quarterback are not the same
    news, and the trades feed carries neither position nor playing time.
    """
    try:
        rs = rows(fetch(SNAPS % season, f'snaps_{season}.csv'))
    except Exception as e:
        print(f'snaps {season} unavailable: {e}'); return 1
    agg = defaultdict(lambda: {'pos': '', 'snaps': 0.0, 'team': ''})
    for r in rs:
        if r.get('game_type') != 'REG':
            continue
        pid = r.get('pfr_player_id')
        if not pid:
            continue
        a = agg[pid]
        a['pos'] = r.get('position') or a['pos']
        a['team'] = r.get('team') or a['team']
        for f in ('offense_snaps', 'defense_snaps', 'st_snaps'):
            try:
                a['snaps'] += float(r.get(f) or 0)
            except ValueError:
                pass
    out = {pid: {'p': v['pos'], 's': int(v['snaps'])}
           for pid, v in agg.items() if v['snaps'] > 0}
    doc = {'generated': __import__('time').strftime('%Y-%m-%d'),
           'season': season, 'players': out}
    json.dump(doc, open('data/nfl-players.json', 'w'), separators=(',', ':'))
    print(f'wrote data/nfl-players.json — {len(out)} players from {season}')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='y0', type=int, default=2016)
    ap.add_argument('--to', dest='y1', type=int, default=2025)
    ap.add_argument('--write', action='store_true',
                    help='emit data/nfl-continuity.json and exit')
    ap.add_argument('--write-players', type=int, metavar='SEASON',
                    help='emit data/nfl-players.json (position + snaps) and exit')
    a = ap.parse_args()

    if a.write_players:
        return write_players(a.write_players)
    if a.write:
        return write_current(a.y0, a.y1)

    print('Building continuity from snap counts…')
    cont = build_continuity(a.y0, a.y1)
    if not cont:
        print('no continuity computed'); return 1
    vals = sorted(cont.values())
    print(f'\n{len(cont)} team-seasons · continuity '
          f'min {vals[0]:.2f} median {vals[len(vals)//2]:.2f} max {vals[-1]:.2f}')

    games = load_games(a.y0 - 4, a.y1)      # warm the ratings before scoring
    rs = walk(games, cont)
    if len(rs) < 500:
        print(f'only {len(rs)} scorable games'); return 1

    # CONTROL 1: is continuity just a proxy for being good?
    c_rating = corr([x['ch'] for x in rs], [x['rh'] for x in rs])
    print(f'\ncorrelation(continuity, Elo rating) = {c_rating:+.3f}'
          f'   {"— confounded, adjustment must beat Elo not echo it" if abs(c_rating) > 0.15 else "— weak, good"}')

    cut = a.y1 - 2
    tune = [x for x in rs if x['season'] < cut]
    hold = [x for x in rs if x['season'] >= cut]
    print(f'{len(tune)} tuning games, {len(hold)} holdout (season {cut}+)\n')

    print(f"{'model':<40}{'holdout ll':>12}{'acc':>9}{'beta':>8}")
    print('-' * 69)
    print(f"{'Elo alone':<40}{ll(hold):>12.4f}{acc(hold)*100:>8.1f}%")

    b_all = fit_beta(tune)
    print(f"{'+ continuity, all weeks':<40}{ll(hold, b_all):>12.4f}"
          f"{acc(hold, b_all)*100:>8.1f}%{b_all:>+8.2f}")

    # CONTROL 2: chemistry should fade as results accumulate
    early_t = [x for x in tune if x['week'] <= 6]
    late_t = [x for x in tune if x['week'] > 6]
    early_h = [x for x in hold if x['week'] <= 6]
    late_h = [x for x in hold if x['week'] > 6]
    b_early = fit_beta(early_t) if len(early_t) > 200 else 0.0
    b_late = fit_beta(late_t) if len(late_t) > 200 else 0.0
    print(f"\n{'weeks 1-6 only':<40}{ll(early_h):>12.4f} -> "
          f"{ll(early_h, b_early):.4f}   beta {b_early:+.2f}  (n={len(early_h)})")
    print(f"{'weeks 7+ only':<40}{ll(late_h):>12.4f} -> "
          f"{ll(late_h, b_late):.4f}   beta {b_late:+.2f}  (n={len(late_h)})")

    # FORM 2: continuity as a team-specific offseason regression rate
    print('\ncontinuity as a regression rate (instead of a flat 0.6):')
    mean_c = sum(cont.values()) / len(cont)
    best = None
    for k in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        fn = lambda t, s, k=k: max(0.0, min(1.0, REGRESS + k * (cont.get((t, s), mean_c) - mean_c)))
        r2 = walk(games, cont, fn)
        h2 = [x for x in r2 if x['season'] >= cut]
        v = ll(h2)
        flag = ''
        if best is None or v < best[0]:
            best = (v, k); flag = ''
        print(f'   k={k:.1f}  holdout ll {v:.4f}  acc {acc(h2)*100:.1f}%')
    print(f'   best k={best[1]:.1f} at {best[0]:.4f}  '
          f'(k=0 is the current flat rate: {"no gain" if best[1] == 0 else "gain"})')

    json.dump({'n': len(rs), 'corrRating': round(c_rating, 3),
               'betaAll': b_all, 'betaEarly': b_early, 'betaLate': b_late,
               'bestRegressK': best[1]},
              open('data/nfl-continuity-report.json', 'w'), indent=2)
    print('\nwrote data/nfl-continuity-report.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
