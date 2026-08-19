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

/* Trades cockpit layout alignment */
(function () {
  'use strict';
  if (window.__agentTradesCockpitLayoutInstalled) return;
  window.__agentTradesCockpitLayoutInstalled = true;

  function qs(id) { return document.getElementById(id); }

  function injectCockpitStyles() {
    let style = qs('agentTradesCockpitLayoutStyles');
    if (!style) {
      style = document.createElement('style');
      style.id = 'agentTradesCockpitLayoutStyles';
      style.textContent = `
        #tab-trades #agentChartPanel .chart-head-row #chartSizeBtn {
          display: none !important;
        }

        #tab-trades #agentChartPanel .chart-toolbar #chartSizeBtn {
          display: inline-flex !important;
          align-items: center !important;
          justify-content: center !important;
          white-space: nowrap !important;
          height: 34px !important;
          min-height: 34px !important;
          padding: 7px 12px !important;
        }

        @media (min-width: 1181px) {
          #tab-trades #agentChartPanel {
            display: grid !important;
            grid-template-columns: minmax(0, 1.42fr) minmax(390px, .88fr) !important;
            grid-template-rows: auto auto auto !important;
            column-gap: 12px !important;
            row-gap: 8px !important;
            align-items: start !important;
          }

          #tab-trades #agentChartPanel .chart-head-row {
            grid-column: 1 !important;
            grid-row: 1 !important;
            margin: 0 !important;
            align-items: flex-start !important;
          }

          #tab-trades #agentChartPanel .chart-head-row h2 {
            margin: 0 0 3px !important;
          }

          #tab-trades #agentChartPanel .chart-head-row .card-sub {
            margin: 0 !important;
            font-size: 10px !important;
            line-height: 1.35 !important;
          }

          #tab-trades #agentChartPanel .chart-toolbar {
            grid-column: 1 !important;
            grid-row: 2 !important;
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 8px !important;
            align-items: end !important;
            margin: 6px 0 8px !important;
          }

          #tab-trades #agentChartPanel .chart-toolbar label {
            font-size: 10px !important;
            gap: 3px !important;
          }

          #tab-trades #agentChartPanel .chart-toolbar select {
            min-width: 112px !important;
            height: 34px !important;
          }

          #tab-trades #agentChartPanel .chart-toolbar button {
            height: 34px !important;
            min-height: 34px !important;
            padding: 7px 12px !important;
            font-size: 12px !important;
          }

          #tab-trades #agentChartPanel .chart-workspace {
            grid-column: 1 !important;
            grid-row: 3 !important;
            display: block !important;
            margin: 0 !important;
            min-width: 0 !important;
          }

          #tab-trades #agentChartPanel .chart-main-panel {
            min-width: 0 !important;
            width: 100% !important;
          }

          #tab-trades #agentChartPanel .chart-right-rail {
            grid-column: 2 !important;
            grid-row: 1 / span 3 !important;
            display: grid !important;
            gap: 10px !important;
            align-self: start !important;
            width: 100% !important;
            min-width: 0 !important;
          }

          #tab-trades #agentChartPanel #chartAccountPanel,
          #tab-trades #agentChartPanel #quickTradePanel {
            position: static !important;
            transform: none !important;
            margin: 0 !important;
            width: 100% !important;
            min-width: 0 !important;
            align-self: start !important;
          }

          #tab-trades #agentChartPanel #chartAccountPanel {
            padding: 10px !important;
            min-height: 0 !important;
          }

          #tab-trades #agentChartPanel #quickTradePanel {
            padding: 10px !important;
          }

          #tab-trades #agentChartPanel .chart-account-top {
            margin-bottom: 6px !important;
          }

          #tab-trades #agentChartPanel .chart-account-title,
          #tab-trades #agentChartPanel .quick-trade-title {
            font-size: 14px !important;
          }

          #tab-trades #agentChartPanel .chart-account-sub {
            font-size: 9px !important;
          }

          #tab-trades #agentChartPanel .chart-money-grid {
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
            gap: 7px !important;
            margin: 7px 0 !important;
          }

          #tab-trades #agentChartPanel .chart-money-cell {
            padding: 7px !important;
            min-height: 46px !important;
            border-radius: 9px !important;
          }

          #tab-trades #agentChartPanel .chart-money-label {
            font-size: 9px !important;
            margin-bottom: 3px !important;
          }

          #tab-trades #agentChartPanel .chart-money-value {
            font-size: 13px !important;
            line-height: 1.2 !important;
          }

          #tab-trades #agentChartPanel .chart-position-list {
            max-height: 82px !important;
            margin-top: 7px !important;
            padding-top: 7px !important;
          }

          #tab-trades #agentChartPanel .chart-position-row {
            padding: 6px 0 !important;
          }

          #tab-trades #agentChartPanel .chart-account-note,
          #tab-trades #agentChartPanel .quick-trade-warning {
            font-size: 9px !important;
            line-height: 1.3 !important;
            margin-top: 6px !important;
          }

          #tab-trades #agentChartPanel .quick-trade-title-row {
            margin-bottom: 7px !important;
          }

          #tab-trades #agentChartPanel .quick-trade-grid,
          #tab-trades #agentChartPanel .quick-trade-action-grid,
          #tab-trades #agentChartPanel .quick-trade-close-grid {
            gap: 6px !important;
            margin-bottom: 6px !important;
          }

          #tab-trades #agentChartPanel .quick-trade-field span,
          #tab-trades #agentChartPanel .quick-trade-field label {
            font-size: 9px !important;
          }

          #tab-trades #agentChartPanel .quick-trade-field input,
          #tab-trades #agentChartPanel .quick-trade-field select,
          #tab-trades #agentChartPanel .quick-close-select {
            height: 31px !important;
            min-height: 31px !important;
            font-size: 11px !important;
            padding: 6px 8px !important;
          }

          #tab-trades #agentChartPanel .quick-trade-panel button,
          #tab-trades #agentChartPanel .quick-trade-panel .btn-primary,
          #tab-trades #agentChartPanel .quick-trade-panel .btn-buy,
          #tab-trades #agentChartPanel .quick-trade-panel .btn-sell,
          #tab-trades #agentChartPanel .quick-trade-panel .btn-quick-close {
            height: 31px !important;
            min-height: 31px !important;
            padding: 6px 8px !important;
            font-size: 11px !important;
          }

          #tab-trades #agentChartPanel .chart-frame {
            min-height: 330px !important;
          }

          #tab-trades #agentChartPanel #agentLiveChart {
            height: 330px !important;
          }

          #tab-trades #agentChartPanel.chart-expanded {
            grid-template-columns: 1fr !important;
          }

          #tab-trades #agentChartPanel.chart-expanded .chart-head-row,
          #tab-trades #agentChartPanel.chart-expanded .chart-toolbar,
          #tab-trades #agentChartPanel.chart-expanded .chart-workspace {
            grid-column: 1 !important;
          }

          #tab-trades #agentChartPanel.chart-expanded .chart-right-rail {
            display: none !important;
          }

          #tab-trades #agentChartPanel.chart-expanded .chart-frame {
            min-height: 680px !important;
          }

          #tab-trades #agentChartPanel.chart-expanded #agentLiveChart {
            height: 680px !important;
          }
        }

        @media (max-width: 1180px) {
          #tab-trades #agentChartPanel .chart-right-rail {
            display: grid !important;
            gap: 10px !important;
            width: 100% !important;
          }

          #tab-trades #agentChartPanel #chartAccountPanel,
          #tab-trades #agentChartPanel #quickTradePanel {
            position: static !important;
            transform: none !important;
            margin: 0 !important;
            width: 100% !important;
          }
        }
      `;
    }
    document.head.appendChild(style);
  }

  function moveExpandButton(panel) {
    const button = qs('chartSizeBtn');
    const autoButton = qs('chartAutoBtn');
    const toolbar = panel && panel.querySelector('.chart-toolbar');
    if (button && autoButton && toolbar && button.parentElement !== toolbar) {
      autoButton.insertAdjacentElement('afterend', button);
    }
  }

  function ensureRightRail(panel) {
    if (!panel) return;
    const accountPanel = qs('chartAccountPanel');
    const quickPanel = qs('quickTradePanel');
    if (!accountPanel && !quickPanel) return;

    let rail = panel.querySelector('.chart-right-rail');
    if (!rail) {
      rail = document.createElement('aside');
      rail.className = 'chart-right-rail';
      panel.appendChild(rail);
    }

    if (accountPanel && accountPanel.parentElement !== rail) rail.appendChild(accountPanel);
    if (quickPanel && quickPanel.parentElement !== rail) rail.appendChild(quickPanel);
  }

  function applyCockpitLayout() {
    const panel = qs('agentChartPanel');
    if (!panel) return;
    injectCockpitStyles();
    moveExpandButton(panel);
    ensureRightRail(panel);
  }

  function start() {
    applyCockpitLayout();
    const observer = new MutationObserver(applyCockpitLayout);
    observer.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('resize', applyCockpitLayout);
    setTimeout(applyCockpitLayout, 150);
    setTimeout(applyCockpitLayout, 600);
    setTimeout(applyCockpitLayout, 1200);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
