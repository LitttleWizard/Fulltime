# On hold: trading and accounts

Written but **deliberately not deployed**. Files live here rather than in
`api/` because anything in `api/` becomes a live endpoint on the next
`vercel --prod`, whether or not it is committed.

| File | What it does |
|---|---|
| `kalshi-order.js` | Places one limit order, signed server-side with RSA-PSS |
| `kalshi-portfolio.js` | Reads balance, positions, fills — read-only |
| `../assets/auth.js` | Supabase accounts, position sync (inert until configured) |
| `../supabase/schema.sql` | Positions table + row-level security |

## Before enabling any of this

**The Kalshi API key can place and cancel orders.** It belongs in Vercel
environment variables you set yourself (`KALSHI_KEY_ID`,
`KALSHI_PRIVATE_KEY`) — never in the repo, never in the browser. Move the two
files back into `api/` only when you have decided to run a live order endpoint
behind a public URL.

Safeguards already built into `kalshi-order.js`: limit orders only, a required
`client_order_id` so a double-click cannot become two positions, a 500-contract
cap, and one order per request.

The market-data proxy (`api/kalshi.js`) is unrelated and stays live: it is
read-only, whitelisted to three series, and needs no credentials.
