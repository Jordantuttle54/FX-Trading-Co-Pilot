/* dashboard_review.js - agent vs you, and results by day.
 *
 * The origin split is the reason every trade records who placed it. One shared
 * wallet, three sets of results: what the agent did unattended, what you took
 * from the scanner, and what you drew yourself.
 *
 * Average R is shown next to the pounds deliberately. The agent risks a fixed
 * 0.5%; a hand-placed trade can be any size. Comparing pounds therefore tells
 * you who risked more, not who traded better, and the pounds are the figure
 * everyone looks at first.
 */
'use strict';

(function () {
  // Mirrors ORIGIN_LABELS / LEGACY_SETUP_ORIGINS in backend/paper_mvp_persistent.py.
  const ORIGIN_LABELS = {
    agent_auto: 'AGENT TRADE',
    scanner_manual_execute: 'Manual-Scanner',
    ai_quick_open: 'Manual-Scanner',
    personal_quick_open: 'Personal',
    manual_copilot: 'Personal',
  };
  const LEGACY_SETUP_ORIGINS = {
    live_data_trend_continuation: 'scanner_manual_execute',
    live_data_mean_reversion: 'scanner_manual_execute',
    personal_quick_paper_trade: 'personal_quick_open',
    manual_copilot_paper_trade: 'manual_copilot',
  };
  const ORDER = ['AGENT TRADE', 'Manual-Scanner', 'Personal', 'Unknown'];

  // Below this, a win rate is noise rather than a result.
  const THIN_SAMPLE = 5;

  function qs(id) { return document.getElementById(id); }

  function esc(v) {
    return String(v ?? '').replace(/[&<>'"]/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[c]));
  }

  function num(v, fallback = null) {
    if (v === null || v === undefined || v === '') return fallback;
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  function money(v) {
    const n = num(v, 0);
    const sign = n > 0 ? '+' : n < 0 ? '-' : '';
    return `${sign}£${Math.abs(n).toLocaleString('en-GB', {
      minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function cls(v) {
    const n = num(v, 0);
    return n > 0 ? 'review-up' : n < 0 ? 'review-down' : 'review-flat';
  }

  function originLabel(t) {
    if (t.trade_origin_label) return t.trade_origin_label;
    const o = String(t.trade_origin || t.origin || '').trim().toLowerCase();
    if (ORIGIN_LABELS[o]) return ORIGIN_LABELS[o];
    const legacy = LEGACY_SETUP_ORIGINS[String(t.setup_type || '').trim().toLowerCase()];
    return legacy ? ORIGIN_LABELS[legacy] : 'Unknown';
  }

  const isClosed = t => String(t.status || '').toLowerCase() === 'closed'
                        && num(t.result_r, null) !== null;

  function drawdown(trades) {
    const ordered = trades.slice().sort((a, b) =>
      String(a.closed_at || a.created_at || '').localeCompare(String(b.closed_at || b.created_at || '')));
    let running = 0, peak = 0, worst = 0;
    ordered.forEach((t) => {
      running += num(t.result_r, 0);
      peak = Math.max(peak, running);
      worst = Math.max(worst, peak - running);
    });
    return worst;
  }

  function summarise(trades) {
    const rs = trades.map(t => num(t.result_r, 0));
    const wins = rs.filter(r => r > 0).length;
    const totalR = rs.reduce((a, b) => a + b, 0);
    return {
      count: trades.length,
      winRate: trades.length ? (wins / trades.length) * 100 : 0,
      totalR,
      avgR: trades.length ? totalR / trades.length : 0,
      money: trades.reduce((a, t) => a + num(t.result_money, 0), 0),
      drawdown: drawdown(trades),
    };
  }

  function renderOriginSplit(closed) {
    const panel = qs('originSplitPanel');
    if (!panel) return;
    if (!closed.length) {
      panel.innerHTML = '<div class="review-empty">No closed trades yet.</div>';
      return;
    }

    const groups = {};
    closed.forEach((t) => {
      const label = originLabel(t);
      (groups[label] = groups[label] || []).push(t);
    });

    const labels = ORDER.filter(l => groups[l]).concat(
      Object.keys(groups).filter(l => !ORDER.includes(l)).sort());

    panel.innerHTML = `
      <div class="review-scroll">
        <table class="review-table">
          <thead><tr>
            <th>Placed by</th><th>Trades</th><th>Win rate</th>
            <th>Avg R</th><th>Total R</th><th>Worst run</th><th>P&amp;L</th>
          </tr></thead>
          <tbody>
            ${labels.map((label) => {
              const s = summarise(groups[label]);
              const thin = s.count < THIN_SAMPLE;
              return `<tr>
                <td><span class="review-origin ${label === 'AGENT TRADE' ? 'agent'
                    : label === 'Manual-Scanner' ? 'scanner' : ''}">${esc(label)}</span></td>
                <td class="review-num">${s.count}${thin ? '<span class="review-thin" title="Fewer than 5 closed trades - too few to read anything into">*</span>' : ''}</td>
                <td class="review-num">${s.winRate.toFixed(0)}%</td>
                <td class="review-num ${cls(s.avgR)}">${s.avgR > 0 ? '+' : ''}${s.avgR.toFixed(2)}R</td>
                <td class="review-num ${cls(s.totalR)}">${s.totalR > 0 ? '+' : ''}${s.totalR.toFixed(2)}R</td>
                <td class="review-num">${s.drawdown.toFixed(2)}R</td>
                <td class="review-num ${cls(s.money)}">${money(s.money)}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
      ${labels.some(l => groups[l].length < THIN_SAMPLE)
        ? '<div class="review-note">* fewer than 5 closed trades &mdash; too few to read anything into.</div>' : ''}`;
  }

  function dayKey(trade) {
    const raw = String(trade.closed_at || trade.updated_at || trade.created_at || '');
    return raw.slice(0, 10) || 'unknown';
  }

  function renderByDay(closed) {
    const panel = qs('dayBreakdownPanel');
    if (!panel) return;
    if (!closed.length) {
      panel.innerHTML = '<div class="review-empty">No closed trades yet.</div>';
      return;
    }

    const byDay = {};
    closed.forEach(t => (byDay[dayKey(t)] = byDay[dayKey(t)] || []).push(t));
    const days = Object.keys(byDay).sort().reverse().slice(0, 10);

    panel.innerHTML = `
      <div class="review-scroll">
        <table class="review-table">
          <thead><tr><th>Day</th><th>Trades</th><th>Total R</th><th>P&amp;L</th></tr></thead>
          <tbody>
            ${days.map((day) => {
              const s = summarise(byDay[day]);
              const label = day === 'unknown' ? 'Undated' : new Date(day + 'T00:00:00Z')
                .toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
              return `<tr>
                <td>${esc(label)}</td>
                <td class="review-num">${s.count}</td>
                <td class="review-num ${cls(s.totalR)}">${s.totalR > 0 ? '+' : ''}${s.totalR.toFixed(2)}R</td>
                <td class="review-num ${cls(s.money)}">${money(s.money)}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>`;
  }

  async function refresh() {
    const split = qs('originSplitPanel');
    if (!split) return;
    try {
      const res = await fetch('/api/agent/trades', { headers: { 'Content-Type': 'application/json' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
      const trades = Array.isArray(data) ? data : (data.trades || data.items || []);
      const closed = trades.filter(isClosed);
      renderOriginSplit(closed);
      renderByDay(closed);
    } catch (err) {
      const message = `<div class="review-empty">Could not load results: ${esc(err.message || err)}</div>`;
      split.innerHTML = message;
      const day = qs('dayBreakdownPanel');
      if (day) day.innerHTML = message;
    }
  }
  window.refreshDashboardReview = refresh;

  function init() {
    if (!qs('originSplitPanel')) return;
    refresh();
    const previous = window.switchTab;
    if (typeof previous === 'function' && !previous.__reviewEnhanced) {
      window.switchTab = function switchTabReviewEnhanced(name) {
        const result = previous.apply(this, arguments);
        if (name === 'dashboard') setTimeout(refresh, 150);
        return result;
      };
      window.switchTab.__reviewEnhanced = true;
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
