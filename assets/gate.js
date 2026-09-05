/**
 * Sign-in gate for the league tabs.
 *
 * No session, no entry — anyone without one is sent to the hero, which is the
 * only sign-in surface. There is deliberately no fallback: if accounts are not
 * configured, nobody gets in, including the owner, and the hero says so rather
 * than leaving a dead page.
 *
 * BE CLEAR ABOUT WHAT THIS IS. It is a UX gate, not access control. The site is
 * static: every file under /data is still fetchable by URL and the page source
 * is public, so a determined visitor can read the numbers without an account.
 * What this controls is the front door, not the walls. Real protection would
 * mean serving data through authenticated endpoints — a different architecture,
 * not a flag.
 *
 * The page is hidden before paint so a signed-out visitor never sees a flash of
 * content on the way out.
 */
(function (global) {
  'use strict';

  const HOME = 'index.html';
  const TIMEOUT_MS = 6000;

  function hide() {
    const s = document.createElement('style');
    s.id = 'gate-style';
    s.textContent = '.shell{visibility:hidden}';
    (document.head || document.documentElement).appendChild(s);
    return s;
  }

  function reveal(style) {
    if (style && style.parentNode) style.parentNode.removeChild(style);
  }

  function bounce(reason) {
    // Remember where they were headed so signing in can return them there.
    try {
      sessionStorage.setItem('fulltime-after-signin',
        location.pathname.split('/').pop() + location.search);
    } catch (e) { /* private mode */ }
    location.replace(`${HOME}?signin=1&why=${encodeURIComponent(reason)}`);
  }

  async function check() {
    const style = hide();

    if (typeof Auth === 'undefined' || !Auth.configured || !Auth.configured()) {
      bounce('unconfigured');
      return;
    }

    let up = false;
    try {
      up = await Promise.race([
        Auth.ready(),
        new Promise(r => setTimeout(() => r(false), TIMEOUT_MS))
      ]);
    } catch (e) {
      up = false;
    }
    if (!up) { bounce('unreachable'); return; }

    if (Auth.user()) { reveal(style); return; }
    bounce('signedout');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', check);
  } else {
    check();
  }

  global.Gate = { check };
})(window);
