#!/usr/bin/env python3
"""
Honest accuracy evaluation for the Fulltime Elo model.

calibrate_elo.py tunes the model's constants and reports the score on the SAME
matches it tuned on — that number is optimistically biased. This script answers
"how accurate is it really?" by:

  1. Splitting into a tuning era and a held-out era the constants never saw.
  2. Scoring against baselines (uniform, base-rate, always-pick-home) so the
     numbers have a floor to be compared to.
  3. Scoring against the betting market (de-vigged closing odds) — the practical
     ceiling for this kind of model.
  4. Printing a reliability table: when it says 60%, does it happen 60% of the time?

Usage:  python3 evaluate.py
"""
import csv
import json
import math
import urllib.request
from collections import defaultdict

SEASONS = ['2017-18','2018-19','2019-20','2020-21','2021-22',
           '2022-23','2023-24','2024-25','2025-26','2026-27']
FD_CODES = {'2017-18':'1718','2018-19':'1819','2019-20':'1920','2020-21':'2021',
            '2021-22':'2122','2022-23':'2223','2023-24':'2324','2024-25':'2425',
            '2025-26':'2526','2026-27':'2627'}
OPENFOOTBALL = 'https://raw.githubusercontent.com/openfootball/football.json/master'
FOOTBALL_DATA = 'https://www.football-data.co.uk/mmz4281/{code}/E0.csv'

WARMUP_SEASONS = 1
# Seasons held out of the constant-tuning in calibrate_elo.py's grid search.
# Everything before this is "in-sample"; from here on is a genuine holdout.
HOLDOUT_FROM = '2024-25'
FORM_WINDOW = 8
EPS = 1e-15

# Calibrated constants currently shipping in index.html
P = dict(K=20, HOME_ADV=50, REGRESS=0.9,
         DRAW_BASE=0.28, DRAW_SLOPE=0.0004, DRAW_FLOOR=0.06, DRAW_CAP=0.30,
         GOAL_W=0.25, SHOT_W=0.12, NUDGE_SCALE=1.5, NUDGE_CAP=0.10)
DEFAULT_RATING = 1500.0

NAME_MAP = {
    "Arsenal": "Arsenal FC", "Aston Villa": "Aston Villa FC", "Bournemouth": "AFC Bournemouth",
    "Brentford": "Brentford FC", "Brighton": "Brighton & Hove Albion FC", "Burnley": "Burnley FC",
    "Chelsea": "Chelsea FC", "Coventry": "Coventry City FC", "Crystal Palace": "Crystal Palace FC",
    "Everton": "Everton FC", "Fulham": "Fulham FC", "Hull": "Hull City AFC",
    "Ipswich": "Ipswich Town FC", "Leeds": "Leeds United FC", "Leicester": "Leicester City FC",
    "Liverpool": "Liverpool FC", "Luton": "Luton Town FC", "Man City": "Manchester City FC",
    "Man United": "Manchester United FC", "Newcastle": "Newcastle United FC",
    "Nott'm Forest": "Nottingham Forest FC", "Sheffield United": "Sheffield United FC",
    "Southampton": "Southampton FC", "Sunderland": "Sunderland AFC",
    "Tottenham": "Tottenham Hotspur FC", "West Ham": "West Ham United FC",
    "Wolves": "Wolverhampton Wanderers FC", "Watford": "Watford FC",
    "West Brom": "West Bromwich Albion FC", "Norwich": "Norwich City FC",
    "Middlesbrough": "Middlesbrough FC", "Cardiff": "Cardiff City FC",
    "Huddersfield": "Huddersfield Town FC", "Swansea": "Swansea City FC",
    "Stoke": "Stoke City FC", "Blackburn": "Blackburn Rovers FC",
}


def final_score(m):
    s = m.get('score')
    if not s:
        return None
    if isinstance(s, dict) and isinstance(s.get('ft'), list):
        return s['ft']
    if isinstance(s, list):
        return s
    return None


def fetch_seasons():
    out = []
    for s in SEASONS:
        with urllib.request.urlopen(f'{OPENFOOTBALL}/{s}/en.1.json') as r:
            d = json.load(r)
        ms = [m for m in d['matches'] if final_score(m)]
        ms.sort(key=lambda m: m.get('date', ''))
        out.append({'season': s, 'matches': ms})
    return out


