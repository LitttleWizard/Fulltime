/**
 * Place a Kalshi order — one explicit, human-initiated order per request.
 *
 * WHY THE KEY LIVES HERE AND NOT IN THE BROWSER
 * Kalshi authenticates with an API key id plus an RSA private key, and that
 * key can place and cancel orders. In a browser it would sit behind nothing
 * but localStorage, readable by any extension, any XSS, anyone at the machine.
 * So it stays in a Vercel environment variable that only you ever set:
 *
 *   KALSHI_KEY_ID       the key's UUID
 *   KALSHI_PRIVATE_KEY  the PEM, newlines as \n
 *
 * Set them in Vercel → Settings → Environment Variables. They are never in the
 * repo, never sent to the browser, and never logged.
 *
 * SAFEGUARDS, and why each exists
 *   - POST only, one order per call. No batch endpoint to misuse.
 *   - MAX_CONTRACTS caps blast radius if the page is ever wrong.
 *   - `limit` orders only: a market order can fill at a price you did not see.
 *   - The caller must send an explicit client_order_id, so a retry or a
 *     double-click cannot become two positions.
 *   - Nothing here decides WHAT to trade. It places what it is told, and the
 *     page only tells it when a person clicks confirm.
 */
import crypto from 'node:crypto';

const HOST = 'https://api.elections.kalshi.com';
const MAX_CONTRACTS = 500;          // guardrail, not a limit you should hit

function sign(privateKeyPem, timestamp, method, path) {
  // Kalshi signs: timestamp + METHOD + path, RSA-PSS over SHA-256
  const msg = `${timestamp}${method}${path}`;
  return crypto.sign('sha256', Buffer.from(msg), {
    key: privateKeyPem,
    padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
    saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST
  }).toString('base64');
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'content-type');

  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });

  const keyId = process.env.KALSHI_KEY_ID;
  const pem = (process.env.KALSHI_PRIVATE_KEY || '').replace(/\\n/g, '\n');
  if (!keyId || !pem) {
    return res.status(503).json({
      error: 'Trading is not configured. Set KALSHI_KEY_ID and ' +
             'KALSHI_PRIVATE_KEY in the Vercel project to enable it.'
    });
  }

  const b = req.body || {};
  const ticker = String(b.ticker || '');
  const side = b.side === 'no' ? 'no' : 'yes';
  const action = b.action === 'sell' ? 'sell' : 'buy';
  const count = Math.floor(Number(b.count));
  const price = Math.floor(Number(b.price));
  const clientOrderId = String(b.client_order_id || '');

  if (!/^KX[A-Z0-9]+-[A-Z0-9]+-[A-Z]+$/.test(ticker)) {
    return res.status(400).json({ error: 'ticker looks wrong' });
  }
  if (!Number.isFinite(count) || count < 1 || count > MAX_CONTRACTS) {
    return res.status(400).json({ error: `count must be 1-${MAX_CONTRACTS}` });
  }
  if (!Number.isFinite(price) || price < 1 || price > 99) {
    return res.status(400).json({ error: 'price must be 1-99 cents' });
  }
  if (!clientOrderId) {
    return res.status(400).json({ error: 'client_order_id required (prevents duplicates)' });
  }

  const path = '/trade-api/v2/portfolio/orders';
  const ts = Date.now().toString();
  const order = {
    ticker, action, side, count,
    type: 'limit',                       // never market: no surprise fills
    client_order_id: clientOrderId,
    [side === 'yes' ? 'yes_price' : 'no_price']: price
  };

  try {
    const r = await fetch(HOST + path, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'KALSHI-ACCESS-KEY': keyId,
        'KALSHI-ACCESS-TIMESTAMP': ts,
        'KALSHI-ACCESS-SIGNATURE': sign(pem, ts, 'POST', path)
      },
      body: JSON.stringify(order)
    });
    const text = await r.text();
    let data; try { data = JSON.parse(text); } catch (e) { data = { raw: text.slice(0, 400) }; }
    // Pass the upstream status through so the page can tell a rejected order
    // from a broken one, but never echo anything derived from the key.
    return res.status(r.status).json(data);
  } catch (e) {
    return res.status(502).json({ error: 'could not reach Kalshi' });
  }
}
