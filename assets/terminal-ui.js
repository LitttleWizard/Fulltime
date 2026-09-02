/**
 * Rendering helpers shared by the league tabs.
 *
 * Deliberately small. These four were byte-identical copies across pages, so
 * sharing them changes nothing. `formPills`, `renderWatchlist` and
 * `h2hSummary` look duplicated but are NOT: football reports draws and counts
 * five meetings, the American sports count six and have no draw column, and
 * each tab labels teams differently. Forcing those together would change what
 * the pages render, so they stay local — a real difference is not duplication.
 *
 *   UI.esc(s)                        escape untrusted text bound for innerHTML
 *   UI.clamp(v, lo, hi)
 *   UI.recentStats(history, team, n) scoring / margin / wins over the last n
 *   UI.metricRow(label, away, home, dp)
 */
(function (global) {
  'use strict';

  var ENT = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ENT[c]; });
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function recentStats(history, team, n) {
    var h = (history[team] || []).slice(-n);
    if (!h.length) return null;
    return {
      pf: h.reduce(function (s, m) { return s + m.gf; }, 0) / h.length,
      pa: h.reduce(function (s, m) { return s + m.ga; }, 0) / h.length,
      margin: h.reduce(function (s, m) { return s + (m.gf - m.ga); }, 0) / h.length,
      wins: h.filter(function (m) { return m.result === 'W'; }).length,
      n: h.length
    };
  }

  function metricRow(label, away, home, dp) {
    var max = Math.max(away || 0, home || 0, 0.01) * 1.15;
    var fmt = function (v) { return v == null ? '—' : v.toFixed(dp); };
    var bar = function (v, side) {
      return '<div class="metric-bar-row">' +
             '<div class="metric-bar-track"><div class="metric-bar-fill ' + side +
             '" style="width:' + clamp(((v || 0) / max) * 100, 0, 100) + '%"></div></div>' +
             '<div class="metric-bar-val">' + fmt(v) + '</div>' +
             '</div>';
    };
    return '\n        <div class="metric-group">\n          <div class="metric-label">' +
           label + '</div>\n          ' + bar(away, 'away') + bar(home, 'home') +
           '\n        </div>';
  }

  global.UI = { esc: esc, clamp: clamp, recentStats: recentStats, metricRow: metricRow };
})(window);
