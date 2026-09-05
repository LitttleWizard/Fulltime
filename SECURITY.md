# Security

Where sensitive data lives, what protects it, and what does not.

## The one rule

**Secrets live in Vercel environment variables and nowhere else.** Not in the
repo, not in a config file, not in the browser. A watcher auto-commits and
pushes this directory and the GitHub repo is public, so a key that touches a
file here is published within seconds and stays in git history permanently.

If a key ever does land in a file: rotate it. Deleting the file does not undo
the push.

## Configuration only the owner can reach

Set in **Vercel → Settings → Environment Variables**. Vercel shows these to the
project owner and injects them at runtime; they are never served to a browser
and never appear in the repo.

| Variable | Used by | Why it is sensitive |
|---|---|---|
| `KALSHI_KEY_ID` | order + portfolio endpoints | Identifies the trading key |
| `KALSHI_PRIVATE_KEY` | order + portfolio endpoints | **Can place and cancel orders.** Full account control, no scoping |
| `OWNER_USER_ID` | `api/_owner.js` | The one Supabase account allowed to trade |
| `SUPABASE_URL` | `api/_owner.js` | Same value as the public config |
| `SUPABASE_ANON_KEY` | `api/_owner.js` | Same value as the public config |

Never set `SUPABASE_SERVICE_ROLE_KEY` here. It bypasses row-level security and
nothing in this project needs it.

## What is deliberately public

- **`assets/supabase-config.js`** — the project URL and anon key. Public by
  design: the anon key identifies the project, not a user. Row-level security
  in `supabase/schema.sql` is what actually separates one account's rows from
  another's, which is why every table must have it enabled.
- **`/api/kalshi`** — the market-data proxy. Read-only, whitelisted to three
  series, needs no credentials. Verified to reject unknown series and path
  traversal with 400.
- **Everything under `/data`** — match history and ratings. See the honest
  limits below.

## Owner-only endpoints

`api/_owner.js` guards anything that can move money. The browser sends its
Supabase access token; the server asks Supabase whether that token is valid and
whose it is, then compares against `OWNER_USER_ID`. One account passes.

It **fails closed**: missing configuration returns 503, a missing or invalid
token 401, a valid token belonging to anyone else 403. A misconfiguration must
never leave a trading endpoint open. This is verified — see the checks in the
commit that introduced it.

Order-specific limits, in `kalshi-order.js`:

- limit orders only, never market — no fills at a price you did not see
- a required `client_order_id`, so a retry or double-click cannot become two
  positions
- a 500-contract cap
- one order per request; there is no batch path to misuse

## Honest limits — what this does NOT protect

**The sign-in gate is not access control.** The site is static. Every file under
`/data` is fetchable by URL and the page source is public, with or without an
account. The gate controls the front door, not the walls. Real protection means
serving data through authenticated endpoints, which is a different architecture.

**Positions in `localStorage` are unencrypted** and readable by anything running
in the browser, including extensions. They are your own notes, not credentials,
but they are not private from software on your machine.

**Anyone signed in can read the model.** Accounts separate *positions*, not
analysis.

## If something leaks

1. **Kalshi key** — delete it at Kalshi → Settings → API Keys immediately. It
   can place and cancel orders; assume anything holding it has full account
   access.
2. **Supabase anon key** — low severity, it is public by design. Confirm RLS is
   enabled on every table: `select count(*) from pg_policies;`
3. **Supabase service_role key** — rotate at once and audit the data. It
   bypasses RLS entirely.

## Checks worth re-running

```bash
# no secrets staged
git diff --cached --name-only | grep -Ei '\.(pem|key|env)$|secret|credential'

# every table has row-level security
# (Supabase SQL editor)
select tablename from pg_tables where schemaname='public'
  and tablename not in (select tablename from pg_policies);

# the proxy still refuses what it should
curl -s -o /dev/null -w '%{http_code}\n' 'https://fulltime.beer/api/kalshi?series=EVIL'   # 400
```
