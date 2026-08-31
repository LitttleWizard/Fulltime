#!/usr/bin/env python3
"""
Does NFL trade activity predict anything the Elo rating doesn't already know?

The model already regresses every rating 40% toward the mean each offseason to
account for roster churn. The question is whether a team's actual trade balance
tells us anything beyond that blanket assumption.

Tested as a logistic adjustment fitted on the training era and scored on the
2023+ holdout, same protocol as nfl_features.py.
"""
import csv, io, math, sys, urllib.request
from collections import defaultdict

sys.path.insert(0, '/Users/aaronho1880/ui:ux/fulltime')
import nfl_features as nf

TRADES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/trades.csv'


def load_trades():
    req = urllib.request.Request(TRADES, headers={'User-Agent': 'fulltime/1.0'})
    text = urllib.request.urlopen(req).read().decode('utf-8')
    # net player movement per (season, team): players in minus players out
    net = defaultdict(int)
    gross = defaultdict(int)
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get('pfr_name'):          # draft-pick-only row
            continue
        try:
            s = int(r['season'])
        except (TypeError, ValueError):
            continue
        gave, recv = r.get('gave'), r.get('received')
        if gave:
            net[(s, gave)] -= 1
            gross[(s, gave)] += 1
        if recv:
            net[(s, recv)] += 1
            gross[(s, recv)] += 1
    return net, gross


def main():
    net, gross = load_trades()
    print(f'trade records covering {len({k[0] for k in net})} seasons')

    games = nf.load()
    rows = nf.build(games)

    # attach trade features. build() drops team names, so re-walk the games in
    # the same order and filter identically.
    played = [g for g in games if g['season'] >= nf.FIRST_SEASON + nf.WARMUP]
    played = [g for g in played if (g['hs'] - g['as']) != 0]
    if len(played) != len(rows):
        print(f'WARNING row mismatch: {len(played)} vs {len(rows)}')
        return

    for r, g in zip(rows, played):
        s, h, a = g['season'], g['home'], g['away']
        r['tnet'] = (net.get((s, h), 0) - net.get((s, a), 0)) / 4.0
        r['tgross'] = (gross.get((s, h), 0) - gross.get((s, a), 0)) / 6.0

    train = [r for r in rows if r['season'] < nf.HOLDOUT_FROM]
    hold = [r for r in rows if r['season'] >= nf.HOLDOUT_FROM]
    base_tr, base_ho = nf.logloss(train), nf.logloss(hold)

    covered = sum(1 for r in rows if r['tnet'] != 0) / len(rows) * 100
    print(f'{len(rows)} games; {covered:.0f}% have a non-zero trade differential\n')
    print(f'Elo baseline        train {base_tr:.4f}   holdout {base_ho:.4f}\n')
    print(f"{'feature':<34}{'beta':>7}{'train gain':>12}{'HOLDOUT gain':>14}")
    print('-' * 68)
    for f, label in [('tnet', 'Net players traded for/away'),
                     ('tgross', 'Total trade activity')]:
        b = nf.fit_beta(train, f)
        gt = base_tr - nf.logloss(train, (f,), (b,))
        gh = base_ho - nf.logloss(hold, (f,), (b,))
        print(f'{label:<34}{b:>7.2f}{gt:>12.4f}{gh:>14.4f}')

    print('\nFor scale, the signals already in the model gained:')
    print('  QB change +0.0030 · rest +0.0007 · divisional +0.0003 (holdout)')


if __name__ == '__main__':
    main()
