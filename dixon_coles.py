#!/usr/bin/env python3
"""
Dixon-Coles model for the Fulltime predictor, backtested head-to-head against
the Elo model on the exact same held-out matches.

Why this should beat Elo: Elo collapses every match into one win/draw/loss
number. Dixon-Coles keeps the goals — each team gets a separate attack and
defence strength, goals are Poisson, and a correction term fixes Poisson's
known underestimation of low-scoring draws. That uses strictly more information
per match and produces a full scoreline distribution.

    goals_home ~ Poisson(exp(atk[H] - def[A] + gamma))
    goals_away ~ Poisson(exp(atk[A] - def[H]))

Fitted by weighted maximum likelihood with exponential time decay, refit as the
season walks forward so every prediction uses only prior information.

No numpy/scipy on this machine, so the optimiser is hand-rolled gradient ascent
with analytic gradients (the log-link makes them clean) plus a line search for
the low-score correction rho.

Usage:  python3 dixon_coles.py
"""
import json
import math
import urllib.request
from collections import defaultdict

SEASONS = ['2017-18','2018-19','2019-20','2020-21','2021-22',
           '2022-23','2023-24','2024-25','2025-26','2026-27']
BASE = 'https://raw.githubusercontent.com/openfootball/football.json/master'
HOLDOUT_FROM = '2024-25'
WARMUP_SEASONS = 1
EPS = 1e-15
MAX_GOALS = 8          # scoreline grid for turning lambdas into H/D/A

# --- hyperparameters -------------------------------------------------------
HALF_LIFE_DAYS = 240   # exponential decay on match weight
REFIT_EVERY = 10       # matches between refits (warm-started, so this is cheap)
HISTORY_DAYS = 1000    # ignore matches older than this when fitting
PROMOTED_PENALTY = 0.0 # set >0 to handicap teams with little history
FIT_ITERS = 260
WARM_ITERS = 60
LR = 0.05


def canonical(name):
    """openfootball switched naming conventions in 2020-21: 'Manchester City'
    before, 'Manchester City FC' after. Without this, 13 clubs are two separate
    entities and every rating resets at that boundary."""
    n = name.strip()
    for suf in (' FC', ' AFC'):
        if n.endswith(suf):
            n = n[: -len(suf)]
            break
    return n


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
    # days since epoch-ish; exact calendar not needed, only differences
    return (y * 365) + (mo * 30.4) + d


def load():
    out = []
    for s in SEASONS:
        with urllib.request.urlopen(f'{BASE}/{s}/en.1.json') as r:
            d = json.load(r)
        ms = [m for m in d['matches'] if final_score(m)]
        for m in ms:
            m['team1'] = canonical(m['team1'])
            m['team2'] = canonical(m['team2'])
        ms.sort(key=lambda m: m.get('date', ''))
        out.append((s, ms))
    return out


# --- Dixon-Coles low-score correction --------------------------------------
def tau(x, y, lh, la, rho):
    if x == 0 and y == 0:
        return 1 - lh * la * rho
    if x == 0 and y == 1:
        return 1 + lh * rho
    if x == 1 and y == 0:
        return 1 + la * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


class DixonColes:
    def __init__(self):
        self.atk = defaultdict(float)
        self.dfn = defaultdict(float)
        self.gamma = 0.25          # home advantage, in log-goals
        self.rho = -0.05

    def lambdas(self, home, away):
        lh = math.exp(self.atk[home] - self.dfn[away] + self.gamma)
        la = math.exp(self.atk[away] - self.dfn[home])
        return min(lh, 8.0), min(la, 8.0)

    def fit(self, matches, now_day, iters):
        """matches: list of (day, home, away, hg, ag). Weighted MLE."""
        if not matches:
            return
        decay = math.log(2) / HALF_LIFE_DAYS
        data = []
        for day, h, a, hg, ag in matches:
            age = now_day - day
            if age > HISTORY_DAYS:
                continue
            data.append((math.exp(-decay * age), h, a, hg, ag))
        if not data:
            return

        teams = set()
        for _, h, a, _, _ in data:
            teams.add(h); teams.add(a)

        for _ in range(iters):
            g_atk = defaultdict(float)
            g_dfn = defaultdict(float)
            g_gam = 0.0
            for w, h, a, hg, ag in data:
                lh, la = self.lambdas(h, a)
                rh = w * (hg - lh)      # d logL / d(atk[h]) and d/d(gamma)
                ra = w * (ag - la)      # d logL / d(atk[a])
                g_atk[h] += rh
                g_dfn[a] -= rh
                g_atk[a] += ra
                g_dfn[h] -= ra
                g_gam += rh
            n = len(data)
            for t in teams:
                self.atk[t] += LR * g_atk[t] / n * 10
                self.dfn[t] += LR * g_dfn[t] / n * 10
            self.gamma += LR * g_gam / n * 10
            # identifiability: attack strengths sum to zero
            mean_atk = sum(self.atk[t] for t in teams) / len(teams)
            mean_dfn = sum(self.dfn[t] for t in teams) / len(teams)
            for t in teams:
                self.atk[t] -= mean_atk
                self.dfn[t] -= mean_dfn

        self._fit_rho(data)

    def _fit_rho(self, data):
        """Line-search rho over the low-score cells it actually affects."""
        best, best_ll = self.rho, -1e18
        for cand in [x / 100 for x in range(-18, 6, 2)]:
            ll = 0.0
            ok = True
            for w, h, a, hg, ag in data:
                if hg > 1 or ag > 1:
                    continue
                lh, la = self.lambdas(h, a)
                t = tau(hg, ag, lh, la, cand)
                if t <= 0:
                    ok = False
                    break
                ll += w * math.log(t)
            if ok and ll > best_ll:
                best_ll, best = ll, cand
        self.rho = best

    def predict(self, home, away):
        lh, la = self.lambdas(home, away)
        ph = [math.exp(-lh) * lh ** k / math.factorial(k) for k in range(MAX_GOALS + 1)]
        pa = [math.exp(-la) * la ** k / math.factorial(k) for k in range(MAX_GOALS + 1)]
        H = D = A = 0.0
        for x in range(MAX_GOALS + 1):
            for y in range(MAX_GOALS + 1):
                p = ph[x] * pa[y] * tau(x, y, lh, la, self.rho)
                if p <= 0:
                    continue
                if x > y:   H += p
                elif x == y: D += p
                else:        A += p
        tot = H + D + A
        return (H / tot, D / tot, A / tot)


