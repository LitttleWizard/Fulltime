/**
 * Dark / light theme for the Fulltime terminal.
 *
 * Runs synchronously in <head> so the stored choice is applied before first
 * paint — otherwise a light-mode user gets a dark flash on every navigation.
 * Defaults to the OS preference until the user picks explicitly.
 */
(function () {
  'use strict';
  var KEY = 'fulltime-theme';

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function systemPrefersLight() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
  }
  function resolve() {
    return stored() || (systemPrefersLight() ? 'light' : 'dark');
  }
  function apply(theme) {
    if (theme === 'light') document.documentElement.setAttribute('data-theme', 'light');
    else document.documentElement.removeAttribute('data-theme');
  }

  apply(resolve());   // before paint

  window.FulltimeTheme = {
    current: resolve,
    toggle: function () {
      var next = resolve() === 'light' ? 'dark' : 'light';
      try { localStorage.setItem(KEY, next); } catch (e) { /* private mode */ }
      apply(next);
      return next;
    },
    /** Wire a button: sets its icon/label and keeps them in sync. */
    mount: function (btn) {
      if (!btn) return;
      var sync = function () {
        var light = resolve() === 'light';
        btn.textContent = light ? '☾' : '☀';
        btn.setAttribute('aria-label', light ? 'Switch to dark theme' : 'Switch to light theme');
        btn.setAttribute('title', light ? 'Dark theme' : 'Light theme');
      };
      btn.addEventListener('click', function () {
        window.FulltimeTheme.toggle();
        sync();
        // charts are drawn as SVG with baked-in colours; redraw on theme change
        if (typeof window.onFulltimeThemeChange === 'function') window.onFulltimeThemeChange();
      });
      sync();
    }
  };

  // follow the OS while the user hasn't chosen explicitly
  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: light)');
    var onChange = function () {
      if (!stored()) {
        apply(resolve());
        if (typeof window.onFulltimeThemeChange === 'function') window.onFulltimeThemeChange();
      }
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }
})();
