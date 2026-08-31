#!/usr/bin/env python3
"""
Calibrates the constants used by epl-predictor.html's Elo model against the same
historical data the page fetches at runtime, instead of hand-picked values.

Walk-forward backtest: replays matches in chronological order, predicting each
match with only the info available before it, then updates ratings/history with
the real result. First season is warm-up (not scored) so ratings aren't just
noise around 1500. Loss = multiclass log-loss on (home, draw, away).

Usage:
    python3 calibrate_elo.py
"""
import json
import math
import urllib.request

SEASONS = ['2017-18','2018-19','2019-20','2020-21','2021-22',
           '2022-23','2023-24','2024-25','2025-26','2026-27']
OPENFOOTBALL_BASE = 'https://raw.githubusercontent.com/openfootball/football.json/master'
SHOTS_FILE = 'epl-shots.json'
WARMUP_SEASONS = 1  # first N seasons build state only, not scored
FORM_WINDOW = 8


def final_score(m):
    # openfootball.json mostly uses {ht:[..], ft:[h,a]}, but some rows (seen in
    # 2025-26) give the final score directly as score:[h,a] with no ft key.
    score = m.get('score')
    if not score:
        return None
    if isinstance(score, dict) and isinstance(score.get('ft'), list):
        return score['ft']
    if isinstance(score, list):
        return score
    return None


def fetch_seasons():
    seasons = []
    for s in SEASONS:
        url = f'{OPENFOOTBALL_BASE}/{s}/en.1.json'
        with urllib.request.urlopen(url) as r:
            d = json.load(r)
        matches = [m for m in d['matches'] if final_score(m)]
        matches.sort(key=lambda m: m.get('date', ''))
        seasons.append({'season': s, 'matches': matches})
    return seasons


def load_shots():
    with open(SHOTS_FILE) as f:
        d = json.load(f)
    idx = {}
    for m in d['matches']:
        idx[(m['date'], m['home'], m['away'])] = m
    return idx


