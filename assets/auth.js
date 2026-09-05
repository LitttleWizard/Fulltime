/**
 * Accounts and position sync, on Supabase.
 *
 * What this does: signs you in, and keeps your positions in a table keyed to
 * your user id so they follow you between devices. Signed out — or with no
 * project configured — everything still works against localStorage, so the
 * page is never broken by this being absent.
 *
 * What this does NOT do, by design:
 *   - It holds no Kalshi credentials and cannot see your Kalshi account.
 *   - It cannot place, size or cancel a trade. Positions here are what you
 *     typed in; the order itself is yours to make, on Kalshi.
 *   - It never stores a password. Supabase handles that; this only ever sees
 *     a session token.
 *
 * The anon key in supabase-config.js is public by design. Row-level security
 * in schema.sql is what actually stops one account reading another's rows.
 *
 *   Auth.ready()                     -> Promise<boolean>  configured & loaded
 *   Auth.user()                      -> { id, email } | null
 *   Auth.signUp(email, password)     -> { error }
 *   Auth.signIn(email, password)     -> { error }
 *   Auth.signOut()
 *   Auth.onChange(fn)
 *   Auth.list(league)                -> positions (remote when signed in)
 *   Auth.add(league, position)
 *   Auth.remove(league, id)
 *   Auth.pushLocal(league)           -> migrate localStorage rows up, once
 */
(function (global) {
  'use strict';

  const CDN = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
  let client = null, session = null, loading = null;
  const listeners = [];

  const configured = () =>
    !!(global.SUPABASE_URL && global.SUPABASE_ANON_KEY);

  function ready() {
    if (loading) return loading;
    if (!configured()) { loading = Promise.resolve(false); return loading; }
    loading = import(/* webpackIgnore: true */ CDN)
      .then(({ createClient }) => {
        client = createClient(global.SUPABASE_URL, global.SUPABASE_ANON_KEY, {
          auth: { persistSession: true, autoRefreshToken: true }
        });
        return client.auth.getSession();
      })
      .then(({ data }) => {
        session = (data && data.session) || null;
        client.auth.onAuthStateChange((_e, s) => {
          session = s || null;
          listeners.forEach(fn => { try { fn(user()); } catch (e) { /* isolate */ } });
        });
        return true;
      })
      .catch(() => false);          // offline or blocked: fall back to local
    return loading;
  }

  function user() {
    if (!session || !session.user) return null;
    return { id: session.user.id, email: session.user.email };
  }

  function onChange(fn) { listeners.push(fn); return () => {
    const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1);
  }; }

  async function signUp(email, password) {
    if (!await ready()) return { error: 'Accounts are not configured for this site.' };
    const { error } = await client.auth.signUp({ email, password });
    return { error: error ? error.message : null };
  }

  async function signIn(email, password) {
    if (!await ready()) return { error: 'Accounts are not configured for this site.' };
    const { error } = await client.auth.signInWithPassword({ email, password });
    return { error: error ? error.message : null };
  }

  async function signOut() {
    if (client) await client.auth.signOut();
    session = null;
    listeners.forEach(fn => { try { fn(null); } catch (e) { /* isolate */ } });
  }

  /* ── positions: remote when signed in, local otherwise ───────────────── */

  const toRow = (league, p) => ({
    league, match_date: p.date, home: p.home, away: p.away,
    side: p.side, contracts: p.contracts, price: p.price
  });
  const fromRow = r => ({
    id: r.id, date: r.match_date, home: r.home, away: r.away,
    side: r.side, contracts: r.contracts, price: r.price, added: (r.created_at || '').slice(0, 10)
  });

  async function list(league) {
    if (!user()) return global.Kalshi ? global.Kalshi.positions(league) : [];
    const { data, error } = await client
      .from('positions').select('*')
      .eq('league', league).order('match_date', { ascending: true });
    if (error) return global.Kalshi ? global.Kalshi.positions(league) : [];
    return (data || []).map(fromRow);
  }

  async function add(league, p) {
    if (!user()) return global.Kalshi ? global.Kalshi.addPosition(league, p) : null;
    const row = Object.assign(toRow(league, p), { user_id: user().id });
    const { error } = await client.from('positions').insert(row);
    return { error: error ? error.message : null };
  }

  async function remove(league, id) {
    if (!user()) return global.Kalshi ? global.Kalshi.removePosition(league, id) : null;
    const { error } = await client.from('positions').delete().eq('id', id);
    return { error: error ? error.message : null };
  }

  /**
   * Copy anything already in localStorage up to the account, once, on first
   * sign-in — otherwise signing in would appear to wipe your positions.
   * Local rows are left alone so a failed upload loses nothing.
   */
  async function pushLocal(league) {
    const u = user();
    if (!u || !global.Kalshi) return { moved: 0 };
    const local = global.Kalshi.positions(league);
    if (!local.length) return { moved: 0 };
    const flag = `fulltime-migrated-${league}-${u.id}`;
    try { if (localStorage.getItem(flag)) return { moved: 0 }; } catch (e) { /* ignore */ }
    const rows = local.map(p => Object.assign(toRow(league, p), { user_id: u.id }));
    const { error } = await client.from('positions').insert(rows);
    if (error) return { moved: 0, error: error.message };
    try { localStorage.setItem(flag, '1'); } catch (e) { /* ignore */ }
    return { moved: rows.length };
  }

  global.Auth = { ready, user, onChange, signUp, signIn, signOut,
                  list, add, remove, pushLocal, configured };
})(window);
