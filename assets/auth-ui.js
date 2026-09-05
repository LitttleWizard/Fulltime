/**
 * Sign-in dialog, shared by every page.
 *
 * Injects a modal behind the nav button so account state is consistent across
 * the league tabs rather than living inside one panel. Does nothing at all if
 * Supabase is not configured — the button stays hidden and every page works
 * exactly as before, which is the point: accounts are additive here, never
 * load-bearing.
 *
 * No password is stored or seen by this code. Supabase handles the exchange
 * and hands back a session token; that is all this ever holds.
 *
 * Auth-UI.mount() is called automatically once the DOM is ready.
 */
(function (global) {
  'use strict';

  const DIALOG_ID = 'auth-dialog';

  function build() {
    if (document.getElementById(DIALOG_ID)) return document.getElementById(DIALOG_ID);
    const d = document.createElement('dialog');
    d.id = DIALOG_ID;
    d.className = 'auth-dialog';
    d.innerHTML = `
      <form method="dialog" class="auth-close-form">
        <button class="auth-x" aria-label="Close">&times;</button>
      </form>
      <div class="auth-title">Sign in to Fulltime</div>
      <div class="auth-sub" id="auth-dialog-sub">
        Keeps your tracked teams and positions in sync across devices.
      </div>
      <form id="auth-dialog-form" autocomplete="on">
        <input id="auth-dialog-email" type="email" placeholder="you@example.com"
               autocomplete="email" required aria-label="Email" />
        <input id="auth-dialog-pass" type="password" placeholder="password"
               autocomplete="current-password" required minlength="6" aria-label="Password" />
        <div class="auth-actions">
          <button type="submit" class="tb-btn" id="auth-dialog-in">Sign in</button>
          <button type="button" class="tb-btn" id="auth-dialog-up">Create account</button>
        </div>
      </form>
      <div class="auth-dialog-msg" id="auth-dialog-msg" role="status"></div>
      <div class="auth-note">
        Fulltime never sees your Kalshi credentials and cannot trade on your
        behalf. An account here only syncs what you have typed in.
      </div>`;
    document.body.appendChild(d);
    return d;
  }

  async function mount() {
    const btn = document.getElementById('nav-auth');
    if (!btn || typeof Auth === 'undefined') return;

    const on = await Auth.ready();
    if (!on) { btn.hidden = true; return; }   // not configured: stay anonymous
    btn.hidden = false;

    const dialog = build();
    const form = document.getElementById('auth-dialog-form');
    const msg = document.getElementById('auth-dialog-msg');
    const email = document.getElementById('auth-dialog-email');
    const pass = document.getElementById('auth-dialog-pass');

    const paint = u => {
      btn.textContent = u ? (u.email || 'Account') : 'Sign in';
      btn.title = u ? 'Signed in — click to sign out' : 'Sign in or create an account';
      btn.classList.toggle('is-on', !!u);
    };

    btn.addEventListener('click', async () => {
      if (Auth.user()) {
        await Auth.signOut();
        return;
      }
      msg.textContent = '';
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
      email.focus();
    });

    const attempt = async (fn, okText) => {
      msg.textContent = '';
      const { error } = await fn((email.value || '').trim(), pass.value);
      if (error) { msg.textContent = error; return; }
      pass.value = '';
      msg.textContent = okText;
      if (okText === '') dialog.close();
    };

    form.addEventListener('submit', e => {
      e.preventDefault();
      attempt(Auth.signIn, '');
    });
    document.getElementById('auth-dialog-up').addEventListener('click', () => {
      if (!form.reportValidity()) return;
      attempt(Auth.signUp, 'Check your email to confirm, then sign in.');
    });

    Auth.onChange(u => {
      paint(u);
      if (u) dialog.close();
      // let a page refresh whatever it keys off the session
      if (typeof global.onFulltimeAuthChange === 'function') global.onFulltimeAuthChange(u);
    });
    paint(Auth.user());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  global.AuthUI = { mount };
})(window);
