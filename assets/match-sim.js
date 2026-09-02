/**
 * Match simulation.
 *
 * What this does and does not add, stated plainly because it matters:
 *
 *   It does NOT improve the win probability. Dixon-Coles enumerates its
 *   scoreline grid exactly and Elo gives a closed form, so sampling from those
 *   converges to the number the page already shows. The simulated win% is
 *   printed as a CHECK on the closed form, not as a better estimate.
 *
 *   It DOES expose everything else. The Elo tabs previously output a win
 *   probability and a single point estimate of the score — no distribution at
 *   all. Simulation gives the margin distribution, totals, the chance of a
 *   close finish, and cover probabilities against any line.
 *
 * Margins are sampled from EMPIRICAL residuals (data/sim-dist.json), not a
 * normal. NFL margins pile up on 3 and 7 because of how scoring works; a
 * Gaussian smears those away and misprices the most common results in the
 * sport. Football samples the Dixon-Coles grid directly, low-score correction
 * included, which is exact rather than approximate.
 *
 *   MatchSim.ready()                              -> Promise
 *   MatchSim.elo({league, spread, total, runs})   -> distribution
 *   MatchSim.football({lh, la, rho, runs})        -> distribution
 */
(function (global) {
  'use strict';

  let DIST = null, loading = null;

  function ready() {
    if (loading) return loading;
    loading = fetch('data/sim-dist.json')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { DIST = d; return d; })
      .catch(() => null);          // callers degrade to no simulation
    return loading;
  }

  const pick = arr => arr[(Math.random() * arr.length) | 0];

  function summarise(margins, totals, opts) {
    const runs = margins.length;
    let hw = 0, push = 0;
    const mBins = Object.create(null);
    for (let i = 0; i < runs; i++) {
      const m = margins[i];
      if (m > 0) hw++; else if (m === 0) push++;
      const b = Math.max(-40, Math.min(40, m));
      mBins[b] = (mBins[b] || 0) + 1;
    }
    totals.sort((a, b) => a - b);
    const q = p => totals[Math.min(totals.length - 1, Math.floor(p * totals.length))];
    const sorted = margins.slice().sort((a, b) => a - b);
    const mq = p => sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];

    return {
      runs,
      homeWin: hw / runs,
      awayWin: (runs - hw - push) / runs,
      push: push / runs,
      /** P(|margin| <= n) — how often this is a close game. */
      within: n => margins.reduce((c, m) => c + (Math.abs(m) <= n ? 1 : 0), 0) / runs,
      /** P(home margin > line): the cover probability against any spread. */
      cover: line => margins.reduce((c, m) => c + (m > line ? 1 : 0), 0) / runs,
      /** P(total > line). */
      over: line => totals.reduce((c, t) => c + (t > line ? 1 : 0), 0) / runs,
      marginBins: mBins,
      marginMedian: mq(0.5),
      margin10: mq(0.1), margin90: mq(0.9),
      totalMedian: q(0.5), total10: q(0.1), total90: q(0.9)
    };
  }

  /**
   * Elo leagues: margin from empirical residuals, total from its own.
   *
   * `targetWinProb` matters. Left to itself the margin view disagrees with the
   * logistic win probability by a point or two — they are different
   * parameterisations, and the Elo-to-points conversion is a fitted average,
   * not an identity. Showing 61% in one panel and 59% in another would be a
   * bug in the reader's eyes even if both are defensible. The win probability
   * is the quantity that has been validated (calibrated, 67% held-out), so the
   * margin distribution is shifted to agree with it rather than the reverse.
   */
  function elo(opts) {
    const d = DIST && DIST[opts.league];
    if (!d) return null;
    const runs = opts.runs || 20000;
    const mr = d.marginResid, tr = d.totalResid;

    let loc = opts.spread;
    if (opts.targetWinProb != null) {
      // P(loc + resid > 0) is monotone in loc, so bisect on it.
      const share = L => {
        let c = 0;
        for (let i = 0; i < mr.length; i++) if (L + mr[i] > 0) c++;
        return c / mr.length;
      };
      let lo = opts.spread - 30, hi = opts.spread + 30;
      for (let it = 0; it < 24; it++) {
        const mid = (lo + hi) / 2;
        if (share(mid) < opts.targetWinProb) lo = mid; else hi = mid;
      }
      loc = (lo + hi) / 2;
    }

    const margins = new Array(runs), totals = new Array(runs);
    for (let i = 0; i < runs; i++) {
      let m = Math.round(loc + pick(mr));
      if (m === 0) m = Math.random() < 0.5 ? 1 : -1;   // no draws in these sports
      margins[i] = m;
      totals[i] = Math.max(0, Math.round(opts.total + pick(tr)));
    }
    const out = summarise(margins, totals, opts);
    out.shift = loc - opts.spread;
    return out;
  }

  /**
   * Football: sample the Dixon-Coles grid itself rather than two independent
   * Poissons, so the low-score correction is respected.
   */
  function football(opts) {
    const runs = opts.runs || 20000;
    const MAX = 9;
    const rho = opts.rho || 0;
    const pois = lam => {
      const out = []; let f = 1;
      for (let k = 0; k <= MAX; k++) { if (k) f *= k; out.push(Math.exp(-lam) * Math.pow(lam, k) / f); }
      return out;
    };
    const ph = pois(opts.lh), pa = pois(opts.la);
    const cells = [], cum = [];
    let acc = 0;
    for (let x = 0; x <= MAX; x++) {
      for (let y = 0; y <= MAX; y++) {
        let p = ph[x] * pa[y];
        // Dixon-Coles low-score adjustment
        if (x === 0 && y === 0) p *= 1 - opts.lh * opts.la * rho;
        else if (x === 0 && y === 1) p *= 1 + opts.lh * rho;
        else if (x === 1 && y === 0) p *= 1 + opts.la * rho;
        else if (x === 1 && y === 1) p *= 1 - rho;
        p = Math.max(p, 0);
        acc += p;
        cells.push([x, y]);
        cum.push(acc);
      }
    }
    const margins = new Array(runs), totals = new Array(runs);
    const scores = Object.create(null);
    let btts = 0, over25 = 0, cleanH = 0;
    for (let i = 0; i < runs; i++) {
      const r = Math.random() * acc;
      let lo = 0, hi = cum.length - 1;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (cum[mid] < r) lo = mid + 1; else hi = mid; }
      const [x, y] = cells[lo];
      margins[i] = x - y;
      totals[i] = x + y;
      const k = x + '-' + y;
      scores[k] = (scores[k] || 0) + 1;
      if (x > 0 && y > 0) btts++;
      if (x + y > 2.5) over25++;
      if (y === 0) cleanH++;
    }
    const out = summarise(margins, totals, opts);
    out.scores = scores;
    out.btts = btts / runs;
    out.over25 = over25 / runs;
    out.cleanSheetHome = cleanH / runs;
    return out;
  }

  /**
   * P(home wins) implied by the margin distribution, rather than by the
   * logistic on the rating gap.
   *
   * These are two estimators of the same quantity and they disagree by a point
   * or so. For the NBA the margin view is measurably better on held-out games
   * (0.6083 -> 0.6075 log-loss, 66.7% -> 67.1%, bootstrap CI excluding zero),
   * so that tab uses this as its base. For the NFL the difference is inside
   * the noise, so that tab keeps the logistic. See
   * scripts/margin_vs_logistic.py — the disagreement was worth testing rather
   * than papering over.
   */
  function winProbFromMargin(league, spread) {
    const d = DIST && DIST[league];
    if (!d || !d.marginResid || !d.marginResid.length) return null;
    const a = d.marginResid;                 // sorted ascending
    // count residuals > -spread, i.e. outcomes where spread + resid > 0
    let lo = 0, hi = a.length;
    const target = -spread;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (a[mid] <= target) lo = mid + 1; else hi = mid; }
    const p = 1 - lo / a.length;
    return Math.min(Math.max(p, 0.005), 0.995);
  }

  function generated() { return DIST && DIST.generated; }

  global.MatchSim = { ready, elo, football, generated, winProbFromMargin };
})(window);
