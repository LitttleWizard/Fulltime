/**
 * Shared rating-trend chart for the Fulltime terminal (EPL + NFL tabs).
 *
 * Interactive: a range selector (10/20/40/All) and a crosshair that snaps to
 * the nearest game.
 *
 * Informative: the tooltip explains *why* the line moved — opponent, venue,
 * score, result and the rating change that game caused — rather than repeating
 * the number already on the axis. The band between the two lines is shaded
 * because that gap is what actually drives the prediction, a baseline marks the
 * 1500 league average, per-game markers show W/D/L by fill shape (colour is
 * already carrying team identity), and a footer sums up the visible window.
 *
 * Expects each ratingTrail point to carry match context:
 *   { date, rating, delta, opp, venue, gf, ga, result }
 */
(function (global) {
  'use strict';

  function niceStep(range) {
    const raw = range / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const norm = raw / mag;
    return (norm < 1.5 ? 1 : norm < 3.5 ? 2.5 : norm < 7.5 ? 5 : 10) * mag;
  }
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function TrendChart(opts) {
    this.box = opts.box;
    this.legend = opts.legend;
    this.foot = opts.foot;
    this.title = opts.title;
    this.rangeWrap = opts.rangeWrap;
    this.label = opts.label || (t => t);      // team code -> display name
    this.unit = opts.unit || 'Matches';
    this.baseline = opts.baseline == null ? 1500 : opts.baseline;
    this.range = opts.defaultRange || 20;     // 0 = all
    this.state = null;

    if (this.rangeWrap) {
      this.rangeWrap.addEventListener('click', e => {
        const btn = e.target.closest('.range-btn');
        if (!btn) return;
        this.range = Number(btn.getAttribute('data-n'));
        this.rangeWrap.querySelectorAll('.range-btn')
          .forEach(b => b.classList.toggle('is-on', b === btn));
        if (this.state) this.render(this.state.trail, this.state.home, this.state.away);
      });
    }
  }

  TrendChart.prototype.render = function (ratingTrail, home, away) {
    this.state = { trail: ratingTrail, home, away };
    const box = this.box;
    const cut = a => (this.range > 0 ? a.slice(-this.range) : a.slice());
    const th = cut(ratingTrail[home] || []);
    const ta = cut(ratingTrail[away] || []);

    if (this.title) {
      this.title.textContent = this.range > 0
        ? `Elo Rating — Last ${this.range} ${this.unit}`
        : 'Elo Rating — Full History';
    }
    if (this.legend) {
      this.legend.innerHTML =
        `<div class="legend-item"><span class="legend-swatch" style="background:var(--series-home)"></span>${esc(this.label(home))}</div>` +
        `<div class="legend-item"><span class="legend-swatch" style="background:var(--series-away)"></span>${esc(this.label(away))}</div>`;
    }
    if (this.foot) {
      const move = (arr, name) => {
        if (arr.length < 2) return `${esc(name)} —`;
        const d = arr[arr.length - 1].rating - arr[0].rating;
        const cls = d > 0.5 ? 'up' : d < -0.5 ? 'down' : '';
        const c = { W: 0, D: 0, L: 0 };
        arr.forEach(p => { if (p.result in c) c[p.result]++; });
        const rec = c.D ? `${c.W}W ${c.D}D ${c.L}L` : `${c.W}-${c.L}`;
        return `${esc(name)} <span class="${cls}">${d >= 0 ? '+' : ''}${Math.round(d)}</span> · ${rec}`;
      };
      this.foot.innerHTML = `<span>${move(th, this.label(home))}</span><span>${move(ta, this.label(away))}</span>`;
    }

    if (th.length < 2 && ta.length < 2) {
      box.innerHTML = '<div style="font-size:12px;color:var(--muted);padding:12px 0;">Not enough history yet for a trend line.</div>';
      return;
    }

    const m = box.getBoundingClientRect();
    const W = Math.max(340, Math.round(m.width) || 560);
    const H = Math.max(220, Math.round(m.height) || 300);
    const PAD_L = 44, PAD_R = 46, PAD_T = 16, PAD_B = 40;   // PAD_B leaves room for the x axis
    const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;

    const all = th.concat(ta).map(p => p.rating);
    let lo = Math.min(...all), hi = Math.max(...all);
    if (this.baseline != null && all.length) {           // keep the mean in view
      lo = Math.min(lo, this.baseline); hi = Math.max(hi, this.baseline);
    }
    if (lo === hi) { lo -= 10; hi += 10; }
    const step = niceStep(hi - lo);
    lo = Math.floor(lo / step) * step - step * 0.4;
    hi = Math.ceil(hi / step) * step + step * 0.4;

    const maxLen = Math.max(th.length, ta.length, 2);
    const x = i => PAD_L + (i / (maxLen - 1)) * plotW;
    const y = r => PAD_T + plotH - ((r - lo) / (hi - lo)) * plotH;
    const hOff = maxLen - th.length, aOff = maxLen - ta.length;
    const path = (s, off) => s.map((p, i) =>
      `${i === 0 ? 'M' : 'L'} ${x(i + off).toFixed(1)} ${y(p.rating).toFixed(1)}`).join(' ');

    // gridlines + y axis
    const grid = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      const gy = y(v);
      grid.push(`<line class="trend-gridline" x1="${PAD_L}" x2="${W - PAD_R}" y1="${gy.toFixed(1)}" y2="${gy.toFixed(1)}"/>`);
      grid.push(`<text class="trend-axis-label" x="${PAD_L - 6}" y="${(gy + 3).toFixed(1)}" text-anchor="end">${Math.round(v)}</text>`);
    }

    // ── X axis: dated ticks across the window ──────────────────────────────
    // Both series are right-aligned to the most recent game, so index -> date
    // comes from whichever series covers that slot.
    const dateAt = i => {
      const p = th[i - hOff] || ta[i - aOff];
      return p && p.date ? p.date : null;
    };
    const fmtTick = d => {
      const parts = String(d).split('-');
      if (parts.length < 3) return d;
      const mon = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+parts[1] - 1] || '';
      return `${mon} ${+parts[2]}`;
    };
    const axis = [
      `<line class="trend-axis" x1="${PAD_L}" x2="${W - PAD_R}" y1="${(PAD_T + plotH).toFixed(1)}" y2="${(PAD_T + plotH).toFixed(1)}"/>`
    ];
    // aim for a tick roughly every 90px, and always label both ends
    const want = clamp(Math.floor(plotW / 90), 2, 7);
    const stride = Math.max(1, Math.round((maxLen - 1) / (want - 1)));
    const ticks = new Set();
    for (let i = 0; i < maxLen; i += stride) ticks.add(i);
    ticks.add(maxLen - 1);
    let lastYear = null;
    Array.from(ticks).sort((a, b) => a - b).forEach(i => {
      const d = dateAt(i);
      if (!d) return;
      const tx = x(i);
      const anchor = i === 0 ? 'start' : (i === maxLen - 1 ? 'end' : 'middle');
      axis.push(`<line class="trend-tick" x1="${tx.toFixed(1)}" x2="${tx.toFixed(1)}" y1="${(PAD_T + plotH).toFixed(1)}" y2="${(PAD_T + plotH + 4).toFixed(1)}"/>`);
      axis.push(`<text class="trend-axis-label" x="${tx.toFixed(1)}" y="${(PAD_T + plotH + 15).toFixed(1)}" text-anchor="${anchor}">${fmtTick(d)}</text>`);
      // add the year once, and again whenever it rolls over
      const yr = String(d).slice(0, 4);
      if (yr !== lastYear) {
        axis.push(`<text class="trend-axis-year" x="${tx.toFixed(1)}" y="${(PAD_T + plotH + 25).toFixed(1)}" text-anchor="${anchor}">${yr}</text>`);
        lastYear = yr;
      }
    });

    // league-average baseline
    let baseEls = '';
    if (this.baseline != null && this.baseline > lo && this.baseline < hi) {
      const by = y(this.baseline);
      baseEls =
        `<line class="trend-baseline" x1="${PAD_L}" x2="${W - PAD_R}" y1="${by.toFixed(1)}" y2="${by.toFixed(1)}"/>` +
        `<text class="trend-baseline-label" x="${W - PAD_R + 4}" y="${(by + 3).toFixed(1)}">avg</text>`;
    }

    // shaded gap band over the overlapping stretch — the gap drives the prediction
    let gapEl = '';
    const start = Math.max(hOff, aOff);
    if (th.length >= 2 && ta.length >= 2 && maxLen - start >= 2) {
      const top = [], bot = [];
      for (let i = start; i < maxLen; i++) {
        top.push(`${x(i).toFixed(1)} ${y(th[i - hOff].rating).toFixed(1)}`);
        bot.push(`${x(i).toFixed(1)} ${y(ta[i - aOff].rating).toFixed(1)}`);
      }
      bot.reverse();
      const lead = th[th.length - 1].rating >= ta[ta.length - 1].rating
        ? 'var(--series-home)' : 'var(--series-away)';
      gapEl = `<path class="trend-gap" fill="${lead}" d="M ${top.join(' L ')} L ${bot.join(' L ')} Z"/>`;
    }

    // per-game markers: fill encodes result, colour stays team identity
    const markers = [];
    const addMarks = (s, off, colour) => {
      if (s.length > 45) return;
      s.forEach((p, i) => {
        const cx = x(i + off).toFixed(1), cy = y(p.rating).toFixed(1);
        if (p.result === 'W') markers.push(`<circle class="trend-marker" r="3.4" cx="${cx}" cy="${cy}" fill="${colour}" stroke="var(--bg)"/>`);
        else if (p.result === 'L') markers.push(`<circle class="trend-marker" r="3.2" cx="${cx}" cy="${cy}" fill="var(--bg)" stroke="${colour}"/>`);
        else markers.push(`<circle class="trend-marker" r="1.9" cx="${cx}" cy="${cy}" fill="${colour}" stroke="none"/>`);
      });
    };
    addMarks(th, hOff, 'var(--series-home)');
    addMarks(ta, aOff, 'var(--series-away)');

    const lastH = th[th.length - 1], lastA = ta[ta.length - 1];
    const ends = [];
    if (lastH) ends.push(
      `<circle class="trend-end-dot" r="4.5" cx="${x(maxLen - 1).toFixed(1)}" cy="${y(lastH.rating).toFixed(1)}" fill="var(--series-home)"/>` +
      `<text class="trend-end-label" x="${(x(maxLen - 1) + 8).toFixed(1)}" y="${(y(lastH.rating) + 3).toFixed(1)}" fill="var(--series-home)">${Math.round(lastH.rating)}</text>`);
    if (lastA) ends.push(
      `<circle class="trend-end-dot" r="4.5" cx="${x(maxLen - 1).toFixed(1)}" cy="${y(lastA.rating).toFixed(1)}" fill="var(--series-away)"/>` +
      `<text class="trend-end-label" x="${(x(maxLen - 1) + 8).toFixed(1)}" y="${(y(lastA.rating) + 3).toFixed(1)}" fill="var(--series-away)">${Math.round(lastA.rating)}</text>`);

    box.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
        ${grid.join('')}${axis.join('')}${baseEls}${gapEl}
        ${th.length >= 2 ? `<path class="trend-line" d="${path(th, hOff)}" stroke="var(--series-home)"/>` : ''}
        ${ta.length >= 2 ? `<path class="trend-line" d="${path(ta, aOff)}" stroke="var(--series-away)"/>` : ''}
        ${markers.join('')}${ends.join('')}
        <line class="trend-crosshair" x1="0" x2="0" y1="${PAD_T}" y2="${PAD_T + plotH}"/>
        <rect class="trend-hit" x="${PAD_L}" y="${PAD_T}" width="${plotW}" height="${plotH}"/>
      </svg>
      <div class="trend-tooltip"></div>`;

    const svg = box.querySelector('svg');
    const hit = box.querySelector('.trend-hit');
    const cross = box.querySelector('.trend-crosshair');
    const tip = box.querySelector('.trend-tooltip');
    const label = this.label;

    const show = clientX => {
      const r = svg.getBoundingClientRect();
      const scale = W / r.width;
      let idx = Math.round(((clientX - r.left) * scale - PAD_L) / plotW * (maxLen - 1));
      idx = clamp(idx, 0, maxLen - 1);
      const cx = x(idx);
      cross.setAttribute('x1', cx.toFixed(1));
      cross.setAttribute('x2', cx.toFixed(1));
      cross.style.opacity = '1';

      const hp = th[idx - hOff], ap = ta[idx - aOff];
      if (!hp && !ap) { tip.style.opacity = '0'; return; }

      const row = (p, name, colour) => {
        if (!p) return '';
        let out = `<div class="tt-row"><span class="tt-key" style="background:${colour}"></span>${esc(label(name))}`;
        const d = p.delta == null ? null : Math.round(p.delta);
        out += `<span class="tt-val">${Math.round(p.rating)}`;
        if (d != null) {
          const cls = d > 0 ? 'up' : d < 0 ? 'down' : 'flat';
          out += `<span class="tt-delta ${cls}">${d >= 0 ? '+' : ''}${d}</span>`;
        }
        out += '</span></div>';
        if (p.opp) {
          out += `<div class="tt-sub"><span class="tt-res ${p.result || ''}">${p.result || ''}</span> ` +
                 `${p.venue === 'home' ? 'vs' : '@'} ${esc(label(p.opp))} &nbsp;${p.gf}–${p.ga}</div>`;
        }
        return out;
      };

      let html = `<div class="tt-date">${esc((hp && hp.date) || (ap && ap.date) || '')}</div>` +
                 row(hp, home, 'var(--series-home)') + row(ap, away, 'var(--series-away)');
      if (hp && ap) {
        const g = Math.round(hp.rating - ap.rating);
        html += `<div class="tt-gap">Gap ${g >= 0 ? '+' : ''}${g} → ${esc(label(g >= 0 ? home : away))}</div>`;
      }
      tip.innerHTML = html;
      tip.style.opacity = '1';
      let left = (cx / scale) + 12;
      if (left + 215 > box.getBoundingClientRect().width) left = (cx / scale) - 227;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = '4px';
    };

    hit.addEventListener('pointermove', e => show(e.clientX));
    hit.addEventListener('pointerleave', () => {
      cross.style.opacity = '0'; tip.style.opacity = '0';
    });
  };

  global.TrendChart = TrendChart;
})(window);
