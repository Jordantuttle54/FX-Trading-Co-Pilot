/* agent_control.js - switch the autonomous agent on/off and watch what it does */
'use strict';

(function () {
  let cache = null;

  function qs(id) { return document.getElementById(id); }

  function esc(v) {
    return String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }

  function when(iso) {
    if (!iso) return 'never';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return esc(iso);
    const mins = Math.round((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins} min ago`;
    if (mins < 1440) return `${Math.round(mins / 60)} hr ago`;
    return d.toLocaleString('en-GB');
  }

  function pill(label, tone) {
    return `<span class="badge-${tone}">${esc(label)}</span>`;
  }

  function render(data, runs) {
    const el = qs('agentControlPanel');
    if (!el) return;
    const c = data.config;
    const lim = data.limits || {};
    const blockers = [];
    if (data.kill_switch) blockers.push('Kill switch is on');
    if (lim.daily_breached) blockers.push(`Daily loss limit reached (${lim.daily_loss_pct}%)`);
    if (lim.weekly_breached) blockers.push(`Weekly loss limit reached (${lim.weekly_loss_pct}%)`);
    if (c.respect_window && !data.in_window) blockers.push('Outside the London window');
    if (data.open_trades >= c.max_open_trades) blockers.push(`Holding ${data.open_trades}/${c.max_open_trades} trades`);

    const status = !c.enabled
      ? pill('AGENT OFF', 'neutral')
      : blockers.length ? pill('ON - STANDING DOWN', 'warn') : pill('ON - TRADING', 'safe');

    const last = runs.runs && runs.runs[0];
    const strategyBoxes = data.available_strategies.map(s => `
      <label style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;">
        <input type="checkbox" class="agent-strategy" value="${esc(s.id)}"
               ${(c.strategies || []).includes(s.id) ? 'checked' : ''}/> ${esc(s.label)}
      </label>`).join('');

    const pairBoxes = data.watchlist.map(p => `
      <label style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;">
        <input type="checkbox" class="agent-pair" value="${esc(p)}"
               ${(c.pairs || []).includes(p) ? 'checked' : ''}/> ${esc(p)}
      </label>`).join('');

    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px;">
        ${status}
        <span class="small muted">Last run: ${when(runs.last_run_at)}</span>
        <span class="small muted">Open ${esc(data.open_trades)}/${esc(c.max_open_trades)}</span>
        <span class="small muted">Today ${esc(data.opened_today)}/${esc(c.max_trades_per_day)}</span>
      </div>

      ${blockers.length && c.enabled ? `<div class="small" style="margin-bottom:12px;color:var(--muted);">
        Standing down because: ${esc(blockers.join(' &middot; '))}</div>` : ''}

      <div class="wallet-actions" style="align-items:flex-end;">
        <div class="wallet-action-group">
          <label>Max open trades
            <input type="number" id="agentMaxOpen" min="0" max="20" value="${esc(c.max_open_trades)}"/>
          </label>
        </div>
        <div class="wallet-action-group">
          <label>Max trades per day
            <input type="number" id="agentMaxDay" min="0" max="50" value="${esc(c.max_trades_per_day)}"/>
          </label>
        </div>
        <div class="wallet-action-group">
          <label>Minimum confidence %
            <input type="number" id="agentMinConf" min="0" max="100" value="${esc(c.min_confidence)}"/>
          </label>
        </div>
      </div>

      <div style="margin-top:14px;">
        <label class="agent-toggle">
          <input type="checkbox" id="agentRespectWindow" ${c.respect_window ? 'checked' : ''}/>
          Only trade in the London window
        </label>
      </div>

      <div style="margin-top:14px;">
        <div class="card-eyebrow" style="margin-bottom:6px;">Strategies <span class="muted">(none ticked = each pair's own setting)</span></div>
        ${strategyBoxes}
      </div>

      <div style="margin-top:14px;">
        <div class="card-eyebrow" style="margin-bottom:6px;">Pairs it may trade <span class="muted">(none ticked = all)</span></div>
        ${pairBoxes}
      </div>

      <div class="wallet-actions" style="margin-top:18px;">
        <div class="wallet-action-group">
          <button class="btn-secondary" onclick="saveAgentConfig(false)">Save Settings</button>
        </div>
        <div class="wallet-action-group">
          <button class="${c.enabled ? 'btn-danger' : 'btn-safe'}" onclick="toggleAgent()">
            ${c.enabled ? '&#9632; Turn Agent Off' : '&#9654; Turn Agent On'}
          </button>
        </div>
        <div class="wallet-action-group">
          <button class="btn-secondary" onclick="testAgentRun(true)">Test Run (no trades)</button>
        </div>
        <div class="wallet-action-group">
          <button class="btn-secondary" onclick="testAgentRun(false)">Run Now</button>
        </div>
      </div>

      <div id="agentRunResult" class="small" style="margin-top:12px"></div>

      ${last ? `<div style="margin-top:16px;">
        <div class="card-eyebrow" style="margin-bottom:8px;">Last run</div>
        <div class="small muted">${esc(last.halted ? `Stood down - ${last.halt_reason}` :
          `Scanned ${last.pairs_scanned || 0} pair(s), opened ${last.opened_count || 0}`)}</div>
        ${(last.opened || []).map(o => `<div class="small" style="margin-top:6px;">
          &#9654; <strong>${esc(o.pair)}</strong> ${esc(String(o.direction || '').toUpperCase())}
          &middot; ${esc(o.strategy)} &middot; ${esc(o.confidence)}%</div>`).join('')}
        ${(last.skipped || []).slice(0, 6).map(s => `<div class="small muted" style="margin-top:4px;">
          &mdash; ${esc(s.pair)}: ${esc(s.reason)}</div>`).join('')}
      </div>` : ''}
    `;
  }

  function readForm() {
    return {
      max_open_trades: Number(qs('agentMaxOpen')?.value || 0),
      max_trades_per_day: Number(qs('agentMaxDay')?.value || 0),
      min_confidence: Number(qs('agentMinConf')?.value || 0),
      respect_window: !!qs('agentRespectWindow')?.checked,
      strategies: Array.from(document.querySelectorAll('.agent-strategy:checked')).map(i => i.value),
      pairs: Array.from(document.querySelectorAll('.agent-pair:checked')).map(i => i.value),
    };
  }

  async function load() {
    const el = qs('agentControlPanel');
    if (!el) return;
    try {
      const [data, runs] = await Promise.all([
        api('/api/agent/agent-config'),
        api('/api/agent/agent-runs?limit=5'),
      ]);
      cache = data;
      render(data, runs);
    } catch (err) {
      el.innerHTML = `<div class="result-loss small">Could not load agent settings: ${esc(err.message || err)}</div>`;
    }
  }

  // load() rebuilds the whole panel, including the result line, so anything
  // worth showing has to be written after the reload rather than before it.
  function say(html) {
    const out = qs('agentRunResult');
    if (out) out.innerHTML = html;
  }

  window.saveAgentConfig = async function saveAgentConfig(silent) {
    try {
      await api('/api/agent/agent-config', { method: 'POST', body: JSON.stringify(readForm()) });
      await load();
      if (!silent) say('<span class="result-win">Settings saved.</span>');
    } catch (err) {
      say(`<span class="result-loss">Could not save: ${esc(err.message || err)}</span>`);
    }
  };

  window.toggleAgent = async function toggleAgent() {
    const turningOn = !(cache && cache.config.enabled);
    if (turningOn && !confirm('Turn the agent on? It will open paper trades by itself on a schedule, without asking first.')) return;
    try {
      await api('/api/agent/agent-config', {
        method: 'POST',
        body: JSON.stringify({ ...readForm(), enabled: turningOn }),
      });
      await load();
      say(`<span class="${turningOn ? 'result-win' : 'muted'}">Agent ${turningOn ? 'is now on' : 'is now off'}.</span>`);
    } catch (err) {
      say(`<span class="result-loss">Could not change that: ${esc(err.message || err)}</span>`);
    }
  };

  window.testAgentRun = async function testAgentRun(dryRun) {
    if (!dryRun && !confirm('Run the agent now? Any setup that passes will be opened as a real paper trade.')) return;
    say(`<span class="muted">${dryRun ? 'Checking what it would do' : 'Running'}&hellip;</span>`);
    try {
      const r = await api('/api/agent/agent-run', { method: 'POST', body: JSON.stringify({ dry_run: !!dryRun }) });
      await load();
      if (r.halted) {
        say(`<span class="muted">Stood down: ${esc(r.halt_reason)}</span>`);
      } else {
        const n = (r.opened || []).length;
        say(`<span class="${n ? 'result-win' : 'muted'}">${dryRun ? 'Would open' : 'Opened'} ${n} trade(s) from ${esc(r.pairs_scanned)} pair(s).</span>`);
      }
      if (!dryRun && typeof loadAllTrades === 'function') loadAllTrades();
    } catch (err) {
      say(`<span class="result-loss">Run failed: ${esc(err.message || err)}</span>`);
    }
  };

  function init() {
    if (!qs('agentControlPanel')) return;
    load();
    setInterval(() => { if (qs('tab-settings')?.classList.contains('active')) load(); }, 60000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
