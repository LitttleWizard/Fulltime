#!/usr/bin/env python3
"""
Bake EA FC 26 Premier League ratings into `epl-players.json` for the browser.

The upstream CSV is ~9MB and every row carries 100+ columns the page never
reads, so fetching it at runtime would be absurd. This trims it to the EPL and
to the fields the matcher needs. Same pattern as `build_shots.py`.

Name matching happens in the browser against these pre-normalised tokens —
ESPN and EA FC spell players differently, and Iberian double surnames
("Ezri Konsa Ngoyo" vs ESPN's "Ezri Konsa") break naive last-token matching.

Usage:  python3 build_players.py
"""
import csv, io, json, os, re, sys, unicodedata, urllib.request
from collections import defaultdict, deque

# Paths below are relative to the repo root, so the script works from any
# working directory. The join is absolute, so re-running it (a script that
# imports another that also does this) is a no-op rather than climbing up.
import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))


FIFA = 'https://raw.githubusercontent.com/ismailoksuz/EAFC26-DataHub/main/data/players.csv'
OUT = 'data/epl-players.json'
LINEUPS = 'data/lineups.json'
FORM_N = 6        # matches in a club's rolling baseline XI, as tested
SOFT = 6.0        # softmax temperature; see xiStrength() in players.js


def norm(s):
    s = str(s or '').replace('ß', 'ss').replace('Ø', 'o').replace('ø', 'o')
    s = s.replace('đ', 'd').replace('ð', 'd')
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z ]', ' ', s.lower()).split()


def canon(n):
    m = re.match(r'^(.*?)\s+(?:FC|AFC)$', str(n or '').strip())
    return m.group(1) if m else str(n or '').strip()


def soft(vals):
    """Softmax-mean of an XI, matching xiStrength() in players.js.

    A plain mean dilutes a missing star into nothing across eleven players;
    this weights the top of the XI more heavily. Of the encodings tried in
    `epl_players.py` it gave the most stable cross-fitted betas.
    """
    import math
    return SOFT * math.log(sum(math.exp(v / SOFT) for v in vals) / len(vals))


def baselines(players, club_mean):
    """Each club's rolling recent-XI strength, from the cached lineups.

    This is the reference the live XI is compared against, so it has to be
    built the same way `epl_players.py` built it when the effect was measured —
    hence reusing the cache rather than a "best available XI" shortcut.
    """
    if not os.path.exists(LINEUPS):
        print(f'  ({LINEUPS} absent — no baselines; run fetch_lineups.py)')
        return {}

    idx = defaultdict(list)
    for p in players:
        idx[p['c']].append(p)

    def rate(club, disp):
        d = norm(disp)
        if not d:
            return None
        dsur, dini = set(d[1:] if len(d) > 1 else d), d[0][0]
        for scope in (idx.get(club) or [], players):
            exact = [p for p in scope if p['f'] == ' '.join(d)]
            if len(exact) == 1:
                return exact[0]['o']
            c = [p for p in scope if (set(p['s']) & dsur) and (dini in p['i'] or not p['i'])]
            if len(c) == 1:
                return c[0]['o']
            if len(c) > 1 and scope is not players:
                return max(x['o'] for x in c)
        return None

    recent = defaultdict(lambda: deque(maxlen=FORM_N))
    data = json.load(open(LINEUPS))
    for key in sorted(data.keys()):
        _, home, away = key.split('|')
        lu = data[key]
        for club, names in ((home, lu['home']), (away, lu['away'])):
            fb = club_mean.get(club, 0) or 0
            vals = [rate(club, n) or fb for n in names if n]
            if len(vals) >= 10 and fb:
                recent[club].append(soft(vals))
    return {c: round(sum(v) / len(v), 3) for c, v in recent.items() if v}


def main():
    print('fetching EA FC 26 player data…')
    with urllib.request.urlopen(FIFA, timeout=180) as r:
        text = r.read().decode('utf-8', 'replace')

    players, date = [], None
    for x in csv.DictReader(io.StringIO(text)):
        if (x.get('league_name') or '').strip() != 'Premier League':
            continue
        date = date or x.get('fifa_update_date')
        ln, sn = norm(x['long_name']), norm(x['short_name'])
        if not ln:
            continue
        players.append({
            'c': canon(x['club_name']),
            'n': x['short_name'],
            'f': ' '.join(ln),
            's': sorted(set(ln[1:] if len(ln) > 1 else ln) |
                        set(sn[1:] if len(sn) > 1 else sn)),
            'i': sorted({t[0] for t in (ln[:1] + sn[:1]) if t}),
            'o': int(x['overall'] or 0),
            'p': (x.get('player_positions') or '').split(',')[0].strip(),
        })

    by_club = defaultdict(list)
    for p in players:
        by_club[p['c']].append(p['o'])
    club_mean = {c: round(sum(v) / len(v), 2) for c, v in by_club.items()}

    out = {
        'snapshot': date,
        'clubMean': club_mean,
        'clubBaseline': baselines(players, club_mean),
        'players': players,
    }
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))

    print(f'wrote {OUT}: {len(players)} players, {len(by_club)} clubs, '
          f'{len(out["clubBaseline"])} baselines, snapshot {date}, '
          f'{os.path.getsize(OUT)/1024:.0f} KB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
