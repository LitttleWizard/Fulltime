#!/usr/bin/env python3
"""
Bake NBA game results into `nba-games.json` for the browser.

Why baked rather than fetched live: ESPN's scoreboard only answers a date
range at a time, so five seasons is ~90 requests. Fine offline, absurd on page
load. The page reads this file for history and hits ESPN live only for today's
scores — the same split `build_shots.py` uses for EPL.

hoopR-data publishes NBA schedules but stops at 2023, and FiveThirtyEight's
nba_elo files are gone from their repo, so ESPN is the only current source that
is both complete and CORS-open.

Usage:  python3 build_nba.py [--from 2021] [--to 2026]
"""
import argparse, json, os, sys, time, urllib.request
from datetime import date, timedelta

# Paths below are relative to the repo root, so the script works from any
# working directory. The join is absolute, so re-running it (a script that
# imports another that also does this) is a no-op rather than climbing up.
import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))


ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
OUT = 'data/nba-games.json'
BLOCK = 14                      # days per request


def get(url, tries=3):
    # No custom User-Agent: ESPN 403s on one, and is happy with urllib's default.
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.5 * (i + 1))
    return None


def season_span(end_year):
    """An NBA season labelled by the year it ends: Oct (y-1) → Jun (y)."""
    return date(end_year - 1, 10, 1), date(end_year, 6, 30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='y0', type=int, default=2021)
    ap.add_argument('--to', dest='y1', type=int, default=date.today().year)
    args = ap.parse_args()

    # The 30 current franchises. ESPN's NBA scoreboard also carries preseason
    # exhibitions against international clubs (Real Madrid, Flamengo, Australian
    # NBL sides) and All-Star squads (EAST/WEST/STARS/STRIPES). Those are real
    # games in the feed but they are not NBA results, and letting them through
    # moves a franchise's Elo for beating a EuroLeague team in October.
    league = get(f'{ESPN}/teams?limit=50')
    names = {}
    for t in (((league or {}).get('sports') or [{}])[0].get('leagues') or [{}])[0].get('teams') or []:
        tm = t.get('team') or {}
        if tm.get('abbreviation'):
            names[tm['abbreviation']] = tm.get('displayName') or tm['abbreviation']
    if len(names) < 25:
        print(f'refusing to build: only {len(names)} franchises resolved', file=sys.stderr)
        return 1
    print(f'{len(names)} franchises; filtering everything else out')

    seen, games, dropped = set(), [], {}
    for yr in range(args.y0, args.y1 + 1):
        start, end = season_span(yr)
        if start > date.today():
            continue
        end = min(end, date.today())
        got = 0
        cur = start
        while cur <= end:
            stop = min(cur + timedelta(days=BLOCK - 1), end)
            d = get(f'{ESPN}/scoreboard?dates={cur:%Y%m%d}-{stop:%Y%m%d}&limit=1000')
            for ev in (d or {}).get('events', []):
                c = (ev.get('competitions') or [{}])[0]
                st = ((c.get('status') or {}).get('type') or {})
                if st.get('state') != 'post':
                    continue                      # only completed games
                comp = c.get('competitors') or []
                h = next((x for x in comp if x.get('homeAway') == 'home'), None)
                a = next((x for x in comp if x.get('homeAway') == 'away'), None)
                if not h or not a:
                    continue
                try:
                    hs, as_ = int(h.get('score')), int(a.get('score'))
                except (TypeError, ValueError):
                    continue
                if hs == as_:
                    continue                      # basketball has no draws
                ha = (h.get('team') or {}).get('abbreviation')
                aa = (a.get('team') or {}).get('abbreviation')
                if ha not in names or aa not in names:
                    for x in (ha, aa):
                        if x not in names:
                            dropped[x] = dropped.get(x, 0) + 1
                    continue
                gid = ev.get('id')
                if gid in seen:
                    continue
                seen.add(gid)
                games.append({
                    'id': gid,
                    'date': (ev.get('date') or '')[:10],
                    'season': yr,
                    'home': ha,
                    'away': aa,
                    'hs': hs, 'as': as_,
                    'neutral': bool(c.get('neutralSite')),
                    'post': bool((c.get('season') or {}).get('slug') == 'post-season'),
                })
                got += 1
            cur = stop + timedelta(days=1)
            time.sleep(0.12)
        print(f'  season {yr}: {got} games')

    games.sort(key=lambda g: (g['date'], g['id']))
    if dropped:
        top = sorted(dropped.items(), key=lambda kv: -kv[1])[:8]
        print(f'\ndropped {sum(dropped.values())} non-NBA appearances: ' +
              ', '.join(f'{k}x{v}' for k, v in top))

    out = {'generated': time.strftime('%Y-%m-%d'), 'teams': names, 'games': games}
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print(f'\nwrote {OUT}: {len(games)} games, {len(names)} teams, '
          f'{os.path.getsize(OUT)/1024:.0f} KB')
    if games:
        print(f'range {games[0]["date"]} .. {games[-1]["date"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
