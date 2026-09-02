#!/usr/bin/env python3
"""
Which extra signals are actually worth adding to the NFL Elo model?

The nflverse games file already carries rest days, divisional flags, roof,
weather and — usefully — the starting QB for each side. Rather than assume any
of these help, this fits each one as a logistic adjustment on top of the Elo
prediction:

    p' = sigmoid( logit(p_elo) + beta * feature )

beta is fitted on the training era only; the improvement is then measured on a
held-out era. A feature that doesn't beat 0.0000 on the holdout isn't worth the
complexity, no matter how sensible it sounds.

Usage:  python3 nfl_features.py
"""
import csv
import io
import math
import urllib.request

GAMES_URL = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
FIRST_SEASON = 1999
HOLDOUT_FROM = 2023
WARMUP = 2
K, HOME_ADV, REGRESS, DEFAULT = 20, 48, 0.6, 1500.0
EPS = 1e-15


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load():
    req = urllib.request.Request(GAMES_URL, headers={'User-Agent': 'fulltime/1.0'})
    with urllib.request.urlopen(req) as r:
        text = r.read().decode('utf-8')
    out = []
    for g in csv.DictReader(io.StringIO(text)):
        try:
            season = int(g['season'])
        except (TypeError, ValueError):
            continue
        if season < FIRST_SEASON:
            continue
        hs, as_ = g.get('home_score'), g.get('away_score')
        if not hs or not as_:
            continue
        out.append({
            'season': season, 'date': g.get('gameday') or '',
            'home': g['home_team'], 'away': g['away_team'],
            'hs': int(hs), 'as': int(as_),
            'home_rest': num(g.get('home_rest')), 'away_rest': num(g.get('away_rest')),
            'div': g.get('div_game') == '1',
            'roof': (g.get('roof') or '').strip(),
            'temp': num(g.get('temp')), 'wind': num(g.get('wind')),
            'home_qb': (g.get('home_qb_id') or '').strip(),
            'away_qb': (g.get('away_qb_id') or '').strip(),
        })
    out.sort(key=lambda r: (r['date'], r['home']))
    return out


def mov(margin, winner_diff):
    return math.log(abs(margin) + 1) * (2.2 / (winner_diff * 0.001 + 2.2))


def build(games):
    """Replay Elo, and while walking forward record each game's features using
    only information available before kickoff."""
    ratings, prev_season = {}, None
    last_qb = {}          # team -> qb_id of their previous game
    qb_games = {}         # (team, qb) -> how many starts we've seen
    rows = []

    for g in games:
        if prev_season is not None and g['season'] != prev_season:
            for t in ratings:
                ratings[t] = DEFAULT + (ratings[t] - DEFAULT) * REGRESS
        prev_season = g['season']

        h, a = g['home'], g['away']
        Rh, Ra = ratings.get(h, DEFAULT), ratings.get(a, DEFAULT)
        dr = Rh - Ra + HOME_ADV
        p = 1 / (1 + 10 ** (-dr / 400))
        margin = g['hs'] - g['as']

        if g['season'] >= FIRST_SEASON + WARMUP and margin != 0:
            # rest advantage, capped so a bye/short week doesn't dominate
            rd = 0.0
            if g['home_rest'] is not None and g['away_rest'] is not None:
                rd = max(-7, min(7, g['home_rest'] - g['away_rest']))

            # QB change: is this team's starter different from their last game's,
            # and is that starter inexperienced? Net = away disruption - home's.
            def qb_flag(team, qb):
                if not qb:
                    return 0.0
                prev = last_qb.get(team)
                if prev is None:
                    return 0.0
                if qb == prev:
                    return 0.0
                return 1.0 if qb_games.get((team, qb), 0) < 4 else 0.5

            qb_net = qb_flag(a, g['away_qb']) - qb_flag(h, g['home_qb'])

            rows.append({
                'season': g['season'],
                'p': p,
                'y': 1 if margin > 0 else 0,
                'rest': rd / 7.0,
                'div': 1.0 if g['div'] else 0.0,
                'indoor': 1.0 if g['roof'] in ('dome', 'closed') else 0.0,
                'wind': (min(g['wind'], 25) / 25.0) if g['wind'] is not None else 0.0,
                'cold': ((50 - g['temp']) / 50.0) if (g['temp'] is not None and g['temp'] < 50) else 0.0,
                'qb': qb_net,
            })

        # update state
        actual = 1.0 if margin > 0 else (0.0 if margin < 0 else 0.5)
        mult = 1.0 if margin == 0 else mov(margin, dr if margin > 0 else -dr)
        d = K * mult * (actual - p)
        ratings[h], ratings[a] = Rh + d, Ra - d
        for team, qb in ((h, g['home_qb']), (a, g['away_qb'])):
            if qb:
                qb_games[(team, qb)] = qb_games.get((team, qb), 0) + 1
                last_qb[team] = qb
    return rows


