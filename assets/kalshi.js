/**
 * Kalshi market prices, and a local list of teams you are tracking.
 *
 * Two separate things, kept in one module because they are always used
 * together:
 *
 *   Kalshi.prices(league)      live market prices, via /api/kalshi
 *   Kalshi.tracked(league)     teams you have starred, from localStorage
 *
 * The prices are READ-ONLY and public. Nothing here touches an account, an API
 * key, or an order — this cannot place a trade and must not be extended to.
 * The tracking list is yours alone: it lives in this browser's localStorage,
 * is never uploaded, and Kalshi never learns about it.
 *
 * A market's yes-price in cents doubles as an implied probability, which is
 * what makes it directly comparable to the model's number. Games generally do
 * not open for trading until close to kickoff, so null prices are the normal
 * case and every caller must handle them.
 */
(function (global) {
  'use strict';

  const SERIES = { nfl: 'KXNFLGAME', nba: 'KXNBAGAME', epl: 'KXEPLGAME' };

  /* Kalshi's team codes are not the ones this site uses. Only the differences
     are listed; anything absent passes through unchanged. */
  const TO_KALSHI = {
    nfl: { LA: 'LAR', JAX: 'JAC', WAS: 'WAS' },
    nba: { NY: 'NYK', SA: 'SAS', GS: 'GSW', NO: 'NOP', UTAH: 'UTA',
           PHX: 'PHO', WSH: 'WAS' },
    epl: {
      'Arsenal': 'ARS', 'Aston Villa': 'AVL', 'AFC Bournemouth': 'BOU',
      'Bournemouth': 'BOU', 'Brentford': 'BRE', 'Brighton & Hove Albion': 'BRI',
      'Burnley': 'BUR', 'Chelsea': 'CFC', 'Coventry City': 'COV',
      'Crystal Palace': 'CRY', 'Everton': 'EVE', 'Fulham': 'FUL',
      'Hull City': 'HUL', 'Ipswich Town': 'IPS', 'Leeds United': 'LEE',
      'Liverpool': 'LFC', 'Manchester City': 'MCI', 'Manchester United': 'MUN',
      'Newcastle United': 'NEW', 'Nottingham Forest': 'NFO',
      'Sunderland': 'SUN', 'Tottenham Hotspur': 'TOT', 'West Ham United': 'WHU',
      'Wolverhampton Wanderers': 'WOL'
    }
  };

  const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];

  function code(league, team) {
    const map = TO_KALSHI[league] || {};
    return map[team] || String(team || '').toUpperCase();
  }

  /** '2026-09-21' -> '26SEP21', the form Kalshi puts in its tickers. */
  function tickerDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
    if (!m) return null;
    return m[1].slice(2) + MONTHS[+m[2] - 1] + m[3];
  }

  /**
   * The ticker prefix for one fixture: KX<LEAGUE>GAME-<date><away><home>.
   * Away comes first — KXNFLGAME-26SEP21NYGLAR is the Giants AT the Rams.
   */
  function gameKey(league, date, home, away) {
    const d = tickerDate(date);
    if (!d) return null;
    return `${SERIES[league]}-${d}${code(league, away)}${code(league, home)}`;
  }

  const cache = Object.create(null);

  async function prices(league) {
    const series = SERIES[league];
    if (!series) return null;
    const hit = cache[league];
    if (hit && Date.now() - hit.at < 60000) return hit.data;
    try {
      const r = await fetch(`/api/kalshi?series=${series}`, { cache: 'no-store' });
      if (!r.ok) return null;
      const d = await r.json();
      const byTicker = Object.create(null);
      for (const m of (d.markets || [])) byTicker[m.ticker] = m;
      const data = { fetched: d.fetched, byTicker };
      cache[league] = { at: Date.now(), data };
      return data;
    } catch (e) {
      return null;                 // market data is additive; never break a page
    }
  }

  /**
   * Implied probability for one side of one fixture, 0-1, or null.
   * Prefers the midpoint of the book; falls back to the last trade.
   */
  function impliedFor(data, league, date, home, away, side) {
    if (!data) return null;
    const key = gameKey(league, date, home, away);
    if (!key) return null;
    const want = side === 'tie' ? 'TIE' : code(league, side);
    const m = data.byTicker[`${key}-${want}`];
    if (!m) return null;
    const bid = m.yesBid, ask = m.yesAsk;
    const cents = (bid != null && ask != null) ? (bid + ask) / 2
                : (m.last != null ? m.last : null);
    return cents == null ? null : Math.min(Math.max(cents / 100, 0), 1);
  }

  /* ── positions you have entered (this browser only) ─────────────────
   *
   * Kalshi's portfolio endpoints need an API key, and that same key can place
   * orders. Holding one in a browser would put a trading credential behind
   * nothing but localStorage — any extension, any XSS, anyone at the machine.
   * So positions are entered by hand instead. Less convenient, and the only
   * version worth shipping.
   *
   * A position is a fixture plus an outcome, not just a team: football settles
   * three ways and a draw is a position you can hold. Stored as
   *   { date, home, away, side, contracts, price }
   * where side is a team code/name or 'tie', and price is in cents (1-99).
   */
  const POS_KEY = l => `fulltime-positions-${l}`;

  function positions(league) {
    try {
      const raw = localStorage.getItem(POS_KEY(league));
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }

  function savePositions(league, list) {
    try { localStorage.setItem(POS_KEY(league), JSON.stringify(list)); }
    catch (e) { /* private mode */ }
    return list;
  }

  function addPosition(league, p) {
    const list = positions(league);
    list.push({
      id: Date.now() + '-' + Math.random().toString(36).slice(2, 7),
      date: p.date || '', home: p.home || '', away: p.away || '',
      side: p.side || p.home || '',        // team, or 'tie' for a draw
      contracts: Math.max(1, Math.round(Number(p.contracts) || 1)),
      price: Math.min(99, Math.max(1, Math.round(Number(p.price) || 50))),
      added: new Date().toISOString().slice(0, 10)
    });
    return savePositions(league, list);
  }

  function removePosition(league, id) {
    return savePositions(league, positions(league).filter(x => x.id !== id));
  }

  /**
   * Mark a position against the current market.
   * Contracts settle at 100 or 0, so value is contracts x price in cents.
   */
  function markToMarket(pos, marketProb) {
    const cost = pos.contracts * pos.price;
    if (marketProb == null) return { cost, value: null, pl: null };
    const nowCents = Math.round(marketProb * 100);
    const value = pos.contracts * nowCents;
    return { cost, value, pl: value - cost };
  }

  /* ── tracking list (this browser only) ─────────────────────────────── */
  const KEY = l => `fulltime-tracked-${l}`;

  function tracked(league) {
    try {
      const raw = localStorage.getItem(KEY(league));
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch (e) { return new Set(); }
  }

  function toggle(league, team) {
    const s = tracked(league);
    if (s.has(team)) s.delete(team); else s.add(team);
    try { localStorage.setItem(KEY(league), JSON.stringify([...s])); }
    catch (e) { /* private mode: tracking is best-effort */ }
    return s;
  }

  global.Kalshi = {
    prices, impliedFor, gameKey, code, tracked, toggle, SERIES,
    positions, addPosition, removePosition, markToMarket
  };
})(window);
