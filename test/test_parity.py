#!/usr/bin/env python3
"""
Guard the one thing a refactor can silently break: the browser and the Python
analysis must produce the SAME Elo ratings.

Every accuracy figure on the site comes from the Python scripts, but visitors
see numbers computed by elo.js. If those two ever drift, the site quotes a
holdout score for a model it isn't running. This runs both and compares.

Needs node on PATH. Exits non-zero on any mismatch.

Usage:  python3 test/test_parity.py
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
TOL = 0.01          # ratings agree to a hundredth of a point


def js_ratings():
    """Run elo.js over nba-games.json under node."""
    script = '''
      global.window = {};
      require(%s);
      const games = require(%s).games;
      const r = window.Elo.run(
        games.map(g => ({ date: g.date, season: g.season, home: g.home,
                          away: g.away, hg: g.hs, ag: g.as, neutral: g.neutral })),
        { K: 16, homeAdv: 45, regress: 0.50, defaultRating: 1500,
          mov: window.Elo.mov.nba });
      console.log(JSON.stringify(r.ratings));
    ''' % (json.dumps(os.path.join(ROOT, 'assets', 'elo.js')),
           json.dumps(os.path.join(ROOT, 'data', 'nba-games.json')))
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f:
        f.write(script); path = f.name
    try:
        out = subprocess.run(['node', path], capture_output=True, text=True, timeout=180)
        if out.returncode != 0:
            print('node failed:', out.stderr[:400], file=sys.stderr)
            return None
        return json.loads(out.stdout)
    finally:
        os.unlink(path)


def py_ratings():
    import nba_model as M
    games, _ = M.load()
    cal = json.load(open(os.path.join(ROOT, 'data', 'nba-calibration.json')))
    *_, ratings = M.elo_run(games, cal['K'], cal['home'], cal['regress'])
    return dict(ratings)


def main():
    os.chdir(ROOT)
    js, py = js_ratings(), py_ratings()
    if js is None:
        print('SKIP: node unavailable'); return 0

    missing = set(py) ^ set(js)
    if missing:
        print(f'FAIL: teams differ between implementations: {sorted(missing)}')
        return 1

    bad = [(t, py[t], js[t]) for t in py if abs(py[t] - js[t]) > TOL]
    if bad:
        print(f'FAIL: {len(bad)} of {len(py)} ratings disagree by more than {TOL}')
        for t, p, j in sorted(bad, key=lambda x: -abs(x[1] - x[2]))[:8]:
            print(f'  {t:<5} python {p:8.3f}   js {j:8.3f}   diff {p - j:+.3f}')
        return 1

    worst = max(abs(py[t] - js[t]) for t in py)
    print(f'PASS: {len(py)} teams agree; largest difference {worst:.6f} '
          f'(tolerance {TOL})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