def backtest():
    seasons = load()
    model = DixonColes()
    history = []      # (day, home, away, hg, ag)
    rows = []
    since_fit = 10 ** 9
    first_fit = True

    for si, (sname, matches) in enumerate(seasons):
        for m in matches:
            hg, ag = final_score(m)
            h, a = m['team1'], m['team2']
            day = day_num(m['date'])

            if since_fit >= REFIT_EVERY and len(history) > 60:
                model.fit(history, day, FIT_ITERS if first_fit else WARM_ITERS)
                first_fit = False
                since_fit = 0

            if si >= WARMUP_SEASONS and not first_fit:
                probs = model.predict(h, a)
                actual = 0 if hg > ag else (2 if hg < ag else 1)
                rows.append({'season': sname, 'probs': probs, 'actual': actual})

            history.append((day, h, a, hg, ag))
            since_fit += 1
    return rows, model


def score(rows):
    n = len(rows)
    if not n:
        return None
    ll = br = 0.0
    correct = 0
    for r in rows:
        p = r['probs']
        ll += -math.log(max(p[r['actual']], EPS))
        br += sum((p[i] - (1.0 if i == r['actual'] else 0.0)) ** 2 for i in range(3))
        if p.index(max(p)) == r['actual']:
            correct += 1
    return {'n': n, 'logloss': ll / n, 'brier': br / n, 'acc': correct / n}


def fmt(label, s):
    return (f"{label:<32} n={s['n']:<5} acc={s['acc']*100:5.1f}%   "
            f"logloss={s['logloss']:.4f}   brier={s['brier']:.4f}")


def main():
    print('Fitting Dixon-Coles (walk-forward)…')
    rows, model = backtest()
    holdout = [r for r in rows if r['season'] >= HOLDOUT_FROM]
    insample = [r for r in rows if r['season'] < HOLDOUT_FROM]

    print('\n' + '=' * 86)
    print('HELD-OUT ERA (' + HOLDOUT_FROM + ' onward)')
    print('=' * 86)
    print(fmt('Dixon-Coles', score(holdout)))
    print(f"{'Elo model (measured earlier)':<32} n=770   acc= 50.4%   logloss=1.0073   brier=0.6036")
    print(f"{'betting market':<32} n=770   acc= 51.9%   logloss=0.9928   brier=0.5942")
    print(f"{'base rates':<32} n=770   acc= 42.1%   logloss=1.0822   brier=0.6552")

    print('\nEARLIER ERA')
    print(fmt('Dixon-Coles', score(insample)))

    print('\nPer season')
    for s in SEASONS:
        rs = [r for r in rows if r['season'] == s]
        if rs:
            tag = 'holdout ' if s >= HOLDOUT_FROM else 'earlier  '
            print('  ', fmt(f'{s} ({tag})', score(rs)))

    print(f'\nFitted home advantage gamma = {model.gamma:.4f} log-goals '
          f'(~{(math.exp(model.gamma)-1)*100:.0f}% more goals at home)')
    print(f'Fitted low-score correction rho = {model.rho:.3f}')
    print('\nTop attack / defence ratings (current fit):')
    ts = sorted(model.atk, key=lambda t: model.atk[t] - model.dfn[t], reverse=True)[:6]
    for t in ts:
        print(f'   {t:<28} atk {model.atk[t]:+.3f}   def {model.dfn[t]:+.3f}')


if __name__ == '__main__':
    main()
