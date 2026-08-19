/* agent_quick_trade.js - quick paper open/close controls */
'use strict';

(function () {
  const PAIRS = ['GBP/USD', 'EUR/USD', 'USD/JPY', 'EUR/GBP', 'GBP/JPY', 'XAU/USD'];

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

  function optionalNumber(id) {
    const raw = qs(id)?.value;
    if (raw === undefined || raw === null || String(raw).trim() === '') return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  function selectedPair() {
    return qs('quickTradePair')?.value || qs('chartPair')?.value || 'GBP/USD';
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

  function selectedManualSl() {
    return optionalNumber('quickTradeManualSl');
  }

  function selectedManualTp() {
    return optionalNumber('quickTradeManualTp');
  }

  function selectedFixedUnits() {
    const value = Number(qs('fixedTradeUnits')?.value || 0);
    return value > 0 ? value : null;
  }

  function selectedQuickCloseTrade() {
    return qs('quickCloseTradeSelect')?.value || '';
  }

  function syncQuickPairFromChart() {
    const quickPair = qs('quickTradePair');
    const chartPair = qs('chartPair');
    if (quickPair && chartPair && quickPair.value !== chartPair.value) quickPair.value = chartPair.value;
  }

  function syncChartPairFromQuick() {
    const quickPair = qs('quickTradePair');
    const chartPair = qs('chartPair');
    if (quickPair && chartPair && chartPair.value !== quickPair.value) {
      chartPair.value = quickPair.value;
      if (typeof window.loadAgentChart === 'function') window.loadAgentChart();
    }
  }

  function injectStyles() {
    if (qs('quickTradeStyles')) return;
    const style = document.createElement('style');
    style.id = 'quickTradeStyles';
    style.textContent = `
      #tab-trades #agentChartPanel {
        padding: 14px !important;
      }
      #tab-trades #agentChartPanel .chart-head-row {
        margin-bottom: 5px !important;
        align-items: flex-start !important;
      }
      #tab-trades #agentChartPanel .chart-head-row h2 {
        margin-bottom: 3px !important;
      }
      #tab-trades #agentChartPanel .chart-head-row .card-sub {
        font-size: 10px !important;
        line-height: 1.3 !important;
      }
      #tab-trades #agentChartPanel .chart-head-row > #chartSizeBtn {
        display: none !important;
      }
      #tab-trades #agentChartPanel .chart-toolbar {
        align-items: end !important;
        gap: 7px !important;
        margin: 5px 0 8px !important;
      }
      #tab-trades #agentChartPanel .chart-toolbar label {
        font-size: 9px !important;
        gap: 2px !important;
      }
      #tab-trades #agentChartPanel .chart-toolbar select,
      #tab-trades #agentChartPanel .chart-toolbar button {
        min-height: 30px !important;
        height: 30px !important;
        padding: 5px 9px !important;
        font-size: 11px !important;
        border-radius: 8px !important;
      }
      #tab-trades #agentChartPanel .chart-toolbar select {
        min-width: 96px !important;
      }
      #tab-trades #agentChartPanel .chart-toolbar #chartTradeSelect {
        min-width: 138px !important;
      }
      #tab-trades #agentChartPanel .chart-toolbar #chartSizeBtn {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        white-space: nowrap !important;
      }
      #tab-trades #agentChartPanel .chart-workspace {
        display: grid !important;
        grid-template-columns: minmax(0, 1.5fr) minmax(348px, .92fr) !important;
        grid-template-rows: auto auto !important;
        gap: 10px !important;
        align-items: start !important;
      }
      #tab-trades #agentChartPanel .chart-main-panel {
        grid-column: 1 !important;
        grid-row: 1 / span 2 !important;
        min-width: 0 !important;
        align-self: start !important;
      }
      #tab-trades #agentChartPanel #chartAccountPanel {
        grid-column: 2 !important;
        grid-row: 1 !important;
        min-height: 0 !important;
        padding: 10px !important;
        margin: 0 !important;
        position: static !important;
        transform: none !important;
        width: 100% !important;
        align-self: start !important;
      }
      #tab-trades #agentChartPanel #quickTradePanel {
        grid-column: 2 !important;
        grid-row: 2 !important;
        margin: 0 !important;
        min-width: 0 !important;
        position: static !important;
        transform: none !important;
        width: 100% !important;
        align-self: start !important;
      }
      #tab-trades #agentChartPanel .chart-frame {
        min-height: 330px !important;
      }
      #tab-trades #agentChartPanel #agentLiveChart {
        height: 330px !important;
      }
      #tab-trades #agentChartPanel.chart-expanded .chart-workspace {
        grid-template-columns: 1fr !important;
      }
      #tab-trades #agentChartPanel.chart-expanded .chart-main-panel {
        grid-column: 1 !important;
        grid-row: 1 !important;
      }
      #tab-trades #agentChartPanel.chart-expanded #quickTradePanel,
      #tab-trades #agentChartPanel.chart-expanded #chartAccountPanel {
        display: none !important;
      }
      #tab-trades #agentChartPanel.chart-expanded .chart-frame {
        min-height: 680px !important;
      }
      #tab-trades #agentChartPanel.chart-expanded #agentLiveChart {
        height: 680px !important;
      }
      #tab-trades #agentChartPanel .chart-status-row {
        gap: 6px !important;
        margin-top: 6px !important;
      }
      #tab-trades #agentChartPanel .chart-pill {
        min-height: 23px !important;
        padding: 3px 8px !important;
        font-size: 9px !important;
      }
      #tab-trades #agentChartPanel .chart-trade-list {
        margin-top: 7px !important;
      }
      #tab-trades #agentChartPanel .chart-account-top {
        margin-bottom: 7px !important;
      }
      #tab-trades #agentChartPanel .chart-account-title {
        font-size: 13px !important;
      }
      #tab-trades #agentChartPanel .chart-account-sub {
        font-size: 9px !important;
      }
      #tab-trades #agentChartPanel .chart-money-grid {
        gap: 7px !important;
        margin: 7px 0 !important;
      }
      #tab-trades #agentChartPanel .chart-money-cell {
        padding: 7px !important;
        min-height: 49px !important;
      }
      #tab-trades #agentChartPanel .chart-money-label {
        font-size: 9px !important;
        margin-bottom: 2px !important;
      }
      #tab-trades #agentChartPanel .chart-money-value {
        font-size: 13px !important;
      }
      #tab-trades #agentChartPanel .chart-position-list {
        max-height: 115px !important;
        margin-top: 7px !important;
        padding-top: 7px !important;
      }
      #tab-trades #agentChartPanel .chart-account-note {
        font-size: 9px !important;
        margin-top: 6px !important;
      }
      .quick-trade-panel {
        border: 1px solid var(--border);
        background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(7,13,24,.96));
        border-radius: 14px;
        padding: 10px;
        box-shadow: 0 14px 34px rgba(0,0,0,.20);
      }
      .quick-trade-title-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 7px;
      }
      .quick-trade-title {
        display: flex;
        align-items: center;
        gap: 7px;
        font-size: 13px;
        font-weight: 950;
        letter-spacing: -0.03em;
      }
      .quick-trade-icon {
        color: #facc15;
        font-size: 14px;
      }
      .quick-trade-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 6px;
        margin-bottom: 7px;
      }
      .quick-trade-field {
        display: flex;
        flex-direction: column;
        min-width: 0;
        gap: 3px;
      }
      .quick-trade-field label,
      .quick-trade-field span {
        color: var(--muted, #9fb0c7);
        font-size: 9px;
        font-weight: 850;
        line-height: 1.1;
      }
      .quick-trade-field input,
      .quick-trade-field select,
      .quick-close-select {
        width: 100% !important;
        min-width: 0 !important;
        height: 30px !important;
        min-height: 30px !important;
        font-size: 11px !important;
        padding: 5px 8px !important;
      }
      .quick-trade-action-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 6px;
        margin: 6px 0;
      }
      .quick-trade-close-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;
        align-items: end;
      }
      .quick-close-select-row {
        margin-top: 6px;
      }
      .quick-trade-panel button,
      .quick-trade-panel .btn-primary,
      .quick-trade-panel .btn-buy,
      .quick-trade-panel .btn-sell,
      .quick-trade-panel .btn-quick-close {
        width: 100%;
        min-height: 31px !important;
        height: 31px !important;
        padding: 6px 8px !important;
        font-size: 11px !important;
        white-space: nowrap;
      }
      .quick-trade-warning {
        color: var(--text-muted, #9fb0c7);
        font-size: 9px;
        margin-top: 6px;
        line-height: 1.3;
      }
      .quick-trade-result {
        font-size: 10px;
        margin-top: 6px;
        line-height: 1.3;
      }
      .btn-buy {
        background: #16a34a;
        color: #fff;
        border: 0;
        border-radius: 8px;
        font-weight: 900;
        cursor: pointer;
      }
      .btn-sell {
        background: #dc2626;
        color: #fff;
        border: 0;
        border-radius: 8px;
        font-weight: 900;
        cursor: pointer;
      }
      .btn-quick-close {
        background: #f59e0b;
        color: #111827;
        border: 0;
        border-radius: 8px;
        font-weight: 900;
        cursor: pointer;
      }
      .btn-close-all {
        background: rgba(15,23,42,.70) !important;
        color: #f8fafc !important;
        border: 1px solid rgba(248,113,113,.45) !important;
        border-radius: 8px !important;
        font-weight: 900 !important;
      }
      .btn-close-all:hover {
        background: rgba(127,29,29,.35) !important;
      }
      @media (max-width: 1180px) {
        #tab-trades #agentChartPanel .chart-workspace {
          grid-template-columns: 1fr !important;
        }
        #tab-trades #agentChartPanel .chart-main-panel,
        #tab-trades #agentChartPanel #chartAccountPanel,
        #tab-trades #agentChartPanel #quickTradePanel {
          grid-column: 1 !important;
          grid-row: auto !important;
        }
        #tab-trades #agentChartPanel #chartAccountPanel { order: 2; }
        #tab-trades #agentChartPanel #quickTradePanel { order: 3; }
      }
      @media (max-width: 760px) {
        .quick-trade-grid,
        .quick-trade-action-grid,
        .quick-trade-close-grid {
          grid-template-columns: 1fr !important;
        }
        #tab-trades #agentChartPanel .chart-frame { min-height: 320px !important; }
        #tab-trades #agentChartPanel #agentLiveChart { height: 320px !important; }
      }
    `;
    document.head.appendChild(style);
  }

  function quickPairOptions() {
    const selected = qs('chartPair')?.value || 'GBP/USD';
    return PAIRS.map(pair => `<option value="${pair}" ${pair === selected ? 'selected' : ''}>${pair}</option>`).join('');
  }

  function positionChartSizeButton() {
    const panel = qs('agentChartPanel');
    const toolbar = panel?.querySelector('.chart-toolbar');
    const autoButton = qs('chartAutoBtn');
    const sizeButton = qs('chartSizeBtn');
    if (toolbar && autoButton && sizeButton && sizeButton.parentElement !== toolbar) {
      autoButton.insertAdjacentElement('afterend', sizeButton);
    }
  }

  function positionQuickPanel(panel) {
    const accountPanel = qs('chartAccountPanel');
    const chartPanel = qs('agentChartPanel');
    const toolbar = chartPanel?.querySelector('.chart-toolbar');

    positionChartSizeButton();

    if (accountPanel && accountPanel.parentNode && panel.parentNode !== accountPanel.parentNode) {
      accountPanel.insertAdjacentElement('afterend', panel);
      return;
    }
    if (accountPanel && accountPanel.nextSibling !== panel) {
      accountPanel.insertAdjacentElement('afterend', panel);
      return;
    }
    if (toolbar && toolbar.parentNode && !panel.parentNode) {
      toolbar.parentNode.insertBefore(panel, toolbar.nextSibling);
    }
  }

  function injectQuickTradePanel() {
    injectStyles();
    positionChartSizeButton();
    const chartPanel = qs('agentChartPanel');
    if (!chartPanel) return;

    let panel = qs('quickTradePanel');
    if (panel) {
      positionQuickPanel(panel);
      syncQuickPairFromChart();
      return;
    }

    panel = document.createElement('div');
    panel.id = 'quickTradePanel';
    panel.className = 'quick-trade-panel';
    panel.innerHTML = `
      <div class="quick-trade-title-row">
        <div class="quick-trade-title"><span class="quick-trade-icon">&#9889;</span> Quick Paper Trading</div>
      </div>

      <div class="quick-trade-grid">
        <div class="quick-trade-field">
          <span>Balance</span>
          <input id="quickTradeBalance" type="number" value="${escapeHtml(qs('scanBalance')?.value || 10000)}" min="100" step="100">
        </div>
        <div class="quick-trade-field">
          <span>Risk %</span>
          <input id="quickTradeRisk" type="number" value="0.5" min="0.01" max="5" step="0.01">
        </div>
        <div class="quick-trade-field">
          <span>Stop pips</span>
          <input id="quickTradeStopPips" type="number" value="10" min="1" step="1">
        </div>
        <div class="quick-trade-field">
          <span>SL price</span>
          <input id="quickTradeManualSl" type="number" placeholder="Optional" step="0.00001">
        </div>
        <div class="quick-trade-field">
          <span>TP price</span>
          <input id="quickTradeManualTp" type="number" placeholder="Optional" step="0.00001">
        </div>
        <div class="quick-trade-field">
          <span>RR</span>
          <input id="quickTradeRR" type="number" value="1" min="0.1" step="0.1">
        </div>
        <div class="quick-trade-field" style="grid-column:1 / -1;">
          <span>Pair</span>
          <select id="quickTradePair">${quickPairOptions()}</select>
        </div>
      </div>

      <div class="quick-trade-action-grid">
        <button class="btn-buy" onclick="quickOpenPersonalTrade('buy')">Personal Buy</button>
        <button class="btn-sell" onclick="quickOpenPersonalTrade('sell')">Personal Sell</button>
        <button class="btn-primary" onclick="quickOpenAiTrade()">AI Quick Open</button>
      </div>

      <div class="quick-trade-close-grid">
        <button class="btn-quick-close" onclick="quickCloseSelectedTrade()">Quick Close</button>
        <button class="btn-close-all" onclick="quickCloseAllTrades()">Close All Trades</button>
      </div>
      <div class="quick-trade-field quick-close-select-row">
        <span>Close open trade</span>
        <select id="quickCloseTradeSelect" class="quick-close-select"><option value="">Loading...</option></select>
      </div>

      <div class="quick-trade-warning">Paper only. Manual SL/TP are optional. If left blank, Stop pips and RR are used.</div>
      <div id="quickTradeResult" class="quick-trade-result"></div>
    `;

    positionQuickPanel(panel);
    qs('quickTradePair')?.addEventListener('change', syncChartPairFromQuick);
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

  function personalPayload(direction) {
    const payload = {
      pair: selectedPair(),
      direction,
      account_balance: selectedBalance(),
      risk_pct: selectedRiskPct(),
      rr: selectedRR(),
      stop_pips: selectedStopPips(),
      fixed_units: selectedFixedUnits(),
    };
    const manualSl = selectedManualSl();
    const manualTp = selectedManualTp();
    if (manualSl !== null) {
      payload.manual_sl = manualSl;
      payload.stop_loss = manualSl;
    }
    if (manualTp !== null) {
      payload.manual_tp = manualTp;
      payload.take_profit = manualTp;
    }
    return payload;
  }

  window.quickOpenPersonalTrade = async function quickOpenPersonalTrade(direction) {
    const payload = personalPayload(direction);
    const pair = payload.pair;
    if (!confirm(`Open a PERSONAL paper ${String(direction).toUpperCase()} trade on ${pair}?`)) return;
    try {
      const result = await post('/api/agent/trades/quick-open', payload);
      showResult(`Personal paper ${String(direction).toUpperCase()} opened on ${pair}. Trade ID: ${result.trade_id || result.trade?.id || ''}`);
      await refreshTradingUi();
    } catch (e) {
      if (e.status === 409 && confirm(`A similar trade may already be open. Open another anyway?`)) {
        try {
          const retryPayload = { ...payload, force_duplicate: true };
          const retry = await post('/api/agent/trades/quick-open', retryPayload);
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
      const result = await post('/api/agent/trades/quick-open-ai', { pair, account_balance: selectedBalance(), fixed_units: selectedFixedUnits() });
      showResult(`AI paper trade opened on ${pair}. Trade ID: ${result.trade_id || result.trade?.id || ''}`);
      await refreshTradingUi();
    } catch (e) {
      if (e.status === 409 && confirm(`A similar AI trade may already be open. Open another anyway?`)) {
        try {
          const retry = await post('/api/agent/trades/quick-open-ai', { pair, account_balance: selectedBalance(), fixed_units: selectedFixedUnits(), force_duplicate: true });
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

  window.quickCloseAllTrades = async function quickCloseAllTrades() {
    try {
      const data = await api('/api/agent/trades/open');
      const rows = data.open_trades || data.trades || data.items || [];
      if (!rows.length) return showResult('No open paper trades to close.', true);
      const names = rows.slice(0, 8).map(t => t.display_name || t.friendly_name || `${t.pair || ''} ${String(t.direction || '').toUpperCase()}`).join('\n');
      const more = rows.length > 8 ? `\n...and ${rows.length - 8} more` : '';
      if (!confirm(`Close ALL ${rows.length} open paper trade(s) at the latest available market quotes?\n\n${names}${more}`)) return;

      const results = [];
      for (const trade of rows) {
        const id = trade.id;
        if (!id) continue;
        try {
          const closed = await post(`/api/agent/trades/${encodeURIComponent(id)}/quick-close`, { reason: 'Close all trades from dashboard' });
          results.push({ ok: true, trade, closed });
        } catch (e) {
          results.push({ ok: false, trade, error: e });
        }
      }
      const closedCount = results.filter(r => r.ok).length;
      const failedCount = results.length - closedCount;
      showResult(`Close all complete: ${closedCount} closed${failedCount ? `, ${failedCount} failed` : ''}.`, Boolean(failedCount));
      await refreshTradingUi();
    } catch (e) {
      showResult(`Close all failed: ${e.message}`, true);
    }
  };

  function init() {
    injectQuickTradePanel();
    scheduleQuickCloseChoices(200);
    document.addEventListener('change', (event) => {
      if (event.target && event.target.id === 'chartPair') {
        syncQuickPairFromChart();
        scheduleQuickCloseChoices(100);
      }
      if (event.target && event.target.id === 'quickTradePair') scheduleQuickCloseChoices(100);
    });
    const observer = new MutationObserver(() => {
      injectQuickTradePanel();
      positionChartSizeButton();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    setTimeout(positionChartSizeButton, 150);
    setTimeout(positionChartSizeButton, 600);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
