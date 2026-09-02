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
 *   Live.injuries(league)  ->  { teamDisplayName: [{ name, pos, status, ... }] }
 *      One league-wide request. Injury status is published days ahead, so
 *      unlike a football lineup it can inform a prediction.
 *
 *   Live.lastLineup(league, club)  ->  { names, date, opponent, formation }
 *      The last XI a club actually fielded — the stand-in for a fixture whose
 *      real lineup ESPN has not published yet.
 *
 *   Live.detail(league, eventId, rawHome)  ->  { goals, feed, lineups }
 *      One summary request yielding everything the match view needs: goal
 *      timings, the play-by-play feed (goals, cards, substitutions, injuries)
 *      and the starting XI once ESPN publishes it.
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
  const PATHS = { epl: 'soccer/eng.1', nfl: 'football/nfl', nba: 'basketball/nba' };

  // ESPN's NFL abbreviations differ from nflverse's for exactly two clubs.
  const NFL_FIX = { LAR: 'LA', WSH: 'WAS' };
  // NBA history is baked from this same ESPN feed, so the abbreviations already
  // agree and need no remapping.
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
        let abbrHome = null, abbrAway = null, rawHome = null, rawAway = null;
        for (const t of (c.competitors || [])) {
          const byAbbr = league === 'nfl' || league === 'nba';
          const raw = byAbbr
            ? (t.team && t.team.abbreviation)
            : stripSuffix(t.team && t.team.displayName);
          const name = league === 'nfl' ? (NFL_FIX[raw] || raw)
                     : league === 'nba' ? raw
                     : (EPL_FIX[raw] || raw);
          const score = t.score == null || t.score === '' ? null : parseInt(t.score, 10);
          const abbr = (t.team && t.team.abbreviation) || '';
          const disp = (t.team && t.team.displayName) || '';
          if (t.homeAway === 'home') { home = name; hs = score; abbrHome = abbr; rawHome = disp; }
          else { away = name; as = score; abbrAway = abbr; rawAway = disp; }
        }
        if (!home || !away) continue;
        out.push({
          id: ev.id, home, away, hs, as, abbrHome, abbrAway, rawHome, rawAway,
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

  /* ── match detail: goals, play-by-play, lineups ────────────────────────
   *
   * All three come from the same `summary` document, so they are fetched once
   * and split apart here rather than costing a request each.
   */

  async function summary(league, eventId) {
    const path = PATHS[league];
    if (!path || !eventId) return null;
    try {
      const r = await fetch(`${ESPN}/${path}/summary?event=${encodeURIComponent(eventId)}`,
                            { cache: 'no-store' });
      return r.ok ? await r.json() : null;
    } catch (e) {
      return null;
    }
  }

  /** Leading number of an ESPN clock string: "24'" and "45'+4'" both give 24. */
  function clockMin(e) {
    const m = /(\d+)/.exec((e.clock && e.clock.displayValue) || '');
    return m ? parseInt(m[1], 10) : null;
  }

  /**
   * Classify a keyEvent into the handful of kinds the feed renders.
   * ESPN's `type.text` is free-form ("Goal - Header", "Yellow Card"), so this
   * matches loosely and falls back to a neutral kind rather than dropping the
   * event.
   */
  function classify(e) {
    const t = ((e.type && e.type.text) || '').toLowerCase();
    const txt = (e.text || '').toLowerCase();
    if (e.scoringPlay || t.startsWith('goal')) {
      return t.includes('own') ? 'own-goal'
           : (t.includes('penalty') || txt.includes('penalty')) ? 'pen-goal' : 'goal';
    }
    if (t.includes('red card') || t.includes('second yellow')) return 'red';
    if (t.includes('yellow')) return 'yellow';
    if (t.includes('substitution')) {
      // ESPN spells injuries out in the substitution text itself; there is no
      // separate injury event to read.
      return txt.includes('injur') ? 'injury' : 'sub';
    }
    if (t.includes('penalty')) return 'pen-miss';
    if (t.includes('kickoff') || t.includes('halftime') || t.includes('half') ||
        t.includes('end regular')) return 'period';
    return 'note';
  }

  /**
   * Full detail for one match.
   *   goals   [{min, side}]                       — for the win-probability path
   *   feed    [{min, kind, side, text, players}]  — newest last
   *   lineups {home: [names], away: [names], formation: {...}} or null
   *
   * ESPN only populates rosters near kickoff, so `lineups` is null for a
   * fixture that is still days away — callers must handle that.
   */
  async function detail(league, eventId, rawHome) {
    const d = await summary(league, eventId);
    if (!d) return { goals: [], feed: [], lineups: null };

    const sideOf = e => {
      const team = (e.team && e.team.displayName) || '';
      return team && rawHome && team === rawHome ? 'home' : (team ? 'away' : null);
    };

    const goals = [], feed = [];
    for (const e of (d.keyEvents || [])) {
      const min = clockMin(e);
      const kind = classify(e);
      if (e.scoringPlay && min != null) {
        goals.push({ min: Math.min(90, min), side: sideOf(e) || 'away' });
      }
      feed.push({
        min, kind, side: sideOf(e),
        text: e.text || '',
        players: (e.participants || [])
          .map(p => (p.athlete && p.athlete.displayName) || '')
          .filter(Boolean)
      });
    }
    goals.sort((a, b) => a.min - b.min);
    feed.sort((a, b) => (a.min == null ? -1 : a.min) - (b.min == null ? -1 : b.min));

    let lineups = null;
    for (const t of (d.rosters || [])) {
      const side = t.homeAway === 'home' ? 'home' : 'away';
      const starters = (t.roster || [])
        .filter(p => p.starter)
        .map(p => (p.athlete && p.athlete.displayName) || '')
        .filter(Boolean);
      if (starters.length >= 10) {
        lineups = lineups || { home: [], away: [], formation: {} };
        lineups[side] = starters;
        lineups.formation[side] = t.formation || '';
      }
    }
    if (lineups && (!lineups.home.length || !lineups.away.length)) lineups = null;

    return { goals, feed, lineups };
  }

  /* ── Injuries ──────────────────────────────────────────────────────────
   *
   * ESPN publishes one league-wide injury document, so this is a single
   * request for every team rather than one per club. Unlike football lineups —
   * which only appear about an hour before kickoff — injury status is posted
   * days ahead, which is what makes it usable for a prediction rather than
   * only for a post-mortem.
   *
   * Keyed by the team's displayName, because that is what the feed gives; the
   * caller maps it onto whatever key its model uses.
   *
   *   -> { 'Boston Celtics': [{ name, pos, status, type, comment }] }
   */
  let injuryCache = null;

  async function injuries(league) {
    const path = PATHS[league];
    if (!path) return {};
    if (injuryCache) return injuryCache;
    try {
      const r = await fetch(`${ESPN}/${path}/injuries`, { cache: 'no-store' });
      if (!r.ok) return {};
      const d = await r.json();
      const out = Object.create(null);
      for (const t of (d.injuries || [])) {
        const rows = [];
        for (const x of (t.injuries || [])) {
          const ath = x.athlete || {};
          const name = ath.displayName;
          if (!name) continue;
          rows.push({
            name,
            pos: (ath.position && ath.position.abbreviation) || '',
            status: x.status || '',
            type: (x.details && x.details.type) || '',
            returnDate: (x.details && x.details.returnDate) || '',
            comment: x.shortComment || ''
          });
        }
        if (t.displayName && rows.length) out[t.displayName] = rows;
      }
      injuryCache = out;
      return out;
    } catch (e) {
      return {};
    }
  }

  /* ── Expected XI ───────────────────────────────────────────────────────
   *
   * ESPN only publishes a lineup near kickoff, so a fixture days out has no
   * roster at all. Rather than showing nothing, fall back to the last XI each
   * club actually fielded — labelled as expected, never as confirmed.
   *
   * The scan is one scoreboard sweep over the past few weeks, done once and
   * reused, plus one summary request per club the page actually asks about.
   */
  const RECENT_DAYS = 35;
  let recentIndex = null;          // club -> [{id, date, rawHome}] newest first
  const lastXICache = new Map();

  function ymd(d) {
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}` +
           `${String(d.getDate()).padStart(2, '0')}`;
  }

  async function buildRecentIndex(league) {
    if (recentIndex) return recentIndex;
    const path = PATHS[league];
    const idx = Object.create(null);
    if (!path) return (recentIndex = idx);
    const end = new Date();
    const start = new Date(end.getTime() - RECENT_DAYS * 86400000);
    try {
      const r = await fetch(
        `${ESPN}/${path}/scoreboard?dates=${ymd(start)}-${ymd(end)}&limit=400`,
        { cache: 'no-store' });
      if (r.ok) {
        const d = await r.json();
        for (const ev of (d.events || [])) {
          const c = (ev.competitions || [])[0];
          if (!c) continue;
          const state = ((c.status || {}).type || {}).state;
          if (state !== 'post') continue;            // only matches that were played
          const comp = c.competitors || [];
          const h = comp.find(t => t.homeAway === 'home');
          const a = comp.find(t => t.homeAway === 'away');
          if (!h || !a) continue;
          const rawHome = (h.team && h.team.displayName) || '';
          const date = (ev.date || '').slice(0, 10);
          for (const t of [h, a]) {
            const club = stripSuffix((t.team && t.team.displayName) || '');
            if (!club) continue;
            (idx[club] = idx[club] || []).push({ id: ev.id, date, rawHome });
          }
        }
        for (const k of Object.keys(idx)) idx[k].sort((x, y) => (x.date < y.date ? 1 : -1));
      }
    } catch (e) { /* leave the index empty; callers degrade to no XI */ }
    return (recentIndex = idx);
  }

  /**
   * The most recent XI a club actually fielded.
   * -> { names, date, opponent, formation } or null.
   */
  async function lastLineup(league, club) {
    if (lastXICache.has(club)) return lastXICache.get(club);
    const idx = await buildRecentIndex(league);
    const events = idx[club] || [];
    let out = null;
    for (const ev of events.slice(0, 4)) {          // walk back if a summary is thin
      const d = await summary(league, ev.id);
      if (!d) continue;
      for (const t of (d.rosters || [])) {
        const name = stripSuffix((t.team && t.team.displayName) || '');
        if (name !== club) continue;
        const names = (t.roster || [])
          .filter(p => p.starter)
          .map(p => (p.athlete && p.athlete.displayName) || '')
          .filter(Boolean);
        if (names.length >= 10) {
          const opp = (d.rosters || [])
            .map(x => stripSuffix((x.team && x.team.displayName) || ''))
            .find(n => n && n !== club) || '';
          out = { names, date: ev.date, opponent: opp, formation: t.formation || '' };
        }
      }
      if (out) break;
    }
    lastXICache.set(club, out);
    return out;
  }

  /** Back-compat: goal timings only. */
  async function timeline(league, eventId, rawHome) {
    return (await detail(league, eventId, rawHome)).goals;
  }

  global.Live = { fetch: fetchLive, winProb, minsLeft, timeline, detail, lastLineup, injuries };
})(window);
