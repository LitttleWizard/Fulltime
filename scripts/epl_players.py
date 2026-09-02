#!/usr/bin/env python3
"""
Do individual player ratings improve the EPL match prediction?

`epl_squad.py` showed that a club's *overall* squad rating adds nothing: the
Dixon-Coles model already infers team strength from results, and results beat a
video-game rating as soon as you have any.

This asks a sharper question. Dixon-Coles knows a team's TYPICAL strength. What
it cannot know is that today's XI is missing three first-choice players. So the
feature here is not "how good is this squad" but:

    delta = (rating of today's XI) - (rating of this team's recent typical XI)

which is, by construction, information the team-level model does not contain.

Lineups come from `lineups.json` (built by `fetch_lineups.py`). Ratings come
from the EA FC 26 snapshot dated 2025-09-19, so only matches played after that
date are scored — the snapshot cannot encode results it predates.

Every beta is cross-fitted: fitted on one half of the season, scored on the
other, then swapped, so no match is ever scored by a beta that saw it.

Usage:  python3 epl_players.py
"""
import csv, io, json, math, re, sys, unicodedata, urllib.request
from collections import defaultdict, deque

# Paths below are relative to the repo root, so the script works from any
# working directory. The join is absolute, so re-running it (a script that
# imports another that also does this) is a no-op rather than climbing up.
import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))


FIFA = 'https://raw.githubusercontent.com/ismailoksuz/EAFC26-DataHub/main/data/players.csv'
OF = 'https://raw.githubusercontent.com/openfootball/football.json/master'
SEASONS = ['2022-23', '2023-24', '2024-25', '2025-26']
TEST_SEASON = '2025-26'
SNAPSHOT = '2025-09-19'      # EA FC data date; score only matches after it
FORM_N = 6                   # matches of rolling baseline XI strength
HALF_LIFE, HISTORY_DAYS, ITERS, MAXG = 200, 1000, 320, 8
EPS = 1e-15


def norm(s):
    s = str(s or '').replace('ß', 'ss').replace('Ø', 'o').replace('ø', 'o')
    s = s.replace('đ', 'd').replace('ð', 'd')
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z ]', ' ', s.lower()).split()


def canon(n):
    m = re.match(r'^(.*?)\s+(?:FC|AFC)$', str(n or '').strip())
    return m.group(1) if m else str(n or '').strip()


def final_score(m):
    s = m.get('score')
    if not s: return None
    if isinstance(s, dict) and isinstance(s.get('ft'), list): return s['ft']
    if isinstance(s, list): return s
    return None


def day_num(ds):
    from datetime import date
    y, mo, d = map(int, ds.split('-')); return date(y, mo, d).toordinal()


# ── EA FC ratings, and matching ESPN display names onto them ──────────────
def load_players():
    with urllib.request.urlopen(FIFA, timeout=120) as r:
        text = r.read().decode('utf-8', 'replace')
    pool = []
    for x in csv.DictReader(io.StringIO(text)):
        if (x.get('league_name') or '').strip() != 'Premier League':
            continue
        ln, sn = norm(x['long_name']), norm(x['short_name'])
        pool.append({
            'club': canon(x['club_name']),
            # surname tokens: every token but the first, from both name forms —
            # Iberian double surnames ("Konsa Ngoyo") break last-token matching
            'sur': set(ln[1:] if len(ln) > 1 else ln) | set(sn[1:] if len(sn) > 1 else sn),
            'ini': {t[0] for t in (ln[:1] + sn[:1]) if t},
            'full': ' '.join(ln),
            'ovr': int(x['overall'] or 0),
        })
    return pool