def mov_multiplier(gd):
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def run_backtest(seasons, shots_idx, params, collect=False):
    K = params['K']
    HOME_ADV = params['HOME_ADV']
    REGRESS = params['REGRESS']
    DRAW_BASE = params['DRAW_BASE']
    DRAW_SLOPE = params['DRAW_SLOPE']
    DRAW_FLOOR = params['DRAW_FLOOR']
    DRAW_CAP = params['DRAW_CAP']
    GOAL_W = params['GOAL_W']
    SHOT_W = params['SHOT_W']
    NUDGE_SCALE = params['NUDGE_SCALE']
    NUDGE_CAP = params['NUDGE_CAP']
    DEFAULT_RATING = 1500.0

    ratings = {}
    goal_hist = {}   # team -> list of (gf, ga) chronological
    shot_hist = {}   # team -> list of (stFor, stAgainst) chronological

    def get_rating(t):
        return ratings.get(t, DEFAULT_RATING)

    def recent_goal_stats(team):
        h = goal_hist.get(team, [])[-FORM_WINDOW:]
        if not h:
            return None
        gf = sum(x[0] for x in h) / len(h)
        ga = sum(x[1] for x in h) / len(h)
        return gf, ga

    def recent_shot_stats(team):
        h = shot_hist.get(team, [])[-FORM_WINDOW:]
        if not h:
            return None
        sf = sum(x[0] for x in h) / len(h)
        sa = sum(x[1] for x in h) / len(h)
        return sf, sa

    league_gf, league_ga = 1.4, 1.4  # running league averages, updated per season

    records = []  # (predicted_probs, actual_idx) for scoring
    eps = 1e-9

    for si, season in enumerate(seasons):
        if si > 0:
            for t in list(ratings.keys()):
                ratings[t] = DEFAULT_RATING + (ratings[t] - DEFAULT_RATING) * REGRESS
            # refresh league goal averages from teams seen with history so far
            avgs = [recent_goal_stats(t) for t in goal_hist]
            avgs = [a for a in avgs if a]
            if avgs:
                league_gf = sum(a[0] for a in avgs) / len(avgs)
                league_ga = sum(a[1] for a in avgs) / len(avgs)

        scored_season = si >= WARMUP_SEASONS

        for m in season['matches']:
            home, away = m['team1'], m['team2']
            hg, ag = final_score(m)
            date = m.get('date', '')

            Rh, Ra = get_rating(home), get_rating(away)
            dr = Rh - Ra + HOME_ADV
            win_share = 1 / (1 + 10 ** (-dr / 400))
            draw_p = clamp(DRAW_BASE - DRAW_SLOPE * abs(dr), DRAW_FLOOR, DRAW_CAP)

            home_win = (1 - draw_p) * win_share
            away_win = (1 - draw_p) * (1 - win_share)
            draw = draw_p

            g_home = recent_goal_stats(home)
            g_away = recent_goal_stats(away)
            s_home = recent_shot_stats(home)
            s_away = recent_shot_stats(away)

            nudge = 0.0
            if g_home and g_away:
                net_home = (g_home[0] - league_gf) - (g_home[1] - league_ga)
                net_away = (g_away[0] - league_gf) - (g_away[1] - league_ga)
                diff = (net_home - net_away) * GOAL_W
                if s_home and s_away:
                    shot_net_home = s_home[0] - s_home[1]
                    shot_net_away = s_away[0] - s_away[1]
                    diff += (shot_net_home - shot_net_away) * SHOT_W
                nudge = math.tanh(diff / NUDGE_SCALE) * NUDGE_CAP

            home_win = max(0.02, home_win + nudge)
            away_win = max(0.02, away_win - nudge)
            total = home_win + draw + away_win
            home_win, draw, away_win = home_win / total, draw / total, away_win / total

            if scored_season:
                actual = 0 if hg > ag else (2 if hg < ag else 1)
                probs = (home_win, draw, away_win)
                records.append((probs, actual))
                if collect:
                    pass

            # update Elo with real result
            actual_score = 1.0 if hg > ag else (0.0 if hg < ag else 0.5)
            mult = mov_multiplier(abs(hg - ag))
            delta = K * mult * (actual_score - win_share_true(Rh, Ra, HOME_ADV))
            ratings[home] = Rh + delta
            ratings[away] = Ra - delta

            goal_hist.setdefault(home, []).append((hg, ag))
            goal_hist.setdefault(away, []).append((ag, hg))

            srow = shots_idx.get((date, home, away))
            if srow and srow.get('hst') is not None and srow.get('ast') is not None:
                shot_hist.setdefault(home, []).append((srow['hst'], srow['ast']))
                shot_hist.setdefault(away, []).append((srow['ast'], srow['hst']))

    # scoring
    n = len(records)
    if n == 0:
        return None
    logloss = 0.0
    brier = 0.0
    correct = 0
    for probs, actual in records:
        p = max(probs[actual], eps)
        logloss += -math.log(p)
        onehot = [1.0 if i == actual else 0.0 for i in range(3)]
        brier += sum((probs[i] - onehot[i]) ** 2 for i in range(3))
        if probs.index(max(probs)) == actual:
            correct += 1
    return {
        'n': n,
        'logloss': logloss / n,
        'brier': brier / n,
        'accuracy': correct / n,
    }


def win_share_true(Rh, Ra, HOME_ADV):
    # the *unadjusted* Elo win-share used for the rating UPDATE step — this stays
    # fixed (doesn't depend on the draw-prob / nudge params being calibrated),
    # matching how the runtime JS separates rating updates from outcome prediction.
    dr = Rh - Ra + HOME_ADV
    return 1 / (1 + 10 ** (-dr / 400))


DEFAULTS = {
    'K': 20, 'HOME_ADV': 65, 'REGRESS': 0.75,
    'DRAW_BASE': 0.30, 'DRAW_SLOPE': 0.0007, 'DRAW_FLOOR': 0.06, 'DRAW_CAP': 0.30,
    'GOAL_W': 0.5, 'SHOT_W': 0.06, 'NUDGE_SCALE': 3.0, 'NUDGE_CAP': 0.08,
}


def grid_search(seasons, shots_idx, base_params, grid, keys):
    best = None
    best_params = None
    from itertools import product
    for combo in product(*[grid[k] for k in keys]):
        params = dict(base_params)
        for k, v in zip(keys, combo):
            params[k] = v
        result = run_backtest(seasons, shots_idx, params)
        if result is None:
            continue
        if best is None or result['logloss'] < best['logloss']:
            best = result
            best_params = params
    return best_params, best


