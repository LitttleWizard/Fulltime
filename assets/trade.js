/**
 * Trade ticket and live account view.
 *
 * Lets you act on what the page is showing without leaving it: your real
 * balance and open positions, and a ticket to send an order — signed
 * server-side, because the Kalshi key can place and cancel orders and has no
 * business in a browser.
 *
 * Three constraints, each there for a reason:
 *
 *   1. NOTHING SENDS ON ONE CLICK. Building a ticket and submitting it are
 *      separate actions, and the review step spells out contracts, limit price
 *      and worst-case cost first. This spends real money; a stray click should
 *      not.
 *
 *   2. NO SIZING OR SELECTION ADVICE. The page shows what the model thinks and
 *      what the market thinks. It does not rank opportunities, compute an
 *      "edge", or suggest a stake — the model loses to the market on its own
 *      history, so a suggestion would be worse than useless.
 *
 *   3. LIMIT ORDERS ONLY, each with its own client_order_id, so a retry or a
 *      double-click cannot quietly become two positions.
 *
 *   Trade.account()        -> { configured, cents, positions } | null
 *   Trade.place(order)     -> { ok, data, error }
 *   Trade.newOrderId()
 *   Trade.maxCost(n, price)
 */
(function (global) {
  'use strict';

  async function account() {
    try {
      const [b, p] = await Promise.all([
        fetch('/api/kalshi-portfolio?what=balance', { cache: 'no-store' }),
        fetch('/api/kalshi-portfolio?what=positions', { cache: 'no-store' })
      ]);
      if (b.status === 404 || b.status === 503) return { configured: false };
      const balance = b.ok ? await b.json() : null;
      const positions = p.ok ? await p.json() : null;
      return {
        configured: true,
        cents: balance && typeof balance.balance === 'number' ? balance.balance : null,
        positions: (positions && (positions.market_positions || positions.positions)) || []
      };
    } catch (e) {
      return null;
    }
  }

  /** Unique per attempt, so the server can reject a duplicate submission. */
  function newOrderId() {
    return 'fulltime-' + Date.now().toString(36) + '-' +
           Math.random().toString(36).slice(2, 8);
  }

  /** Worst case for a buy: every contract fills at the limit price. */
  function maxCost(count, price) {
    return Math.max(0, Math.round(Number(count) * Number(price)));
  }

  /**
   * Send one order. This does NOT confirm anything — the caller must have
   * shown a review step first. Kept deliberately dumb: it submits what it is
   * given and reports what came back.
   */
  async function place(order) {
    try {
      const r = await fetch('/api/kalshi-order', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(order)
      });
      const data = await r.json().catch(() => ({}));
      if (r.status === 404) {
        return { ok: false, error: 'Order endpoint is not deployed on this site.' };
      }
      if (!r.ok) {
        return { ok: false, error: data.error || data.message || `rejected (${r.status})`, data };
      }
      return { ok: true, data };
    } catch (e) {
      return { ok: false, error: 'could not reach the order endpoint' };
    }
  }

  global.Trade = { account, place, newOrderId, maxCost };
})(window);
