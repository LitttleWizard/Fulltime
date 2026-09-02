/**
 * Monte Carlo season simulation.
 *
 * Simulating a single match would be pointless — Dixon-Coles enumerates its
 * scoreline grid exactly and Elo gives a closed-form probability, so sampling
 * from them just reproduces a number the page already has, plus noise. A SEASON
 * is different: the quantity of interest (where a team finishes) depends on
 * every remaining fixture jointly, and there is no closed form for that.
 *
 *   SeasonSim.run({ teams, standings, fixtures, sample, sims, sortKey })
 *
 *     teams      [teamId]
 *     standings  { team: { pts, w, d, l, gf, ga, played } }  state so far
 *     fixtures   [{ home, away }]                            still to play
 *     sample     (home, away) => { hg, ag }   one sampled result
 *     sortKey    (row) => [primary, secondary, …]  higher is better
 *
 *   -> { team: { posDist: [...], avgPos, avgPts, top: n } }
 *
 * Ratings are held fixed across a simulated season. They would drift in
 * reality, but drift is roughly symmetric noise here and updating them inside
 * every run multiplies the cost for an effect much smaller than the sampling
 * spread the simulation is measuring.
 */
(function (global) {
  'use strict';

  /** Poisson sample by inversion — fine for the small means football produces. */
  function poisson(lambda) {
    if (!(lambda > 0)) return 0;
    if (lambda > 30) return Math.round(lambda + Math.sqrt(lambda) * gauss());
    const L = Math.exp(-lambda);
    let k = 0, p = 1;
    do { k++; p *= Math.random(); } while (p > L);
    return k - 1;
  }

  let spare = null;
  function gauss() {
    if (spare !== null) { const s = spare; spare = null; return s; }
    let u, v, s;
    do { u = Math.random() * 2 - 1; v = Math.random() * 2 - 1; s = u * u + v * v; }
    while (s === 0 || s >= 1);
    const m = Math.sqrt(-2 * Math.log(s) / s);
    spare = v * m;
    return u * m;
  }

  function blankRow(team, seed) {
    const s = (seed && seed[team]) || {};
    return {
      team: team,
      pts: s.pts || 0, w: s.w || 0, d: s.d || 0, l: s.l || 0,
      gf: s.gf || 0, ga: s.ga || 0, played: s.played || 0
    };
  }

  function run(opts) {
    const teams = opts.teams;
    const fixtures = opts.fixtures || [];
    const sims = opts.sims || 5000;
    const sample = opts.sample;
    const sortKey = opts.sortKey;
    const pointsFor = opts.pointsFor || function (gf, ga) {
      return gf > ga ? 3 : gf === ga ? 1 : 0;
    };

    const n = teams.length;
    const idx = Object.create(null);
    teams.forEach(function (t, i) { idx[t] = i; });

    // posDist[i][p] = how often team i finished in position p
    const posDist = teams.map(function () { return new Array(n).fill(0); });
    const ptsTotal = new Array(n).fill(0);

    for (let s = 0; s < sims; s++) {
      const rows = teams.map(function (t) { return blankRow(t, opts.standings); });

      for (let f = 0; f < fixtures.length; f++) {
        const fx = fixtures[f];
        const hi = idx[fx.home], ai = idx[fx.away];
        if (hi === undefined || ai === undefined) continue;
        const r = sample(fx.home, fx.away);
        const hg = r.hg, ag = r.ag;
        const H = rows[hi], A = rows[ai];
        H.gf += hg; H.ga += ag; A.gf += ag; A.ga += hg;
        H.played++; A.played++;
        H.pts += pointsFor(hg, ag);
        A.pts += pointsFor(ag, hg);
        if (hg > ag) { H.w++; A.l++; }
        else if (hg < ag) { A.w++; H.l++; }
        else { H.d++; A.d++; }
      }

      rows.sort(function (a, b) {
        const ka = sortKey(a), kb = sortKey(b);
        for (let i = 0; i < ka.length; i++) {
          if (kb[i] !== ka[i]) return kb[i] - ka[i];
        }
        return Math.random() - 0.5;          // unresolved ties broken at random
      });

      for (let p = 0; p < rows.length; p++) {
        const i = idx[rows[p].team];
        posDist[i][p]++;
        ptsTotal[i] += rows[p].pts;
      }
    }

    const out = Object.create(null);
    teams.forEach(function (t, i) {
      const dist = posDist[i].map(function (c) { return c / sims; });
      let avgPos = 0;
      dist.forEach(function (p, k) { avgPos += p * (k + 1); });
      out[t] = { posDist: dist, avgPos: avgPos, avgPts: ptsTotal[i] / sims };
    });
    return out;
  }

  /** Probability a team finishes in positions [from, to], 1-indexed inclusive. */
  function inRange(entry, from, to) {
    let s = 0;
    for (let p = from - 1; p <= to - 1 && p < entry.posDist.length; p++) s += entry.posDist[p];
    return s;
  }

  global.SeasonSim = { run: run, poisson: poisson, gauss: gauss, inRange: inRange };
})(window);