class Ratings:
    def __init__(self, pool):
        self.pool = pool
        self.by_club = defaultdict(list)
        for p in pool:
            self.by_club[p['club']].append(p)
        self.club_mean = {c: sum(x['ovr'] for x in v) / len(v)
                          for c, v in self.by_club.items()}
        self.league_mean = sum(p['ovr'] for p in pool) / len(pool)
        self._memo = {}

    def rate(self, club, disp):
        key = (club, disp)
        if key in self._memo:
            return self._memo[key]
        d = norm(disp)
        val = None
        if d:
            dsur = set(d[1:] if len(d) > 1 else d)
            dini = d[0][0]
            for scope in (self.by_club.get(club) or [], self.pool):
                exact = [p for p in scope if p['full'] == ' '.join(d)]
                if len(exact) == 1:
                    val = exact[0]['ovr']; break
                c = [p for p in scope if (p['sur'] & dsur) and (dini in p['ini'] or not p['ini'])]
                if len(c) == 1:
                    val = c[0]['ovr']; break
                if len(c) > 1 and scope is not self.pool:
                    val = max(x['ovr'] for x in c); break
        self._memo[key] = val
        return val

    def xi(self, club, names):
        """Mean rating of a starting XI; unmatched players fall back to club mean."""
        fb = self.club_mean.get(club, self.league_mean)
        vals = [self.rate(club, n) or fb for n in names]
        return (sum(vals) / len(vals), sum(1 for n in names if self.rate(club, n) is None)) if vals else (fb, len(names))


# ── Dixon-Coles (same maths the site ships) ───────────────────────────────
def fit_dc(matches, now_day):
    decay = math.log(2) / HALF_LIFE
    data = [(math.exp(-decay * (now_day - d)), h, a, hg, ag)
            for d, h, a, hg, ag in matches if now_day - d <= HISTORY_DAYS]
    if not data: return None
    atk, dfn = defaultdict(float), defaultdict(float)
    teams = {t for _, h, a, _, _ in data for t in (h, a)}
    gamma, n = 0.25, len(data)
    for _ in range(ITERS):
        ga, gd = defaultdict(float), defaultdict(float); gg = 0.0
        for w, h, a, hg, ag in data:
            lh = min(math.exp(atk[h] - dfn[a] + gamma), 8)
            la = min(math.exp(atk[a] - dfn[h]), 8)
            rh, ra = w * (hg - lh), w * (ag - la)
            ga[h] += rh; gd[a] -= rh; ga[a] += ra; gd[h] -= ra; gg += rh
        step = 0.5 / n
        for t in teams:
            atk[t] += step * ga[t]; dfn[t] += step * gd[t]
        gamma += step * gg
        ma = sum(atk[t] for t in teams) / len(teams)
        md = sum(dfn[t] for t in teams) / len(teams)
        for t in teams:
            atk[t] -= ma; dfn[t] -= md
    return {'atk': dict(atk), 'dfn': dict(dfn), 'gamma': gamma}


def dc_probs(model, home, away):
    a, d, g = model['atk'], model['dfn'], model['gamma']
    lh = min(math.exp(a.get(home, 0) - d.get(away, 0) + g), 8)
    la = min(math.exp(a.get(away, 0) - d.get(home, 0)), 8)
    def pois(lam):
        out, f = [], 1
        for k in range(MAXG + 1):
            if k: f *= k
            out.append(math.exp(-lam) * lam ** k / f)
        return out
    ph, pa = pois(lh), pois(la)
    H = D = A = 0.0
    for x in range(MAXG + 1):
        for y in range(MAXG + 1):
            p = ph[x] * pa[y]
            if x > y: H += p
            elif x == y: D += p
            else: A += p
    t = H + D + A or 1
    return H / t, D / t, A / t


def apply_beta(probs, feat, beta):
    h, d, a = probs
    z = math.log(max(h, EPS) / max(a, EPS)) + beta * feat
    r = math.exp(z); rest = h + a
    nh = rest * r / (1 + r)
    return (nh, d, rest - nh)


def logloss(rows, key=None, beta=0.0):
    tot = 0.0
    for r in rows:
        p = apply_beta(r['probs'], r[key], beta) if (key and beta) else r['probs']
        tot += -math.log(max(p[r['actual']], EPS))
    return tot / len(rows)


def acc(rows, key=None, beta=0.0):
    ok = 0
    for r in rows:
        p = apply_beta(r['probs'], r[key], beta) if (key and beta) else r['probs']
        ok += (list(p).index(max(p)) == r['actual'])
    return ok / len(rows)


def fit_beta(rows, key):
    best, bb, b = logloss(rows), 0.0, -1.5
    while b <= 1.5001:
        v = logloss(rows, key, b)
        if v < best: best, bb = v, b
        b += 0.01
    return bb


