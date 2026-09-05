# Supabase setup

Five minutes, done once. Nothing here needs a secret in the repo — the browser
only ever holds the **anon** key, which is public by design.

1. Create a project at [supabase.com](https://supabase.com) (free tier is plenty).
2. **SQL Editor → New query**, paste `schema.sql`, run it. It creates the
   `positions` table and four row-level-security policies.
3. **Project Settings → API**, copy the **Project URL** and the **anon public**
   key.
4. Put them in `assets/supabase-config.js`:

   ```js
   window.SUPABASE_URL = 'https://xxxx.supabase.co';
   window.SUPABASE_ANON_KEY = 'eyJ…';
   ```

5. **Authentication → Providers**, make sure Email is enabled.
6. **Turn on "Confirm email"** (Authentication → Providers → Email). With the
   site open to other people this matters: without it anyone can create an
   account on any address they like, including someone else's.
7. **Authentication → Rate limits** — leave the defaults on. They are what stops
   someone brute-forcing sign-ins or mass-creating accounts.

## Because other people can sign up

- **Every table needs RLS.** `schema.sql` enables it on `positions` with one
  policy per verb. Any table added later without it is readable by anyone with
  the anon key, which is everyone.
- **Signing up gets an account, not the ability to trade.** The order endpoint
  checks `OWNER_USER_ID` and refuses every other user with 403.
- **Nobody's Kalshi credentials are ever collected.** Kalshi has no OAuth, so
  connecting an account would mean storing other people's RSA private keys —
  keys that can place and cancel orders on their accounts. The site does not
  ask for them and must not be extended to. Other users track positions they
  type in.
- **Check what a signed-in stranger can read:**

  ```sql
  select tablename from pg_tables where schemaname = 'public'
    and tablename not in (select tablename from pg_policies);
  ```

  Anything listed is world-readable. Fix before inviting anyone.

## What is and is not safe here

The **anon key is meant to be public** — it identifies the project, not a user.
What stops one person reading another's rows is row-level security, which is why
`schema.sql` enables it and adds a policy per verb. If you ever add a table,
enable RLS on it too; an unprotected table is readable by anyone with the anon
key, which is everyone.

Never put the **service_role** key in this repo or in the browser. It bypasses
RLS entirely.

No Kalshi credentials are involved at any point. Positions are what you type in;
the site cannot see your Kalshi account and cannot place trades.
