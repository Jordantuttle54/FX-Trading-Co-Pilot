/* agent_trading_preview.js - integrated Trading Desk preview branch */
'use strict';

(function () {
  if (window.__agentTradingPreviewInstalled) return;
  window.__agentTradingPreviewInstalled = true;

  let mt4Timer = null;
  let scannerTimer = null;
  let runScanPatched = false;

  function qs(id) { return document.getElementById(id); }
  function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }
  function esc(v) { return String(v ?? '').replace(/[&<>'\"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '\"': '&quot;' }[c])); }
  function num(v, fb = null) {
    if (v === null || v === undefined || v === '') return fb;
    const n = Number(String(v).replace(/[£$,R%]/g, ''));
    return Number.isFinite(n) ? n : fb;
  }
  function isOpen(t) { return String(t.status || '').toLowerCase() === 'open'; }
  function side(t) { return String(t.direction || t.side || '').toLowerCase(); }
  function pairId(pair) { return String(pair || '').replace('/', '').toUpperCase(); }
  function entry(t) { return num(t.entry_price, num(t.entry, num(t.open_price, null))); }
  function sl(t) { return num(t.stop_loss, num(t.sl, null)); }
  function tp(t) { return num(t.take_profit, num(t.target, num(t.tp, null))); }

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
  function riskMoney(t) {
    const direct = num(t.risk_amount, num(t.risk_money, null));
    if (direct !== null) return direct;
    const balance = num(t.account_balance, num(qs('quickTradeBalance')?.value, num(qs('scanBalance')?.value, 10000))) || 10000;
    const riskPct = num(t.risk_pct, 0.5) || 0.5;
    return balance * (riskPct / 100);
  }

  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }
  function post(path, body) { return api(path, { method: 'POST', body: JSON.stringify(body || {}) }); }

  function installStyles() {
    if (qs('agentTradingPreviewStyles')) return;
    const style = document.createElement('style');
    style.id = 'agentTradingPreviewStyles';
    style.textContent = `
      body.td-preview-enabled .agent-tab[data-tab="scanner"] { display: none !important; }
      body.td-preview-enabled .agent-tab[data-tab="trades"] { background: linear-gradient(180deg, #58a6ff, #2f81f7) !important; color: #031224 !important; box-shadow: 0 0 28px rgba(88,166,255,.22) !important; }
      body.td-preview-enabled #tab-trades { max-width: 1880px; margin: 0 auto; }
      body.td-preview-enabled #openTradesDetailCard,
      body.td-preview-enabled #postTradeReviewsCard { display: none !important; }
      body.td-preview-enabled #agentChartPanel { padding: 16px !important; }
      body.td-preview-enabled #agentChartPanel .chart-head-row h2::after { content: ' - Trading Desk Preview'; color: #58a6ff; font-size: 12px; font-weight: 900; margin-left: 8px; }
      body.td-preview-enabled #agentChartPanel .chart-workspace {
        grid-template-columns: minmax(0, 1.15fr) minmax(330px, .58fr) !important;
        gap: 14px !important;
        align-items: start !important;
      }
      body.td-preview-enabled #agentChartPanel .chart-main-panel { min-width: 0 !important; }
      body.td-preview-enabled #agentChartPanel .chart-frame { min-height: 500px !important; }
      body.td-preview-enabled #agentChartPanel #agentLiveChart { height: 500px !important; }
      .td-scanner-panel, .td-mt4-panel, .td-dashboard-journal-card {
        border: 1px solid rgba(88,166,255,.18);
        background: radial-gradient(circle at 0 0, rgba(88,166,255,.11), transparent 30%), linear-gradient(180deg, rgba(15,23,42,.88), rgba(6,11,20,.94));
        border-radius: 16px;
        box-shadow: 0 22px 60px rgba(0,0,0,.26);
        backdrop-filter: blur(12px) saturate(125%);
      }
      .td-scanner-panel { margin-top: 14px; padding: 14px; }
      .td-panel-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 12px; }
      .td-panel-title { font-size: 16px; font-weight: 950; color: #f8fafc; letter-spacing: -.03em; }
      .td-panel-sub { color: var(--muted, #9fb0c7); font-size: 11px; margin-top: 3px; line-height: 1.35; }
      .td-panel-actions { display: flex; gap: 8px; align-items: center; }
      .td-setup-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; }
      .td-setup-card {
        display: grid;
        grid-template-columns: minmax(78px,.7fr) minmax(70px,.55fr) minmax(92px,.72fr) auto;
        gap: 10px;
        align-items: center;
        border: 1px solid rgba(148,163,184,.18);
        border-radius: 13px;
        background: linear-gradient(180deg, rgba(15,23,42,.78), rgba(7,13,24,.82));
        padding: 11px;
      }
      .td-setup-pair { font-size: 14px; font-weight: 950; color: #f8fafc; }
      .td-dir { display: inline-flex; width: fit-content; border-radius: 999px; padding: 5px 9px; font-size: 10px; font-weight: 950; text-transform: uppercase; }
      .td-dir.buy { background: rgba(34,197,94,.20); color: #4ade80; border: 1px solid rgba(34,197,94,.35); }
      .td-dir.sell { background: rgba(248,81,73,.20); color: #fb7185; border: 1px solid rgba(248,81,73,.35); }
      .td-conf strong { display: block; font-size: 20px; line-height: 1; color: #f8fafc; }
      .td-conf span, .td-meta span, .td-level span { display: block; color: var(--muted, #9fb0c7); font-size: 10px; }
      .td-meta { font-size: 11px; color: #d7e3f3; line-height: 1.35; }
      .td-levels { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 6px; grid-column: 1 / -1; padding: 8px; border: 1px solid rgba(148,163,184,.15); border-radius: 10px; background: rgba(2,6,23,.32); }
      .td-level strong { display: block; color: #f8fafc; font-size: 11px; white-space: nowrap; }
      .td-trade-btn { min-height: 36px !important; padding: 7px 13px !important; font-size: 11px !important; border-radius: 10px !important; font-weight: 950 !important; }
      .td-rejected-mini { margin-top: 13px; padding-top: 12px; border-top: 1px solid rgba(148,163,184,.16); }
      .td-rejected-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 9px; margin-top: 8px; }
      .td-reject-card { border: 1px solid rgba(248,81,73,.16); border-radius: 12px; padding: 10px; background: rgba(15,23,42,.55); min-width: 0; }
      .td-reject-card strong { display: block; color: #f8fafc; font-size: 13px; }
      .td-reject-card p { margin: 5px 0 0; font-size: 10px; color: #aebbd1; line-height: 1.35; overflow-wrap: anywhere; }
      .td-mt4-panel { margin-top: 14px; padding: 14px; }
      .td-mt4-top { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 10px; }
      .td-mt4-table-wrap { overflow-x: auto; border-radius: 12px; border: 1px solid rgba(148,163,184,.14); }
      .td-mt4-table { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 1120px; }
      .td-mt4-table th { text-align: left; padding: 9px 10px; color: #bfd0e7; background: rgba(44,58,78,.72); font-size: 10px; text-transform: uppercase; letter-spacing: .04em; }
      .td-mt4-table td { padding: 9px 10px; border-top: 1px solid rgba(148,163,184,.13); color: #d7e3f3; white-space: nowrap; }
      .td-mt4-table tfoot td { font-weight: 950; background: rgba(88,166,255,.08); }
      .td-pos { color: #22c55e !important; font-weight: 950; }
      .td-neg { color: #ef4444 !important; font-weight: 950; }
      .td-close-btn { min-height: 28px !important; height: 28px !important; padding: 4px 12px !important; font-size: 11px !important; border-radius: 8px !important; }
      .td-dashboard-journal-card { margin-top: 16px; padding: 14px; }
      .td-dashboard-journal-card .trade-table { font-size: 11px; }
      @media (max-width: 1450px) {
        body.td-preview-enabled #agentChartPanel .chart-workspace { grid-template-columns: 1fr minmax(330px, .52fr) !important; }
        body.td-preview-enabled #agentChartPanel .chart-frame { min-height: 390px !important; }
        body.td-preview-enabled #agentChartPanel #agentLiveChart { height: 390px !important; }
      }
      @media (max-width: 1050px) {
        body.td-preview-enabled #agentChartPanel .chart-workspace { grid-template-columns: 1fr !important; }
      }
    `;
    document.head.appendChild(style);
  }

  function setupNav() {
    document.body.classList.add('td-preview-enabled');
    const tradingTab = document.querySelector('.agent-tab[data-tab="trades"]');
    if (tradingTab) tradingTab.textContent = 'Trading Desk';
  }

  function hideOldCards() {
    const openTrades = qs('openTradesDetail')?.closest('.agent-card');
    if (openTrades) openTrades.id = 'openTradesDetailCard';
    const reviews = qs('reviewResult')?.closest('.agent-card');
    if (reviews) reviews.id = 'postTradeReviewsCard';
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

  function currentScanResults() {
    try { if (typeof lastScanResults !== 'undefined' && lastScanResults) return lastScanResults; } catch (_) {}
    return window.lastScanResults || null;
  }

  function candidateCard(c) {
    const dir = side(c) || 'buy';
    const pair = c.pair || '';
    const conf = Math.round(num(c.confidence, 0));
    const trend = c.trend || c.trend_label || (dir === 'sell' ? 'Down' : 'Up');
    const session = c.session || 'Off-session';
    return `
      <article class="td-setup-card">
        <div><div class="td-setup-pair">${esc(pairId(pair))}</div><span class="td-dir ${esc(dir)}">${esc(dir)}</span></div>
        <div class="td-conf"><strong>${conf}%</strong><span>Confidence</span></div>
        <div class="td-meta"><span>Trend</span><strong>${esc(trend)}</strong><br><span>Session</span><strong>${esc(session)}</strong></div>
        <button class="btn-primary td-trade-btn" data-td-trade-pair="${esc(pair)}">Trade</button>
        <div class="td-levels">
          <div class="td-level"><span>Entry</span><strong>${price(pair, c.entry)}</strong></div>
          <div class="td-level"><span>SL</span><strong>${price(pair, c.stop_loss)}</strong></div>
          <div class="td-level"><span>TP</span><strong>${price(pair, c.take_profit)}</strong></div>
          <div class="td-level"><span>RR</span><strong>${(num(c.rr_estimate, num(c.risk_reward, 0)) || 0).toFixed(1)}R</strong></div>
        </div>
      </article>`;
  }

  function renderTradingScannerPanel() {
    const panel = qs('tradingDeskScannerPanel');
    if (!panel) return;
    const data = currentScanResults();
    const candidates = (data && data.candidates) || [];
    const rejected = ((data && data.rejected) || []).slice(0, 3);
    const approvedHtml = candidates.length
      ? candidates.slice(0, 4).map(candidateCard).join('')
      : '<div class="muted small">Run a scan from here to bring approved setups into the Trading Desk.</div>';
    const rejectedHtml = rejected.length
      ? `<div class="td-rejected-grid">${rejected.map(r => `<div class="td-reject-card"><strong>${esc(pairId(r.pair))}</strong><p>${esc(r.rejection_reason || r.entry_reason || 'Rejected by scanner rules.')}</p></div>`).join('')}</div>`
      : '<div class="muted small">Rejected setups will appear here after a scan.</div>';
    panel.innerHTML = `
      <div class="td-panel-head">
        <div><div class="td-panel-title">AI Scanner / Approved Setups</div><div class="td-panel-sub">Integrated scanner preview inside the Trading Desk</div></div>
        <div class="td-panel-actions"><button class="btn-secondary" id="tdRunScanBtn">Run Scan</button></div>
      </div>
      <div class="td-setup-list">${approvedHtml}</div>
      <div class="td-rejected-mini"><div class="td-panel-title" style="font-size:13px">Lower Confidence / Rejected Setups</div>${rejectedHtml}</div>`;
    qs('tdRunScanBtn')?.addEventListener('click', async () => {
      const btn = qs('tdRunScanBtn');
      if (btn) btn.textContent = 'Scanning...';
      try {
        if (typeof window.runScan === 'function') await window.runScan();
        else if (typeof runScan === 'function') await runScan();
      } finally {
        setTimeout(renderTradingScannerPanel, 350);
      }
    });
    qsa('[data-td-trade-pair]', panel).forEach(btn => {
      btn.addEventListener('click', () => {
        const pair = btn.getAttribute('data-td-trade-pair');
        if (typeof window.executeTrade === 'function') window.executeTrade(pair);
        else if (typeof executeTrade === 'function') executeTrade(pair);
      });
    });
  }

  function ensureTradingScannerPanel() {
    const tab = qs('tab-trades');
    const chartPanel = qs('agentChartPanel');
    if (!tab || !chartPanel) return false;
    let panel = qs('tradingDeskScannerPanel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'tradingDeskScannerPanel';
      panel.className = 'td-scanner-panel';
      chartPanel.insertAdjacentElement('afterend', panel);
    }
    renderTradingScannerPanel();
    return true;
  }

  function patchRunScan() {
    if (runScanPatched) return;
    const fn = window.runScan || (typeof runScan === 'function' ? runScan : null);
    if (typeof fn !== 'function') return;
    runScanPatched = true;
    const wrapped = async function tdPreviewRunScan(...args) {
      const result = await fn.apply(this, args);
      setTimeout(renderTradingScannerPanel, 150);
      return result;
    };
    window.runScan = wrapped;
  }

  function closePriceForTrade(trade, quote) {
    if (!quote) return num(trade.current_price, num(trade.market_price, entry(trade)));
    const dir = side(trade);
    if (dir === 'buy') return num(quote.bid, num(quote.price, num(quote.mid, entry(trade))));
    if (dir === 'sell') return num(quote.ask, num(quote.price, num(quote.mid, entry(trade))));
    return num(quote.price, num(quote.mid, entry(trade)));
  }
  function resultForTrade(t, current) {
    if (!isOpen(t)) return { r: num(t.result_r, 0), money: num(t.result_money, num(t.pnl, 0)) };
    const ent = entry(t);
    const stop = sl(t);
    if (ent === null || stop === null || current === null || ent === stop) return { r: 0, money: 0 };
    const move = side(t) === 'sell' ? ent - current : current - ent;
    const r = move / Math.abs(ent - stop);
    return { r, money: r * riskMoney(t) };
  }
  async function loadTradesForMt4() {
    const data = await api('/api/agent/trades');
    return Array.isArray(data) ? data : (data.trades || data.items || []);
  }
  async function quoteMap(trades) {
    const pairs = Array.from(new Set((trades || []).filter(isOpen).map(t => t.pair).filter(Boolean)));
    const pairsWithQuotes = await Promise.all(pairs.map(async p => {
      try { return [p, await api(`/api/agent/chart/tick?pair=${encodeURIComponent(p)}`)]; } catch (_) { return [p, null]; }
    }));
    return Object.fromEntries(pairsWithQuotes);
  }
  function renderMt4Rows(trades, quotes) {
    const open = (trades || []).filter(isOpen);
    if (!open.length) return '<tr><td colspan="14" class="muted">No open positions.</td></tr>';
    let totalMoney = 0;
    let totalPips = 0;
    const rows = open.map(t => {
      const p = t.pair || '';
      const current = closePriceForTrade(t, quotes[p]);
      const res = resultForTrade(t, current);
      totalMoney += res.money;
      const ent = entry(t) || 0;
      const pipMove = side(t) === 'sell' ? (ent - current) / pipSize(p) : (current - ent) / pipSize(p);
      totalPips += pipMove;
      const units = num(t.position_units, num(t.fixed_units, 0));
      const lots = units ? (units / 100000).toFixed(2) : '--';
      const cls = res.money >= 0 ? 'td-pos' : 'td-neg';
      const pipCls = pipMove >= 0 ? 'td-pos' : 'td-neg';
      return `<tr>
        <td><strong>${esc(p)}</strong></td><td>${esc(String(t.id || '').slice(0,8))}</td><td>${esc((t.filled_at || t.created_at || '').slice(0,16).replace('T',' '))}</td>
        <td><span class="td-dir ${esc(side(t))}">${esc(side(t) || '')}</span></td><td>${lots}</td>
        <td>${price(p, ent)}</td><td>${price(p, sl(t))}</td><td>${price(p, tp(t))}</td><td><strong>${price(p, current)}</strong></td>
        <td>0.00</td><td>0.00</td><td class="${cls}">${money(res.money)}</td><td class="${pipCls}">${pipMove >= 0 ? '+' : ''}${pipMove.toFixed(1)}</td>
        <td><button class="btn-secondary td-close-btn" data-td-close="${esc(t.id)}">Close</button></td>
      </tr>`;
    }).join('');
    const totalCls = totalMoney >= 0 ? 'td-pos' : 'td-neg';
    const totalPipCls = totalPips >= 0 ? 'td-pos' : 'td-neg';
    return `${rows}<tfoot><tr><td colspan="4"><strong>Total</strong></td><td colspan="7">${open.length} position${open.length === 1 ? '' : 's'}</td><td class="${totalCls}">${money(totalMoney)}</td><td class="${totalPipCls}">${totalPips >= 0 ? '+' : ''}${totalPips.toFixed(1)}</td><td></td></tr></tfoot>`;
  }
  async function refreshMt4Panel() {
    const body = qs('tdMt4Rows');
    if (!body) return;
    try {
      const trades = await loadTradesForMt4();
      const quotes = await quoteMap(trades);
      body.innerHTML = renderMt4Rows(trades, quotes);
      qsa('[data-td-close]').forEach(btn => {
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
      body.innerHTML = `<tr><td colspan="14" class="muted">Unable to load open positions: ${esc(e.message || e)}</td></tr>`;
    }
  }
  function ensureMt4Panel() {
    const tab = qs('tab-trades');
    const chartPanel = qs('agentChartPanel');
    if (!tab || !chartPanel) return false;
    if (!qs('tdMt4Panel')) {
      const panel = document.createElement('div');
      panel.id = 'tdMt4Panel';
      panel.className = 'td-mt4-panel';
      panel.innerHTML = `
        <div class="td-mt4-top">
          <div><div class="td-panel-title">Open Positions (MT4-Style)</div><div class="td-panel-sub">Live paper trades - close-side P/L - manage positions</div></div>
          <div class="td-panel-actions"><button class="btn-secondary" id="tdMt4Refresh">Refresh</button></div>
        </div>
        <div class="td-mt4-table-wrap"><table class="td-mt4-table"><thead><tr>
          <th>Symbol</th><th>Ticket</th><th>Time</th><th>Type</th><th>Size</th><th>Price</th><th>SL</th><th>TP</th><th>Current</th><th>Swap</th><th>Commission</th><th>Profit (GBP)</th><th>Pips</th><th>Actions</th>
        </tr></thead><tbody id="tdMt4Rows"><tr><td colspan="14" class="muted">Loading open positions...</td></tr></tbody></table></div>`;
      const scanner = qs('tradingDeskScannerPanel');
      if (scanner) scanner.insertAdjacentElement('afterend', panel);
      else chartPanel.insertAdjacentElement('afterend', panel);
      qs('tdMt4Refresh')?.addEventListener('click', refreshMt4Panel);
    }
    refreshMt4Panel();
    if (!mt4Timer) mt4Timer = setInterval(refreshMt4Panel, 15000);
    return true;
  }

  function setupTradingPreview() {
    installStyles();
    setupNav();
    hideOldCards();
    moveJournalToDashboard();
    patchRunScan();
    const scannerReady = ensureTradingScannerPanel();
    const mt4Ready = ensureMt4Panel();
    return scannerReady && mt4Ready;
  }

  function start() {
    setupTradingPreview();
    const started = Date.now();
    const timer = setInterval(() => {
      const ready = setupTradingPreview();
      if (ready && Date.now() - started > 2500) clearInterval(timer);
      if (Date.now() - started > 20000) clearInterval(timer);
    }, 350);
    if (!scannerTimer) scannerTimer = setInterval(renderTradingScannerPanel, 10000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