def fetch_market_and_shots():
    """(date, home, away) -> {'odds': (h,d,a) de-vigged, 'hst':, 'ast':}"""
    idx = {}
    for season, code in FD_CODES.items():
        try:
            with urllib.request.urlopen(FOOTBALL_DATA.format(code=code)) as r:
                text = r.read().decode('utf-8-sig')
        except Exception:
            continue
        for row in csv.DictReader(text.splitlines()):
            h, a = row.get('HomeTeam'), row.get('AwayTeam')
            if not h or not a:
                continue
            try:
                d, mth, y = row['Date'].split('/')
                y = ('20' + y) if len(y) == 2 else y
                date = f'{y}-{mth}-{d}'
            except Exception:
                continue
            key = (date, NAME_MAP.get(h, h), NAME_MAP.get(a, a))

            def num(k):
                try:
                    return float(row.get(k, '') or '')
                except ValueError:
                    return None

            rec = {'hst': num('HST'), 'ast': num('AST')}
            # Prefer market average odds; fall back to Bet365
            oh, od, oa = num('AvgH'), num('AvgD'), num('AvgA')
            if None in (oh, od, oa):
                oh, od, oa = num('B365H'), num('B365D'), num('B365A')
            if None not in (oh, od, oa) and min(oh, od, oa) > 1.0:
                inv = (1 / oh, 1 / od, 1 / oa)
                tot = sum(inv)                      # >1 by the bookmaker's margin
                rec['odds'] = tuple(x / tot for x in inv)   # de-vigged
            idx[key] = rec
    return idx


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def mov_mult(gd):
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8


def run(seasons, market):
    """Walk-forward: predict each match using only prior information."""
    ratings, goal_hist, shot_hist = {}, defaultdict(list), defaultdict(list)
    league_gf = league_ga = 1.4
    rows = []

    for si, season in enumerate(seasons):
        if si > 0:
            for t in ratings:
                ratings[t] = DEFAULT_RATING + (ratings[t] - DEFAULT_RATING) * P['REGRESS']
            avgs = []
            for t in goal_hist:
                h = goal_hist[t][-FORM_WINDOW:]
                if h:
                    avgs.append((sum(x[0] for x in h) / len(h), sum(x[1] for x in h) / len(h)))
            if avgs:
                league_gf = sum(a[0] for a in avgs) / len(avgs)
                league_ga = sum(a[1] for a in avgs) / len(avgs)

        for m in season['matches']:
            home, away = m['team1'], m['team2']
            hg, ag = final_score(m)
            date = m.get('date', '')
            Rh, Ra = ratings.get(home, DEFAULT_RATING), ratings.get(away, DEFAULT_RATING)

            dr = Rh - Ra + P['HOME_ADV']
            win_share = 1 / (1 + 10 ** (-dr / 400))
            draw = clamp(P['DRAW_BASE'] - P['DRAW_SLOPE'] * abs(dr), P['DRAW_FLOOR'], P['DRAW_CAP'])
            ph, pa = (1 - draw) * win_share, (1 - draw) * (1 - win_share)

            def recent(store, team):
                h = store[team][-FORM_WINDOW:]
                if not h:
                    return None
                return (sum(x[0] for x in h) / len(h), sum(x[1] for x in h) / len(h))

            gh, ga_ = recent(goal_hist, home), recent(goal_hist, away)
            sh, sa = recent(shot_hist, home), recent(shot_hist, away)
            if gh and ga_:
                net_h = (gh[0] - league_gf) - (gh[1] - league_ga)
                net_a = (ga_[0] - league_gf) - (ga_[1] - league_ga)
                diff = (net_h - net_a) * P['GOAL_W']
                if sh and sa:
                    diff += ((sh[0] - sh[1]) - (sa[0] - sa[1])) * P['SHOT_W']
                nudge = math.tanh(diff / P['NUDGE_SCALE']) * P['NUDGE_CAP']
                ph, pa = max(0.02, ph + nudge), max(0.02, pa - nudge)
            tot = ph + draw + pa
            probs = (ph / tot, draw / tot, pa / tot)

            actual = 0 if hg > ag else (2 if hg < ag else 1)
            if si >= WARMUP_SEASONS:
                mk = market.get((date, home, away), {})
                rows.append({'season': season['season'], 'probs': probs,
                             'actual': actual, 'odds': mk.get('odds')})

            # update state with the real result
            delta = P['K'] * mov_mult(abs(hg - ag)) * ((1.0 if hg > ag else 0.0 if hg < ag else 0.5) - win_share)
            ratings[home], ratings[away] = Rh + delta, Ra - delta
            goal_hist[home].append((hg, ag))
            goal_hist[away].append((ag, hg))
            mk = market.get((date, home, away), {})
            if mk.get('hst') is not None and mk.get('ast') is not None:
                shot_hist[home].append((mk['hst'], mk['ast']))
                shot_hist[away].append((mk['ast'], mk['hst']))
    return rows


