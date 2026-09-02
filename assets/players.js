/**
 * Player ratings for the Fulltime EPL terminal.
 *
 * Source: EA FC 26, snapshot dated 2025-09-19, baked into `epl-players.json`
 * by `build_players.py`. The upstream CSV is ~9MB of mostly irrelevant columns,
 * so the page reads the trimmed file instead.
 *
 *   Players.ready()                     -> Promise, resolves when data is loaded
 *   Players.rate(club, displayName)     -> 0-99 overall, or null if unmatched
 *   Players.xi(club, [displayNames])    -> { strength, rated, unrated, best, worst }
 *   Players.delta(club, [displayNames]) -> XI strength vs that club's recent norm,
 *                                          in rating points; null if unknown
 *   Players.adjust(probs, dh, da)       -> probs nudged by the lineup deltas
 *
 * WHAT THIS IS WORTH, measured (`epl_players.py`, 340 matches of 2025-26, all
 * after the ratings snapshot, betas cross-fitted so no match is scored by a
 * beta that saw it):
 *
 *   Dixon-Coles alone                     logloss 1.0350
 *   + absolute XI quality gap             logloss 1.0450   WORSE — betas flip sign
 *   + XI vs that club's recent norm       logloss 1.0347   +0.0003, betas +0.53/+0.54
 *
 * So the disruption signal is real — the same positive sign in both folds and
 * across four different encodings — but it is worth almost nothing. The reason
 * the absolute gap fails is that Dixon-Coles already infers team strength from
 * results, and results beat a video-game rating as soon as you have any. Only
 * the deviation from a club's own norm is new information.
 *
 * It is included because it is honest information to show — you can see who is
 * missing — not because it moves the number much. BETA is deliberately the
 * measured value and should not be talked up.
 */
(function (global) {
  'use strict';

  const SRC = 'data/epl-players.json';
  const SOFT = 6.0;    // softmax temperature; must match build_players.py
  const BETA = 0.53;   // measured, per 10 rating points of deviation

  let DATA = null;
  let loading = null;
  const memo = new Map();

  function ready() {
    if (loading) return loading;
    loading = fetch(SRC, { cache: 'force-cache' })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { DATA = d; return d; })
      .catch(() => null);          // page must survive without player data
    return loading;
  }

  /**
   * Normalise a name for matching. ESPN and EA FC disagree constantly:
   * accents, and Iberian double surnames especially ("Ezri Konsa Ngoyo" in EA
   * FC vs ESPN's "Ezri Konsa"), which is why matching is on the SET of
   * surname tokens rather than the last one.
   */
  function norm(s) {
    return String(s || '')
      .replace(/ß/g, 'ss').replace(/[Øø]/g, 'o').replace(/[đð]/g, 'd')
      .normalize('NFKD').replace(/[̀-ͯ]/g, '')
      .toLowerCase().replace(/[^a-z ]/g, ' ')
      .split(/\s+/).filter(Boolean);
  }

  function stripSuffix(n) {
    const m = String(n || '').trim().match(/^(.*?)\s+(?:FC|AFC)$/i);
    return m ? m[1] : String(n || '').trim();
  }

  function rate(club, disp) {
    if (!DATA) return null;
    const c = stripSuffix(club);
    const key = c + '|' + disp;
    if (memo.has(key)) return memo.get(key);

    const d = norm(disp);
    let val = null;
    if (d.length) {
      const full = d.join(' ');
      const dsur = new Set(d.length > 1 ? d.slice(1) : d);
      const dini = d[0][0];
      const clubPool = DATA.players.filter(p => p.c === c);
      for (const scope of [clubPool, DATA.players]) {
        const exact = scope.filter(p => p.f === full);
        if (exact.length === 1) { val = exact[0].o; break; }
        const cand = scope.filter(p =>
          p.s.some(s => dsur.has(s)) && (!p.i.length || p.i.includes(dini)));
        if (cand.length === 1) { val = cand[0].o; break; }
        // Within a single club an ambiguous surname is nearly always the
        // better-known player; league-wide it is a coin flip, so give up there.
        if (cand.length > 1 && scope !== DATA.players) {
          val = Math.max(...cand.map(p => p.o)); break;
        }
      }
    }
    memo.set(key, val);
    return val;
  }

  /**
   * Softmax-mean strength of a starting XI.
   *
   * A plain mean buries a missing star: drop a 90 for a 72 and eleven-player
   * average moves 1.6 points. Weighting the top of the XI more heavily tracks
   * the intuition better, and gave the steadiest cross-fitted betas of the
   * encodings tried.
   */
  function xiStrength(vals) {
    if (!vals.length) return null;
    const s = vals.reduce((t, v) => t + Math.exp(v / SOFT), 0) / vals.length;
    return SOFT * Math.log(s);
  }

  /**
   * Rate a starting XI.
   *
   * Always returns the roster, even when the club is absent from the ratings
   * file — a promoted side sits in the Championship slice of a snapshot taken
   * before it came up, and that is precisely the club worth looking at. In
   * that case `strength` is null and the names still come back unrated, so
   * callers show the team sheet and simply omit the numbers.
   */
  function xi(club, names) {
    if (!DATA || !names || !names.length) return null;
    const c = stripSuffix(club);
    const fb = DATA.clubMean[c];
    const rows = names.map(n => ({ name: n, ovr: rate(c, n) }));
    const vals = rows.map(r => (r.ovr == null ? fb : r.ovr)).filter(v => v != null);
    const rated = rows.filter(r => r.ovr != null).sort((a, b) => b.ovr - a.ovr);
    const enough = vals.length >= names.length * 0.6;
    return {
      strength: enough ? xiStrength(vals) : null,
      mean: enough ? vals.reduce((t, v) => t + v, 0) / vals.length : null,
      rows,
      rated,
      unrated: rows.filter(r => r.ovr == null).length,
      best: rated[0] || null,
      worst: rated[rated.length - 1] || null
    };
  }

  /** Today's XI vs this club's recent-norm XI, in rating points. */
  function delta(club, names) {
    const c = stripSuffix(club);
    const info = xi(c, names);
    const base = DATA && DATA.clubBaseline ? DATA.clubBaseline[c] : null;
    if (!info || info.strength == null || base == null) return null;
    return info.strength - base;
  }

  /**
   * Nudge win/draw/loss by the two lineup deltas.
   *
   * Applied in log-odds on the home:away ratio, leaving the draw alone — the
   * same form the beta was fitted under. Feature units are 10 rating points.
   */
  function adjust(probs, dh, da) {
    if (dh == null || da == null) return probs;
    const feat = ((dh || 0) - (da || 0)) / 10;
    if (!isFinite(feat) || feat === 0) return probs;
    const h = probs.home, d = probs.draw, a = probs.away;
    const z = Math.log(Math.max(h, 1e-15) / Math.max(a, 1e-15)) + BETA * feat;
    const r = Math.exp(z), rest = h + a;
    const nh = rest * r / (1 + r);
    return { home: nh, draw: d, away: rest - nh };
  }

  function snapshot() { return DATA && DATA.snapshot; }

  global.Players = { ready, rate, xi, delta, adjust, snapshot, BETA };
})(window);
