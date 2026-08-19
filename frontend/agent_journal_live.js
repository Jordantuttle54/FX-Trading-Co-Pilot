/* agent_journal_live.js - live current price and money P&L in the trade journal */
'use strict';

(function () {
  if (window.__agentJournalLiveInstalled) return;
  window.__agentJournalLiveInstalled = true;

  let allTrades = [];
  let livePrices = {};
  let priceLoadedAt = {};
  let refreshTimer = null;

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  function num(value, fallback = null) {
    if (value === null || value === undefined || value === '') return fallback;
    const n = Number(String(value).replace(/[£$,]/g, ''));
    return Number.isFinite(n) ? n : fallback;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || data.message || res.statusText;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function isOpen(trade) {
    return String(trade.status || '').toLowerCase() === 'open';
  }

  function entryValue(trade) {
    return num(trade.entry_price, num(trade.entry, num(trade.open_price, null)));
  }

  function stopValue(trade) {
    return num(trade.stop_loss, num(trade.sl, null));
  }

  function closeValue(trade) {
    return num(trade.exit_price, num(trade.close_price, num(trade.closed_price, num(trade.current_price, null))));
  }

  function currentValue(trade) {
    if (!isOpen(trade)) return closeValue(trade);
    const pair = trade.pair;
    return num(livePrices[pair], num(trade.current_price, num(trade.market_price, null)));
  }

  function riskMoney(trade) {
    const direct = num(trade.risk_amount, num(trade.risk_money, num(trade.money_risked, num(trade.risk_value, null))));
    if (direct !== null) return direct;
    const balance = num(trade.account_balance, num(window.walletCashBalance, num(qs('scanBalance')?.value, 10000))) || 10000;
    const riskPct = num(trade.risk_pct, 0.5) || 0.5;
    return balance * (riskPct / 100);
  }

  function savedMoneyResult(trade) {
    const direct = num(trade.result_money, num(trade.pnl, num(trade.profit, num(trade.result_profit, null))));
    if (direct !== null) return direct;
    const r = num(trade.result_r, null);
    return r !== null ? r * riskMoney(trade) : null;
  }

  function liveMoneyResult(trade) {
    if (!isOpen(trade)) return savedMoneyResult(trade);
    const current = currentValue(trade);
    const entry = entryValue(trade);
    const stop = stopValue(trade);
    if (current === null || entry === null || stop === null || current === entry || stop === entry) return null;
    const direction = String(trade.direction || '').toLowerCase();
    const move = direction === 'sell' ? (entry - current) : (current - entry);
    const riskDistance = Math.abs(entry - stop);
    if (!riskDistance) return null;
    return (move / riskDistance) * riskMoney(trade);
  }

  function resultR(trade) {
    if (!isOpen(trade)) return num(trade.result_r, null);
    const money = liveMoneyResult(trade);
    const risk = riskMoney(trade);
    if (money === null || !risk) return null;
    return money / risk;
  }

  function formatMoney(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
    const n = Number(value);
    const sign = n > 0 ? '+' : n < 0 ? '-' : '';
    return `${sign}£${Math.abs(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function formatPrice(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return n >= 100 ? n.toFixed(3) : n.toFixed(5);
  }

  function tradeName(trade) {
    return trade.display_name || trade.friendly_name || trade.trade_name || trade.short_name || trade.label || `${trade.pair || ''} ${String(trade.direction || '').toUpperCase()}`.trim() || trade.id || 'Trade';
  }

  function openedAt(trade) {
    return (trade.filled_at || trade.opened_at || trade.created_at || '').slice(0, 16).replace('T', ' ');
  }

  function resultClass(value, trade) {
    if (isOpen(trade) && value === null) return 'result-open';
    if (value > 0) return 'result-win';
    if (value < 0) return 'result-loss';
    return isOpen(trade) ? 'result-open' : 'muted';
  }

  function moneyResultMarkup(trade) {
    const money = liveMoneyResult(trade);
    const r = resultR(trade);
    const cls = resultClass(money, trade);
    const source = isOpen(trade) ? 'Live' : 'Saved';
    const rText = r !== null ? `${r > 0 ? '+' : ''}${r.toFixed(2)}R` : '';
    if (money === null) return `<span class="result-open">${isOpen(trade) ? 'OPEN' : '--'}</span>`;
    return `<div class="${cls}" style="font-weight:900">${formatMoney(money)}</div><div class="muted" style="font-size:10px;margin-top:2px">${source}${rText ? ` · ${rText}` : ''}</div>`;
  }

  async function refreshLivePrices(trades, force = false) {
    const pairs = Array.from(new Set((trades || []).filter(isOpen).map(t => t.pair).filter(Boolean)));
    await Promise.allSettled(pairs.map(async (pair) => {
      if (!force && livePrices[pair] !== undefined && Date.now() - (priceLoadedAt[pair] || 0) < 6500) return;
      const tick = await api(`/api/agent/chart/tick?pair=${encodeURIComponent(pair)}`);
      const price = num(tick.price, num(tick.mid, num(tick.ask, num(tick.bid, null))));
      if (price !== null) {
        livePrices[pair] = price;
        priceLoadedAt[pair] = Date.now();
        window.lastPrices = window.lastPrices || {};
        window.lastPrices[pair] = price;
      }
    }));
  }

  function renderTradeTable(trades, containerId) {
    const el = qs(containerId);
    if (!el) return;
    if (!trades.length) {
      el.innerHTML = '<div class="muted small">No trades found.</div>';
      return;
    }

    el.innerHTML = `
      <table class="trade-table journal-live-table">
        <thead><tr>
          <th>Trade</th><th>Pair</th><th>Dir</th><th>Setup</th><th>Conf</th><th>RR</th>
          <th>Entry</th><th>Current</th><th>SL</th><th>TP</th><th>Status</th><th>Result</th><th>Tag</th><th>Opened</th>
        </tr></thead>
        <tbody>
          ${trades.map(t => {
            const money = liveMoneyResult(t);
            return `<tr>
              <td><strong>${escapeHtml(tradeName(t))}</strong><div class="muted" style="font-size:10px;margin-top:2px">ID: ${escapeHtml(t.id || '')}</div></td>
              <td><strong>${escapeHtml(t.pair || '')}</strong></td>
              <td><span class="candidate-dir dir-${escapeHtml(String(t.direction || '').toLowerCase())}">${escapeHtml(String(t.direction || '').toUpperCase())}</span></td>
              <td class="small">${escapeHtml(t.setup_label || t.setup_type || '')}</td>
              <td>${t.confidence != null ? `${escapeHtml(t.confidence)}%` : '--'}</td>
              <td>${num(t.rr_estimate, 0).toFixed(1)}R</td>
              <td class="small">${formatPrice(entryValue(t))}</td>
              <td class="small"><strong>${formatPrice(currentValue(t))}</strong></td>
              <td class="small">${formatPrice(stopValue(t))}</td>
              <td class="small">${formatPrice(num(t.take_profit, num(t.target, num(t.tp, null))))}</td>
              <td>${escapeHtml(t.status || '')}</td>
              <td class="${resultClass(money, t)}">${moneyResultMarkup(t)}</td>
              <td>${t.quality_tag ? `<span class="tag-pill">${escapeHtml(String(t.quality_tag).replace(/_/g, ' '))}</span>` : ''}</td>
              <td class="muted small">${escapeHtml(openedAt(t))}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    `;
  }

  function filterTrades() {
    const filter = qs('tradeFilter')?.value || 'all';
    const filtered = filter === 'all' ? allTrades : allTrades.filter(t => String(t.status || '').toLowerCase() === filter);
    renderTradeTable(filtered, 'tradeJournalPanel');
  }

  async function loadAllTrades() {
    const el = qs('tradeJournalPanel');
    try {
      allTrades = await api('/api/agent/trades');
      if (!Array.isArray(allTrades)) allTrades = allTrades.trades || allTrades.items || [];
      await refreshLivePrices(allTrades);
      filterTrades();
    } catch (e) {
      if (el) el.innerHTML = `<span class="muted small">Error: ${escapeHtml(e.message || e)}</span>`;
    }
  }

  function injectStyles() {
    if (qs('journalLiveStyles')) return;
    const style = document.createElement('style');
    style.id = 'journalLiveStyles';
    style.textContent = `
      .journal-live-table th,
      .journal-live-table td { white-space: nowrap; }
      .journal-live-table th:first-child,
      .journal-live-table td:first-child { min-width: 170px; }
      .journal-live-table th:nth-child(4),
      .journal-live-table td:nth-child(4) { min-width: 180px; }
      .journal-live-table th:nth-child(12),
      .journal-live-table td:nth-child(12) { min-width: 100px; }
      .result-win { color: var(--green, #22c55e); font-weight: 850; }
      .result-loss { color: var(--red, #ef4444); font-weight: 850; }
      .result-open { color: var(--accent, #60a5fa); font-weight: 850; }
    `;
    document.head.appendChild(style);
  }

  function startJournalRefresh() {
    if (refreshTimer) return;
    refreshTimer = setInterval(() => {
      if (document.querySelector('#tab-trades.active') && qs('tradeJournalPanel')) loadAllTrades();
    }, 10000);
  }

  window.loadAllTrades = loadAllTrades;
  window.filterTrades = filterTrades;
  window.renderTradeTable = renderTradeTable;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { injectStyles(); startJournalRefresh(); });
  } else {
    injectStyles();
    startJournalRefresh();
  }
})();
