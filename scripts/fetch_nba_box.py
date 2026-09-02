#!/usr/bin/env python3
"""
Cache NBA box scores -> nba-box.json, for testing whether player absence helps.

One request per game, so this is a long offline job. The cache is append-only:
re-running fetches only what is missing, and it flushes every 50 games so an
interruption costs at most that.

Stores the minimum the availability test needs — per player: id, minutes,
points, and whether they appeared — not the full box score.

Usage:  python3 fetch_nba_box.py [--seasons 2025,2026]
"""
import argparse, json, os, sys, time, urllib.request

# Paths below are relative to the repo root, so the script works from any
# working directory. The join is absolute, so re-running it (a script that
# imports another that also does this) is a no-op rather than climbing up.
import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))


ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
OUT = 'data/nba-box.json'


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


def mins(v):
    try:
        return int(str(v).split(':')[0])
    except (ValueError, AttributeError):
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='2025,2026')
    args = ap.parse_args()
    want_seasons = {int(x) for x in args.seasons.split(',')}

    hist = json.load(open('data/nba-games.json'))['games']
    target = [g for g in hist if g['season'] in want_seasons]

    cache = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = [g for g in target if g['id'] not in cache]
    print(f'{len(target)} games in seasons {sorted(want_seasons)}; '
          f'{len(cache)} cached, {len(todo)} to fetch', flush=True)

    done = 0
    for g in todo:
        d = get(f'{ESPN}/summary?event={g["id"]}')
        time.sleep(0.08)
        rec = {}
        for t in ((d or {}).get('boxscore') or {}).get('players') or []:
            abbr = (t.get('team') or {}).get('abbreviation')
            st = (t.get('statistics') or [{}])[0]
            labels = st.get('labels') or []
            try:
                mi, pi = labels.index('MIN'), labels.index('PTS')
            except ValueError:
                continue
            rows = []
            for a in (st.get('athletes') or []):
                ath = a.get('athlete') or {}
                pid = ath.get('id')
                if not pid:
                    continue
                stats = a.get('stats') or []
                played = not a.get('didNotPlay') and len(stats) > max(mi, pi)
                rows.append([pid,
                             mins(stats[mi]) if played else 0,
                             int(stats[pi]) if played and str(stats[pi]).isdigit() else 0,
                             1 if played else 0])
            if abbr and rows:
                rec[abbr] = rows
        if len(rec) == 2:
            cache[g['id']] = rec
        done += 1
        if done % 50 == 0:
            json.dump(cache, open(OUT, 'w'), separators=(',', ':'))
            print(f'  {done}/{len(todo)} cached={len(cache)}', flush=True)

    json.dump(cache, open(OUT, 'w'), separators=(',', ':'))
    print(f'wrote {OUT}: {len(cache)} games, {os.path.getsize(OUT)/1024/1024:.1f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
