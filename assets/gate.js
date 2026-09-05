/**
 * Sign-in gate for the league tabs.
 *
 * Sends anyone without a session back to the hero page, which doubles as the
 * sign-in surface.
 *
 * BE CLEAR ABOUT WHAT THIS IS. This is a UX gate, not access control. The site
 * is static: every data file under /data is still fetchable by URL, and the
 * page source is public. Anyone determined can read the numbers without an
 * account. What this changes is the front door, not the walls.
 *
 * Real protection would mean serving data through authenticated endpoints
 * instead of static files — a different architecture, not a flag.
 *
 * Two deliberate escape hatches, because locking the owner out of their own
 * site would be worse than not gating at all:
 *   - If Supabase is not configured, nothing is gated.
 *   - If the auth check errors or times out, nothing is gated.
 * Failing open is the right default for a gate whose job is tidiness.
 */
(function (global) {
  'use strict';

  const HOME = 'index.html';
  const TIMEOUT_MS = 6000;

  function hide() {
    // Hide before paint so a signed-out visitor never sees a flash of content.
    const s = document.createElement('style');
    s.id = 'gate-style';
    s.textContent = '.shell{visibility:hidden}';
    (document.head || document.documentElement).appendChild(s);
    return s;
  }

  function reveal(style) {
    if (style && style.parentNode) style.parentNode.removeChild(style);
  }

  async function check() {
    if (typeof Auth === 'undefined' || !Auth.configured || !Auth.configured()) {
      return;                                   // not configured: no gate
    }
    const style = hide();
    let configured = false;
    try {
      configured = await Promise.race([
        Auth.ready(),
        new Promise(r => setTimeout(() => r(false), TIMEOUT_MS))
      ]);
    } catch (e) {
      configured = false;
    }
    if (!configured) { reveal(style); return; }  // fail open

    if (Auth.user()) { reveal(style); return; }

    // Remember where they were headed, so signing in can return them.
    try {
      sessionStorage.setItem('fulltime-after-signin',
        location.pathname.split('/').pop() + location.search);
    } catch (e) { /* private mode */ }
    location.replace(HOME + '?signin=1');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', check);
  } else {
    check();
  }

  global.Gate = { check };
})(window);
