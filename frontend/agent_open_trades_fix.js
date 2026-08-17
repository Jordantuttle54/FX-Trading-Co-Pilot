/* agent_open_trades_fix.js - keep open trades detail rendering after layout cleanup */
(function () {
  'use strict';

  async function fetchJson(path) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
    }
    return res.json();
  }

  function renderFallbackTradeCards(trades, containerId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!trades || !trades.length) {
      el.innerHTML = '<div class="muted small">No open trades.</div>';
      return;
    }
    el.innerHTML = trades.map((t) => {
      const name = t.display_name || t.friendly_name || t.id || 'Open trade';
      const pair = t.pair || '';
      const direction = String(t.direction || '').toLowerCase();
      const directionLabel = direction ? direction.toUpperCase() : 'TRADE';
      return `
        <div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px">
            <div>
              <strong>${name}</strong>
              <div class="small muted">${pair}</div>
            </div>
            <span class="candidate-dir dir-${direction}">${directionLabel}</span>
          </div>
          <div class="small muted" style="margin-top:6px">
            Entry: ${t.entry_price || t.entry || '-'} &nbsp;|&nbsp; SL: ${t.stop_loss || '-'} &nbsp;|&nbsp; TP: ${t.take_profit || t.target || '-'}
          </div>
          <div class="small muted">Setup: ${t.setup_label || t.setup_type || '-'} &nbsp;|&nbsp; Confidence: ${t.confidence || '-'}%</div>
          <div class="small muted">Opened: ${t.filled_at || t.created_at || t.opened_at || '-'}</div>
        </div>
      `;
    }).join('');
  }

  window.loadOpenTradesDetail = async function loadOpenTradesDetailFixed() {
    const target = document.getElementById('openTradesDetail');
    if (!target) return;
    try {
      const data = await fetchJson('/api/agent/trades/open');
      const trades = data.open_trades || data.trades || data.items || [];
      if (typeof window.renderOpenTrades === 'function') {
        window.renderOpenTrades(trades, 'openTradesDetail');
      } else {
        renderFallbackTradeCards(trades, 'openTradesDetail');
      }
    } catch (e) {
      target.innerHTML = `<span class="muted small">Error: ${e.message}</span>`;
    }
  };
})();
