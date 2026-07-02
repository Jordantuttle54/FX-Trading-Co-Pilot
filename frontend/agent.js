/* agent.js – AI FX Trading Agent dashboard JavaScript */
'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let lastScanResults = null;
let lastPrices = {};
let killSwitchActive = false;

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
    const res = await fetch(path, {
          headers: { 'Content-Type': 'application/json', ...options.headers },
          ...options,
    });
    if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
    }
    return res.json();
}

function post(path, body) {
    return api(path, { method: 'POST', body: JSON.stringify(body) });
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------
function switchTab(name) {
    document.querySelectorAll('.agent-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.agent-section').forEach(s => s.classList.remove('active'));
    document.querySelector(`[data-tab="${name}"]`).classList.add('active');
    document.getElementById(`tab-${name}`).classList.add('active');

  // Lazy-load tab content
  if (name === 'dashboard')   loadDashboard();
    if (name === 'trades')      { loadOpenTradesDetail(); loadAllTrades(); }
    if (name === 'calendar')    loadCalendar();
    if (name === 'settings')    loadSettings();
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function loadDashboard() {
    loadStatus();
    loadAuditLog();
    loadUpcomingNews();
}

async function loadStatus() {
    try {
          const data = await api('/api/agent/status');
          killSwitchActive = data.kill_switch_active;
          updateStatusStrip(data);
          renderTradingStatus(data);
          renderOpenTrades(data.open_trades, 'openTradesPanel');
    } catch (e) {
          document.getElementById('tradingStatusPanel').innerHTML = `<span class="muted">Error: ${e.message}</span>`;
    }
}

function updateStatusStrip(data) {
    const dot = document.getElementById('statusDot');
    const label = document.getElementById('statusLabel');
    const ks = document.getElementById('killSwitchBadge');
    const wb = document.getElementById('windowBadge');
    const ob = document.getElementById('openTradeBadge');

  if (data.kill_switch_active) {
        dot.className = 'status-dot dot-danger';
        label.textContent = 'KILL SWITCH ACTIVE';
        ks.className = 'badge-danger';
        ks.textContent = 'KILL SWITCH ON';
  } else if (data.trading_allowed && !data.trading_allowed.allowed) {
        dot.className = 'status-dot dot-warn';
        label.textContent = 'TRADING PAUSED';
        ks.className = 'badge-safe';
        ks.textContent = 'KILL SWITCH OFF';
  } else {
        dot.className = 'status-dot dot-ok';
        label.textContent = 'SYSTEM ACTIVE';
        ks.className = 'badge-safe';
        ks.textContent = 'KILL SWITCH OFF';
  }

  if (data.london_window_now) {
        wb.className = 'badge-safe';
        wb.textContent = 'LONDON WINDOW OPEN';
  } else {
        wb.className = 'badge-neutral';
        wb.textContent = 'OUTSIDE WINDOW';
  }

  const n = data.open_trade_count || 0;
    ob.textContent = `${n} OPEN TRADE${n !== 1 ? 'S' : ''}`;
    ob.className = n > 0 ? 'badge-warn' : 'badge-neutral';
}

function renderTradingStatus(data) {
    const el = document.getElementById('tradingStatusPanel');
    const ta = data.trading_allowed || {};
    const cls = ta.allowed ? 'status-allowed' : 'status-blocked';
    const icon = ta.allowed ? '&#9989;' : '&#128683;';

  const daily  = ta.daily_loss_pct  != null ? ta.daily_loss_pct.toFixed(2)  : '0.00';
    const weekly = ta.weekly_loss_pct != null ? ta.weekly_loss_pct.toFixed(2) : '0.00';

  document.getElementById('dailyLossDisplay').textContent  = daily + '%';
    document.getElementById('weeklyLossDisplay').textContent = weekly + '%';

  el.className = `status-panel ${cls}`;
    el.innerHTML = `
        <div style="font-size:15px;font-weight:700;margin-bottom:8px">${icon} ${ta.allowed ? 'Trading is allowed' : 'Trading is PAUSED'}</div>
            ${ta.reason ? `<div class="muted small">${ta.reason}</div>` : ''}
                <div class="small" style="margin-top:8px">Daily loss: <strong>${daily}%</strong> / ${ta.daily_limit || 1.5}% &nbsp;|&nbsp; Weekly loss: <strong>${weekly}%</strong> / ${ta.weekly_limit || 4}%</div>
                  `;
}

function renderOpenTrades(trades, containerId) {
    const el = document.getElementById(containerId);
    if (!trades || trades.length === 0) {
          el.innerHTML = '<div class="muted small">No open trades.</div>';
          return;
    }
    el.innerHTML = trades.map(t => `
        <div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:8px;">
              <div style="display:flex;justify-content:space-between;align-items:center">
                      <strong>${t.pair}</strong>
                              <span class="candidate-dir dir-${t.direction}">${t.direction.toUpperCase()}</span>
                                    </div>
                                          <div class="small muted" style="margin-top:6px">
                                                  Entry: ${t.entry_price} &nbsp;|&nbsp; SL: ${t.stop_loss} &nbsp;|&nbsp; TP: ${t.take_profit}
                                                        </div>
                                                              <div class="small muted">Setup: ${t.setup_label || t.setup_type} &nbsp;|&nbsp; Confidence: ${t.confidence}%</div>
                                                                    <div class="small muted">Opened: ${t.filled_at || t.created_at}</div>
                                                                        </div>
                                                                          `).join('');
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------
async function loadAuditLog() {
    try {
          const data = await api('/api/agent/audit');
          const el = document.getElementById('auditLogPanel');
          if (!data || data.length === 0) {
                  el.innerHTML = '<div class="muted small">No audit entries yet.</div>';
                  return;
          }
          el.innerHTML = data.slice(0, 50).map(r => `
                <div class="audit-row">
                        <span class="audit-time">${(r.created_at || '').slice(0, 19).replace('T', ' ')}</span>
                                <span class="audit-event">${r.event_type || ''}</span>
                                        <span class="audit-pair">${r.pair || ''}</span>
                                                <span class="audit-decision ${r.decision}">${r.decision || ''}</span>
                                                        <span class="audit-reason">${r.reason || ''}</span>
                                                              </div>
                                                                  `).join('');
    } catch (e) {
          document.getElementById('auditLogPanel').innerHTML = `<span class="muted small">Error: ${e.message}</span>`;
    }
}

// ---------------------------------------------------------------------------
// London clock
// ---------------------------------------------------------------------------
function startClock() {
    function tick() {
          const now = new Date();
          const london = new Date(now.toLocaleString('en-US', { timeZone: 'Europe/London' }));
          const hh = String(london.getHours()).padStart(2, '0');
          const mm = String(london.getMinutes()).padStart(2, '0');
          document.getElementById('londonClock').textContent = `${hh}:${mm}`;

      const h = london.getHours();
          const inWindow = h >= 7 && h < 11;
          const ws = document.getElementById('windowStatus');
          ws.textContent = inWindow ? 'WINDOW OPEN' : 'WINDOW CLOSED';
          ws.className = `window-status ${inWindow ? 'window-open' : 'window-closed'}`;
    }
    tick();
    setInterval(tick, 10000);
}

// ---------------------------------------------------------------------------
// Scanner
// ---------------------------------------------------------------------------
async function runScan() {
    const balance = parseFloat(document.getElementById('scanBalance')?.value || 10000);
    const statusEl = document.getElementById('scannerStatus');
    if (statusEl) statusEl.textContent = 'Scanning all pairs...';

  // Show loading in header
  document.getElementById('statusLabel').textContent = 'SCANNING...';

  try {
        const data = await post('/api/agent/scan', { account_balance: balance });
        lastScanResults = data;

      // Store prices for trade management
      if (data.candidates) {
              data.candidates.forEach(c => { if (c.entry) lastPrices[c.pair] = c.entry; });
      }

      if (statusEl) {
              statusEl.innerHTML = `
                      Scan complete at ${new Date().toLocaleTimeString()} &nbsp;|&nbsp;
                              <span style="color:var(--green)">${data.candidates?.length || 0} candidates</span> &nbsp;|&nbsp;
                                      <span style="color:var(--text-muted)">${data.rejected?.length || 0} rejected</span> &nbsp;|&nbsp;
                                              ${data.kill_switch ? '<span style="color:var(--red)">KILL SWITCH ACTIVE</span>' : ''}
                                                    `;
      }

      renderCandidates(data.candidates || []);
        renderRejected(data.rejected || []);
        renderNoSetup(data.no_setup || []);

      document.getElementById('candidatesSection').style.display = (data.candidates?.length > 0) ? 'block' : 'none';
        document.getElementById('rejectedSection').style.display   = (data.rejected?.length > 0)   ? 'block' : 'none';
        document.getElementById('noSetupSection').style.display    = (data.no_setup?.length > 0)    ? 'block' : 'none';

      await loadStatus();
  } catch (e) {
        if (statusEl) statusEl.innerHTML = `<span style="color:var(--red)">Scan failed: ${e.message}</span>`;
  }
}

function renderCandidates(candidates) {
    const el = document.getElementById('candidatesList');
    if (!candidates.length) { el.innerHTML = ''; return; }
    el.innerHTML = candidates.map(c => {
          const confClass = c.confidence >= 90 ? 'conf-high' : c.confidence >= 85 ? 'conf-med' : 'conf-low';
          return `
                <div class="candidate-card">
                        <div class="candidate-pair">${c.pair}</div>
                                <span class="candidate-dir dir-${c.direction}">${c.direction.toUpperCase()}</span>
                                        <div class="candidate-setup">${c.setup_label || c.setup_type}</div>
                                                <div class="candidate-conf ${confClass}">${c.confidence}<span style="font-size:14px;font-weight:400">%</span></div>
                                                        <div class="candidate-rr">RR: <strong>${(c.rr_estimate || 0).toFixed(1)}R</strong> &nbsp;|&nbsp; Session: ${c.session}</div>
                                                                <div class="candidate-reason">${c.entry_reason || ''}</div>
                                                                        <div style="font-size:11px;color:var(--text-muted)">
                                                                                  Entry: ${c.entry || '?'} &nbsp;| SL: ${c.stop_loss || '?'} &nbsp;| TP: ${c.take_profit || '?'}
                                                                                          </div>
                                                                                                  <div class="candidate-execute">
                                                                                                            <button class="btn-primary" style="font-size:11px;padding:6px 12px" onclick="executeTrade('${c.pair}')">
                                                                                                                        Execute Demo Trade
                                                                                                                                  </button>
                                                                                                                                          </div>
                                                                                                                                                </div>
                                                                                                                                                    `;
    }).join('');
}

function renderRejected(rejected) {
    const el = document.getElementById('rejectedList');
    el.innerHTML = rejected.map(r => `
        <div class="rejected-row">
              <span class="rejected-pair">${r.pair}</span>
                    <span class="candidate-setup">${r.setup_label || r.setup_type}</span>
                          <span class="rejected-reason">${r.rejection_reason || r.entry_reason || ''}</span>
                              </div>
                                `).join('');
}

function renderNoSetup(nosetup) {
    const el = document.getElementById('noSetupList');
    el.innerHTML = nosetup.map(r => `
        <div class="nosetup-row">
              <span class="rejected-pair">${r.pair}</span>
                    <span class="rejected-reason">No pattern detected. ${r.entry_reason || ''}</span>
                        </div>
                          `).join('');
}

async function loadScanHistory() {
    const el = document.getElementById('scanHistoryPanel');
    el.innerHTML = '<span class="muted small">Loading...</span>';
    try {
          const data = await api('/api/agent/scan/history');
          if (!data.length) { el.innerHTML = '<span class="muted small">No scan history yet.</span>'; return; }
          el.innerHTML = `
                <table class="trade-table" style="margin-top:8px">
                        <thead><tr>
                                  <th>Time</th><th>Pair</th><th>Setup</th><th>Conf</th><th>RR</th><th>Status</th><th>Reason</th>
                                          </tr></thead>
                                                  <tbody>
                                                            ${data.slice(0, 100).map(r => `<tr>
                                                                        <td class="muted">${(r.scanned_at || '').slice(0,16).replace('T',' ')}</td>
                                                                                    <td><strong>${r.pair}</strong></td>
                                                                                                <td class="small">${r.setup_type}</td>
                                                                                                            <td>${r.confidence}%</td>
                                                                                                                        <td>${(r.rr_estimate || 0).toFixed(1)}R</td>
                                                                                                                                    <td>${r.status}</td>
                                                                                                                                                <td class="muted small">${r.rejection_reason || ''}</td>
                                                                                                                                                          </tr>`).join('')}
                                                                                                                                                                  </tbody>
                                                                                                                                                                        </table>
                                                                                                                                                                            `;
    } catch (e) {
          el.innerHTML = `<span class="muted small">Error: ${e.message}</span>`;
    }
}

// ---------------------------------------------------------------------------
// Trade execution
// ---------------------------------------------------------------------------
async function executeTrade(pair) {
    const balance = parseFloat(document.getElementById('scanBalance')?.value || 10000);
    if (!confirm(`Execute a DEMO trade on ${pair}?\n\nThis will place a paper/demo trade using your current scan results. No real money is involved.`)) return;
    try {
          const result = await post('/api/agent/execute', { pair, account_balance: balance });
          alert(`Demo trade placed!\nTrade ID: ${result.trade_id}\nMode: ${result.execution?.mode}\nOrder: ${result.execution?.order_id}`);
          loadStatus();
          loadAllTrades();
    } catch (e) {
          alert(`Execution failed: ${e.message}`);
    }
}

// ---------------------------------------------------------------------------
// Trade management
// ---------------------------------------------------------------------------
async function loadOpenTradesDetail() {
    try {
          const data = await api('/api/agent/trades/open');
          renderOpenTrades(data.open_trades || [], 'openTradesDetail');
          populatePriceForms(data.open_trades || []);
    } catch (e) {
          document.getElementById('openTradesDetail').innerHTML = `<span class="muted small">Error: ${e.message}</span>`;
    }
}

function populatePriceForms(trades) {
    const el = document.getElementById('priceForms');
    if (!trades.length) { el.innerHTML = '<div class="muted small">No open trades to manage.</div>'; return; }
    el.innerHTML = trades.map(t => `
        <label style="display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:12px">
              <strong style="min-width:70px">${t.pair}</strong>
                    Current price:
                          <input type="number" id="price_${t.pair.replace('/','_')}" step="0.0001" value="${lastPrices[t.pair] || t.entry_price || 0}" style="width:120px"/>
                              </label>
                                `).join('');
}

async function manageTrades() {
    const resultEl = document.getElementById('manageResult');
    resultEl.textContent = 'Running management rules...';
    const prices = {};
    document.querySelectorAll('[id^="price_"]').forEach(inp => {
          const pair = inp.id.replace('price_', '').replace('_', '/');
          prices[pair] = parseFloat(inp.value);
    });
    try {
          const balance = parseFloat(document.getElementById('scanBalance')?.value || 10000);
          const result = await post('/api/agent/manage', { current_prices: prices, account_balance: balance });
          const actions = result.actions_taken || [];
          resultEl.innerHTML = actions.length
            ? `<div style="color:var(--green)">&#9989; ${actions.length} management action(s) taken:</div>` +
                    actions.map(a => `<div class="small muted" style="margin-top:4px">&#8226; ${a.pair}: ${a.action} — ${a.reason}</div>`).join('')
                  : '<div class="muted small">No trades hit stop or target at current prices.</div>';
          loadOpenTradesDetail();
    } catch (e) {
          resultEl.innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
    }
}

// ---------------------------------------------------------------------------
// Trade journal
// ---------------------------------------------------------------------------
let allTrades = [];

async function loadAllTrades() {
    try {
          allTrades = await api('/api/agent/trades');
          filterTrades();
    } catch (e) {
          document.getElementById('tradeJournalPanel').innerHTML = `<span class="muted small">Error: ${e.message}</span>`;
    }
}

function filterTrades() {
    const filter = document.getElementById('tradeFilter')?.value || 'all';
    const filtered = filter === 'all' ? allTrades : allTrades.filter(t => t.status === filter);
    renderTradeTable(filtered, 'tradeJournalPanel');
}

function renderTradeTable(trades, containerId) {
    const el = document.getElementById(containerId);
    if (!trades.length) { el.innerHTML = '<div class="muted small">No trades found.</div>'; return; }
    el.innerHTML = `
        <table class="trade-table">
              <thead><tr>
                      <th>ID</th><th>Pair</th><th>Dir</th><th>Setup</th><th>Conf</th><th>RR</th>
                              <th>Entry</th><th>SL</th><th>TP</th><th>Status</th><th>Result</th><th>Tag</th><th>Opened</th>
                                    </tr></thead>
                                          <tbody>
                                                  ${trades.map(t => {
                                                              const r = t.result_r;
                                                              const rClass = t.status === 'open' ? 'result-open' : (r > 0 ? 'result-win' : 'result-loss');
                                                              const rText = t.status === 'open' ? 'OPEN' : (r != null ? `${r > 0 ? '+' : ''}${r.toFixed(2)}R` : '--');
                                                              return `<tr>
                                                                          <td class="muted">${t.id}</td>
                                                                                      <td><strong>${t.pair}</strong></td>
                                                                                                  <td><span class="candidate-dir dir-${t.direction}">${(t.direction || '').toUpperCase()}</span></td>
                                                                                                              <td class="small">${t.setup_label || t.setup_type}</td>
                                                                                                                          <td>${t.confidence}%</td>
                                                                                                                                      <td>${(t.rr_estimate || 0).toFixed(1)}R</td>
                                                                                                                                                  <td class="small">${t.entry_price}</td>
                                                                                                                                                              <td class="small">${t.stop_loss}</td>
                                                                                                                                                                          <td class="small">${t.take_profit}</td>
                                                                                                                                                                                      <td>${t.status}</td>
                                                                                                                                                                                                  <td class="${rClass}">${rText}</td>
                                                                                                                                                                                                              <td>${t.quality_tag ? `<span class="tag-pill">${t.quality_tag.replace(/_/g,' ')}</span>` : ''}</td>
                                                                                                                                                                                                                          <td class="muted small">${(t.filled_at || t.created_at || '').slice(0,16).replace('T',' ')}</td>
                                                                                                                                                                                                                                    </tr>`;
                                                  }).join('')}
                                                        </tbody>
                                                            </table>
                                                              `;
}

async function reviewPending() {
    const el = document.getElementById('reviewResult');
    el.textContent = 'Running post-trade reviews...';
    try {
          const result = await post('/api/agent/review/pending/all', {});
          el.innerHTML = `<div style="color:var(--green)">&#9989; ${result.reviewed_count} trade(s) reviewed.</div>` +
                  (result.reviews || []).map(r => `
                          <div style="margin-top:8px;background:var(--bg3);border-radius:6px;padding:10px">
                                    <div class="small"><strong>Trade ${r.trade_id}</strong> &nbsp;|&nbsp; Tag: <span class="tag-pill">${(r.tag_label || '').replace(/_/g,' ')}</span></div>
                                              <pre style="margin-top:8px;font-size:11px">${r.review}</pre>
                                                      </div>
                                                            `).join('');
    } catch (e) {
          el.innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
    }
}

// ---------------------------------------------------------------------------
// Calendar
// ---------------------------------------------------------------------------
async function loadCalendar() {
    const el = document.getElementById('calendarPanel');
    const rm = document.getElementById('pairRiskMap');
    el.innerHTML = '<span class="muted small">Loading calendar...</span>';
    try {
          const data = await api('/api/calendar');
          const events = data.events || [];

      if (!events.length) {
              el.innerHTML = '<div class="muted small">No calendar events available. Check your calendar provider configuration.</div>';
              return;
      }

      el.innerHTML = `
            <table class="trade-table">
                    <thead><tr>
                              <th>Time (UTC)</th><th>Currency</th><th>Event</th><th>Impact</th><th>Previous</th><th>Forecast</th><th>Actual</th>
                                      </tr></thead>
                                              <tbody>
                                                        ${events.slice(0, 50).map(e => {
                                                                      const impact = (e.impact || '').toLowerCase();
                                                                      const impactColor = impact === 'high' || impact === 'critical' ? 'var(--red)' : impact === 'medium' ? 'var(--orange)' : 'var(--text-muted)';
                                                                      return `<tr>
                                                                                    <td class="muted small">${e.time || e.datetime || ''}</td>
                                                                                                  <td><strong>${e.currency || ''}</strong></td>
                                                                                                                <td>${e.event || e.name || ''}</td>
                                                                                                                              <td style="color:${impactColor};font-weight:600">${e.impact || ''}</td>
                                                                                                                                            <td class="muted small">${e.previous || ''}</td>
                                                                                                                                                          <td class="muted small">${e.forecast || ''}</td>
                                                                                                                                                                        <td class="small">${e.actual || '--'}</td>
                                                                                                                                                                                    </tr>`;
                                                        }).join('')}
                                                                </tbody>
                                                                      </table>
                                                                          `;

      // Pair risk map
      const pairs = ['GBP/USD', 'EUR/USD', 'USD/JPY', 'EUR/GBP', 'GBP/JPY', 'XAU/USD'];
          const highEvents = events.filter(e => ['high','critical'].includes((e.impact||'').toLowerCase()));
          rm.innerHTML = pairs.map(pair => {
                  const currencies = pair === 'XAU/USD' ? ['XAU','USD'] : pair.split('/');
                  const affected = highEvents.filter(e => currencies.includes(e.currency));
                  const riskClass = affected.length > 0 ? 'risk-blocked' : 'risk-safe';
                  return `
                          <div class="risk-cell ${riskClass}">
                                    <div class="risk-pair">${pair}</div>
                                              <div class="small">${affected.length > 0
                                                                               ? `<span style="color:var(--red)">&#9888; ${affected.length} high-impact event(s)</span><br>${affected.map(e => e.event || e.name).join(', ')}`
                                                                               : '<span style="color:var(--green)">&#9989; Clear</span>'
                                                                 }</div>
                                                                         </div>
                                                                               `;
          }).join('');
    } catch (e) {
          el.innerHTML = `<span class="muted small">Error: ${e.message}</span>`;
    }
}

// ---------------------------------------------------------------------------
// Performance
// ---------------------------------------------------------------------------
async function loadPerformance() {
    const el = document.getElementById('performancePanel');
    el.innerHTML = '<span class="muted">Generating report...</span>';
    try {
          const data = await api('/api/agent/performance');
          if (data.status === 'insufficient_data') {
                  el.innerHTML = `<div class="muted">${data.message}</div>`;
                  return;
          }
          const o = data.overall;
          el.innerHTML = `
                <div class="agent-grid-3" style="margin-bottom:12px">
                        ${perfCell('Total Trades', o.count, '')}
                                ${perfCell('Win Rate', o.win_rate + '%', o.win_rate >= 50 ? 'positive' : 'negative')}
                                        ${perfCell('Expectancy', o.expectancy + 'R', o.expectancy >= 0 ? 'positive' : 'negative')}
                                                ${perfCell('Profit Factor', o.profit_factor, o.profit_factor >= 1.5 ? 'positive' : 'negative')}
                                                        ${perfCell('Avg R', (o.avg_r >= 0 ? '+' : '') + o.avg_r + 'R', o.avg_r >= 0 ? 'positive' : 'negative')}
                                                                ${perfCell('Max Drawdown', data.max_drawdown_r + 'R', 'negative')}
                                                                      </div>
                                                                          `;

      document.getElementById('performanceBreakdowns').style.display = 'block';
          renderPerfBreakdown(data.by_pair,    'perfGridPair',    'Performance by Pair');
          renderPerfBreakdown(data.by_setup,   'perfGridSetup',   'Performance by Setup Type');
          renderPerfBreakdown(data.by_session, 'perfGridSession', 'Performance by Session');
          renderPerfBreakdown(data.by_confidence, 'perfGridConf', 'Performance by Confidence Band');
    } catch (e) {
          el.innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
    }
}

function perfCell(label, value, type) {
    return `
        <div class="perf-cell">
              <div class="perf-label">${label}</div>
                    <div class="perf-metric perf-${type || 'neutral'}">${value}</div>
                        </div>
                          `;
}

function renderPerfBreakdown(data, containerId, title) {
    const el = document.getElementById(containerId);
    if (!data || !Object.keys(data).length) { el.innerHTML = ''; return; }
    const inner = Object.entries(data).map(([key, stats]) => `
        <div class="perf-cell">
              <div class="perf-label">${key}</div>
                    <div class="perf-metric perf-${stats.expectancy >= 0 ? 'positive' : 'negative'}">${stats.expectancy}R exp.</div>
                          <div class="perf-meta">WR: ${stats.win_rate}% | ${stats.count} trades | PF: ${stats.profit_factor}</div>
                              </div>
                                `).join('');
    el.innerHTML = `<h3 style="font-size:13px;margin-bottom:8px;color:var(--text-muted)">${title}</h3>${inner}`;
}

async function loadProposals() {
    const el = document.getElementById('proposalsPanel');
    el.innerHTML = '<span class="muted">Generating proposals...</span>';
    const save = document.getElementById('saveVersionCheck')?.checked || false;
    try {
          const data = await post('/api/agent/optimise', { save_as_version: save, description: '' });
          const proposals = data.proposals || [];
          el.innerHTML = proposals.map(p => {
                  const priority = p.priority === 'HIGH' ? ' proposal-high' : '';
                  return `
                          <div class="proposal-card${priority}">
                                    <div class="proposal-type">${p.type || 'info'}</div>
                                              <div class="proposal-obs">${p.observation || p.message || ''}</div>
                                                        ${p.suggestion ? `<div class="proposal-sugg">&#8594; ${p.suggestion}</div>` : ''}
                                                                  ${p.auto_apply === false ? '<div class="small muted" style="margin-top:6px">&#128274; Requires manual approval before activation.</div>' : ''}
                                                                          </div>
                                                                                `;
          }).join('');
          if (data.version_id) {
                  el.innerHTML += `<div class="muted small" style="margin-top:8px">Saved as strategy version ID: ${data.version_id}</div>`;
          }
    } catch (e) {
          el.innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
    }
}

async function loadVersions() {
    const el = document.getElementById('versionsPanel');
    el.innerHTML = '<span class="muted">Loading...</span>';
    try {
          const data = await api('/api/agent/strategy/versions');
          if (!data.length) { el.innerHTML = '<div class="muted small">No strategy versions yet.</div>'; return; }
          el.innerHTML = `
                <table class="trade-table">
                        <thead><tr><th>ID</th><th>Version</th><th>Description</th><th>Created</th><th>Approved</th><th>Active</th></tr></thead>
                                <tbody>
                                          ${data.map(v => `<tr>
                                                      <td>${v.id}</td>
                                                                  <td><code>${v.version}</code></td>
                                                                              <td class="small muted">${v.description}</td>
                                                                                          <td class="muted small">${(v.created_at || '').slice(0,16).replace('T',' ')}</td>
                                                                                                      <td>${v.approved ? '<span style="color:var(--green)">&#9989;</span>' : '<span class="muted">&#10060;</span>'}</td>
                                                                                                                  <td>${v.active ? '<span style="color:var(--accent)">&#9679;</span>' : ''}</td>
                                                                                                                            </tr>`).join('')}
                                                                                                                                    </tbody>
                                                                                                                                          </table>
                                                                                                                                              `;
    } catch (e) {
          el.innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
    }
}

// ---------------------------------------------------------------------------
// Kill switch
// ---------------------------------------------------------------------------
async function toggleKillSwitch() {
    if (killSwitchActive) {
          await deactivateKillSwitch();
    } else {
          await activateKillSwitch();
    }
}

async function activateKillSwitch() {
    const reason = document.getElementById('killSwitchReason')?.value || 'Manual emergency stop';
    if (!confirm(`Activate kill switch?\n\nThis will halt all new trading immediately.\n\nReason: ${reason}`)) return;
    try {
          await post('/api/agent/kill-switch/activate', { reason });
          killSwitchActive = true;
          updateKillSwitchUI(true);
          await loadStatus();
    } catch (e) {
          alert(`Error: ${e.message}`);
    }
}

async function deactivateKillSwitch() {
    if (!confirm('Deactivate kill switch and resume normal trading?')) return;
    try {
          await post('/api/agent/kill-switch/deactivate', {});
          killSwitchActive = false;
          updateKillSwitchUI(false);
          await loadStatus();
    } catch (e) {
          alert(`Error: ${e.message}`);
    }
}

function updateKillSwitchUI(active) {
    const statusEl = document.getElementById('killSwitchStatus');
    if (statusEl) {
          statusEl.className = active ? 'kill-status-active' : 'kill-status-safe';
          statusEl.textContent = active
            ? 'KILL SWITCH IS ACTIVE — All new trading halted'
                  : 'KILL SWITCH IS OFF — Trading active';
    }
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
async function loadSettings() {
    try {
          const config = await api('/api/config');
          const el = document.getElementById('riskRulesPanel');
          const rules = config.rules || {};
          el.innerHTML = Object.entries(rules).map(([k, v]) => `
                <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:12px">
                        <span class="muted">${k.replace(/_/g, ' ')}</span>
                                <strong>${v}</strong>
                                      </div>
                                          `).join('');

      const wp = document.getElementById('watchlistPanel');
          wp.innerHTML = (config.watchlist || []).map(p =>
                  `<div style="padding:6px 0;border-bottom:1px solid var(--border);font-size:13px;font-weight:600">${p}</div>`
                                                          ).join('');

      const pp = document.getElementById('providerPanel');
          const cfg = config.configured || {};
          pp.innerHTML = Object.entries(cfg).map(([k, v]) =>
                  `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:12px">
                          <span class="muted">${k.replace(/_/g, ' ')}</span>
                                  <strong style="color:${v ? 'var(--green)' : 'var(--text-muted)'}">${v === true ? '&#9989; configured' : v === false ? '&#10060; not set' : v}</strong>
                                        </div>`
                                                     ).join('');

      // Kill switch status
      const ks = await api('/api/agent/kill-switch/status');
          killSwitchActive = ks.active;
          updateKillSwitchUI(ks.active);
    } catch (e) {
          console.error('Settings load error:', e);
    }
}

async function loadUpcomingNews() {
    const el = document.getElementById('upcomingNewsPanel');
    try {
          const data = await api('/api/calendar');
          const events = (data.events || [])
            .filter(e => ['high','critical'].includes((e.impact||'').toLowerCase()))
            .slice(0, 8);
          if (!events.length) {
                  el.innerHTML = '<div class="muted small">No high-impact events found.</div>';
                  return;
          }
          el.innerHTML = events.map(e => `
                <div style="padding:8px 0;border-bottom:1px solid var(--border);font-size:12px">
                        <div style="display:flex;justify-content:space-between">
                                  <strong>${e.currency} — ${e.event || e.name}</strong>
                                            <span style="color:var(--red);font-weight:600">${e.impact}</span>
                                                    </div>
                                                            <div class="muted" style="margin-top:2px">${e.time || e.datetime || ''}</div>
                                                                  </div>
                                                                      `).join('');
    } catch {
          el.innerHTML = '<div class="muted small">Calendar not available.</div>';
    }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    startClock();
    loadDashboard();
    // Auto-refresh status every 60 seconds
                            setInterval(loadStatus, 60000);
});
