/**
 * Dixon-Coles goals model — shared by the EPL tab and the prediction log.
 *
 * Each club gets an attack and a defence strength; goals are Poisson, with
 * Dixon-Coles' correction for low scores that plain Poisson gets wrong. Fitted
 * by weighted maximum likelihood with exponential time decay, in the browser.
 *
 * Exposes: fitDixonColes(matches, nowDay) -> model
 *          dcPredict(model, home, away)   -> {homeWin, draw, awayWin, lh, la, scorelines}
 */
(function (global) {
  'use strict';

  // ── Dixon-Coles ────────────────────────────────────────────────────────
  // Each team gets an attack and a defence strength; goals are Poisson:
  //   home ~ Poisson(exp(atk[H] - def[A] + gamma)),  away ~ Poisson(exp(atk[A] - def[H]))
  // plus Dixon-Coles' correction for low scores, which plain Poisson gets wrong.
  // Fitted by weighted maximum likelihood with exponential time decay.
  const DC_HALF_LIFE = 200, DC_HISTORY_DAYS = 1000, DC_ITERS = 320, DC_MAX_GOALS = 8;

  function dcTau(x, y, lh, la, rho) {
    if (x === 0 && y === 0) return 1 - lh * la * rho;
    if (x === 0 && y === 1) return 1 + lh * rho;
    if (x === 1 && y === 0) return 1 + la * rho;
    if (x === 1 && y === 1) return 1 - rho;
    return 1;
  }

  function fitDixonColes(matches, nowDay) {
    const decay = Math.log(2) / DC_HALF_LIFE;
    const data = [];
    for (const m of matches) {
      const age = nowDay - m.day;
      if (age > DC_HISTORY_DAYS) continue;
      data.push({ w: Math.exp(-decay * age), h: m.home, a: m.away, hg: m.hg, ag: m.ag });
    }
    const atk = Object.create(null), dfn = Object.create(null);
    const teams = [];
    for (const d of data) {
      for (const t of [d.h, d.a]) {
        if (!(t in atk)) { atk[t] = 0; dfn[t] = 0; teams.push(t); }
      }
    }
    let gamma = 0.25, rho = -0.05;
    if (!data.length || !teams.length) return { atk, dfn, gamma, rho };

    const n = data.length;
    for (let it = 0; it < DC_ITERS; it++) {
      const gAtk = Object.create(null), gDfn = Object.create(null);
      for (const t of teams) { gAtk[t] = 0; gDfn[t] = 0; }
      let gGam = 0;
      for (const d of data) {
        const lh = Math.min(Math.exp(atk[d.h] - dfn[d.a] + gamma), 8);
        const la = Math.min(Math.exp(atk[d.a] - dfn[d.h]), 8);
        const rh = d.w * (d.hg - lh), ra = d.w * (d.ag - la);
        gAtk[d.h] += rh; gDfn[d.a] -= rh;
        gAtk[d.a] += ra; gDfn[d.h] -= ra;
        gGam += rh;
      }
      const step = 0.5 / n;
      for (const t of teams) { atk[t] += step * gAtk[t]; dfn[t] += step * gDfn[t]; }
      gamma += step * gGam;
      // identifiability: centre both scales
      let ma = 0, md = 0;
      for (const t of teams) { ma += atk[t]; md += dfn[t]; }
      ma /= teams.length; md /= teams.length;
      for (const t of teams) { atk[t] -= ma; dfn[t] -= md; }
    }

    // line-search rho on the low-score cells it actually affects
    let best = rho, bestLL = -Infinity;
    for (let c = -0.18; c <= 0.04; c += 0.02) {
      let ll = 0, ok = true;
      for (const d of data) {
        if (d.hg > 1 || d.ag > 1) continue;
        const lh = Math.min(Math.exp(atk[d.h] - dfn[d.a] + gamma), 8);
        const la = Math.min(Math.exp(atk[d.a] - dfn[d.h]), 8);
        const t = dcTau(d.hg, d.ag, lh, la, c);
        if (t <= 0) { ok = false; break; }
        ll += d.w * Math.log(t);
      }
      if (ok && ll > bestLL) { bestLL = ll; best = c; }
    }
    return { atk, dfn, gamma, rho: best };
  }

  function dcLambdas(dc, home, away) {
    const ah = dc.atk[home] ?? 0, dh = dc.dfn[home] ?? 0;
    const aa = dc.atk[away] ?? 0, da = dc.dfn[away] ?? 0;
    return [Math.min(Math.exp(ah - da + dc.gamma), 8), Math.min(Math.exp(aa - dh), 8)];
  }

  // Full scoreline distribution -> outcome probabilities + likeliest scores
  function dcPredict(dc, home, away) {
    const [lh, la] = dcLambdas(dc, home, away);
    const pois = (lam) => {
      const out = []; let f = 1;
      for (let k = 0; k <= DC_MAX_GOALS; k++) {
        if (k > 0) f *= k;
        out.push(Math.exp(-lam) * Math.pow(lam, k) / f);
      }
      return out;
    };
    const ph = pois(lh), pa = pois(la);
    let H = 0, D = 0, A = 0;
    const grid = [];
    for (let x = 0; x <= DC_MAX_GOALS; x++) {
      for (let y = 0; y <= DC_MAX_GOALS; y++) {
        const p = Math.max(ph[x] * pa[y] * dcTau(x, y, lh, la, dc.rho), 0);
        grid.push({ x, y, p });
        if (x > y) H += p; else if (x === y) D += p; else A += p;
      }
    }
    const tot = H + D + A || 1;
    grid.forEach(g => { g.p /= tot; });
    grid.sort((a, b) => b.p - a.p);
    return { homeWin: H / tot, draw: D / tot, awayWin: A / tot, lh, la, scorelines: grid.slice(0, 5) };
  }


  global.DixonColes = { fit: fitDixonColes, predict: dcPredict, lambdas: dcLambdas, tau: dcTau };
})(window);
