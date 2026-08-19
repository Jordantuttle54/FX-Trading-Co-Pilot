/* agent_trade_repair.js - preview and apply the trigger-fill trade repair */
'use strict';

(function () {
  const ENDPOINT = '/api/agent/trades/repair-trigger-fills';

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  function money(value) {
    const n = Number(value || 0);
    const sign = n < 0 ? '-' : '';
    return `${sign}£${Math.abs(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function signedMoney(value) {
    const n = Number(value || 0);
    const abs = Math.abs(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${n < 0 ? '-' : '+'}£${abs}`;
  }

  function setApplyEnabled(enabled) {
    const btn = qs('applyRepairBtn');
    if (btn) btn.disabled = !enabled;
  }

  function renderRepairs(data, applied) {
    const el = qs('tradeRepairResult');
    if (!el) return;

    if (!data.affected_count) {
      el.innerHTML = `<div class="muted small">No trades need repairing &mdash; all ${data.closed_trades_checked} closed trade(s) are recorded correctly.</div>`;
      setApplyEnabled(false);
      return;
    }

    const delta = Number(data.money_delta || 0);
    const deltaClass = delta >= 0 ? 'result-win' : 'result-loss';
    const heading = applied
      ? `Repaired ${data.affected_count} trade(s). Your balance changed by <span class="${deltaClass}">${signedMoney(delta)}</span>.`
      : `${data.affected_count} trade(s) would be corrected. Your balance would change by <span class="${deltaClass}">${signedMoney(delta)}</span>.`;

    const rows = data.repairs.map(r => {
      const rowDelta = Number(r.money_delta || 0);
      return `<tr>
        <td><strong>${escapeHtml(r.pair || '')}</strong></td>
        <td><span class="candidate-dir dir-${escapeHtml(String(r.direction || '').toLowerCase())}">${escapeHtml(String(r.direction || '').toUpperCase())}</span></td>
        <td class="small">${escapeHtml(String(r.close_reason || '').replace(/_/g, ' '))}</td>
        <td class="small">${escapeHtml(r.old_close_price)} &rarr; <strong>${escapeHtml(r.new_close_price)}</strong></td>
        <td class="small">${Number(r.old_result_r).toFixed(2)}R &rarr; <strong>${Number(r.new_result_r).toFixed(2)}R</strong></td>
        <td class="small">${money(r.old_result_money)} &rarr; <strong>${money(r.new_result_money)}</strong></td>
        <td class="${rowDelta >= 0 ? 'result-win' : 'result-loss'}">${signedMoney(rowDelta)}</td>
      </tr>`;
    }).join('');

    el.innerHTML = `
      <div style="margin-bottom:10px;">${heading}</div>
      <div style="overflow-x:auto;">
        <table class="trade-table">
          <thead><tr>
            <th>Pair</th><th>Dir</th><th>Closed by</th><th>Fill price</th><th>Result</th><th>P&amp;L</th><th>Change</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${applied ? '' : '<div class="muted small" style="margin-top:10px;">Nothing has been saved yet. Click <strong>Apply Repair</strong> to write these corrections.</div>'}
    `;
    setApplyEnabled(!applied);
  }

  async function request(apply) {
    const res = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apply }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }

  async function run(apply) {
    const el = qs('tradeRepairResult');
    if (el) el.innerHTML = `<div class="muted small">${apply ? 'Applying repair' : 'Checking your closed trades'}&hellip;</div>`;
    try {
      const data = await request(apply);
      renderRepairs(data, apply);
      if (apply) {
        if (typeof loadWalletPanel === 'function') loadWalletPanel();
        if (typeof loadAllTrades === 'function') loadAllTrades();
        if (typeof loadDashboard === 'function') loadDashboard();
      }
    } catch (err) {
      if (el) el.innerHTML = `<div class="result-loss small">Repair failed: ${escapeHtml(err.message || err)}</div>`;
      setApplyEnabled(false);
    }
  }

  window.previewTradeRepair = function previewTradeRepair() {
    return run(false);
  };

  window.applyTradeRepair = function applyTradeRepair() {
    if (!confirm('Apply these corrections to your trade history? Your wallet balance will be recalculated from the corrected results.')) return;
    return run(true);
  };
})();
