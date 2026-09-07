/* data_source_banner.js - say loudly when the prices on screen are not real.
 *
 * A deployment without market-data credentials looks exactly like a live one:
 * same UI, same database, same trades. The only tell was a row near the bottom
 * of Settings. This puts it where it cannot be missed, because every number on
 * the page - prices, live P&L, the scanner - is invented when it shows.
 */
'use strict';

(function () {
  const el = () => document.getElementById('dataSourceBanner');

  function esc(v) {
    return String(v ?? '').replace(/[&<>'"]/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[c]));
  }

  function show(provider) {
    const node = el();
    if (!node) return;
    node.innerHTML =
      '<strong>&#9888; Not live market data.</strong> This deployment is showing ' +
      'invented prices (<code>' + esc(provider) + '</code>), so every price, ' +
      'P&amp;L figure and scanner result on this page is meaningless. Opening a ' +
      'trade is blocked while this is showing.';
    node.hidden = false;
  }

  async function check() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) return;
      const health = await res.json();
      const provider = String(health.data_provider || '');
      const live = provider && !/synthetic|failed|fallback/i.test(provider);
      if (live) {
        const node = el();
        if (node) node.hidden = true;
      } else {
        show(provider || 'unknown');
      }
    } catch (err) {
      /* A failed health check is not itself proof the data is fake, so stay
         quiet rather than crying wolf on a dropped request. */
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', check);
  else check();
  setInterval(check, 60000);
})();
