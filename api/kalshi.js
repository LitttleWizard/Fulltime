/**
 * Read-only proxy for Kalshi market prices.
 *
 * Kalshi's API answers a server fine but sends no Access-Control-Allow-Origin,
 * so the browser cannot call it directly. This adds that header — and nothing
 * else. It is the one piece of server in an otherwise static site, and it
 * exists only because CORS leaves no alternative for live prices.
 *
 * Deliberately narrow, because an open proxy is a liability:
 *   - only the three game series this site covers are reachable
 *   - only GET, only the public /markets endpoint
 *   - no credentials are read, forwarded, or accepted; this cannot see an
 *     account, place an order, or move money, and must not be extended to
 *   - responses are cached briefly so a reload does not hammer the upstream
 *
 * GET /api/kalshi?series=KXNFLGAME
 */
const UPSTREAM = 'https://api.elections.kalshi.com/trade-api/v2/markets';
const ALLOWED = new Set(['KXNFLGAME', 'KXNBAGAME', 'KXEPLGAME']);

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');

  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'GET only' });

  const series = String((req.query && req.query.series) || '');
  if (!ALLOWED.has(series)) {
    return res.status(400).json({ error: 'unknown series', allowed: [...ALLOWED] });
  }

  try {
    const url = `${UPSTREAM}?series_ticker=${encodeURIComponent(series)}` +
                `&limit=200&status=open`;
    const r = await fetch(url, { headers: { accept: 'application/json' } });
    if (!r.ok) {
      return res.status(502).json({ error: 'upstream ' + r.status });
    }
    const d = await r.json();

    // Trim to what the page uses. Prices are in cents (0-100) and double as
    // probabilities; a market with no bids yet returns nulls, which callers
    // must tolerate — most games do not open until close to kickoff.
    const markets = (d.markets || []).map(m => ({
      ticker: m.ticker,
      title: m.title,
      yesBid: m.yes_bid ?? null,
      yesAsk: m.yes_ask ?? null,
      last: m.last_price ?? null,
      volume: m.volume ?? 0,
      close: m.close_time || ''
    }));

    // 60s shared cache: prices move, but not so fast that every visitor needs
    // their own round trip.
    res.setHeader('Cache-Control', 's-maxage=60, stale-while-revalidate=300');
    return res.status(200).json({ series, fetched: new Date().toISOString(), markets });
  } catch (e) {
    return res.status(502).json({ error: 'upstream unreachable' });
  }
}
