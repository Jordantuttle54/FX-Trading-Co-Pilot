/* agent_phase1.js - Phase 1 paper-trading dashboard enhancements */
'use strict';

(function () {
  function qs(id) { return document.getElementById(id); }

  function safeJsonError(err) {
    if (!err) return 'Unknown error';
    if (typeof err === 'string') return err;
    if (err.message) return err.message;
    try { return JSON.stringify(err); } catch (_) { return String(err); }
  }

  async function phase1Api(path, options = {}) {
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

  function phase1Post(path, body) {
    return phase1Api(path, { method: 'POST', body: JSON.stringify(body || {}) });
  }

  function candidateForPair(pair) {
    const results = window.lastScanResults || (typeof lastScanResults !== 'undefined' ? lastScanResults : null);
    const candidates = (results && results.candidates) || [];
    return candidates.find(c => c.pair === pair) || null;
  }

  function replaceExecuteText(root) {
    const scope = root || document;
    scope.querySelectorAll('button').forEach(btn => {
      if ((btn.textContent || '').trim() === 'Execute Demo Trade') btn.textContent = 'Place Paper Trade';
    });
  }

  async function getOpenTrades() {
    const data = await phase1Api('/api/agent/trades/open');
    return data.open_trades || [];
  }

  async function refreshTradingUi() {
    if (typeof loadStatus === 'function') await loadStatus();
    if (typeof loadOpenTradesDetail === 'function') await loadOpenTradesDetail();
    if (typeof loadAllTrades === 'function') await loadAllTrades();
    if (typeof window.loadAgentChart === 'function') await window.loadAgentChart();
  }

  window.executeTrade = async function executeTradePhase1(pair) {
    const balance = parseFloat(qs('scanBalance')?.value || 10000);
    const candidate = candidateForPair(pair);
    const direction = (candidate && candidate.direction) || '';
    try {
      const openTrades = await getOpenTrades();
      const duplicate = openTrades.find(t =>
        String(t.pair || '').toUpperCase() === String(pair).toUpperCase() &&
        String(t.direction || '').toLowerCase() === String(direction).toLowerCase()
      );
      let forceDuplicate = false;
      if (duplicate) {
        forceDuplicate = confirm(`You already have an open ${String(direction).toUpperCase()} paper trade on ${pair}.\n\nExisting trade ID: ${duplicate.display_name || duplicate.id}\n\nOpen another paper trade anyway?`);
        if (!forceDuplicate) return;
      }
      if (!confirm(`Place a PAPER trade on ${pair}?\n\nNo real money is involved. Live trading remains locked.`)) return;
      const result = await phase1Post('/api/agent/execute', { pair, account_balance: balance, candidate, force_duplicate: forceDuplicate });
      const tradeName = result.trade?.display_name || result.display_name || result.trade_id;
      alert(`Paper trade placed!\nTrade: ${tradeName}\nMode: ${result.execution?.mode}\nOrder: ${result.execution?.order_id}`);
      await refreshTradingUi();
    } catch (e) {
      if (e.status === 409 && e.detail) {
        const d = e.detail;
        alert(`Duplicate paper trade blocked.\n\n${d.message || 'Duplicate open trade found.'}\nExisting trade: ${d.duplicate_display_name || d.duplicate_trade_id || 'unknown'}`);
        return;
      }
      alert(`Paper trade failed: ${safeJsonError(e)}`);
    }
  };

  window.renderOpenTrades = function renderOpenTradesPhase1(trades, containerId) {
    const el = qs(containerId);
    if (!el) return;
    if (!trades || trades.length === 0) {
      el.innerHTML = '<div class="muted small">No open trades.</div>';
      return;
    }
    el.innerHTML = trades.map(t => {
      const id = String(t.id || '');
      const pairSafe = String(t.pair || '').replace(/"/g, '&quot;');
      const direction = String(t.direction || '').toLowerCase();
      const directionLabel = direction ? direction.toUpperCase() : 'TRADE';
      const price = t.entry_price || t.entry || '';
      const displayName = t.display_name || t.friendly_name || t.pair || '';
      const shortId = t.short_trade_id || id.slice(0, 8);
      return `
        <div class="open-trade-card" style="background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;">
            <div>
              <strong>${displayName}</strong>
              <div class="small muted">ID: ${shortId}</div>
            </div>
            <span class="candidate-dir dir-${direction}">${directionLabel}</span>
          </div>
          <div class="small muted" style="margin-top:8px;line-height:1.7;">
            Pair: ${t.pair || ''} &nbsp;|&nbsp; Entry: ${price || '?'} &nbsp;|&nbsp; SL: ${t.stop_loss || '?'} &nbsp;|&nbsp; TP: ${t.take_profit || t.target || '?'}<br>
            Setup: ${t.setup_label || t.setup_type || ''} &nbsp;|&nbsp; Confidence: ${t.confidence || 0}%<br>
            Opened: ${t.filled_at || t.created_at || ''}
          </div>
          ${containerId === 'openTradesDetail' ? `
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;align-items:center;">
              <input type="number" step="0.00001" value="${price || 0}" id="close_${id}" style="width:130px" title="Manual close price">
              <button class="btn-secondary" onclick="manualCloseTrade('${id}', '${pairSafe}')">Manual Close</button>
            </div>` : ''}
        </div>`;
    }).join('');
  };

  window.manualCloseTrade = async function manualCloseTrade(tradeId, pair) {
    const input = qs(`close_${tradeId}`);
    const closePrice = parseFloat(input?.value || '0');
    if (!closePrice || closePrice <= 0) return alert('Please enter a valid close price.');
    if (!confirm(`Manually close paper trade on ${pair || 'this pair'} at ${closePrice}?`)) return;
    try {
      const result = await phase1Post(`/api/agent/trades/${encodeURIComponent(tradeId)}/close`, { close_price: closePrice, reason: 'Manual close from dashboard' });
      const closed = result.closed_trade || {};
      alert(`Paper trade closed.\nTrade: ${closed.display_name || closed.friendly_name || closed.id || tradeId}\nResult: ${closed.result_r || 0}R\nEstimated P/L: ${closed.result_money || 0}`);
      await refreshTradingUi();
    } catch (e) {
      alert(`Manual close failed: ${safeJsonError(e)}`);
    }
  };

  window.resetPaperTestData = async function resetPaperTestData() {
    if (!confirm('Reset all paper-trading test data for this user?\n\nThis will clear open and closed paper trades from the testing table.')) return;
    if (!confirm('Final confirmation: clear paper-trading test data now?')) return;
    try {
      const result = await phase1Post('/api/agent/trades/reset', { confirm: true, include_closed: true });
      alert(`Paper test data reset.\nDeleted rows: ${result.deleted_count || 0}`);
      await refreshTradingUi();
    } catch (e) {
      alert(`Reset failed: ${safeJsonError(e)}`);
    }
  };

  const originalLoadCalendar = window.loadCalendar;
  window.loadCalendar = async function loadCalendarPhase1() {
    const el = qs('calendarPanel');
    const rm = qs('pairRiskMap');
    if (!el || !rm) return originalLoadCalendar ? originalLoadCalendar() : undefined;
    el.innerHTML = '<span class="muted small">Loading calendar...</span>';
    try {
      const data = await phase1Api('/api/calendar');
      const events = data.events || [];
      if (!events.length) {
        el.innerHTML = '<div class="muted small">No calendar events available. Check your calendar provider configuration.</div>';
        rm.innerHTML = '<div class="muted small">No news risk data available.</div>';
        return;
      }
      el.innerHTML = `<table class="trade-table"><thead><tr><th>Time</th><th>Currency</th><th>Event</th><th>Impact</th><th>Previous</th><th>Forecast</th><th>Actual</th></tr></thead><tbody>${events.slice(0, 50).map(e => {
        const eventName = e.event || e.name || '';
        const isPlaceholder = /placeholder/i.test(eventName);
        const impact = isPlaceholder ? 'placeholder' : String(e.impact || '').toLowerCase();
        const impactLabel = isPlaceholder ? 'Placeholder' : (e.impact || '');
        const impactColor = impact === 'high' || impact === 'critical' ? 'var(--red)' : impact === 'medium' ? 'var(--orange)' : 'var(--text-muted)';
        return `<tr><td class="muted small">${e.time || e.datetime || ''}</td><td><strong>${e.currency || ''}</strong></td><td>${eventName}</td><td style="color:${impactColor};font-weight:600">${impactLabel}</td><td class="muted small">${e.previous || ''}</td><td class="muted small">${e.forecast || ''}</td><td class="small">${e.actual || '--'}</td></tr>`;
      }).join('')}</tbody></table>`;
      const pairs = ['GBP/USD', 'EUR/USD', 'USD/JPY', 'EUR/GBP', 'GBP/JPY', 'XAU/USD'];
      const realHighEvents = events.filter(e => !/placeholder/i.test(e.event || e.name || '') && ['high', 'critical'].includes(String(e.impact || '').toLowerCase()));
      rm.innerHTML = pairs.map(pair => {
        const currencies = pair === 'XAU/USD' ? ['XAU', 'USD'] : pair.split('/');
        const affected = realHighEvents.filter(e => currencies.includes(e.currency));
        return `<div class="risk-cell ${affected.length ? 'risk-blocked' : 'risk-safe'}"><div class="risk-pair">${pair}</div><div class="small">${affected.length ? `<span style="color:var(--red)">&#9888; ${affected.length} high-impact event(s)</span><br>${affected.map(e => e.event || e.name).join(', ')}` : '<span style="color:var(--green)">&#9989; Clear / placeholder-only</span>'}</div></div>`;
      }).join('');
    } catch (e) {
      el.innerHTML = `<span class="muted small">Error: ${safeJsonError(e)}</span>`;
    }
  };

  function injectResetButton() {
    const tradeSection = qs('tab-trades');
    if (!tradeSection || qs('resetPaperDataBtn')) return;
    const card = document.createElement('div');
    card.className = 'agent-card';
    card.innerHTML = `<h2>Testing Tools</h2><p class="card-sub">Use this during paper-trading tests only. It clears stored paper trades for the signed-in user.</p><button id="resetPaperDataBtn" class="btn-danger" onclick="resetPaperTestData()">Reset Test Data</button>`;
    tradeSection.appendChild(card);
  }

  function injectScript(src) {
    if (document.querySelector(`script[src="${src}"]`)) return;
    const script = document.createElement('script');
    script.src = src;
    script.defer = true;
    document.body.appendChild(script);
  }

  function injectEnhancementScripts() {
    injectScript('/static/agent_chart.js');
    injectScript('/static/agent_quick_trade.js');
    injectScript('/static/agent_trade_names.js');
    injectScript('/static/agent_auto_close.js');
  }

  function initPhase1Ui() {
    replaceExecuteText(document);
    injectResetButton();
    injectEnhancementScripts();
    const observer = new MutationObserver(mutations => {
      mutations.forEach(m => m.addedNodes.forEach(node => {
        if (node && node.nodeType === 1) replaceExecuteText(node);
      }));
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initPhase1Ui);
  else initPhase1Ui();
})();