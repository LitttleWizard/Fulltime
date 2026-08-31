/**
 * Live scores for the Fulltime terminal.
 *
 * Source: ESPN's public scoreboard endpoint. No key, and it sends
 * `access-control-allow-origin: *` on the first hop, so the browser can call it
 * directly. It is undocumented and unsupported, so every failure path here is
 * silent — if it breaks, the page just shows no live badge rather than erroring.
 *
 *   Live.fetch('epl' | 'nfl')  ->  [{ home, away, hs, as, state, clock, period }]
 *      state: 'pre' | 'in' | 'post'
 *      home/away are already normalised to the keys each tab's model uses.
 *
 *   Live.winProb(lh, la, hs, as, minsLeft)  ->  {home, draw, away}
 *      In-play win probability for football, from the Dixon-Coles expected
 *      goals. Remaining goals over the remaining time are Poisson at a
 *      pro-rated rate, so the pre-match model extends to in-play without any
 *      new data. Caveats in the note on winProb below.
 */
(function (global) {
  'use strict';

  const ESPN = 'https://site.api.espn.com/apis/site/v2/sports';
  const PATHS = { epl: 'soccer/eng.1', nfl: 'football/nfl' };

  // ESPN's NFL abbreviations differ from nflverse's for exactly two clubs.
  const NFL_FIX = { LAR: 'LA', WSH: 'WAS' };
  // EPL: ESPN's displayName already matches our canonical names once the
  // trailing FC/AFC is stripped, so only the odd exception needs listing.
  const EPL_FIX = {};

  function stripSuffix(n) {
    const m = String(n || '').trim().match(/^(.*?)\s+(?:FC|AFC)$/i);
    return m ? m[1] : String(n || '').trim();
  }

  async function fetchLive(league) {
    const path = PATHS[league];
    if (!path) return [];
    try {
      const r = await fetch(`${ESPN}/${path}/scoreboard`, { cache: 'no-store' });
      if (!r.ok) return [];
      const d = await r.json();
      const out = [];
      for (const ev of (d.events || [])) {
        const c = (ev.competitions || [])[0];
        if (!c) continue;
        const st = (c.status || {});
        const type = st.type || {};
        let home = null, away = null, hs = null, as = null;
        for (const t of (c.competitors || [])) {
          const raw = league === 'nfl'
            ? (t.team && t.team.abbreviation)
            : stripSuffix(t.team && t.team.displayName);
          const name = league === 'nfl'
            ? (NFL_FIX[raw] || raw)
            : (EPL_FIX[raw] || raw);
          const score = t.score == null || t.score === '' ? null : parseInt(t.score, 10);
          if (t.homeAway === 'home') { home = name; hs = score; }
          else { away = name; as = score; }
        }
        if (!home || !away) continue;
        out.push({
          home, away, hs, as,
          state: type.state || 'pre',            // pre | in | post
          detail: type.shortDetail || '',
          clock: st.displayClock || '',
          period: st.period || 0,
          date: (ev.date || '').slice(0, 10)
        });
      }
      return out;
    } catch (e) {
      return [];                                  // never let live data break the page
    }
  }

  /**
   * In-play win probability for football.
   *
   * Given the Dixon-Coles expected goals for the full match and how much time
   * is left, the goals still to come are Poisson at the pro-rated rate. Combine
   * with the current score and sum the grid.
   *
   * Deliberately simple, and it is worth knowing what it ignores: teams behave
   * differently when leading or chasing, red cards change everything, and
   * stoppage time is only approximated. It is a sound baseline, not a betting model.
   */
  function winProb(lh, la, hs, as, minsLeft) {
    const f = Math.max(0, Math.min(1, minsLeft / 90));
    const rh = Math.max(lh * f, 1e-9);
    const ra = Math.max(la * f, 1e-9);
    const MAX = 10;
    const pois = lam => {
      const out = []; let fact = 1;
      for (let k = 0; k <= MAX; k++) {
        if (k > 0) fact *= k;
        out.push(Math.exp(-lam) * Math.pow(lam, k) / fact);
      }
      return out;
    };
    const ph = pois(rh), pa = pois(ra);
    let H = 0, D = 0, A = 0;
    for (let x = 0; x <= MAX; x++) {
      for (let y = 0; y <= MAX; y++) {
        const p = ph[x] * pa[y];
        const fh = hs + x, fa = as + y;
        if (fh > fa) H += p; else if (fh === fa) D += p; else A += p;
      }
    }
    const tot = H + D + A || 1;
    return { home: H / tot, draw: D / tot, away: A / tot };
  }

  /** Minutes remaining in a football match, from ESPN's clock. */
  function minsLeft(ev) {
    if (ev.state === 'post') return 0;
    if (ev.state === 'pre') return 90;
    const m = /(\d+)/.exec(ev.clock || ev.detail || '');
    const elapsed = m ? parseInt(m[1], 10) : 0;
    return Math.max(0, 90 - Math.min(elapsed, 90));
  }

  global.Live = { fetch: fetchLive, winProb, minsLeft };
})(window);
