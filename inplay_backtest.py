#!/usr/bin/env python3
"""
Is the in-play win probability actually calibrated?

The prediction log validates the *pre-match* model rigorously. The in-play
model — Dixon-Coles expected goals pro-rated by time remaining — has never been
checked. This does that: replay finished matches minute by minute, ask the
in-play model for a probability at fixed checkpoints, and compare against what
actually happened.

Goal timings come from ESPN (`keyEvents`, scoringPlay). One request per match,
so this is an offline job that writes `inplay-calibration.json` for the log page
to read — the browser can't do 300 round-trips on page load.

Usage:  python3 inplay_backtest.py [--matches 200]
"""
import argparse
import json
import math
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

OF = 'https://raw.githubusercontent.com/openfootball/football.json/master'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1'
SEASONS = ['2023-24', '2024-25', '2025-26', '2026-27']
WARMUP_SEASONS = 2
CHECKPOINTS = [15, 30, 45, 60, 75]
HALF_LIFE, HISTORY_DAYS, ITERS, MAXG = 200, 1000, 320, 8
OUT = 'inplay-calibration.json'


def get(url, tries=3):
    # No custom User-Agent: ESPN 403s on one, and is happy with urllib's default.
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.2 * (i + 1))
    return None


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
    y, mo, d = map(int, ds.split('-'))
    return date(y, mo, d).toordinal()


# ── Dixon-Coles (same maths the site ships) ───────────────────────────────
def tau(x, y, lh, la, rho):
    if x == 0 and y == 0: return 1 - lh * la * rho
    if x == 0 and y == 1: return 1 + lh * rho
    if x == 1 and y == 0: return 1 + la * rho
    if x == 1 and y == 1: return 1 - rho
    return 1.0


def fit_dc(matches, now_day):
    decay = math.log(2) / HALF_LIFE
    data = [(math.exp(-decay * (now_day - d)), h, a, hg, ag)
            for d, h, a, hg, ag in matches if now_day - d <= HISTORY_DAYS]
    if not data:
        return None
    atk, dfn = defaultdict(float), defaultdict(float)
    teams = {t for _, h, a, _, _ in data for t in (h, a)}
    gamma = 0.25
    n = len(data)
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
    return {'atk': dict(atk), 'dfn': dict(dfn), 'gamma': gamma}


def lambdas(model, home, away):
    a = model['atk']; d = model['dfn']; g = model['gamma']
    return (min(math.exp(a.get(home, 0) - d.get(away, 0) + g), 8),
            min(math.exp(a.get(away, 0) - d.get(home, 0)), 8))


def in_play(lh, la, hs, as_, mins_left):
    """Identical to Live.winProb in live.js."""
    f = max(0.0, min(1.0, mins_left / 90))
    rh, ra = max(lh * f, 1e-9), max(la * f, 1e-9)
    def pois(lam):
        out, fact = [], 1
        for k in range(MAXG + 1):
            if k: fact *= k
            out.append(math.exp(-lam) * lam ** k / fact)
        return out
    ph, pa = pois(rh), pois(ra)
    H = D = A = 0.0
    for x in range(MAXG + 1):
        for y in range(MAXG + 1):
            p = ph[x] * pa[y]
            fh, fa = hs + x, as_ + y
            if fh > fa: H += p
            elif fh == fa: D += p
            else: A += p
    tot = H + D + A or 1
    return H / tot, D / tot, A / tot


# ── ESPN goal timings ─────────────────────────────────────────────────────
def espn_index(dates):
    """date -> [(eventId, homeDisplayName, awayDisplayName)] via range queries."""
    idx = {}
    lo, hi = min(dates), max(dates)
    cur = date.fromordinal(day_num(lo))
    end = date.fromordinal(day_num(hi))
    while cur <= end:
        stop = min(cur + timedelta(days=13), end)
        d = get(f'{ESPN}/scoreboard?dates={cur:%Y%m%d}-{stop:%Y%m%d}&limit=400')
        if d:
            for ev in d.get('events', []):
                c = (ev.get('competitions') or [{}])[0]
                comp = c.get('competitors') or []
                h = next((x for x in comp if x.get('homeAway') == 'home'), None)
                a = next((x for x in comp if x.get('homeAway') == 'away'), None)
                if not h or not a:
                    continue
                idx.setdefault(ev.get('date', '')[:10], []).append(
                    (ev.get('id'), h['team'].get('displayName'), a['team'].get('displayName')))
        cur = stop + timedelta(days=1)
        time.sleep(0.15)
    return idx


