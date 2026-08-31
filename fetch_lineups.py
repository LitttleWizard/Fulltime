#!/usr/bin/env python3
"""
Cache ESPN starting lineups for finished EPL matches -> lineups.json

One request per match, so this is an offline job. The cache is keyed by
(date, home, away) and is append-only: re-running only fetches what's missing.

Usage:  python3 fetch_lineups.py [--season 2025-26]
"""
import argparse, json, os, re, sys, time, urllib.request
from datetime import date, timedelta

OF = 'https://raw.githubusercontent.com/openfootball/football.json/master'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1'
OUT = 'lineups.json'


def get(url, tries=3):
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
    if not s: return None
    if isinstance(s, dict) and isinstance(s.get('ft'), list): return s['ft']
    if isinstance(s, list): return s
    return None


def day_num(ds):
    y, mo, d = map(int, ds.split('-')); return date(y, mo, d).toordinal()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', default='2025-26')
    args = ap.parse_args()

    cache = {}
    if os.path.exists(OUT):
        cache = json.load(open(OUT))
    print(f'{len(cache)} matches already cached')

    d = get(f'{OF}/{args.season}/en.1.json')
    fixtures = []
    for m in (d or {}).get('matches', []):
        ft = final_score(m)
        if ft and m.get('date'):
            fixtures.append((m['date'], canon(m['team1']), canon(m['team2'])))
    print(f'{len(fixtures)} finished {args.season} matches')

    todo = [f for f in fixtures if f'{f[0]}|{f[1]}|{f[2]}' not in cache]
    print(f'{len(todo)} to fetch')
    if not todo:
        return 0

    # index ESPN events by date, in fortnight blocks
    idx = {}
    lo = date.fromordinal(day_num(min(f[0] for f in todo)))
    hi = date.fromordinal(day_num(max(f[0] for f in todo)))
    cur = lo
    while cur <= hi:
        stop = min(cur + timedelta(days=13), hi)
        s = get(f'{ESPN}/scoreboard?dates={cur:%Y%m%d}-{stop:%Y%m%d}&limit=400')
        for ev in (s or {}).get('events', []):
            c = (ev.get('competitions') or [{}])[0]
            comp = c.get('competitors') or []
            h = next((x for x in comp if x.get('homeAway') == 'home'), None)
            a = next((x for x in comp if x.get('homeAway') == 'away'), None)
            if h and a:
                idx.setdefault(ev.get('date', '')[:10], []).append(
                    (ev['id'], canon(h['team'].get('displayName')), canon(a['team'].get('displayName'))))
        cur = stop + timedelta(days=1)
        time.sleep(0.15)
    print(f'{sum(len(v) for v in idx.values())} ESPN events indexed')

    got = miss = 0
    for i, (dt, home, away) in enumerate(todo, 1):
        eid = next((e for e, h, a in idx.get(dt, []) if h == home and a == away), None)
        if not eid:
            miss += 1; continue
        s = get(f'{ESPN}/summary?event={eid}')
        time.sleep(0.12)
        rec = {'home': [], 'away': [], 'formation': {}}
        ok = False
        for t in (s or {}).get('rosters') or []:
            side = 'home' if t.get('homeAway') == 'home' else 'away'
            rec['formation'][side] = t.get('formation')
            for p in (t.get('roster') or []):
                if p.get('starter'):
                    nm = (p.get('athlete') or {}).get('displayName')
                    if nm:
                        rec[side].append(nm)
            if len(rec[side]) >= 10:
                ok = True
        if ok and rec['home'] and rec['away']:
            cache[f'{dt}|{home}|{away}'] = rec
            got += 1
        else:
            miss += 1
        if i % 40 == 0:
            print(f'  {i}/{len(todo)}  got={got} miss={miss}')
            json.dump(cache, open(OUT, 'w'), separators=(',', ':'))

    json.dump(cache, open(OUT, 'w'), separators=(',', ':'))
    print(f'\nwrote {OUT}: {len(cache)} matches ({got} new, {miss} unavailable)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
