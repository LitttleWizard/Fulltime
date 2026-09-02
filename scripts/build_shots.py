#!/usr/bin/env python3
"""
Refresh script for epl-shots.json — bundled shots/corners snapshot used by
epl-predictor.html as a secondary adjustment layer on top of the live Elo model.

football-data.co.uk does not send CORS headers, so this data can't be fetched
live from the browser — it has to be pulled here and committed as a static
JSON file. Re-run this whenever you want fresher shot stats:

    python3 build_shots.py

Then copy the resulting epl-shots.json into the site root and redeploy.
"""
import csv
import json
import urllib.request
from datetime import datetime

# Paths below are relative to the repo root, so the script works from any
# working directory. The join is absolute, so re-running it (a script that
# imports another that also does this) is a no-op rather than climbing up.
import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))


SEASONS = ["2223", "2324", "2425", "2526", "2627"]  # last ~4 full seasons + current
BASE = "https://www.football-data.co.uk/mmz4281/{s}/E0.csv"

# football-data.co.uk short names -> openfootball.json canonical names
# (openfootball names are what the live fetch / UI uses, so we normalize to those)
NAME_MAP = {
    "Arsenal": "Arsenal FC",
    "Aston Villa": "Aston Villa FC",
    "Bournemouth": "AFC Bournemouth",
    "Brentford": "Brentford FC",
    "Brighton": "Brighton & Hove Albion FC",
    "Burnley": "Burnley FC",
    "Chelsea": "Chelsea FC",
    "Coventry": "Coventry City FC",
    "Crystal Palace": "Crystal Palace FC",
    "Everton": "Everton FC",
    "Fulham": "Fulham FC",
    "Hull": "Hull City AFC",
    "Ipswich": "Ipswich Town FC",
    "Leeds": "Leeds United FC",
    "Leicester": "Leicester City FC",
    "Liverpool": "Liverpool FC",
    "Luton": "Luton Town FC",
    "Man City": "Manchester City FC",
    "Man United": "Manchester United FC",
    "Newcastle": "Newcastle United FC",
    "Nott'm Forest": "Nottingham Forest FC",
    "Sheffield United": "Sheffield United FC",
    "Southampton": "Southampton FC",
    "Sunderland": "Sunderland AFC",
    "Tottenham": "Tottenham Hotspur FC",
    "West Ham": "West Ham United FC",
    "Wolves": "Wolverhampton Wanderers FC",
    "Watford": "Watford FC",
    "West Brom": "West Bromwich Albion FC",
    "Norwich": "Norwich City FC",
    "Middlesbrough": "Middlesbrough FC",
    "Cardiff": "Cardiff City FC",
    "Huddersfield": "Huddersfield Town FC",
    "Swansea": "Swansea City FC",
    "Stoke": "Stoke City FC",
    "West Brom": "West Bromwich Albion FC",
}


def fetch_csv(season):
    url = BASE.format(s=season)
    with urllib.request.urlopen(url) as r:
        text = r.read().decode("utf-8-sig")
    return list(csv.DictReader(text.splitlines()))


def main():
    matches = []
    unmapped = set()
    for season in SEASONS:
        rows = fetch_csv(season)
        for row in rows:
            home = row.get("HomeTeam")
            away = row.get("AwayTeam")
            if not home or not away:
                continue
            if home not in NAME_MAP:
                unmapped.add(home)
            if away not in NAME_MAP:
                unmapped.add(away)
            try:
                date = datetime.strptime(row["Date"], "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                continue

            def num(key):
                v = row.get(key, "")
                try:
                    return int(v)
                except ValueError:
                    return None

            rec = {
                "date": date,
                "home": NAME_MAP.get(home, home),
                "away": NAME_MAP.get(away, away),
                "hg": num("FTHG"),
                "ag": num("FTAG"),
                "hs": num("HS"),
                "as": num("AS"),
                "hst": num("HST"),
                "ast": num("AST"),
                "hc": num("HC"),
                "ac": num("AC"),
            }
            matches.append(rec)

    if unmapped:
        print("WARNING — unmapped team names (add to NAME_MAP):", sorted(unmapped))

    matches.sort(key=lambda m: m["date"])
    out = {
        "generated": datetime.utcnow().strftime("%Y-%m-%d"),
        "source": "football-data.co.uk",
        "seasons": SEASONS,
        "matches": matches,
    }
    with open("data/epl-shots.json", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"wrote epl-shots.json — {len(matches)} matches")


if __name__ == "__main__":
    main()
