#!/usr/bin/env python3
"""
Bake per-team NBA rotations into `nba-players.json` for the browser.

Scoring averages come from the cached box scores (`nba-box.json`), names and
positions from ESPN's roster endpoint — the box score carries only athlete ids,
and the roster carries no statistics, so neither is usable alone.

Only the most recent season in the cache is averaged: a player's value to a
team this year is what matters, not their 2024 form.

Usage:  python3 build_nba_players.py [--top 12]
"""
import argparse, json, os, sys, time, urllib.request
from collections import defaultdict

# Paths below are relative to the repo root, so the script works from any
# working directory. The join is absolute, so re-running it (a script that
# imports another that also does this) is a no-op rather than climbing up.
import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))


ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
BOX, GAMES, OUT = 'data/nba-box.json', 'data/nba-games.json', 'data/nba-players.json'
MIN_MIN = 8          # matches nba_players.py's rotation threshold
MIN_GAMES = 5


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.0 * (i + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=12)
    args = ap.parse_args()

    if not os.path.exists(BOX):
        print(f'{BOX} missing — run: python3 fetch_nba_box.py', file=sys.stderr)
        return 1
    box = json.load(open(BOX))
    hist = json.load(open(GAMES))
    season_of = {g['id']: g['season'] for g in hist['games']}
    latest = max(season_of.get(gid, 0) for gid in box)
    print(f'averaging season {latest}')

    agg = defaultdict(lambda: defaultdict(lambda: {'g': 0, 'min': 0, 'pts': 0}))
    for gid, rec in box.items():
        if season_of.get(gid) != latest:
            continue
        for team, rows in rec.items():
            for pid, mn, pts, played in rows:
                if played and mn >= MIN_MIN:
                    a = agg[team][pid]
                    a['g'] += 1; a['min'] += mn; a['pts'] += pts

    # names + positions, one request per franchise
    meta = {}
    tl = get(f'{ESPN}/teams?limit=50')
    entries = (((tl or {}).get('sports') or [{}])[0].get('leagues') or [{}])[0].get('teams') or []
    for t in entries:
        tm = t.get('team') or {}
        tid, abbr = tm.get('id'), tm.get('abbreviation')
        if not tid or not abbr:
            continue
        r = get(f'{ESPN}/teams/{tid}/roster')
        time.sleep(0.1)
        for a in ((r or {}).get('athletes') or []):
            if isinstance(a, dict) and 'items' in a:
                for x in a['items']:
                    meta[str(x.get('id'))] = (x.get('displayName'),
                                              ((x.get('position') or {}).get('abbreviation') or ''))
            else:
                meta[str(a.get('id'))] = (a.get('displayName'),
                                          ((a.get('position') or {}).get('abbreviation') or ''))
    print(f'{len(meta)} players named')

    out = {}
    unnamed = 0
    for team, players in agg.items():
        rows = []
        for pid, a in players.items():
            if a['g'] < MIN_GAMES:
                continue
            name, pos = meta.get(str(pid), (None, ''))
            if not name:
                unnamed += 1
                continue                      # traded or waived since; skip rather than show an id
            rows.append({'id': str(pid), 'n': name, 'p': pos, 'g': a['g'],
                         'ppg': round(a['pts'] / a['g'], 1),
                         'mpg': round(a['min'] / a['g'], 1)})
        rows.sort(key=lambda r: -r['ppg'])
        if rows:
            out[team] = rows[:args.top]

    doc = {'generated': time.strftime('%Y-%m-%d'), 'season': latest, 'teams': out}
    json.dump(doc, open(OUT, 'w'), separators=(',', ':'))
    print(f'wrote {OUT}: {len(out)} teams, '
          f'{sum(len(v) for v in out.values())} players, '
          f'{unnamed} dropped as unnamed, {os.path.getsize(OUT)/1024:.0f} KB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
