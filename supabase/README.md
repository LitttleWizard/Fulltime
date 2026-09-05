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

5. **Authentication → Providers**, make sure Email is enabled. Turn on
   "Confirm email" if you want verification.

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
