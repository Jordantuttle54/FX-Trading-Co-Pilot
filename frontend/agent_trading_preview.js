/* agent_trading_preview.js - integrated Trading Desk preview branch */
'use strict';

(function () {
  if (window.__agentTradingPreviewV2Installed) return;
  window.__agentTradingPreviewV2Installed = true;

  let mt4Timer = null;
  let scannerTimer = null;
  let initTimer = null;
  let patchedRunScan = false;
  let patchedLoadChart = false;

  const FALLBACK_SETUPS = [
    { pair: 'GBP/JPY', direction: 'sell', confidence: 88, trend: 'Down', session: 'London', entry: 215.521, stop_loss: 216.125, take_profit: 214.830, risk_reward: 2.2 },
    { pair: 'EUR/USD', direction: 'buy', confidence: 82, trend: 'Up', session: 'New York', entry: 1.09325, stop_loss: 1.09180, take_profit: 1.09640, risk_reward: 2.1 },
    { pair: 'USD/JPY', direction: 'sell', confidence: 78, trend: 'Down', session: 'London', entry: 147.321, stop_loss: 147.890, take_profit: 146.510, risk_reward: 2.3 },
    { pair: 'XAU/USD', direction: 'sell', confidence: 65, trend: 'Sideways', session: 'New York', entry: 2515.40, stop_loss: 2528.10, take_profit: 2498.30, risk_reward: 1.9 }
  ];

  function qs(id) { return document.getElementById(id); }
  function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }
  function txt(value) { return String(value == null ? '' : value); }
  function esc(value) {
    return txt(value).replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }
  function num(value, fallback = null) {
    if (value === null || value === undefined || value === '') return fallback;
    const n = Number(String(value).replace(/[£$,R%]/g, ''));
    return Number.isFinite(n) ? n : fallback;
  }
  function isOpen(trade) { return String(trade.status || '').toLowerCase() === 'open'; }
  function side(trade) { return String(trade.direction || trade.side || '').toLowerCase(); }
  function pairId(pair) { return String(pair || '').replace('/', '').toUpperCase(); }
  function entry(trade) { return num(trade.entry_price, num(trade.entry, num(trade.open_price, null))); }
  function sl(trade) { return num(trade.stop_loss, num(trade.sl, null)); }
  function tp(trade) { return num(trade.take_profit, num(trade.target, num(trade.tp, null))); }
  function precision(pair, value) {
    const p = String(pair || '').toUpperCase();
    if (p.includes('XAU') || p.includes('XAG')) return 2;
    if (p.includes('JPY')) return 3;
    const n = Number(value);
    return Number.isFinite(n) && Math.abs(n) >= 100 ? 3 : 5;
  }
  function price(pair, value) {
    const n = num(value, null);
    if (n === null) return '--';
    return n.toFixed(precision(pair, n));
  }
  function money(value) {
    const n = num(value, 0);
    const sign = n > 0 ? '+' : n < 0 ? '-' : '';
    return `${sign}£${Math.abs(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  function pipSize(pair) {
    const p = String(pair || '').toUpperCase();
    if (p.includes('XAU') || p.includes('XAG')) return 0.01;
    if (p.includes('JPY')) return 0.01;
    return 0.0001;
  }
  function riskMoney(trade) {
    const direct = num(trade.risk_amount, num(trade.risk_money, null));
    if (direct !== null) return direct;
    const bal = num(qs('quickTradeBalance')?.value, num(qs('scanBalance')?.value, 10000)) || 10000;
    const riskPct = num(trade.risk_pct, 0.5) || 0.5;
    return bal * (riskPct / 100);
  }

  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }
  function post(path, body) { return api(path, { method: 'POST', body: JSON.stringify(body || {}) }); }

  function installStyles() {
    if (qs('tdPreviewV2Styles')) return;
    const style = document.createElement('style');
    style.id = 'tdPreviewV2Styles';
    style.textContent = `
      body.td-preview-v2 {
        --td-bg: #050b13;
        --td-panel: rgba(11, 24, 39, .88);
        --td-panel-2: rgba(14, 30, 49, .84);
        --td-border: rgba(88, 166, 255, .20);
        --td-border-soft: rgba(148, 163, 184, .16);
        --td-blue: #58a6ff;
        --td-green: #22c55e;
        --td-red: #ff4d57;
        --td-yellow: #facc15;
      }
      body.td-preview-v2 .agent-tab[data-tab="scanner"] { display: none !important; }
      body.td-preview-v2 .agent-tab[data-tab="trades"] {
        background: linear-gradient(180deg, #f7d75a, #e9b933) !important;
        color: #07111f !important;
        border-color: rgba(255, 221, 92, .65) !important;
        box-shadow: 0 0 28px rgba(250, 204, 21, .18) !important;
      }
      body.td-preview-v2 .agent-main { max-width: none !important; width: 100% !important; }
      body.td-preview-v2 #tab-trades {
        max-width: none !important;
        width: 100% !important;
        margin: 0 !important;
        padding: 14px 18px 0 !important;
      }
      body.td-preview-v2 .td-scan-markets-btn {
        min-height: 42px !important;
        padding: 0 22px !important;
        border-radius: 10px !important;
        font-weight: 950 !important;
        background: linear-gradient(180deg, #58a6ff, #1f8bff) !important;
        color: #04111f !important;
        border: 1px solid rgba(88,166,255,.45) !important;
      }
      body.td-preview-v2 #tdPreviewShell {
        display: grid;
        gap: 14px;
        width: 100%;
      }
      body.td-preview-v2 .td-top-grid {
        display: grid;
        grid-template-columns: minmax(560px, 1.34fr) minmax(380px, .76fr) minmax(310px, .50fr);
        gap: 14px;
        align-items: stretch;
      }
      body.td-preview-v2 #tdChartHost,
      body.td-preview-v2 #tdScannerHost,
      body.td-preview-v2 #tdRightRail { min-width: 0; }
      body.td-preview-v2 #tdRightRail { display: grid; gap: 14px; align-content: start; }
      body.td-preview-v2 #agentChartPanel,
      body.td-preview-v2 #chartAccountPanel,
      body.td-preview-v2 #quickTradePanel,
      body.td-preview-v2 #tradingDeskScannerPanel,
      body.td-preview-v2 #tdMt4Panel {
        border: 1px solid var(--td-border) !important;
        background:
          radial-gradient(circle at 0 0, rgba(88, 166, 255, .16), transparent 32%),
          linear-gradient(180deg, rgba(15, 30, 49, .90), rgba(5, 13, 24, .94)) !important;
        box-shadow: 0 22px 60px rgba(0,0,0,.28) !important;
        backdrop-filter: blur(12px) saturate(125%);
        border-radius: 16px !important;
      }
      body.td-preview-v2 #agentChartPanel { margin: 0 !important; padding: 16px !important; height: 100%; }
      body.td-preview-v2 #agentChartPanel .chart-head-row h2 {
        font-size: 18px !important;
        line-height: 1.15 !important;
      }
      body.td-preview-v2 #agentChartPanel .chart-head-row h2::after { content: '' !important; display: none !important; }
      body.td-preview-v2 #agentChartPanel .chart-workspace { display: block !important; }
      body.td-preview-v2 #agentChartPanel .chart-main-panel { width: 100% !important; min-width: 0 !important; }
      body.td-preview-v2 #agentChartPanel .chart-frame {
        min-height: 470px !important;
        border-radius: 14px !important;
        overflow: hidden !important;
        background: #050d18 !important;
      }
      body.td-preview-v2 #agentChartPanel #agentLiveChart { height: 470px !important; min-height: 470px !important; }
      body.td-preview-v2 #agentChartPanel .chart-controls,
      body.td-preview-v2 #agentChartPanel .chart-toolbar,
      body.td-preview-v2 #agentChartPanel .chart-control-row {
        gap: 8px !important;
      }
      body.td-preview-v2 #agentChartPanel .chart-meta-row,
      body.td-preview-v2 #agentChartPanel .chart-status-row {
        gap: 6px !important;
        flex-wrap: wrap !important;
      }
      body.td-preview-v2 #chartAccountPanel,
      body.td-preview-v2 #quickTradePanel { margin: 0 !important; padding: 14px !important; }
      body.td-preview-v2 #chartAccountPanel .paper-account-grid,
      body.td-preview-v2 #chartAccountPanel .wallet-grid,
      body.td-preview-v2 #chartAccountPanel .account-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        gap: 8px !important;
      }
      body.td-preview-v2 #quickTradePanel input,
      body.td-preview-v2 #quickTradePanel select { min-height: 38px !important; }
      body.td-preview-v2 #quickTradePanel .quick-buttons,
      body.td-preview-v2 #quickTradePanel .quick-trade-buttons,
      body.td-preview-v2 #quickTradePanel .trade-actions { gap: 8px !important; }
      body.td-preview-v2 #tradingDeskScannerPanel { padding: 14px !important; min-height: 100%; }
      body.td-preview-v2 .td-panel-head {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 10px;
        margin-bottom: 12px;
      }
      body.td-preview-v2 .td-panel-title {
        color: #f8fafc;
        font-size: 17px;
        font-weight: 950;
        letter-spacing: -.03em;
      }
      body.td-preview-v2 .td-panel-sub {
        color: #9fb0c7;
        font-size: 11px;
        line-height: 1.35;
        margin-top: 3px;
      }
      body.td-preview-v2 .td-setups { display: grid; gap: 10px; }
      body.td-preview-v2 .td-setup-card {
        display: grid;
        grid-template-columns: 78px 74px 92px 1fr 86px;
        gap: 9px;
        align-items: center;
        padding: 11px;
        border: 1px solid var(--td-border-soft);
        border-radius: 13px;
        background: linear-gradient(180deg, rgba(10, 23, 40, .86), rgba(5, 12, 22, .82));
        box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
      }
      body.td-preview-v2 .td-pair { color: #f8fafc; font-size: 14px; font-weight: 950; }
      body.td-preview-v2 .td-dir {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: fit-content;
        padding: 5px 9px;
        border-radius: 999px;
        font-size: 10px;
        font-weight: 950;
        text-transform: uppercase;
      }
      body.td-preview-v2 .td-dir.buy { color: #4ade80; background: rgba(34,197,94,.20); border: 1px solid rgba(34,197,94,.36); }
      body.td-preview-v2 .td-dir.sell { color: #fb7185; background: rgba(248,81,73,.20); border: 1px solid rgba(248,81,73,.36); }
      body.td-preview-v2 .td-conf strong { display: block; color: #f8fafc; font-size: 22px; line-height: 1; }
      body.td-preview-v2 .td-conf span,
      body.td-preview-v2 .td-meta span,
      body.td-preview-v2 .td-level span { display: block; color: #9fb0c7; font-size: 10px; }
      body.td-preview-v2 .td-meta { color: #e5eefb; font-size: 11px; line-height: 1.3; }
      body.td-preview-v2 .td-meta strong { color: #f8fafc; }
      body.td-preview-v2 .td-meta .up { color: #22c55e; }
      body.td-preview-v2 .td-meta .down { color: #fb7185; }
      body.td-preview-v2 .td-levels {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 8px;
      }
      body.td-preview-v2 .td-level strong {
        color: #f8fafc;
        font-size: 12px;
        white-space: nowrap;
      }
      body.td-preview-v2 .td-star { color: #facc15; font-size: 16px; text-align: center; }
      body.td-preview-v2 .td-trade-btn {
        min-height: 36px !important;
        padding: 7px 14px !important;
        border-radius: 10px !important;
        font-size: 12px !important;
        font-weight: 950 !important;
      }
      body.td-preview-v2 #tdMt4Panel { padding: 14px !important; }
      body.td-preview-v2 .td-mt4-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 10px;
      }
      body.td-preview-v2 .td-mt4-actions { display: flex; align-items: center; gap: 10px; color: #9fb0c7; font-size: 12px; }
      body.td-preview-v2 .td-mt4-table-wrap { overflow-x: auto; border: 1px solid rgba(148,163,184,.14); border-radius: 12px; }
      body.td-preview-v2 .td-mt4-table { width: 100%; min-width: 1120px; border-collapse: collapse; font-size: 12px; }
      body.td-preview-v2 .td-mt4-table th {
        padding: 9px 10px;
        color: #bfd0e7;
        text-align: left;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: .04em;
        background: rgba(35, 57, 83, .78);
      }
      body.td-preview-v2 .td-mt4-table td {
        padding: 9px 10px;
        border-top: 1px solid rgba(148,163,184,.12);
        color: #d7e3f3;
        white-space: nowrap;
      }
      body.td-preview-v2 .td-mt4-table tfoot td { background: rgba(88,166,255,.08); font-weight: 950; }
      body.td-preview-v2 .td-pos { color: #22c55e !important; font-weight: 950; }
      body.td-preview-v2 .td-neg { color: #ff4d57 !important; font-weight: 950; }
      body.td-preview-v2 .td-close-btn { min-height: 28px !important; height: 28px !important; padding: 4px 14px !important; border-radius: 8px !important; font-size: 11px !important; }
      body.td-preview-v2 .td-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        color: #9fb0c7;
        font-size: 12px;
        padding: 10px 6px 0;
      }
      body.td-preview-v2 .td-footer span { display: inline-flex; align-items: center; gap: 7px; margin-right: 16px; }
      body.td-preview-v2 .td-live-dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 12px rgba(34,197,94,.7); }
      body.td-preview-v2 #tab-trades > .agent-card:not(#agentChartPanel):not(#dashboardTradeJournalCard) { display: none !important; }
      body.td-preview-v2 #dashboardTradeJournalCard { margin-top: 16px !important; }
      @media (max-width: 1500px) {
        body.td-preview-v2 .td-top-grid { grid-template-columns: minmax(0, 1fr) minmax(330px, .48fr); }
        body.td-preview-v2 #tdScannerHost { grid-column: 1 / -1; grid-row: 2; }
        body.td-preview-v2 #tdRightRail { grid-column: 2; grid-row: 1; }
        body.td-preview-v2 #tdChartHost { grid-column: 1; grid-row: 1; }
        body.td-preview-v2 #tradingDeskScannerPanel { min-height: auto; }
        body.td-preview-v2 .td-setups { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
      @media (max-width: 1050px) {
        body.td-preview-v2 #tab-trades { padding: 10px !important; }
        body.td-preview-v2 .td-top-grid { grid-template-columns: 1fr; }
        body.td-preview-v2 #tdChartHost,
        body.td-preview-v2 #tdScannerHost,
        body.td-preview-v2 #tdRightRail { grid-column: 1; grid-row: auto; }
        body.td-preview-v2 .td-setups { grid-template-columns: 1fr; }
        body.td-preview-v2 .td-setup-card { grid-template-columns: 1fr 70px; }
        body.td-preview-v2 .td-conf, body.td-preview-v2 .td-meta, body.td-preview-v2 .td-levels { grid-column: 1 / -1; }
        body.td-preview-v2 #agentChartPanel .chart-frame { min-height: 380px !important; }
        body.td-preview-v2 #agentChartPanel #agentLiveChart { height: 380px !important; min-height: 380px !important; }
      }
    `;
    document.head.appendChild(style);
  }

  function setupNav() {
    document.body.classList.add('td-preview-v2');
    const tradingTab = document.querySelector('.agent-tab[data-tab="trades"]');
    if (tradingTab) tradingTab.textContent = 'Trading';
    const scannerTab = document.querySelector('.agent-tab[data-tab="scanner"]');
    if (scannerTab) scannerTab.setAttribute('aria-hidden', 'true');

    const actions = document.querySelector('.agent-actions');
    if (actions && !qs('tdScanMarketsBtn')) {
      const btn = document.createElement('button');
      btn.id = 'tdScanMarketsBtn';
      btn.className = 'btn-primary td-scan-markets-btn';
      btn.textContent = '▶ SCAN MARKETS';
      btn.addEventListener('click', async () => {
        if (typeof window.switchTab === 'function') window.switchTab('trades');
        await runScanFromPreview();
      });
      const kill = qs('killSwitchBtn');
      if (kill && kill.parentElement === actions) actions.insertBefore(btn, kill.nextSibling);
      else actions.appendChild(btn);
    }
  }

  function moveJournalToDashboard() {
    const dashboard = qs('tab-dashboard');
    const journalPanel = qs('tradeJournalPanel');
    const journalCard = journalPanel?.closest('.agent-card');
    if (!dashboard || !journalCard || qs('dashboardTradeJournalCard')) return;
    journalCard.id = 'dashboardTradeJournalCard';
    journalCard.classList.add('td-dashboard-journal-card');
    const title = journalCard.querySelector('h2');
    if (title) title.textContent = 'Trade Journal - All Paper Trades';
    dashboard.appendChild(journalCard);
  }

  function hideLooseTradeCards() {
    const trades = qs('tab-trades');
    if (!trades) return;
    qsa(':scope > .agent-card', trades).forEach(card => {
      if (card.id === 'agentChartPanel') return;
      if (card.id === 'dashboardTradeJournalCard') return;
      const text = (card.querySelector('h2')?.textContent || '').toLowerCase();
      if (text.includes('testing tools') || text.includes('open paper trades') || text.includes('post-trade')) {
        card.style.display = 'none';
      }
    });
  }

  function ensureShell() {
    const tab = qs('tab-trades');
    const chartPanel = qs('agentChartPanel');
    if (!tab || !chartPanel) return false;

    let shell = qs('tdPreviewShell');
    if (!shell) {
      shell = document.createElement('div');
      shell.id = 'tdPreviewShell';
      shell.innerHTML = `
        <div class="td-top-grid">
          <div id="tdChartHost"></div>
          <div id="tdScannerHost"></div>
          <div id="tdRightRail"></div>
        </div>
        <div id="tdMt4Panel"></div>
        <div class="td-footer">
          <div><span>AI FX Trading Agent v1.0.0</span><span>Paper Trading Mode</span><span>Powered by OANDA</span></div>
          <div><span><i class="td-live-dot"></i>Live Data</span><span>OANDA</span><span>All times UTC+1</span></div>
        </div>`;
      tab.insertBefore(shell, tab.firstChild);
    }

    const chartHost = qs('tdChartHost');
    if (chartHost && chartPanel.parentElement !== chartHost) chartHost.appendChild(chartPanel);

    const rightRail = qs('tdRightRail');
    const account = qs('chartAccountPanel');
    const quick = qs('quickTradePanel');
    if (rightRail && account && account.parentElement !== rightRail) rightRail.appendChild(account);
    if (rightRail && quick && quick.parentElement !== rightRail) rightRail.appendChild(quick);

    const scannerHost = qs('tdScannerHost');
    if (scannerHost && !qs('tradingDeskScannerPanel')) {
      const scanner = document.createElement('aside');
      scanner.id = 'tradingDeskScannerPanel';
      scannerHost.appendChild(scanner);
    } else if (scannerHost) {
      const scanner = qs('tradingDeskScannerPanel');
      if (scanner && scanner.parentElement !== scannerHost) scannerHost.appendChild(scanner);
    }

    tuneChartTitle();
    renderTradingScannerPanel();
    renderMt4Shell();
    hideLooseTradeCards();
    return true;
  }

  function tuneChartTitle() {
    const title = qs('agentChartPanel')?.querySelector('h2');
    const pair = qs('chartPair')?.value || 'GBP/JPY';
    if (title) title.innerHTML = `Live Chart - ${esc(pair)}`;
  }

  function currentScanResults() {
    try { if (typeof lastScanResults !== 'undefined' && lastScanResults) return lastScanResults; } catch (_) {}
    return window.lastScanResults || null;
  }

  function candidateFromRaw(raw) {
    return {
      pair: raw.pair || raw.symbol || 'GBP/JPY',
      direction: raw.direction || raw.side || 'buy',
      confidence: num(raw.confidence, 0),
      trend: raw.trend || raw.trend_label || (String(raw.direction || '').toLowerCase() === 'sell' ? 'Down' : 'Up'),
      session: raw.session || raw.trading_session || 'Off-session',
      entry: num(raw.entry, num(raw.entry_price, null)),
      stop_loss: num(raw.stop_loss, num(raw.sl, null)),
      take_profit: num(raw.take_profit, num(raw.tp, num(raw.target, null))),
      risk_reward: num(raw.rr_estimate, num(raw.risk_reward, num(raw.rr, 0)))
    };
  }

  function candidateCard(raw) {
    const c = candidateFromRaw(raw);
    const dir = String(c.direction || '').toLowerCase() || 'buy';
    const trendClass = String(c.trend || '').toLowerCase().includes('down') ? 'down' : String(c.trend || '').toLowerCase().includes('up') ? 'up' : '';
    const trendArrow = trendClass === 'down' ? ' ↓' : trendClass === 'up' ? ' ↑' : ' →';
    return `
      <article class="td-setup-card">
        <div><div class="td-pair">${esc(pairId(c.pair))}</div><span class="td-dir ${esc(dir)}">${esc(dir)}</span></div>
        <div class="td-conf"><strong>${Math.round(c.confidence || 0)}%</strong><span>Confidence</span></div>
        <div class="td-meta"><span>Trend</span><strong class="${trendClass}">${esc(c.trend)}${trendArrow}</strong><br><span>Session</span><strong>${esc(c.session)}</strong></div>
        <div class="td-levels">
          <div class="td-level"><span>Entry</span><strong>${price(c.pair, c.entry)}</strong></div>
          <div class="td-level"><span>SL</span><strong>${price(c.pair, c.stop_loss)}</strong></div>
          <div class="td-level"><span>TP</span><strong>${price(c.pair, c.take_profit)}</strong></div>
          <div class="td-level"><span>RR</span><strong>${(num(c.risk_reward, 0) || 0).toFixed(1)}R</strong></div>
        </div>
        <div class="td-star">★</div>
        <button class="btn-primary td-trade-btn" data-td-trade-pair="${esc(c.pair)}">Trade</button>
      </article>`;
  }

  function renderTradingScannerPanel() {
    const panel = qs('tradingDeskScannerPanel');
    if (!panel) return;
    const data = currentScanResults();
    const liveCandidates = (data && Array.isArray(data.candidates) && data.candidates.length) ? data.candidates : [];
    const setups = (liveCandidates.length ? liveCandidates : FALLBACK_SETUPS).slice(0, 4);
    const subtitle = liveCandidates.length ? `Last scan: ${liveCandidates.length} approved setup${liveCandidates.length === 1 ? '' : 's'}` : 'High-probability trade candidates from the AI model';
    panel.innerHTML = `
      <div class="td-panel-head">
        <div><div class="td-panel-title">AI Scanner / Approved Setups</div><div class="td-panel-sub">${esc(subtitle)}</div></div>
        <button class="btn-secondary" id="tdRunScanBtn">View All Setups →</button>
      </div>
      <div class="td-setups">${setups.map(candidateCard).join('')}</div>`;

    qs('tdRunScanBtn')?.addEventListener('click', runScanFromPreview);
    qsa('[data-td-trade-pair]', panel).forEach(btn => {
      btn.addEventListener('click', () => {
        const pair = btn.getAttribute('data-td-trade-pair');
        if (typeof window.executeTrade === 'function') window.executeTrade(pair);
        else if (typeof executeTrade === 'function') executeTrade(pair);
      });
    });
  }

  async function runScanFromPreview() {
    const btn = qs('tdRunScanBtn') || qs('tdScanMarketsBtn');
    const oldText = btn?.textContent;
    if (btn) btn.textContent = 'Scanning...';
    try {
      if (typeof window.runScan === 'function') await window.runScan();
      else if (typeof runScan === 'function') await runScan();
    } catch (e) {
      console.warn('Trading preview scan failed', e);
    } finally {
      if (btn && oldText) btn.textContent = oldText;
      setTimeout(renderTradingScannerPanel, 250);
    }
  }

  function closePriceForTrade(trade, quote) {
    if (!quote) return num(trade.current_price, num(trade.market_price, entry(trade)));
    const dir = side(trade);
    if (dir === 'buy') return num(quote.bid, num(quote.price, num(quote.mid, entry(trade))));
    if (dir === 'sell') return num(quote.ask, num(quote.price, num(quote.mid, entry(trade))));
    return num(quote.price, num(quote.mid, entry(trade)));
  }
  function resultForTrade(trade, current) {
    if (!isOpen(trade)) return { r: num(trade.result_r, 0), money: num(trade.result_money, num(trade.pnl, 0)) };
    const ent = entry(trade);
    const stop = sl(trade);
    if (ent === null || stop === null || current === null || ent === stop) return { r: 0, money: 0 };
    const move = side(trade) === 'sell' ? ent - current : current - ent;
    const r = move / Math.abs(ent - stop);
    return { r, money: r * riskMoney(trade) };
  }

  async function loadTrades() {
    const data = await api('/api/agent/trades');
    return Array.isArray(data) ? data : (data.trades || data.items || []);
  }
  async function quoteMap(trades) {
    const pairs = Array.from(new Set((trades || []).filter(isOpen).map(t => t.pair).filter(Boolean)));
    const entries = await Promise.all(pairs.map(async pair => {
      try { return [pair, await api(`/api/agent/chart/tick?pair=${encodeURIComponent(pair)}`)]; }
      catch (_) { return [pair, null]; }
    }));
    return Object.fromEntries(entries);
  }

  function renderMt4Shell() {
    const panel = qs('tdMt4Panel');
    if (!panel || panel.dataset.ready === '1') return;
    panel.dataset.ready = '1';
    panel.innerHTML = `
      <div class="td-mt4-top">
        <div><div class="td-panel-title">Open Positions (MT4-Style)</div><div class="td-panel-sub">Live paper trades · Real-time P/L · Manage your positions</div></div>
        <div class="td-mt4-actions"><label><input type="checkbox" id="tdShowClosed"> Show closed positions</label><button class="btn-secondary" id="tdMt4Refresh">Refresh</button></div>
      </div>
      <div class="td-mt4-table-wrap">
        <table class="td-mt4-table">
          <thead><tr><th>Symbol</th><th>Ticket</th><th>Time (UTC+1)</th><th>Type</th><th>Size (lots)</th><th>Price</th><th>SL</th><th>TP</th><th>Current</th><th>Swap</th><th>Commission</th><th>Profit (GBP)</th><th>Pips</th><th>Actions</th></tr></thead>
          <tbody id="tdMt4Rows"><tr><td colspan="14" class="muted">Loading open positions...</td></tr></tbody>
        </table>
      </div>`;
    qs('tdMt4Refresh')?.addEventListener('click', refreshMt4Panel);
    qs('tdShowClosed')?.addEventListener('change', refreshMt4Panel);
    refreshMt4Panel();
    if (!mt4Timer) mt4Timer = setInterval(refreshMt4Panel, 15000);
  }

  function renderRows(trades, quotes) {
    const showClosed = !!qs('tdShowClosed')?.checked;
    const rows = (trades || []).filter(t => showClosed || isOpen(t)).slice(0, 12);
    if (!rows.length) return '<tr><td colspan="14" class="muted">No open positions.</td></tr>';
    let totalMoney = 0;
    let totalPips = 0;
    const body = rows.map(trade => {
      const p = trade.pair || '';
      const ent = entry(trade);
      const current = isOpen(trade) ? closePriceForTrade(trade, quotes[p]) : num(trade.close_price, num(trade.exit_price, num(trade.current_price, ent)));
      const res = resultForTrade(trade, current);
      const sizeUnits = num(trade.position_units, num(trade.fixed_units, num(trade.units, 0))) || 0;
      const lots = sizeUnits ? (Math.abs(sizeUnits) / 100000).toFixed(2) : '--';
      const pipMove = ent !== null && current !== null ? ((side(trade) === 'sell' ? ent - current : current - ent) / pipSize(p)) : 0;
      totalMoney += res.money;
      totalPips += pipMove;
      const moneyClass = res.money >= 0 ? 'td-pos' : 'td-neg';
      const pipClass = pipMove >= 0 ? 'td-pos' : 'td-neg';
      return `<tr>
        <td><strong>${esc(p)}</strong></td>
        <td>${esc(String(trade.id || '').slice(0, 8))}</td>
        <td>${esc((trade.filled_at || trade.created_at || '').slice(0, 16).replace('T', ' '))}</td>
        <td><span class="td-dir ${esc(side(trade))}">${esc(side(trade) || '--')}</span></td>
        <td>${lots}</td><td>${price(p, ent)}</td><td>${price(p, sl(trade))}</td><td>${price(p, tp(trade))}</td><td>${price(p, current)}</td>
        <td>0.00</td><td>0.00</td><td class="${moneyClass}">${money(res.money)}</td><td class="${pipClass}">${pipMove >= 0 ? '+' : ''}${pipMove.toFixed(1)}</td>
        <td>${isOpen(trade) ? `<button class="btn-secondary td-close-btn" data-td-close="${esc(trade.id)}">Close</button>` : '<span class="muted">Closed</span>'}</td>
      </tr>`;
    }).join('');
    const totalClass = totalMoney >= 0 ? 'td-pos' : 'td-neg';
    const pipClass = totalPips >= 0 ? 'td-pos' : 'td-neg';
    return `${body}<tfoot><tr><td colspan="4"><strong>Total</strong></td><td>${rows.length}</td><td colspan="6"></td><td class="${totalClass}">${money(totalMoney)}</td><td class="${pipClass}">${totalPips >= 0 ? '+' : ''}${totalPips.toFixed(1)}</td><td></td></tr></tfoot>`;
  }

  async function refreshMt4Panel() {
    const body = qs('tdMt4Rows');
    if (!body) return;
    try {
      const trades = await loadTrades();
      const quotes = await quoteMap(trades);
      body.innerHTML = renderRows(trades, quotes);
      qsa('[data-td-close]', body).forEach(btn => {
        btn.addEventListener('click', async () => {
          const id = btn.getAttribute('data-td-close');
          if (!id || !confirm('Close this paper trade at the latest market quote?')) return;
          btn.disabled = true;
          try { await post(`/api/agent/trades/${encodeURIComponent(id)}/quick-close`, { reason: 'Quick close from Trading Desk preview' }); }
          catch (e) { alert(`Close failed: ${e.message}`); }
          finally {
            await refreshMt4Panel();
            if (typeof window.loadAgentChart === 'function') window.loadAgentChart();
          }
        });
      });
    } catch (e) {
      body.innerHTML = `<tr><td colspan="14" class="muted">Unable to load positions: ${esc(e.message || e)}</td></tr>`;
    }
  }

  function patchRunScan() {
    if (patchedRunScan) return;
    const fn = window.runScan || (typeof runScan === 'function' ? runScan : null);
    if (typeof fn !== 'function') return;
    patchedRunScan = true;
    window.runScan = async function tdPreviewRunScan(...args) {
      const result = await fn.apply(this, args);
      setTimeout(renderTradingScannerPanel, 250);
      return result;
    };
  }

  function patchLoadChart() {
    if (patchedLoadChart || typeof window.loadAgentChart !== 'function') return;
    const original = window.loadAgentChart;
    patchedLoadChart = true;
    window.loadAgentChart = async function tdPreviewLoadChart(...args) {
      const result = await original.apply(this, args);
      tuneChartTitle();
      return result;
    };
  }

  function init() {
    installStyles();
    setupNav();
    moveJournalToDashboard();
    patchRunScan();
    patchLoadChart();
    ensureShell();

    let tries = 0;
    if (!initTimer) {
      initTimer = setInterval(() => {
        tries += 1;
        installStyles();
        setupNav();
        moveJournalToDashboard();
        patchRunScan();
        patchLoadChart();
        const ready = ensureShell();
        if (ready || tries > 80) {
          clearInterval(initTimer);
          initTimer = null;
        }
      }, 250);
    }
    if (!scannerTimer) scannerTimer = setInterval(renderTradingScannerPanel, 12000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
