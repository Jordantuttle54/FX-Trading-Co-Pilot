/* agent_trade_names.js - friendly paper trade labels */
'use strict';

(function () {
  let updatingQuickCloseSelect = false;

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  async function api(path) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }

  function displayName(trade) {
    if (!trade) return 'Paper Trade';
    if (trade.display_name || trade.friendly_name) return trade.display_name || trade.friendly_name;
    const origin = String(trade.trade_origin || trade.origin || '').toLowerCase().includes('personal') ? 'Personal' : 'AI';
    const pair = trade.pair || 'Unknown';
    const dir = String(trade.direction || 'trade').toLowerCase();
    const dirLabel = dir === 'buy' ? 'Buy' : dir === 'sell' ? 'Sell' : 'Trade';
    const shortId = String(trade.id || '').slice(0, 8);
    return `${origin} ${pair} ${dirLabel}${shortId ? ` - ${shortId}` : ''}`;
  }

  function shortId(trade) {
    return trade?.short_trade_id || String(trade?.id || '').slice(0, 8);
  }

  function addTradeNameStyles() {
    if (qs('tradeNameStyles')) return;
    const style = document.createElement('style');
    style.id = 'tradeNameStyles';
    style.textContent = `
      .trade-friendly-name { font-weight:700; }
      .trade-technical-id { color:var(--text-muted); font-size:11px; margin-top:2px; word-break:break-all; }
      .trade-name-cell strong { display:block; }
      .trade-name-cell code { font-size:10px; color:var(--text-muted); }
    `;
    document.head.appendChild(style);
  }

  function patchOpenTradeRenderer() {
    window.renderOpenTrades = function renderOpenTradesFriendly(trades, containerId) {
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
        const name = displayName(t);
        const tech = shortId(t);
        return `
          <div class="open-trade-card" style="background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:10px;">
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;">
              <div>
                <strong class="trade-friendly-name">${escapeHtml(name)}</strong>
                <div class="trade-technical-id">ID: ${escapeHtml(tech)}</div>
              </div>
              <span class="candidate-dir dir-${escapeHtml(direction)}">${escapeHtml(directionLabel)}</span>
            </div>
            <div class="small muted" style="margin-top:8px;line-height:1.7;">
              Pair: ${escapeHtml(t.pair || '')} &nbsp;|&nbsp; Entry: ${escapeHtml(price || '?')} &nbsp;|&nbsp; SL: ${escapeHtml(t.stop_loss || '?')} &nbsp;|&nbsp; TP: ${escapeHtml(t.take_profit || t.target || '?')}<br>
              Setup: ${escapeHtml(t.setup_label || t.setup_type || '')} &nbsp;|&nbsp; Confidence: ${escapeHtml(t.confidence || 0)}%<br>
              Opened: ${escapeHtml(t.filled_at || t.created_at || '')}
            </div>
            ${containerId === 'openTradesDetail' ? `
              <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;align-items:center;">
                <input type="number" step="0.00001" value="${escapeHtml(price || 0)}" id="close_${escapeHtml(id)}" style="width:130px" title="Manual close price">
                <button class="btn-secondary" onclick="manualCloseTrade('${escapeHtml(id)}', '${escapeHtml(pairSafe)}')">Manual Close</button>
              </div>
            ` : ''}
          </div>
        `;
      }).join('');
    };
  }

  function patchTradeTableRenderer() {
    window.renderTradeTable = function renderTradeTableFriendly(trades, containerId) {
      const el = qs(containerId);
      if (!el) return;
      if (!trades || !trades.length) {
        el.innerHTML = '<div class="muted small">No trades found.</div>';
        return;
      }
      el.innerHTML = `
        <table class="trade-table">
          <thead><tr>
            <th>Trade</th><th>Pair</th><th>Dir</th><th>Setup</th><th>Conf</th><th>RR</th>
            <th>Entry</th><th>SL</th><th>TP</th><th>Status</th><th>Result</th><th>Tag</th><th>Opened</th>
          </tr></thead>
          <tbody>
            ${trades.map(t => {
              const r = t.result_r;
              const rNum = Number(r);
              const rClass = t.status === 'open' ? 'result-open' : (rNum > 0 ? 'result-win' : 'result-loss');
              const rText = t.status === 'open' ? 'OPEN' : (Number.isFinite(rNum) ? `${rNum > 0 ? '+' : ''}${rNum.toFixed(2)}R` : '--');
              return `<tr>
                <td class="trade-name-cell"><strong>${escapeHtml(displayName(t))}</strong><code>ID: ${escapeHtml(shortId(t))}</code></td>
                <td><strong>${escapeHtml(t.pair || '')}</strong></td>
                <td><span class="candidate-dir dir-${escapeHtml(t.direction || '')}">${escapeHtml(String(t.direction || '').toUpperCase())}</span></td>
                <td class="small">${escapeHtml(t.setup_label || t.setup_type || '')}</td>
                <td>${escapeHtml(t.confidence || 0)}%</td>
                <td>${Number(t.rr_estimate || 0).toFixed(1)}R</td>
                <td class="small">${escapeHtml(t.entry_price || t.entry || '')}</td>
                <td class="small">${escapeHtml(t.stop_loss || '')}</td>
                <td class="small">${escapeHtml(t.take_profit || t.target || '')}</td>
                <td>${escapeHtml(t.status || '')}</td>
                <td class="${rClass}">${escapeHtml(rText)}</td>
                <td>${t.quality_tag ? `<span class="tag-pill">${escapeHtml(String(t.quality_tag).replace(/_/g,' '))}</span>` : ''}</td>
                <td class="muted small">${escapeHtml(String(t.filled_at || t.created_at || '').slice(0,16).replace('T',' '))}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      `;
    };
  }

  async function refreshQuickCloseDropdown() {
    const select = qs('quickCloseTradeSelect');
    if (!select || updatingQuickCloseSelect) return;
    updatingQuickCloseSelect = true;
    const previous = select.value;
    try {
      const data = await api('/api/agent/trades/open');
      const rows = data.open_trades || [];
      if (!rows.length) {
        select.innerHTML = '<option value="">No open trades to close</option>';
        return;
      }
      const chartPair = qs('chartPair')?.value || '';
      const sorted = [...rows].sort((a, b) => {
        const ap = String(a.pair || '') === chartPair ? 0 : 1;
        const bp = String(b.pair || '') === chartPair ? 0 : 1;
        return ap - bp;
      });
      select.innerHTML = sorted.map(t => {
        const id = escapeHtml(t.id || '');
        const pair = escapeHtml(t.pair || '');
        const label = escapeHtml(displayName(t));
        const entry = escapeHtml(t.entry_price || t.entry || '?');
        return `<option value="${id}" data-pair="${pair}">${label} @ ${entry}</option>`;
      }).join('');
      if (sorted.some(t => String(t.id) === String(previous))) select.value = previous;
    } catch (_) {
      select.innerHTML = '<option value="">Could not load open trades</option>';
    } finally {
      updatingQuickCloseSelect = false;
    }
  }

  async function refreshChartTradeChipNames() {
    const el = qs('chartTrades');
    if (!el) return;
    const cards = Array.from(el.querySelectorAll('.chart-trade-chip'));
    if (!cards.length) return;
    try {
      const data = await api('/api/agent/trades/open');
      const pair = qs('chartPair')?.value || '';
      const rows = (data.open_trades || []).filter(t => !pair || t.pair === pair);
      cards.forEach((card, index) => {
        const row = rows[index];
        const strong = card.querySelector('strong');
        if (row && strong) strong.textContent = displayName(row);
      });
    } catch (_) {}
  }

  function hookQuickCloseFunction() {
    const oldQuickCloseSelected = window.quickCloseSelectedTrade;
    if (typeof oldQuickCloseSelected !== 'function' || oldQuickCloseSelected.__friendlyNames) return;
    window.quickCloseSelectedTrade = async function quickCloseSelectedTradeFriendly() {
      const select = qs('quickCloseTradeSelect');
      const opt = select?.options?.[select.selectedIndex];
      const id = select?.value || '';
      const pair = opt?.dataset?.pair || '';
      if (typeof window.quickCloseTrade === 'function') return window.quickCloseTrade(id, pair);
      return oldQuickCloseSelected();
    };
    window.quickCloseSelectedTrade.__friendlyNames = true;
  }

  function init() {
    addTradeNameStyles();
    patchOpenTradeRenderer();
    patchTradeTableRenderer();
    hookQuickCloseFunction();
    refreshQuickCloseDropdown();
    refreshChartTradeChipNames();

    const observer = new MutationObserver(() => {
      hookQuickCloseFunction();
      refreshQuickCloseDropdown();
      refreshChartTradeChipNames();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    setInterval(() => {
      hookQuickCloseFunction();
      refreshQuickCloseDropdown();
      refreshChartTradeChipNames();
    }, 8000);
  }

  window.tradeDisplayName = displayName;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
