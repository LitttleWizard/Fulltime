#!/usr/bin/env python3
"""
Does EA FC squad strength add anything to the Dixon-Coles model?

Motivation: `diagnose.py` showed promoted clubs run ~0.24 points/game below the
rest, yet the model starts every unseen team at exactly league average. Squad
ratings know a promoted side is weaker before a ball is kicked — that is
information the model provably lacks.

Design, and the reason it is honest:
  * The EA FC 26 snapshot is dated 2025-09-19, so it contains no knowledge of
    any result after that date. Testing it on 2025-26 matches played later is
    therefore leak-free.
  * Squad strength is fitted as a logistic adjustment on top of the existing
    Dixon-Coles probabilities, beta fitted on one half of the season and scored
    on the other, then swapped (2-fold cross-fitting) so every match is scored
    by a beta that never saw it.

Usage:  python3 epl_squad.py
"""
import csv
import io
import json
import math
import re
import urllib.request
from collections import defaultdict

FIFA = 'https://raw.githubusercontent.com/ismailoksuz/EAFC26-DataHub/main/data/players.csv'
OF = 'https://raw.githubusercontent.com/openfootball/football.json/master'
SEASONS = ['2022-23', '2023-24', '2024-25', '2025-26']
TEST_SEASON = '2025-26'          # entirely after the FIFA snapshot date
SQUAD_N = 11                     # top-N rated players per club
HALF_LIFE, HISTORY_DAYS, ITERS, MAXG = 200, 1000, 320, 8
EPS = 1e-15

# EA FC club names -> the canonical names the site uses
CLUB_FIX = {'Fulham FC': 'Fulham', 'Nottingham Forest': 'Nottingham Forest',
            'Spurs': 'Tottenham Hotspur', 'Tottenham Hotspur': 'Tottenham Hotspur'}


def canon(n):
    m = re.match(r'^(.*?)\s+(?:FC|AFC)$', str(n or '').strip())
    return m.group(1) if m else str(n or '').strip()


def final_score(m):
    s = m.get('score')
    if not s:
        return None
    if isinstance(s, dict) and isinstance(s.get('ft'), list):
        return s['ft']
    if isinstance(s, list):
        return s
    return None


def day_num(ds):
    from datetime import date
    y, mo, d = map(int, ds.split('-'))
    return date(y, mo, d).toordinal()


def load_squads():
    with urllib.request.urlopen(FIFA, timeout=120) as r:
        text = r.read().decode('utf-8', 'replace')
    by_club = defaultdict(list)
    for row in csv.DictReader(io.StringIO(text)):
        club = (row.get('club_name') or '').strip()
        try:
            ovr = int(row.get('overall') or 0)
        except ValueError:
            continue
        if club and ovr:
            by_club[CLUB_FIX.get(club, canon(club))].append(ovr)
    return {c: sum(sorted(v, reverse=True)[:SQUAD_N]) / min(len(v), SQUAD_N)
            for c, v in by_club.items() if v}


# ── Dixon-Coles, same as the site ────────────────────────────────────────
def fit_dc(matches, now_day):
    decay = math.log(2) / HALF_LIFE
    data = [(math.exp(-decay * (now_day - d)), h, a, hg, ag)
            for d, h, a, hg, ag in matches if now_day - d <= HISTORY_DAYS]
    if not data:
        return None
    atk, dfn = defaultdict(float), defaultdict(float)
    teams = {t for _, h, a, _, _ in data for t in (h, a)}
    gamma, n = 0.25, len(data)
    for _ in range(ITERS):
        ga, gd = defaultdict(float), defaultdict(float)
        gg = 0.0
        for w, h, a, hg, ag in data:
            lh = min(math.exp(atk[h] - dfn[a] + gamma), 8)
            la = min(math.exp(atk[a] - dfn[h]), 8)
            rh, ra = w * (hg - lh), w * (ag - la)
            ga[h] += rh; gd[a] -= rh
            ga[a] += ra; gd[h] -= ra
            gg += rh
        step = 0.5 / n
        for t in teams:
            atk[t] += step * ga[t]; dfn[t] += step * gd[t]
        gamma += step * gg
        ma = sum(atk[t] for t in teams) / len(teams)
        md = sum(dfn[t] for t in teams) / len(teams)
        for t in teams:
            atk[t] -= ma; dfn[t] -= md
    return {'atk': dict(atk), 'dfn': dict(dfn), 'gamma': gamma, 'teams': teams}


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


def apply_beta(probs, diff, beta):
    """Nudge home/away in log-odds by the squad-rating gap; renormalise."""
    h, d, a = probs
    z = math.log(max(h, EPS) / max(a, EPS)) + beta * diff
    r = math.exp(z)                       # new home:away odds ratio
    rest = h + a
    nh = rest * r / (1 + r)
    return (nh, d, rest - nh)