def goals_for(event_id, raw_home):
    d = get(f'{ESPN}/summary?event={event_id}')
    if not d:
        return None
    goals = []
    for e in d.get('keyEvents') or []:
        if not e.get('scoringPlay'):
            continue
        disp = ((e.get('clock') or {}).get('displayValue')) or ''
        m = re.search(r'(\d+)', disp)
        if not m:
            continue
        team = ((e.get('team') or {}).get('displayName')) or ''
        goals.append({'min': min(90, int(m.group(1))),
                      'side': 'home' if team and team == raw_home else 'away'})
    goals.sort(key=lambda g: g['min'])
    return goals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--matches', type=int, default=200,
                    help='how many recent finished matches to check')
    args = ap.parse_args()

    print('Loading match history…')
    played = []
    for i, s in enumerate(SEASONS):
        d = get(f'{OF}/{s}/en.1.json')
        if not d:
            continue
        for m in d.get('matches', []):
            ft = final_score(m)
            if not ft or not m.get('date'):
                continue
            played.append({'si': i, 'date': m['date'], 'day': day_num(m['date']),
                           'home': canon(m['team1']), 'away': canon(m['team2']),
                           'hg': ft[0], 'ag': ft[1]})
    played.sort(key=lambda g: g['date'])
    scored = [g for g in played if g['si'] >= WARMUP_SEASONS]
    target = scored[-args.matches:]
    print(f'{len(played)} matches loaded; checking the most recent {len(target)}')

    print('Indexing ESPN events…')
    idx = espn_index([g['date'] for g in target])
    print(f'  {sum(len(v) for v in idx.values())} events indexed')

    # walk forward, refitting periodically, and evaluate the target window
    print('Replaying in-play probabilities…')
    hist, model, since = [], None, 10 ** 9
    want = {(g['date'], g['home'], g['away']) for g in target}
    rows, matched, missing = [], 0, 0

    for g in played:
        key = (g['date'], g['home'], g['away'])
        if since >= 15 and len(hist) > 80:
            model = fit_dc(hist, g['day'])
            since = 0

        if model and key in want:
            ev = None
            for eid, rh, ra in idx.get(g['date'], []):
                if canon(rh) == g['home'] and canon(ra) == g['away']:
                    ev = (eid, rh); break
            if ev:
                goals = goals_for(ev[0], ev[1])
                time.sleep(0.12)
                total_goals = g['hg'] + g['ag']
                if goals is not None and len(goals) == total_goals:
                    matched += 1
                    lh, la = lambdas(model, g['home'], g['away'])
                    actual = 0 if g['hg'] > g['ag'] else (1 if g['hg'] == g['ag'] else 2)
                    for cp in CHECKPOINTS:
                        hs = sum(1 for x in goals if x['min'] <= cp and x['side'] == 'home')
                        as_ = sum(1 for x in goals if x['min'] <= cp and x['side'] == 'away')
                        probs = in_play(lh, la, hs, as_, 90 - cp)
                        rows.append({'cp': cp, 'probs': probs, 'actual': actual})
                else:
                    missing += 1
            else:
                missing += 1

        hist.append((g['day'], g['home'], g['away'], g['hg'], g['ag']))
        since += 1

    print(f'  matched {matched} matches ({missing} skipped — no ESPN goal data)')
    if not rows:
        print('No rows produced; leaving existing output untouched.')
        return 1

    # ── calibration + scores, overall and per checkpoint ──────────────────
    def summarise(rs):
        n = len(rs)
        ll = -sum(math.log(max(r['probs'][r['actual']], 1e-15)) for r in rs) / n
        hits = sum(1 for r in rs if r['probs'].index(max(r['probs'])) == r['actual'])
        bins = defaultdict(lambda: {'n': 0, 'p': 0.0, 'hit': 0})
        for r in rs:
            for i in range(3):
                b = min(int(r['probs'][i] * 10), 9)
                bins[b]['n'] += 1
                bins[b]['p'] += r['probs'][i]
                bins[b]['hit'] += 1 if r['actual'] == i else 0
        cal = [{'lo': b * 10, 'hi': b * 10 + 10, 'n': v['n'],
                'predicted': v['p'] / v['n'], 'actual': v['hit'] / v['n']}
               for b, v in sorted(bins.items()) if v['n'] >= 25]
        return {'n': n, 'logloss': ll, 'acc': hits / n, 'calibration': cal}

    out = {
        'generated': time.strftime('%Y-%m-%d'),
        'matches': matched,
        'checkpoints': CHECKPOINTS,
        'overall': summarise(rows),
        'byMinute': {str(cp): summarise([r for r in rows if r['cp'] == cp])
                     for cp in CHECKPOINTS}
    }
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))

    print(f'\nwrote {OUT} — {matched} matches, {len(rows)} in-play predictions')
    print(f"\n{'minute':>8}{'n':>7}{'acc':>9}{'logloss':>10}")
    for cp in CHECKPOINTS:
        s = out['byMinute'][str(cp)]
        print(f"{cp:>7}'{s['n']:>7}{s['acc']*100:>8.1f}%{s['logloss']:>10.4f}")
    o = out['overall']
    print(f"\noverall  n={o['n']}  acc={o['acc']*100:.1f}%  logloss={o['logloss']:.4f}")
    print('\ncalibration (overall) — predicted vs actual')
    for c in o['calibration']:
        print(f"  {c['lo']:>3}-{c['hi']:<3} n={c['n']:<5} "
              f"predicted {c['predicted']*100:5.1f}%   actual {c['actual']*100:5.1f}%")
    return 0


if __name__ == '__main__':
    sys.exit(main())
