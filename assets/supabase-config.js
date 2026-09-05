/**
 * Supabase project details.
 *
 * Both values are PUBLIC by design — they ship to every visitor in this file.
 * The anon key identifies the PROJECT, not a user, and carries no privileges of
 * its own: row-level security in supabase/schema.sql is what stops one account
 * reading another's rows. That is why every table must have RLS enabled; a
 * table without it is readable by anyone, since everyone has this key.
 *
 * Never put the service_role key here. It bypasses RLS entirely and would make
 * every policy in schema.sql meaningless.
 *
 * Leave these empty to run the site with positions in localStorage only — but
 * note gate.js then keeps everyone out, including you, since sign-in is
 * required to reach the league tabs.
 */
window.SUPABASE_URL = 'https://dttuohlqlouvwadppelx.supabase.co';
window.SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR0dHVvaGxxbG91dndhZHBwZWx4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1NjA1MDcsImV4cCI6MjEwNDEzNjUwN30.99PiVcLUpzgj-OFTyS_pxzQnXkBRQ6KCoaJAPZIMvR0';
