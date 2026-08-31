/**
 * Mobile panel switching for the Fulltime terminal.
 *
 * On desktop the three columns sit side by side. On mobile, stacking them
 * buried the prediction under the whole watchlist, so instead we show one panel
 * at a time and land on the prediction. This injects the bottom tab bar and
 * keeps it in sync; on desktop it does nothing visible (the bar is display:none
 * and every column is shown by CSS).
 */
(function () {
  'use strict';

  var PANELS = [
    { key: 'center',    sel: '.term-center',    icon: '◧', label: 'Predict' },
    { key: 'watchlist', sel: '.term-watchlist', icon: '☰', label: 'Teams' },
    { key: 'quotes',    sel: '.term-quotes',    icon: '◷', label: 'Games' }
  ];
  var KEY = 'fulltime-mobile-panel';

  function init() {
    var shell = document.querySelector('.shell');
    var terminal = document.getElementById('app');
    if (!shell || !terminal || document.querySelector('.mtabs')) return;

    var bar = document.createElement('nav');
    bar.className = 'mtabs';
    bar.setAttribute('aria-label', 'Sections');

    var buttons = {};
    PANELS.forEach(function (p) {
      if (!document.querySelector(p.sel)) return;
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'mtab';
      b.dataset.panel = p.key;
      b.innerHTML = '<span class="mtab-ico" aria-hidden="true">' + p.icon + '</span>' + p.label;
      b.addEventListener('click', function () { show(p.key); });
      bar.appendChild(b);
      buttons[p.key] = b;
    });
    if (!Object.keys(buttons).length) return;
    shell.appendChild(bar);

    function show(key) {
      PANELS.forEach(function (p) {
        var el = document.querySelector(p.sel);
        if (el) el.classList.toggle('m-active', p.key === key);
        if (buttons[p.key]) {
          var on = p.key === key;
          buttons[p.key].classList.toggle('is-on', on);
          buttons[p.key].setAttribute('aria-current', on ? 'true' : 'false');
        }
      });
      try { sessionStorage.setItem(KEY, key); } catch (e) { /* private mode */ }
      // the chart is sized from its box, which just changed
      if (key === 'center' && typeof window.onFulltimePanelShown === 'function') {
        window.onFulltimePanelShown();
      }
    }

    var start = 'center';
    try {
      var saved = sessionStorage.getItem(KEY);
      if (saved && buttons[saved]) start = saved;
    } catch (e) { /* ignore */ }
    show(start);

    // Tapping a team or a fixture jumps you to the prediction — otherwise the
    // selection changes on a panel you can't see.
    document.addEventListener('click', function (e) {
      if (!window.matchMedia('(max-width: 1080px)').matches) return;
      if (e.target.closest('.wl-row') || e.target.closest('.ticker-row')) {
        setTimeout(function () { show('center'); }, 60);
      }
    });

    window.FulltimeMobile = { show: show };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
