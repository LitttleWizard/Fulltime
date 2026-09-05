#!/usr/bin/env python3
"""
Should the market's price feed into the model's own number?

The case for is strong on the face of it: the market BEATS this model on the
same matches (51.9% against 50.4%), because prices absorb injuries, team news
and money the model never sees. Two forecasts of the same event, one of them
better, usually blend to something better than either.

The case against is that a blend stops being a model. At full weight the page
would be reporting Kalshi with extra steps, and the accuracy figures would no
longer say anything about Dixon-Coles. So the question is not "does blending
help" — it is "how much does it help, at what weight, and is what remains still
a model of football".

Method: walk forward exactly as evaluate.py does, fit the blend weight on early
seasons, and score it on a holdout neither saw. Weight is fitted in log-odds,
per outcome, then renormalised.

Usage:  python3 scripts/blend_market.py
"""
import math, sys
from collections import defaultdict

import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
sys.path.insert(0, 'scripts')

import evaluate as E

EPS = 1e-15


def blend(model, market, w):
    """w=1 keeps the model, w=0 becomes the market. Log-odds, renormalised."""
    out = []
    for pm, mk in zip(model, market):
        z = w * math.log(max(pm, EPS)) + (1 - w) * math.log(max(mk, EPS))
        out.append(math.exp(z))
    t = sum(out) or 1.0
    return [x / t for x in out]


def score(rows, w):
    ll = acc = 0.0
    for r in rows:
        p = blend(r['model'], r['odds'], w)
        ll += -math.log(max(p[r['actual']], EPS))
        acc += (p.index(max(p)) == r['actual'])
    return ll / len(rows), acc / len(rows)


def main():
    print('Fetching data…')
    seasons = E.fetch_seasons()          # run() wants loaded seasons, not names
    market = E.fetch_market_and_shots()
    rows = E.run(seasons, market)

    have = [r for r in rows if r.get('odds') and r.get('probs')]
    for r in have:
        r['model'] = list(r['probs'])
    if len(have) < 400:
        print(f'only {len(have)} matches with both a model and odds'); return 1

    # Same split evaluate.py uses, so these numbers sit alongside the published
    # ones rather than being a fresh convenient cut.
    tune = [r for r in have if r['season'] < E.HOLDOUT_FROM]
    hold = [r for r in have if r['season'] >= E.HOLDOUT_FROM]
    print(f'{len(have)} matches with both a model price and closing odds')
    print(f'{len(tune)} tuning (< {E.HOLDOUT_FROM}), {len(hold)} holdout\n')

    best_w, best = 1.0, None
    w = 0.0
    while w <= 1.0001:
        ll, _ = score(tune, w)
        if best is None or ll < best:
            best, best_w = ll, w
        w += 0.05

    print(f"{'weight on model':<22}{'holdout ll':>12}{'acc':>9}")
    print('-' * 43)
    for w in (1.0, 0.8, 0.6, 0.5, 0.4, 0.2, 0.0):
        ll, ac = score(hold, w)
        tag = ''
        if abs(w - 1.0) < 1e-9: tag = '   model alone'
        if abs(w) < 1e-9: tag = '   market alone'
        if abs(w - best_w) < 1e-9: tag += '   <- fitted'
        print(f'{w:<22.2f}{ll:>12.4f}{ac*100:>8.1f}%{tag}')

    ll_m, acc_m = score(hold, 1.0)
    ll_k, acc_k = score(hold, 0.0)
    ll_b, acc_b = score(hold, best_w)
    print(f'\nfitted weight on the model: {best_w:.2f}')
    print(f'  model alone   {ll_m:.4f}  {acc_m*100:.1f}%')
    print(f'  market alone  {ll_k:.4f}  {acc_k*100:.1f}%')
    print(f'  blend         {ll_b:.4f}  {acc_b*100:.1f}%   '
          f'({ll_m - ll_b:+.4f} vs model, {ll_k - ll_b:+.4f} vs market)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
