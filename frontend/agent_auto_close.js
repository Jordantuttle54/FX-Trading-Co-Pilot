/* agent_auto_close.js - TP/SL paper auto-close notifier */
'use strict';

(function () {
  const seenAutoCloseIds = new Set();
  let checking = false;

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }

  function selectedPair() {
    return qs('chartPair')?.value || '';
  }

  function addStyles() {
    if (qs('autoCloseStyles')) return;
    const style = document.createElement('style');
    style.id = 'autoCloseStyles';
    style.textContent = `
      .auto-close-notice { border:1px solid var(--green); background:rgba(34,197,94,0.10); border-radius:10px; padding:10px 12px; margin:10px 0; font-size:12px; line-height:1.5; }
      .auto-close-loss { border-color:var(--red); background:rgba(239,68,68,0.10); }
      .auto-close-notice strong { display:block; margin-bottom:3px; }
    `;
    document.head.appendChild(style);
  }

  function resultLabel(action) {
    const reason = action.reason === 'take_profit_hit' ? 'Take Profit hit' : 'Stop Loss hit';
    const name = action.display_name || action.trade_id || 'Paper trade';
    const r = Number(action.result_r || 0);
    const money = Number(action.result_money || 0);
    return `${name} - ${reason} at ${action.close_price}. Result: ${r >= 0 ? '+' : ''}${r.toFixed(2)}R / ${money >= 0 ? '+' : ''}${money.toFixed(2)}`;
  }

  function showAutoCloseNotice(actions) {
    if (!actions || !actions.length) return;
    addStyles();
    const host = qs('quickTradeResult') || qs('manageResult') || qs('tradeJournalPanel');
    if (!host) return;
    const fresh = actions.filter(a => {
      const key = `${a.trade_id || ''}-${a.reason || ''}-${a.close_price || ''}`;
      if (seenAutoCloseIds.has(key)) return false;
      seenAutoCloseIds.add(key);
      return true;
    });
    if (!fresh.length) return;
    const loss = fresh.some(a => a.reason === 'stop_loss_hit');
    const html = `<div class="auto-close-notice ${loss ? 'auto-close-loss' : ''}"><strong>Paper trade auto-closed</strong>${fresh.map(a => `<div>${escapeHtml(resultLabel(a))}</div>`).join('')}</div>`;
    host.innerHTML = html + (host.innerHTML || '');
  }

  async function refreshTradingUi() {
    if (typeof window.loadStatus === 'function') await window.loadStatus();
    if (typeof window.loadOpenTradesDetail === 'function') await window.loadOpenTradesDetail();
    if (typeof window.loadAllTrades === 'function') await window.loadAllTrades();
    if (typeof window.loadAgentChart === 'function') await window.loadAgentChart();
  }

  async function runAutoCloseCheck(pair) {
    if (checking) return;
    checking = true;
    try {
      const suffix = pair ? `?pair=${encodeURIComponent(pair)}` : '';
      const data = await api(`/api/agent/trades/auto-close-check${suffix}`);
      const actions = data.actions || [];
      if (actions.length) {
        showAutoCloseNotice(actions);
        await refreshTradingUi();
      }
    } catch (_) {
      // Keep this silent so a temporary quote/feed issue does not interrupt the dashboard.
    } finally {
      checking = false;
    }
  }

  function hookChartResponses() {
    const oldLoadChart = window.loadAgentChart;
    if (typeof oldLoadChart === 'function' && !oldLoadChart.__autoCloseHooked) {
      window.loadAgentChart = async function loadAgentChartAutoCloseHooked(...args) {
        const result = await oldLoadChart.apply(this, args);
        await runAutoCloseCheck(selectedPair());
        return result;
      };
      window.loadAgentChart.__autoCloseHooked = true;
    }
  }

  function init() {
    addStyles();
    hookChartResponses();
    setTimeout(() => runAutoCloseCheck(selectedPair()), 2500);
    setInterval(() => {
      hookChartResponses();
      runAutoCloseCheck(selectedPair());
    }, 10000);
  }

  window.checkPaperAutoClose = runAutoCloseCheck;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
