/* agent_quick_trade.js - quick paper open/close controls */
'use strict';

(function () {
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
    const value = Number(qs('quickTradeStop')?.value || 0);
    return value > 0 ? value : null;
  }

  function selectedQuickCloseTrade() {
    const select = qs('quickCloseTradeSelect');
    if (!select || !select.value) return { id: '', pair: '' };
    const opt = select.options[select.selectedIndex];
    return { id: select.value, pair: opt?.dataset?.pair || '' };
  }

  function addQuickTradeStyles() {
    if (qs('quickTradeStyles')) return;
    const style = document.createElement('style');
    style.id = 'quickTradeStyles';
    style.textContent = `
      .quick-trade-panel { border:1px solid var(--border); background:var(--bg2); border-radius:14px; padding:14px; margin:12px 0 16px; }
      .quick-trade-row { display:flex; gap:10px; flex-wrap:wrap; align-items:end; }
      .quick-trade-row label { display:flex; flex-direction:column; gap:4px; font-size:12px; color:var(--text-muted); }
      .quick-trade-row input { width:110px; }
      .quick-close-select { min-width:260px; max-width:360px; }
      .quick-trade-warning { margin-top:10px; font-size:12px; color:var(--text-muted); }
      .quick-trade-result { margin-top:10px; font-size:12px; }
      .btn-buy { background:#16a34a; border-color:#16a34a; color:white; }
      .btn-sell { background:#dc2626; border-color:#dc2626; color:white; }
      .btn-quick-close { background:#f59e0b; border-color:#f59e0b; color:#111827; }
    `;
    document.head.appendChild(style);
  }

  function injectQuickTradePanel() {
    addQuickTradeStyles();
    const chartPanel = qs('agentChartPanel');
    if (!chartPanel || qs('quickTradePanel')) return;
    const toolbar = chartPanel.querySelector('.chart-toolbar');
    const panel = document.createElement('div');
    panel.id = 'quickTradePanel';
    panel.className = 'quick-trade-panel';
    panel.innerHTML = `
      <h3 style="margin:0 0 10px">Quick Paper Trading</h3>
      <div class="quick-trade-row">
        <label>Balance
          <input id="quickTradeBalance" type="number" min="100" step="100" value="${escapeHtml(qs('scanBalance')?.value || 10000)}">
        </label>
        <label>Risk %
          <input id="quickTradeRisk" type="number" min="0.01" max="5" step="0.01" value="0.5">
        </label>
        <label>Stop pips
          <input id="quickTradeStop" type="number" min="1" step="1" value="20">
        </label>
        <label>RR
          <input id="quickTradeRR" type="number" min="0.5" step="0.1" value="2.0">
        </label>
        <button class="btn-buy" onclick="quickOpenPersonalTrade('buy')">Personal Buy</button>
        <button class="btn-sell" onclick="quickOpenPersonalTrade('sell')">Personal Sell</button>
        <button class="btn-primary" onclick="quickOpenAiTrade()">AI Quick Open</button>
        <label>Close open trade
          <select id="quickCloseTradeSelect" class="quick-close-select"><option value="">Loading open trades...</option></select>
        </label>
        <button class="btn-quick-close" onclick="quickCloseSelectedTrade()">Quick Close</button>
      </div>
      <div class="quick-trade-warning">Paper only. Open buttons use the selected chart pair. Quick Close closes the selected open paper trade at the latest available market quote.</div>
      <div id="quickTradeResult" class="quick-trade-result"></div>
    `;
    if (toolbar && toolbar.parentNode) toolbar.parentNode.insertBefore(panel, toolbar.nextSibling);
    else chartPanel.insertBefore(panel, chartPanel.firstChild.nextSibling);

    qs('chartPair')?.addEventListener('change', () => loadQuickCloseChoices());
    loadQuickCloseChoices();
  }

  function showResult(message, isError = false) {
    const el = qs('quickTradeResult');
    if (!el) return;
    el.innerHTML = `<span style="color:${isError ? 'var(--red)' : 'var(--green)'}">${escapeHtml(message)}</span>`;
  }

  async function loadQuickCloseChoices() {
    const select = qs('quickCloseTradeSelect');
    if (!select) return;
    const previous = select.value;
    try {
      const data = await api('/api/agent/trades/open');
      const rows = data.open_trades || [];
      if (!rows.length) {
        select.innerHTML = '<option value="">No open trades to close</option>';
        return;
      }
      const chartPair = selectedPair();
      const sorted = [...rows].sort((a, b) => {
        const ap = String(a.pair || '') === chartPair ? 0 : 1;
        const bp = String(b.pair || '') === chartPair ? 0 : 1;
        return ap - bp;
      });
      select.innerHTML = sorted.map(t => {
        const id = escapeHtml(t.id || '');
        const pair = escapeHtml(t.pair || '');
        const dir = escapeHtml(String(t.direction || '').toUpperCase());
        const entry = escapeHtml(t.entry_price || t.entry || '?');
        const shortId = escapeHtml(String(t.id || '').slice(0, 8));
        return `<option value="${id}" data-pair="${pair}">${pair} ${dir} @ ${entry} - ${shortId}</option>`;
      }).join('');
      if (sorted.some(t => String(t.id) === String(previous))) select.value = previous;
    } catch (e) {
      select.innerHTML = '<option value="">Could not load open trades</option>';
    }
  }

  async function refreshTradingUi() {
    if (typeof window.loadStatus === 'function') await window.loadStatus();
    if (typeof window.loadOpenTradesDetail === 'function') await window.loadOpenTradesDetail();
    if (typeof window.loadAllTrades === 'function') await window.loadAllTrades();
    if (typeof window.loadAgentChart === 'function') await window.loadAgentChart();
    await loadQuickCloseChoices();
  }

  window.quickOpenPersonalTrade = async function quickOpenPersonalTrade(direction) {
    const pair = selectedPair();
    const dirLabel = String(direction).toUpperCase();
    if (!confirm(`Open PERSONAL PAPER ${dirLabel} on ${pair}?\n\nThis is paper trading only. Live-money trading remains locked.`)) return;

    const body = {
      pair,
      direction,
      account_balance: selectedBalance(),
      risk_pct: selectedRiskPct(),
      rr: selectedRR(),
      stop_pips: selectedStopPips(),
      force_duplicate: false,
    };

    try {
      const result = await post('/api/agent/trades/quick-open', body);
      const trade = result.trade || {};
      showResult(`Personal paper ${dirLabel} opened on ${trade.pair || pair}. Trade ID: ${trade.id || result.trade_id}`);
      await refreshTradingUi();
    } catch (e) {
      if (e.status === 409 && e.detail) {
        const duplicate = e.detail.duplicate_trade_id || 'unknown';
        const force = confirm(`${e.detail.message || 'Duplicate open trade found.'}\nExisting trade ID: ${duplicate}\n\nOpen another paper trade anyway?`);
        if (!force) return;
        body.force_duplicate = true;
        try {
          const result = await post('/api/agent/trades/quick-open', body);
          const trade = result.trade || {};
          showResult(`Duplicate personal paper ${dirLabel} opened on ${trade.pair || pair}. Trade ID: ${trade.id || result.trade_id}`);
          await refreshTradingUi();
          return;
        } catch (inner) {
          showResult(`Quick open failed: ${inner.message || inner}`, true);
          return;
        }
      }
      showResult(`Quick open failed: ${e.message || e}`, true);
    }
  };

  window.quickOpenAiTrade = async function quickOpenAiTrade() {
    const pair = selectedPair();
    if (!confirm(`Ask the AI to quick-open a PAPER trade on ${pair}?\n\nIt will only open if the scanner returns a valid candidate. Live trading remains locked.`)) return;
    const body = { pair, account_balance: selectedBalance(), force_duplicate: false };

    try {
      const result = await post('/api/agent/trades/quick-open-ai', body);
      const trade = result.trade || {};
      showResult(`AI paper trade opened on ${trade.pair || pair}. Trade ID: ${trade.id || result.trade_id}`);
      await refreshTradingUi();
    } catch (e) {
      if (e.status === 409 && e.detail) {
        if (e.detail.duplicate_trade_id) {
          const force = confirm(`${e.detail.message || 'Duplicate open AI trade found.'}\nExisting trade ID: ${e.detail.duplicate_trade_id}\n\nOpen another AI paper trade anyway?`);
          if (!force) return;
          body.force_duplicate = true;
          try {
            const result = await post('/api/agent/trades/quick-open-ai', body);
            const trade = result.trade || {};
            showResult(`Duplicate AI paper trade opened on ${trade.pair || pair}. Trade ID: ${trade.id || result.trade_id}`);
            await refreshTradingUi();
            return;
          } catch (inner) {
            showResult(`AI quick open failed: ${inner.message || inner}`, true);
            return;
          }
        }
        showResult(e.detail.message || 'AI did not return a valid trade candidate.', true);
        return;
      }
      showResult(`AI quick open failed: ${e.message || e}`, true);
    }
  };

  window.quickCloseTrade = async function quickCloseTrade(tradeId, pair) {
    if (!tradeId) {
      showResult('Choose an open paper trade to quick close.', true);
      return;
    }
    if (!confirm(`Quick close paper trade ${String(tradeId).slice(0, 8)} on ${pair || 'this pair'} at latest market price?`)) return;
    try {
      const result = await post(`/api/agent/trades/${encodeURIComponent(tradeId)}/quick-close`, {
        reason: 'Quick close at market from dashboard',
      });
      const closed = result.closed_trade || {};
      showResult(`Quick closed ${closed.pair || pair || ''} at ${result.close_price}. Result: ${result.result_r}R / ${result.result_money}`);
      await refreshTradingUi();
    } catch (e) {
      showResult(`Quick close failed: ${e.message || e}`, true);
    }
  };

  window.quickCloseSelectedTrade = async function quickCloseSelectedTrade() {
    const trade = selectedQuickCloseTrade();
    await window.quickCloseTrade(trade.id, trade.pair);
  };

  function initQuickTrade() {
    injectQuickTradePanel();
    loadQuickCloseChoices();
    const observer = new MutationObserver(() => {
      injectQuickTradePanel();
      loadQuickCloseChoices();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initQuickTrade);
  } else {
    initQuickTrade();
  }
})();