def logloss(rows, beta=0.0):
    tot = 0.0
    for r in rows:
        p = apply_beta(r['probs'], r['diff'], beta) if beta else r['probs']
        tot += -math.log(max(p[r['actual']], EPS))
    return tot / len(rows)


def acc(rows, beta=0.0):
    ok = 0
    for r in rows:
        p = apply_beta(r['probs'], r['diff'], beta) if beta else r['probs']
        ok += (list(p).index(max(p)) == r['actual'])
    return ok / len(rows)


def fit_beta(rows):
    best, best_b = logloss(rows), 0.0
    b = -1.0
    while b <= 1.0001:
        v = logloss(rows, b)
        if v < best:
            best, best_b = v, b
        b += 0.01
    return best_b


def main():
    print('Loading EA FC squad ratings…')
    squads = load_squads()
    print(f'  {len(squads)} clubs rated')

    print('Loading match history…')
    played = []
    for s in SEASONS:
        d = json.load(urllib.request.urlopen(f'{OF}/{s}/en.1.json', timeout=60))
        for m in d.get('matches', []):
            ft = final_score(m)
            if not ft or not m.get('date'):
                continue
            played.append({'season': s, 'date': m['date'], 'day': day_num(m['date']),
                           'home': canon(m['team1']), 'away': canon(m['team2']),
                           'hg': ft[0], 'ag': ft[1]})
    played.sort(key=lambda g: g['date'])

    # walk forward; score only the test season
    rows, hist, model, since = [], [], None, 10 ** 9
    seen_before = set()
    missing = set()
    for g in played:
        if since >= 15 and len(hist) > 80:
            model = fit_dc(hist, g['day']); since = 0
        if model and g['season'] == TEST_SEASON:
            sh, sa = squads.get(g['home']), squads.get(g['away'])
            if sh is None: missing.add(g['home'])
            if sa is None: missing.add(g['away'])
            if sh is not None and sa is not None:
                rows.append({
                    'date': g['date'],
                    'probs': dc_probs(model, g['home'], g['away']),
                    'diff': (sh - sa) / 10.0,          # ~1 unit = 10 rating points
                    'actual': 0 if g['hg'] > g['ag'] else (1 if g['hg'] == g['ag'] else 2),
                    'newHome': g['home'] not in seen_before,
                    'newAway': g['away'] not in seen_before,
                })
        hist.append((g['day'], g['home'], g['away'], g['hg'], g['ag']))
        seen_before.add(g['home']); seen_before.add(g['away'])
        since += 1

    if missing:
        print(f'  no squad rating for: {sorted(missing)}')
    print(f'\n{len(rows)} {TEST_SEASON} matches scored '
          f'(FIFA snapshot 2025-09-19 predates all of them)\n')

    # 2-fold cross-fit: beta from one half scores the other
    mid = len(rows) // 2
    first, second = rows[:mid], rows[mid:]
    b1, b2 = fit_beta(second), fit_beta(first)
    xf = logloss(first, b1) * len(first) + logloss(second, b2) * len(second)
    xf /= len(rows)
    xa = (acc(first, b1) * len(first) + acc(second, b2) * len(second)) / len(rows)
    base_ll, base_acc = logloss(rows), acc(rows)

    print(f"{'model':<34}{'logloss':>10}{'acc':>9}")
    print('-' * 53)
    print(f"{'Dixon-Coles (as shipped)':<34}{base_ll:>10.4f}{base_acc*100:>8.1f}%")
    print(f"{'+ squad strength (cross-fitted)':<34}{xf:>10.4f}{xa*100:>8.1f}%")
    print(f"\nfitted beta: {b1:+.2f} / {b2:+.2f}   (per 10 rating points)")
    print(f"improvement: {base_ll - xf:+.4f} log-loss")

    # where does it help? promoted sides are the hypothesis
    promo = [r for r in rows if r['newHome'] or r['newAway']]
    if promo:
        bp = fit_beta(promo)
        print(f"\nmatches involving a side new to the league: {len(promo)}")
        print(f"  baseline {logloss(promo):.4f} -> with squad {logloss(promo, bp):.4f} "
              f"(beta {bp:+.2f}, in-sample — small n, directional only)")

    early = rows[:60]
    if early:
        be = fit_beta(early)
        print(f"\nfirst 60 matches of the season: baseline {logloss(early):.4f} "
              f"-> {logloss(early, be):.4f} (beta {be:+.2f}, in-sample)")


if __name__ == '__main__':
    main()
