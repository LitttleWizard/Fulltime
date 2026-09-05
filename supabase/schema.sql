-- Fulltime — positions storage
--
-- Run once in the Supabase SQL editor (Dashboard → SQL Editor → New query).
--
-- Two things matter here and both are enforced by the database rather than by
-- the page: row-level security so a signed-in user can only ever touch their
-- own rows, and a foreign key to auth.users so deleting an account takes its
-- positions with it. The browser holds only the anon key, which is public by
-- design — RLS is what actually protects the data, so it is not optional.

create table if not exists public.positions (
  id          uuid        primary key default gen_random_uuid(),
  user_id     uuid        not null references auth.users(id) on delete cascade,
  league      text        not null check (league in ('epl','nfl','nba')),
  match_date  date        not null,
  home        text        not null,
  away        text        not null,
  side        text        not null,          -- team name/code, or 'tie'
  contracts   integer     not null check (contracts between 1 and 100000),
  price       integer     not null check (price between 1 and 99),  -- cents
  note        text,
  created_at  timestamptz not null default now()
);

create index if not exists positions_user_league_idx
  on public.positions (user_id, league, match_date);

alter table public.positions enable row level security;

-- One policy per verb, all keyed on the caller's own id. Without these the
-- anon key would let anyone read everyone's positions.
drop policy if exists "read own positions"   on public.positions;
drop policy if exists "insert own positions" on public.positions;
drop policy if exists "update own positions" on public.positions;
drop policy if exists "delete own positions" on public.positions;

create policy "read own positions"   on public.positions
  for select using (auth.uid() = user_id);
create policy "insert own positions" on public.positions
  for insert with check (auth.uid() = user_id);
create policy "update own positions" on public.positions
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "delete own positions" on public.positions
  for delete using (auth.uid() = user_id);

-- Sanity check after running: this must return 4.
-- select count(*) from pg_policies where tablename = 'positions';
