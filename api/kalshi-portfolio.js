/**
 * Read the owner's Kalshi balance and open positions.
 *
 * Same key and same reasoning as kalshi-order.js: it lives in a Vercel
 * environment variable, never in the browser. Read-only — this endpoint cannot
 * place or cancel anything.
 *
 * Owner-only. Other people can sign up and use the site; none of them can see
 * this account. requireOwner fails closed.
 */
import crypto from 'node:crypto';
import { requireOwner } from './_owner.js';

const HOST = 'https://api.elections.kalshi.com';
const ALLOWED = { positions: '/trade-api/v2/portfolio/positions',
                  balance:   '/trade-api/v2/portfolio/balance',
                  fills:     '/trade-api/v2/portfolio/fills' };

function sign(pem, ts, method, path) {
  return crypto.sign('sha256', Buffer.from(`${ts}${method}${path}`), {
    key: pem,
    padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
    saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST
  }).toString('base64');
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'content-type, authorization');

  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'GET only' });

  const what = String((req.query && req.query.what) || 'positions');
  const path = ALLOWED[what];
  if (!path) return res.status(400).json({ error: 'unknown resource', allowed: Object.keys(ALLOWED) });

  // Account data is the owner's alone.
  const gate = await requireOwner(req);
  if (!gate.ok) return res.status(gate.status).json({ error: gate.error });

  const keyId = process.env.KALSHI_KEY_ID;
  const pem = (process.env.KALSHI_PRIVATE_KEY || '').replace(/\\n/g, '\n');
  if (!keyId || !pem) return res.status(503).json({ error: 'not configured' });

  const ts = Date.now().toString();
  try {
    const r = await fetch(HOST + path, {
      headers: {
        'KALSHI-ACCESS-KEY': keyId,
        'KALSHI-ACCESS-TIMESTAMP': ts,
        'KALSHI-ACCESS-SIGNATURE': sign(pem, ts, 'GET', path)
      }
    });
    const d = await r.json().catch(() => ({}));
    res.setHeader('Cache-Control', 'no-store');   // never cache account data
    return res.status(r.status).json(d);
  } catch (e) {
    return res.status(502).json({ error: 'could not reach Kalshi' });
  }
}
