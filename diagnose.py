#!/usr/bin/env python3
"""
Which signals is the Fulltime model actually missing?

Tests candidate improvements against real EPL history before we bother building
them, so the priority list is evidence rather than folklore.
"""
import json, math, urllib.request
from collections import defaultdict

SEASONS = ['2017-18','2018-19','2019-20','2020-21','2021-22',
           '2022-23','2023-24','2024-25','2025-26','2026-27']
BASE = 'https://raw.githubusercontent.com/openfootball/football.json/master'


def fs(m):
    s = m.get('score')
    if not s: return None
    if isinstance(s, dict) and isinstance(s.get('ft'), list): return s['ft']
    if isinstance(s, list): return s
    return None


def load():
    out = []
    for s in SEASONS:
        with urllib.request.urlopen(f'{BASE}/{s}/en.1.json') as r:
            d = json.load(r)
        ms = [m for m in d['matches'] if fs(m)]
        ms.sort(key=lambda m: m.get('date',''))
        out.append((s, ms))
    return out


def d2n(ds):
    y, m, d = map(int, ds.split('-'))
    return (y * 372) + (m * 31) + d   # good enough for day-gap bucketing


seasons = load()

# ── 1. Home advantage per season ──────────────────────────────────────────
print('1. HOME ADVANTAGE BY SEASON  (model assumes a fixed +50 Elo, all seasons)')
print(f"   {'season':<10}{'home win%':>11}{'draw%':>8}{'away win%':>11}{'implied Elo':>13}")
for s, ms in seasons:
    if len(ms) < 50: continue
    h = sum(1 for m in ms if fs(m)[0] > fs(m)[1])
    d = sum(1 for m in ms if fs(m)[0] == fs(m)[1])
    a = len(ms) - h - d
    n = len(ms)
    # Elo points implied by the home side's expected score
    exp = (h + 0.5 * d) / n
    elo = -400 * math.log10(1 / exp - 1)
    print(f'   {s:<10}{h/n*100:>10.1f}%{d/n*100:>7.1f}%{a/n*100:>10.1f}%{elo:>12.0f}')

# ── 2. Newly promoted teams ───────────────────────────────────────────────
print('\n2. NEWLY PROMOTED TEAMS  (model starts every unseen team at 1500 = average)')
seen = set()
prom_pts = prom_n = 0
est_pts = est_n = 0
for i, (s, ms) in enumerate(seasons):
    teams = set()
    for m in ms: teams.add(m['team1']); teams.add(m['team2'])
    new = teams - seen if i else set()
    pts = defaultdict(int); played = defaultdict(int)
    for m in ms:
        hg, ag = fs(m)
        pts[m['team1']] += 3 if hg > ag else (1 if hg == ag else 0)
        pts[m['team2']] += 3 if ag > hg else (1 if hg == ag else 0)
        played[m['team1']] += 1; played[m['team2']] += 1
    for t in teams:
        if not played[t]: continue
        if t in new: prom_pts += pts[t]; prom_n += played[t]
        elif i: est_pts += pts[t]; est_n += played[t]
    seen |= teams
print(f'   promoted sides:  {prom_pts/prom_n:.2f} points per game  (n={prom_n} team-matches)')
print(f'   established:     {est_pts/est_n:.2f} points per game  (n={est_n})')
gap = est_pts/est_n - prom_pts/prom_n
print(f'   -> promoted sides run {gap:.2f} ppg below the rest; starting them at league')
print(f'      average (1500) systematically overrates them all season.')

# ── 3. Rest / congestion ──────────────────────────────────────────────────
print('\n3. REST DAYS  (not in the model at all; derivable from fixture dates we already have)')
last = {}
buckets = defaultdict(lambda: [0, 0])   # [points, matches]
for s, ms in seasons:
    last.clear()
    for m in ms:
        hg, ag = fs(m); day = d2n(m['date'])
        for team, gf, ga in ((m['team1'], hg, ag), (m['team2'], ag, hg)):
            if team in last:
                gap_d = day - last[team]
                b = '≤3 days' if gap_d <= 3 else '4-5 days' if gap_d <= 5 else '6-8 days' if gap_d <= 8 else '9+ days'
                buckets[b][0] += 3 if gf > ga else (1 if gf == ga else 0)
                buckets[b][1] += 1
            last[team] = day
print(f"   {'rest':<12}{'matches':>9}{'points/game':>14}")
for b in ['≤3 days', '4-5 days', '6-8 days', '9+ days']:
    p, n = buckets[b]
    if n > 40:
        print(f'   {b:<12}{n:>9}{p/n:>13.2f}')
