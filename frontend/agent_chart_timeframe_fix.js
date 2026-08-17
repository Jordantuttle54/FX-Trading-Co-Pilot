/* agent_chart_timeframe_fix.js - keep trade overlays stable when timeframe changes */
'use strict';

(function () {
  let scheduled = null;
  let lastHandledAt = 0;

  function scheduleStableTimeframeReload() {
    clearTimeout(scheduled);
    scheduled = setTimeout(async () => {
      if (typeof window.loadAgentChart !== 'function') return;
      try {
        await window.loadAgentChart({ keepTradesCache: true });
        setTimeout(() => {
          if (typeof window.loadAgentChart === 'function') {
            window.loadAgentChart({ keepTradesCache: true });
          }
        }, 350);
      } catch (_) {
        // The main chart module shows chart errors in the UI.
      }
    }, 80);
  }

  document.addEventListener('change', (event) => {
    const target = event.target;
    if (!target || target.id !== 'chartTimeframe') return;

    const now = Date.now();
    if (now - lastHandledAt < 120) return;
    lastHandledAt = now;

    // Stop the base chart listener from doing a full open-trade refresh.
    // Timeframe changes only need new candles; existing open trade overlays should stay cached.
    event.stopImmediatePropagation();
    scheduleStableTimeframeReload();
  }, true);
})();
