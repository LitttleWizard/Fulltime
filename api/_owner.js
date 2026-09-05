/**
 * Owner-only guard for the endpoints that can spend money.
 *
 * The problem this fixes: /api/kalshi-order authenticated nobody. Deployed with
 * a Kalshi key set, anyone who found the URL could place orders on the account.
 * The repo is public and the path is guessable, so that is not a theoretical
 * risk.
 *
 * How it works. The browser sends the Supabase access token it already holds.
 * This asks Supabase whether that token is valid and who it belongs to, then
 * compares the id against OWNER_USER_ID. One account passes. Everyone else,
 * including any other signed-up user, is refused.
 *
 * Why ask Supabase rather than verify the JWT locally: verifying signatures
 * needs the project's JWT secret, which would be one more secret to hold and
 * to leak. Supabase already answers "is this token good, and whose is it".
 *
 * Required environment variables (Vercel → Settings → Environment Variables —
 * only you can set or read these; they are never in the repo or the browser):
 *
 *   SUPABASE_URL        same value as the public config
 *   SUPABASE_ANON_KEY   same value as the public config
 *   OWNER_USER_ID       your Supabase user id (Authentication → Users)
 *
 * If OWNER_USER_ID is unset the guard FAILS CLOSED and refuses everyone. A
 * misconfiguration must never silently open a trading endpoint.
 */
export async function requireOwner(req) {
  const url = process.env.SUPABASE_URL;
  const anon = process.env.SUPABASE_ANON_KEY;
  const owner = process.env.OWNER_USER_ID;

  if (!owner || !url || !anon) {
    return { ok: false, status: 503,
             error: 'Owner check is not configured. Set SUPABASE_URL, ' +
                    'SUPABASE_ANON_KEY and OWNER_USER_ID.' };
  }

  const auth = req.headers.authorization || req.headers.Authorization || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7).trim() : '';
  if (!token) {
    return { ok: false, status: 401, error: 'Sign in first.' };
  }

  let user = null;
  try {
    const r = await fetch(`${url.replace(/\/+$/, '')}/auth/v1/user`, {
      headers: { apikey: anon, authorization: `Bearer ${token}` }
    });
    if (!r.ok) return { ok: false, status: 401, error: 'Session is not valid.' };
    user = await r.json();
  } catch (e) {
    // Cannot confirm identity: refuse rather than assume.
    return { ok: false, status: 503, error: 'Could not verify your session.' };
  }

  if (!user || user.id !== owner) {
    return { ok: false, status: 403, error: 'This account is not permitted to trade here.' };
  }
  return { ok: true, user };
}