def main():
    print('Fetching historical seasons…')
    seasons = fetch_seasons()
    total_matches = sum(len(s['matches']) for s in seasons)
    print(f'Loaded {len(seasons)} seasons, {total_matches} matches.')
    shots_idx = load_shots()
    print(f'Loaded shots index: {len(shots_idx)} matches.')

    baseline = run_backtest(seasons, shots_idx, DEFAULTS)
    print(f"\nBaseline (hand-picked constants): n={baseline['n']} "
          f"logloss={baseline['logloss']:.4f} brier={baseline['brier']:.4f} acc={baseline['accuracy']:.3f}")

    params = dict(DEFAULTS)

    # Round 1: core Elo params
    grid1 = {
        'K': [10, 15, 20, 25, 30, 35, 40],
        'HOME_ADV': [30, 40, 50, 60, 65, 70, 80, 100],
        'REGRESS': [0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0],
    }
    params, r1 = grid_search(seasons, shots_idx, params, grid1, ['K', 'HOME_ADV', 'REGRESS'])
    print(f"Round 1 (K/HOME_ADV/REGRESS): logloss={r1['logloss']:.4f} acc={r1['accuracy']:.3f}  "
          f"K={params['K']} HOME_ADV={params['HOME_ADV']} REGRESS={params['REGRESS']}")

    # Round 2: draw probability formula
    grid2 = {
        'DRAW_BASE': [0.22, 0.24, 0.26, 0.28, 0.30, 0.32],
        'DRAW_SLOPE': [0.0002, 0.0004, 0.0006, 0.0008, 0.0010, 0.0012],
    }
    params, r2 = grid_search(seasons, shots_idx, params, grid2, ['DRAW_BASE', 'DRAW_SLOPE'])
    print(f"Round 2 (draw formula): logloss={r2['logloss']:.4f} acc={r2['accuracy']:.3f}  "
          f"DRAW_BASE={params['DRAW_BASE']} DRAW_SLOPE={params['DRAW_SLOPE']}")

    # Round 3: nudge (goals + shots recent-form adjustment)
    grid3 = {
        'GOAL_W': [0.0, 0.25, 0.5, 0.75, 1.0],
        'SHOT_W': [0.0, 0.03, 0.06, 0.09, 0.12],
        'NUDGE_SCALE': [1.5, 2.0, 3.0, 4.0, 6.0],
        'NUDGE_CAP': [0.04, 0.06, 0.08, 0.10, 0.14],
    }
    params, r3 = grid_search(seasons, shots_idx, params, grid3, ['GOAL_W', 'SHOT_W', 'NUDGE_SCALE', 'NUDGE_CAP'])
    print(f"Round 3 (nudge weights): logloss={r3['logloss']:.4f} acc={r3['accuracy']:.3f}  "
          f"GOAL_W={params['GOAL_W']} SHOT_W={params['SHOT_W']} NUDGE_SCALE={params['NUDGE_SCALE']} NUDGE_CAP={params['NUDGE_CAP']}")

    # Round 4: re-pass over core Elo params now that draw+nudge are set (coordinate descent refinement)
    params, r4 = grid_search(seasons, shots_idx, params, grid1, ['K', 'HOME_ADV', 'REGRESS'])
    print(f"Round 4 (refine K/HOME_ADV/REGRESS): logloss={r4['logloss']:.4f} acc={r4['accuracy']:.3f}  "
          f"K={params['K']} HOME_ADV={params['HOME_ADV']} REGRESS={params['REGRESS']}")

    # sanity check: does the nudge layer actually help vs Elo+draw alone?
    no_nudge_params = dict(params)
    no_nudge_params['GOAL_W'] = 0.0
    no_nudge_params['SHOT_W'] = 0.0
    no_nudge_result = run_backtest(seasons, shots_idx, no_nudge_params)

    print('\n=== FINAL ===')
    print(json.dumps(params, indent=2))
    print(f"Final:            n={r4['n']} logloss={r4['logloss']:.4f} brier={r4['brier']:.4f} acc={r4['accuracy']:.3f}")
    print(f"Elo+draw only:    logloss={no_nudge_result['logloss']:.4f} brier={no_nudge_result['brier']:.4f} acc={no_nudge_result['accuracy']:.3f}")
    print(f"Baseline (hand):  logloss={baseline['logloss']:.4f} brier={baseline['brier']:.4f} acc={baseline['accuracy']:.3f}")

    with open('calibration-report.json', 'w') as f:
        json.dump({
            'params': params,
            'final': r4,
            'elo_draw_only': no_nudge_result,
            'baseline_handpicked': baseline,
            'n_matches_scored': r4['n'],
            'seasons': SEASONS,
            'warmup_seasons': WARMUP_SEASONS,
        }, f, indent=2)
    print('\nWrote calibration-report.json')


if __name__ == '__main__':
    main()
