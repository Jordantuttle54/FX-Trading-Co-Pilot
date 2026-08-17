/* agent_quick_trade.js - quick paper open/close controls */
'use strict';

(function () {
  let closeChoicesTimer = null;
  let closeChoicesLoading = false;
  let closeChoicesPending = false;

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
    if (!res.ok) {
      const detail = data.detail || data.message || res.statusText;
      const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
      error.status = res.status;
      error.detail = detail;
      throw error;
    }
    return data;
  }

  function post(path, body) {
    return api(path, { method: 'POST', body: JSON.stringify(body || {}) });
  }

  function selectedPair() {
    return qs('chartPair')?.value || 'GBP/USD';
  }

  function selectedBalance() {
    return Number(qs('quickTradeBalance')?.value || qs('scanBalance')?.value || 10000);
  }

  function selectedRiskPct() {
    return Number(qs('quickTradeRisk')?.value || 0.5);
  }

  function selectedRR() {
    return Number(qs('quickTradeRR')?.value || 2.0);
  }

  function selectedStopPips() {
    const value = Number(qs('quickTradeStopPips')?.value || 0);
    return value > 0 ? value : null;
  }

  function selectedQuickCloseTrade() {
    return qs('quickCloseTradeSelect')?.value || '';
  }

  function injectStyles() {
    if (qs('quickTradeStyles')) return;
    const style = document.createElement('style');
    style.id = 'quickTradeStyles';
    style.textContent = `
      .quick-trade-panel { border:1px solid var(--border); background:rgba(15,23,42,.72); border-radius:14px; padding:14px; margin:16px 0; }
      .quick-trade-row { display:flex; flex-wrap:wrap; gap:10px; align-items:end; }
      .quick-trade-row label { display:flex; flex-direction:column; gap:5px; color:var(--text-muted); font-size:11px; }
      .quick-trade-row input, .quick-trade-row select { min-width:110px; }
      .quick-close-select { min-width:260px; }
      .quick-trade-warning { color:var(--text-muted); font-size:11px; margin-top:10px; }
      .quick-trade-result { font-size:12px; margin-top:10px; }
      .btn-buy { background:#16a34a; color:#fff; border:0; border-radius:8px; padding:10px 12px; font-weight:800; cursor:pointer; }
      .btn-sell { background:#dc2626; color:#fff; border:0; border-radius:8px; padding:10px 12px; font-weight:800; cursor:pointer; }
      .btn-quick-close { background:#f59e0b; color:#111827; border:0; border-radius:8px; padding:10px 12px; font-weight:800; cursor:pointer; }
    `;
    document.head.appendChild(style);
  }

  function injectQuickTradePanel() {
    injectStyles();
    const chartPanel = qs('agentChartPanel');
    if (!chartPanel || qs('quickTradePanel')) return;

    const panel = document.createElement('div');
    panel.id = 'quickTradePanel';
    panel.className = 'quick-trade-panel';
    panel.innerHTML = `
      <h3 style="font-size:15px;margin:0 0 12px">Quick Paper Trading</h3>
      <div class="quick-trade-row">
        <label>Balance
          <input id="quickTradeBalance" type="number" value="${escapeHtml(qs('scanBalance')?.value || 10000)}" min="100" step="100">
        </label>
        <label>Risk %
          <input id="quickTradeRisk" type="number" value="0.5" min="0.01" max="5" step="0.01">
        </label>
        <label>Stop pips
          <input id="quickTradeStopPips" type="number" value="10" min="1" step="1">
        </label>
        <label>RR
          <input id="quickTradeRR" type="number" value="1" min="0.1" step="0.1">
        </label>
        <button class="btn-buy" onclick="quickOpenPersonalTrade('buy')">Personal Buy</button>
        <button class="btn-sell" onclick="quickOpenPersonalTrade('sell')">Personal Sell</button>
        <button class="btn-primary" onclick="quickOpenAiTrade()">AI Quick Open</button>
        <label>Close open trade
          <select id="quickCloseTradeSelect" class="quick-close-select"><option value="">Loading...</option></select>
        </label>
        <button class="btn-quick-close" onclick="quickCloseSelectedTrade()">Quick Close</button>
      </div>
      <div class="quick-trade-warning">Paper only. Open buttons use the selected chart pair. Quick Close closes the selected open paper trade at the latest available market quote.</div>
      <div id="quickTradeResult" class="quick-trade-result"></div>
    `;

    const toolbar = chartPanel.querySelector('.chart-toolbar');
    if (toolbar && toolbar.parentNode) toolbar.parentNode.insertBefore(panel, toolbar.nextSibling);
    else chartPanel.prepend(panel);
    scheduleQuickCloseChoices(50);
  }

  async function loadQuickCloseChoices() {
    const select = qs('quickCloseTradeSelect');
    if (!select) return;
    if (closeChoicesLoading) {
      closeChoicesPending = true;
      return;
    }
    closeChoicesLoading = true;
    try {
      const previous = select.value;
      const data = await api('/api/agent/trades/open');
      const rows = data.open_trades || data.trades || data.items || [];
      if (!rows.length) {
        select.innerHTML = '<option value="">No open trades to close</option>';
        return;
      }
      const pair = selectedPair();
      const sorted = [...rows].sort((a, b) => {
        const ap = a.pair === pair ? 0 : 1;
        const bp = b.pair === pair ? 0 : 1;
        return ap - bp;
      });
      select.innerHTML = sorted.map((t) => {
        const id = String(t.id || '');
        const name = t.display_name || t.friendly_name || t.trade_name || `${t.pair || ''} ${String(t.direction || '').toUpperCase()} ${id.slice(0, 8)}`;
        const entry = t.entry_price || t.entry || '?';
        return `<option value="${escapeHtml(id)}">${escapeHtml(name)} @ ${escapeHtml(entry)}</option>`;
      }).join('');
      if (previous && sorted.some(t => String(t.id) === String(previous))) select.value = previous;
    } catch (e) {
      select.innerHTML = `<option value="">Unable to load open trades</option>`;
    } finally {
      closeChoicesLoading = false;
      if (closeChoicesPending) {
        closeChoicesPending = false;
        scheduleQuickCloseChoices(500);
      }
    }
  }

  function scheduleQuickCloseChoices(delay = 250) {
    clearTimeout(closeChoicesTimer);
    closeChoicesTimer = setTimeout(loadQuickCloseChoices, delay);
  }

  function showResult(message, isError = false) {
    const el = qs('quickTradeResult');
    if (!el) return;
    el.style.color = isError ? 'var(--red)' : 'var(--green)';
    el.textContent = message;
  }

  async function refreshTradingUi() {
    const jobs = [];
    if (typeof window.loadStatus === 'function') jobs.push(window.loadStatus());
    if (typeof window.loadOpenTradesDetail === 'function') jobs.push(window.loadOpenTradesDetail());
    if (typeof window.loadAllTrades === 'function') jobs.push(window.loadAllTrades());
    if (typeof window.loadAgentChart === 'function') jobs.push(window.loadAgentChart());
    jobs.push(loadQuickCloseChoices());
    await Promise.allSettled(jobs);
  }

  window.quickOpenPersonalTrade = async function quickOpenPersonalTrade(direction) {
    const pair = selectedPair();
    if (!confirm(`Open a PERSONAL paper ${String(direction).toUpperCase()} trade on ${pair}?`)) return;
    try {
      const payload = {
        pair,
        direction,
        account_balance: selectedBalance(),
        risk_pct: selectedRiskPct(),
        rr: selectedRR(),
        stop_pips: selectedStopPips(),
      };
      const result = await post('/api/agent/trades/quick-open', payload);
      showResult(`Personal paper ${String(direction).toUpperCase()} opened on ${pair}. Trade ID: ${result.trade_id || result.trade?.id || ''}`);
      await refreshTradingUi();
    } catch (e) {
      if (e.status === 409 && confirm(`A similar trade may already be open. Open another anyway?`)) {
        try {
          const retry = await post('/api/agent/trades/quick-open', {
            pair,
            direction,
            account_balance: selectedBalance(),
            risk_pct: selectedRiskPct(),
            rr: selectedRR(),
            stop_pips: selectedStopPips(),
            force_duplicate: true,
          });
          showResult(`Duplicate paper trade opened. Trade ID: ${retry.trade_id || retry.trade?.id || ''}`);
          await refreshTradingUi();
          return;
        } catch (retryError) {
          showResult(`Open failed: ${retryError.message}`, true);
          return;
        }
      }
      showResult(`Open failed: ${e.message}`, true);
    }
  };

  window.quickOpenAiTrade = async function quickOpenAiTrade() {
    const pair = selectedPair();
    if (!confirm(`Ask AI to open a paper trade on ${pair}?`)) return;
    try {
      const result = await post('/api/agent/trades/quick-open-ai', { pair, account_balance: selectedBalance() });
      showResult(`AI paper trade opened on ${pair}. Trade ID: ${result.trade_id || result.trade?.id || ''}`);
      await refreshTradingUi();
    } catch (e) {
      if (e.status === 409 && confirm(`A similar AI trade may already be open. Open another anyway?`)) {
        try {
          const retry = await post('/api/agent/trades/quick-open-ai', { pair, account_balance: selectedBalance(), force_duplicate: true });
          showResult(`Duplicate AI paper trade opened. Trade ID: ${retry.trade_id || retry.trade?.id || ''}`);
          await refreshTradingUi();
          return;
        } catch (retryError) {
          showResult(`AI open failed: ${retryError.message}`, true);
          return;
        }
      }
      showResult(`AI open failed: ${e.message}`, true);
    }
  };

  window.quickCloseTrade = async function quickCloseTrade(tradeId) {
    if (!tradeId) return showResult('Select an open trade to close first.', true);
    if (!confirm('Quick close this paper trade at the latest available market price?')) return;
    try {
      const result = await post(`/api/agent/trades/${encodeURIComponent(tradeId)}/quick-close`, { reason: 'Quick close from dashboard' });
      const price = result.close_price || result.trade?.exit_price || result.trade?.close_price || '';
      const pnl = result.result_money ?? result.trade?.result_money;
      showResult(`Trade closed at ${price}${pnl != null ? ` | P&L ${pnl}` : ''}`);
      await refreshTradingUi();
    } catch (e) {
      showResult(`Close failed: ${e.message}`, true);
    }
  };

  window.quickCloseSelectedTrade = function quickCloseSelectedTrade() {
    window.quickCloseTrade(selectedQuickCloseTrade());
  };

  function init() {
    injectQuickTradePanel();
    scheduleQuickCloseChoices(200);
    document.addEventListener('change', (event) => {
      if (event.target && event.target.id === 'chartPair') scheduleQuickCloseChoices(100);
    });
    const observer = new MutationObserver(() => {
      if (!qs('quickTradePanel')) injectQuickTradePanel();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
