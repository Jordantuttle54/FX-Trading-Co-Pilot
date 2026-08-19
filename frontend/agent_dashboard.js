/* agent_dashboard.js - compact dashboard summary widgets */
'use strict';

(function () {
  function qs(id) { return document.getElementById(id); }

  async function dashboardApi(path) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }

  function asArray(data) {
    if (Array.isArray(data)) return data;
    return data.trades || data.items || data.open_trades || data.rows || [];
  }

  function n(value, fallback = 0) {
    if (value === null || value === undefined || value === '') return fallback;
    const parsed = Number(String(value).replace(/[£$,R]/g, ''));
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function tradeDate(trade) {
    const raw = trade.closed_at || trade.filled_at || trade.opened_at || trade.created_at || trade.timestamp;
    const date = new Date(raw || 0);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function money(value) {
    const amount = n(value, 0);
    const sign = amount < 0 ? '-' : '';
    return `${sign}£${Math.abs(amount).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function pnlValue(trade) {
    const direct = [trade.result_money, trade.pnl, trade.profit, trade.result_profit, trade.estimated_pnl]
      .map(v => n(v, NaN))
      .find(Number.isFinite);
    if (Number.isFinite(direct)) return direct;
    const resultR = n(trade.result_r, NaN);
    const risk = n(trade.risk_amount || trade.risk_money || trade.money_risked, NaN);
    if (Number.isFinite(resultR) && Number.isFinite(risk)) return resultR * risk;
    return 0;
  }

  function isClosed(trade) {
    return String(trade.status || '').toLowerCase() === 'closed';
  }

  function bestPair(todayClosed) {
    const byPair = new Map();
    todayClosed.forEach(trade => {
      const pair = trade.pair || 'Unknown';
      byPair.set(pair, (byPair.get(pair) || 0) + pnlValue(trade));
    });
    if (!byPair.size) return '--';
    return [...byPair.entries()].sort((a, b) => b[1] - a[1])[0][0];
  }

  function renderSnapshot({ todayTrades, todayClosed }) {
    const el = qs('dashboardTodaySnapshot');
    if (!el) return;
    const wins = todayClosed.filter(t => pnlValue(t) > 0).length;
    const losses = todayClosed.filter(t => pnlValue(t) < 0).length;
    const pnl = todayClosed.reduce((sum, t) => sum + pnlValue(t), 0);
    el.innerHTML = `
      <div class="dash-pnl-label">Today's P&amp;L</div>
      <div class="dash-pnl-value ${pnl >= 0 ? 'dash-positive' : 'dash-negative'}">${money(pnl)}</div>
      <div class="dash-pnl-stats">
        <div class="dash-mini-stat"><span>Trades today</span><strong>${todayTrades.length}</strong></div>
        <div class="dash-mini-stat"><span>Closed W/L</span><strong>${wins} / ${losses}</strong></div>
        <div class="dash-mini-stat"><span>Best pair</span><strong>${bestPair(todayClosed)}</strong></div>
      </div>
    `;
  }

  async function loadDashboardSnapshot() {
    const el = qs('dashboardTodaySnapshot');
    if (!el) return;
    try {
      const [allData, openData] = await Promise.all([
        dashboardApi('/api/agent/trades'),
        dashboardApi('/api/agent/trades/open'),
      ]);
      const allTrades = asArray(allData);
      const openTrades = asArray(openData);
      const start = new Date();
      start.setHours(0, 0, 0, 0);
      const todayTrades = allTrades.filter(trade => {
        const date = tradeDate(trade);
        return date && date >= start;
      });
      const todayClosed = todayTrades.filter(isClosed);
      renderSnapshot({ todayTrades, todayClosed, openTrades });
    } catch (err) {
      el.innerHTML = `<div class="muted small">Snapshot unavailable: ${err.message || err}</div>`;
    }
  }

  function renameAudit() {
    const auditHeading = document.querySelector('#tab-dashboard .dashboard-audit-card h2');
    if (auditHeading) auditHeading.textContent = 'Confidence Audit Log';
  }

  function enhanceDashboardLoader() {
    if (typeof window.loadDashboard !== 'function' || window.loadDashboard.__dashboardSnapshotEnhanced) return;
    const original = window.loadDashboard;
    window.loadDashboard = async function loadDashboardEnhanced() {
      const result = await original.apply(this, arguments);
      setTimeout(loadDashboardSnapshot, 100);
      return result;
    };
    window.loadDashboard.__dashboardSnapshotEnhanced = true;
  }

  function init() {
    renameAudit();
    enhanceDashboardLoader();
    loadDashboardSnapshot();
    setInterval(loadDashboardSnapshot, 45000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