def logloss(rows, feats=(), betas=()):
    tot = 0.0
    for r in rows:
        p = min(max(r['p'], EPS), 1 - EPS)
        z = math.log(p / (1 - p))
        for f, b in zip(feats, betas):
            z += b * r[f]
        q = 1 / (1 + math.exp(-z))
        q = min(max(q, EPS), 1 - EPS)
        tot += -(math.log(q) if r['y'] else math.log(1 - q))
    return tot / len(rows)


def accuracy(rows, feats=(), betas=()):
    ok = 0
    for r in rows:
        p = min(max(r['p'], EPS), 1 - EPS)
        z = math.log(p / (1 - p))
        for f, b in zip(feats, betas):
            z += b * r[f]
        ok += ((z >= 0) == (r['y'] == 1))
    return ok / len(rows)


def fit_beta(train, feat):
    best_b, best = 0.0, logloss(train)
    b = -1.5
    while b <= 1.5001:
        v = logloss(train, (feat,), (b,))
        if v < best:
            best, best_b = v, b
        b += 0.02
    return best_b


def main():
    print('Fetching nflverse games…')
    games = load()
    rows = build(games)
    train = [r for r in rows if r['season'] < HOLDOUT_FROM]
    hold = [r for r in rows if r['season'] >= HOLDOUT_FROM]
    base_tr, base_ho = logloss(train), logloss(hold)
    print(f'{len(rows)} scored games — train {len(train)}, holdout {len(hold)}')
    print(f'\nElo baseline    train logloss {base_tr:.4f}   holdout {base_ho:.4f} '
          f'(acc {accuracy(hold)*100:.1f}%)\n')

    labels = {
        'qb':     'QB change / backup starting',
        'rest':   'Rest-day advantage',
        'div':    'Divisional game',
        'indoor': 'Indoor stadium',
        'wind':   'High wind',
        'cold':   'Cold weather',
    }
    print(f"{'feature':<32}{'beta':>7}{'train gain':>12}{'HOLDOUT gain':>14}  verdict")
    print('-' * 84)
    results = []
    for f, label in labels.items():
        b = fit_beta(train, f)
        gt = base_tr - logloss(train, (f,), (b,))
        gh = base_ho - logloss(hold, (f,), (b,))
        results.append((f, b, gh))
        verdict = 'worth adding' if gh > 0.0015 else ('marginal' if gh > 0 else 'NO — hurts holdout')
        print(f'{label:<32}{b:>7.2f}{gt:>12.4f}{gh:>14.4f}  {verdict}')

    # ── Joint fit ─────────────────────────────────────────────────────────
    # Fitting features one at a time understates a set that complements each
    # other, so fit them together by coordinate descent before judging.
    #
    # Only features KNOWN BEFORE KICKOFF are eligible. temp/wind are recorded
    # after the game (0 of 272 upcoming games carry them), so they can never
    # feed a real prediction no matter how they score here.
    USABLE = ('qb', 'rest', 'div', 'indoor')
    print('\n' + '=' * 84)
    print('JOINT FIT — features knowable before kickoff (temp/wind excluded: '
          'recorded post-game)')
    print('=' * 84)

    betas = {f: 0.0 for f in USABLE}
    for _ in range(6):
        for f in USABLE:
            best_b, best = betas[f], logloss(train, tuple(betas), tuple(betas.values()))
            b = -1.5
            while b <= 1.5001:
                trial = dict(betas); trial[f] = b
                v = logloss(train, tuple(trial), tuple(trial.values()))
                if v < best:
                    best, best_b = v, b
                b += 0.02
            betas[f] = best_b

    feats = tuple(USABLE)
    bs = tuple(betas[f] for f in USABLE)
    print('  fitted betas: ' + '  '.join(f'{f}={betas[f]:+.2f}' for f in USABLE))
    print(f'\n  {"":<26}{"logloss":>10}{"accuracy":>11}')
    print(f'  {"Elo baseline":<26}{base_ho:>10.4f}{accuracy(hold)*100:>10.1f}%')
    print(f'  {"+ QB only":<26}{logloss(hold, ("qb",), (betas["qb"],)):>10.4f}"'
          f'{accuracy(hold, ("qb",), (betas["qb"],))*100:>9.1f}%'.replace('"', ''))
    print(f'  {"+ all four (joint)":<26}{logloss(hold, feats, bs):>10.4f}'
          f'{accuracy(hold, feats, bs)*100:>10.1f}%')

    gain_all = base_ho - logloss(hold, feats, bs)
    gain_qb = base_ho - logloss(hold, ('qb',), (betas['qb'],))
    print(f'\n  holdout gain — all four: {gain_all:+.4f}   QB alone: {gain_qb:+.4f}')
    print('  => ' + ('the extra three earn their place'
                     if gain_all > gain_qb + 0.0002 else
                     'the extra three add nothing beyond QB'))


if __name__ == '__main__':
    main()