def crossfit(rows, key):
    mid = len(rows) // 2
    a, b = rows[:mid], rows[mid:]
    ba, bb = fit_beta(b, key), fit_beta(a, key)
    ll = (logloss(a, key, ba) * len(a) + logloss(b, key, bb) * len(b)) / len(rows)
    ac = (acc(a, key, ba) * len(a) + acc(b, key, bb) * len(b)) / len(rows)
    return ll, ac, ba, bb


def main():
    try:
        lineups = json.load(open('data/lineups.json'))
    except FileNotFoundError:
        print('lineups.json missing — run: python3 fetch_lineups.py'); return 1

    print('Loading EA FC player ratings…')
    R = Ratings(load_players())
    print(f'  {len(R.pool)} EPL players, {len(R.by_club)} clubs')

    print('Loading match history…')
    played = []
    for s in SEASONS:
        d = json.load(urllib.request.urlopen(f'{OF}/{s}/en.1.json', timeout=60))
        for m in d.get('matches', []):
            ft = final_score(m)
            if ft and m.get('date'):
                played.append({'season': s, 'date': m['date'], 'day': day_num(m['date']),
                               'home': canon(m['team1']), 'away': canon(m['team2']),
                               'hg': ft[0], 'ag': ft[1]})
    played.sort(key=lambda g: g['date'])

    hist, model, since = [], None, 10 ** 9
    form = defaultdict(lambda: deque(maxlen=FORM_N))     # team -> recent XI strengths
    rows, unmatched, total_p = [], 0, 0

    for g in played:
        if since >= 15 and len(hist) > 80:
            model = fit_dc(hist, g['day']); since = 0
        key = f"{g['date']}|{g['home']}|{g['away']}"
        lu = lineups.get(key)

        if lu and model:
            xh, mh = R.xi(g['home'], lu['home'])
            xa, ma = R.xi(g['away'], lu['away'])
            unmatched += mh + ma; total_p += len(lu['home']) + len(lu['away'])
            bh = sum(form[g['home']]) / len(form[g['home']]) if form[g['home']] else None
            ba = sum(form[g['away']]) / len(form[g['away']]) if form[g['away']] else None

            if g['season'] == TEST_SEASON and g['date'] > SNAPSHOT and bh and ba:
                rows.append({
                    'date': g['date'], 'home': g['home'], 'away': g['away'],
                    'probs': dc_probs(model, g['home'], g['away']),
                    'level': (xh - xa) / 10.0,                    # absolute XI quality gap
                    'delta': ((xh - bh) - (xa - ba)) / 10.0,      # disruption vs own norm
                    'dh': xh - bh, 'da': xa - ba,
                    'actual': 0 if g['hg'] > g['ag'] else (1 if g['hg'] == g['ag'] else 2),
                })
            form[g['home']].append(xh); form[g['away']].append(xa)

        hist.append((g['day'], g['home'], g['away'], g['hg'], g['ag']))
        since += 1

    if not rows:
        print('no scorable matches'); return 1
    print(f'\n{len(rows)} matches scored (after {SNAPSHOT}); '
          f'{unmatched}/{total_p} starters unrated ({unmatched/max(total_p,1)*100:.1f}%)\n')

    base_ll, base_acc = logloss(rows), acc(rows)
    print(f"{'model':<42}{'logloss':>10}{'acc':>9}{'betas':>16}")
    print('-' * 77)
    print(f"{'Dixon-Coles (as shipped)':<42}{base_ll:>10.4f}{base_acc*100:>8.1f}%{'':>16}")
    for label, key in [('+ XI quality gap (absolute)', 'level'),
                       ('+ XI disruption vs own recent norm', 'delta')]:
        ll, ac, b1, b2 = crossfit(rows, key)
        flag = '  <-- helps' if ll < base_ll else ''
        print(f"{label:<42}{ll:>10.4f}{ac*100:>8.1f}%{f'{b1:+.2f}/{b2:+.2f}':>16}{flag}")

    print(f'\nlargest measured disruptions (XI vs that club\'s recent norm):')
    worst = sorted(rows, key=lambda r: min(r['dh'], r['da']))[:6]
    for r in worst:
        side, v = ('home ' + r['home'], r['dh']) if r['dh'] < r['da'] else ('away ' + r['away'], r['da'])
        print(f"  {r['date']}  {side:<34}{v:+.2f} rating pts vs norm")
    return 0


if __name__ == '__main__':
    sys.exit(main())