def score(rows, key='probs'):
    n = len(rows)
    if not n:
        return None
    ll = brier = 0.0
    correct = 0
    for r in rows:
        p = r[key]
        ll += -math.log(max(p[r['actual']], EPS))
        brier += sum((p[i] - (1.0 if i == r['actual'] else 0.0)) ** 2 for i in range(3))
        if p.index(max(p)) == r['actual']:
            correct += 1
    return {'n': n, 'logloss': ll / n, 'brier': brier / n, 'acc': correct / n}


def fmt(label, s):
    if not s:
        return f'{label:<34} —'
    return f"{label:<34} n={s['n']:<5} acc={s['acc']*100:5.1f}%   logloss={s['logloss']:.4f}   brier={s['brier']:.4f}"


def main():
    print('Fetching data…')
    seasons = fetch_seasons()
    market = fetch_market_and_shots()
    rows = run(seasons, market)

    insample = [r for r in rows if r['season'] < HOLDOUT_FROM]
    holdout = [r for r in rows if r['season'] >= HOLDOUT_FROM]

    # ---- Baselines -------------------------------------------------------
    # Base rate learned from the in-sample era only, applied to the holdout.
    counts = [0, 0, 0]
    for r in insample:
        counts[r['actual']] += 1
    base = tuple(c / len(insample) for c in counts)
    print(f"\nHistorical outcome split (in-sample): home {base[0]*100:.1f}% / "
          f"draw {base[1]*100:.1f}% / away {base[2]*100:.1f}%")

    for r in rows:
        r['uniform'] = (1 / 3, 1 / 3, 1 / 3)
        r['baserate'] = base
        r['alwayshome'] = (0.98, 0.01, 0.01)

    print('\n' + '=' * 92)
    print('HELD-OUT ERA  (' + HOLDOUT_FROM + ' onward — constants were never tuned on these)')
    print('=' * 92)
    print(fmt('Fulltime Elo model', score(holdout)))
    print(fmt('  baseline: league base rates', score(holdout, 'baserate')))
    print(fmt('  baseline: uniform 33/33/33', score(holdout, 'uniform')))
    print(fmt('  baseline: always pick home', score(holdout, 'alwayshome')))

    mkt = [r for r in holdout if r.get('odds')]
    if mkt:
        for r in mkt:
            r['market'] = r['odds']
        print(fmt('  betting market (de-vigged)', score(mkt, 'market')))
        print(fmt('  our model, same matches', score(mkt)))

    print('\n' + '=' * 92)
    print('IN-SAMPLE ERA  (constants WERE tuned on these — optimistically biased)')
    print('=' * 92)
    print(fmt('Fulltime Elo model', score(insample)))

    print('\nPer season')
    for s in SEASONS:
        rs = [r for r in rows if r['season'] == s]
        if rs:
            tag = 'holdout ' if s >= HOLDOUT_FROM else 'in-sample'
            print(' ', fmt(f'{s} ({tag})', score(rs)))

    # ---- Reliability -----------------------------------------------------
    print('\nReliability — of the outcomes it assigned X% to, how often did they happen?')
    print(f"  {'predicted band':<18}{'n':>7}{'predicted':>12}{'actual':>10}")
    bins = defaultdict(lambda: [0, 0.0, 0])
    for r in rows:
        for i in range(3):
            b = min(int(r['probs'][i] * 10), 9)
            bins[b][0] += 1
            bins[b][1] += r['probs'][i]
            bins[b][2] += 1 if r['actual'] == i else 0
    for b in sorted(bins):
        n, psum, hits = bins[b]
        if n < 25:
            continue
        print(f'  {b*10:>3}–{b*10+10:<14}{n:>7}{psum/n*100:>11.1f}%{hits/n*100:>9.1f}%')


if __name__ == '__main__':
    main()
