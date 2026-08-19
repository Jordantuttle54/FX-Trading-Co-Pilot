/* agent_chart_info_overlay.js - TradingView-style chart info, using app styling */
'use strict';

(function () {
  if (window.__agentChartInfoOverlayInstalled) return;
  window.__agentChartInfoOverlayInstalled = true;

  let installTimer = null;
  let refreshTimer = null;
  let rendering = false;

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  function num(value, fallback = null) {
    if (value === null || value === undefined || value === '') return fallback;
    const n = Number(String(value).replace(/[£$,]/g, ''));
    return Number.isFinite(n) ? n : fallback;
  }

  async function api(path) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }

  function activeTradesTab() {
    return !!document.querySelector('#tab-trades.active');
  }

  function pair() {
    return qs('chartPair')?.value || 'GBP/USD';
  }

  function timeframe() {
    return qs('chartTimeframe')?.value || 'H1';
  }

  function precisionForPair(valuePair) {
    const p = String(valuePair || pair()).toUpperCase();
    if (p.includes('XAU') || p.includes('XAG')) return 2;
    if (p.includes('JPY')) return 3;
    return 5;
  }

  function formatPrice(value, valuePair) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return n.toFixed(precisionForPair(valuePair));
  }

  function tradeNumber(trade) {
    const fields = [trade.display_name, trade.friendly_name, trade.trade_name, trade.short_name, trade.label, trade.short_trade_id, trade.id];
    for (const field of fields) {
      const match = String(field || '').match(/#\d{1,6}/);
      if (match) return match[0];
    }
    const id = String(trade.id || '');
    return id ? `#${id.slice(0, 4)}` : '#----';
  }

  function entryValue(trade) { return num(trade.entry, num(trade.entry_price, num(trade.open_price, null))); }
  function slValue(trade) { return num(trade.stop_loss, num(trade.sl, null)); }
  function tpValue(trade) { return num(trade.take_profit, num(trade.target, num(trade.tp, null))); }

  function directionValue(trade) {
    return String(trade.direction || '').toLowerCase();
  }

  function distanceText(from, to, valuePair) {
    const a = Number(from);
    const b = Number(to);
    if (!Number.isFinite(a) || !Number.isFinite(b)) return '--';
    const p = String(valuePair || pair()).toUpperCase();
    if (p.includes('JPY')) return `${Math.abs(a - b).toFixed(3)}`;
    if (p.includes('XAU') || p.includes('XAG')) return `${Math.abs(a - b).toFixed(2)}`;
    return `${Math.abs(a - b).toFixed(5)}`;
  }

  function injectStyles() {
    if (qs('agentChartInfoOverlayStyles')) return;
    const style = document.createElement('style');
    style.id = 'agentChartInfoOverlayStyles';
    style.textContent = `
      .chart-frame { position: relative !important; }
      .chart-tv-strip {
        position: absolute;
        top: 8px;
        left: 10px;
        right: 86px;
        z-index: 5;
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
        pointer-events: none;
        padding: 6px 8px;
        border: 1px solid rgba(148, 163, 184, .22);
        background: rgba(7, 13, 24, .74);
        backdrop-filter: blur(7px);
        border-radius: 10px;
        color: #cbd5e1;
        font-size: 11px;
        line-height: 1.1;
        box-shadow: 0 10px 26px rgba(0, 0, 0, .22);
      }
      .chart-tv-strip strong { color: #f8fafc; font-weight: 850; }
      .chart-tv-strip .tv-positive { color: #22c55e; font-weight: 850; }
      .chart-tv-strip .tv-negative { color: #ef4444; font-weight: 850; }
      .chart-tv-strip .tv-flat { color: #94a3b8; font-weight: 850; }
      .chart-level-stack {
        position: absolute;
        top: 48px;
        right: 10px;
        z-index: 5;
        display: grid;
        gap: 6px;
        max-width: 190px;
        pointer-events: none;
      }
      .chart-level-chip {
        border-radius: 8px;
        padding: 5px 7px;
        font-size: 10px;
        line-height: 1.15;
        border: 1px solid rgba(255,255,255,.18);
        background: rgba(15, 23, 42, .86);
        color: #f8fafc;
        box-shadow: 0 8px 18px rgba(0,0,0,.22);
        white-space: nowrap;
      }
      .chart-level-chip strong { font-weight: 900; }
      .chart-level-current { border-color: rgba(59,130,246,.7); color: #93c5fd; }
      .chart-level-entry { border-color: rgba(250,204,21,.75); color: #fde68a; }
      .chart-level-sl { border-color: rgba(239,68,68,.75); color: #fca5a5; }
      .chart-level-tp { border-color: rgba(34,197,94,.75); color: #86efac; }
      @media (max-width: 900px) {
        .chart-tv-strip { right: 12px; font-size: 10px; }
        .chart-level-stack { display: none; }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureContainers() {
    const frame = document.querySelector('#agentLiveChart')?.closest('.chart-frame');
    if (!frame) return null;
    let strip = qs('chartTvStrip');
    if (!strip) {
      strip = document.createElement('div');
      strip.id = 'chartTvStrip';
      strip.className = 'chart-tv-strip';
      frame.appendChild(strip);
    }
    let levels = qs('chartLevelStack');
    if (!levels) {
      levels = document.createElement('div');
      levels.id = 'chartLevelStack';
      levels.className = 'chart-level-stack';
      frame.appendChild(levels);
    }
    return { strip, levels };
  }

  function renderStrip(container, data) {
    const candles = data.candles || [];
    const last = candles[candles.length - 1] || {};
    const previous = candles[candles.length - 2] || last;
    const valuePair = data.pair || pair();
    const open = num(last.open, null);
    const high = num(last.high, null);
    const low = num(last.low, null);
    const close = num(last.close, null);
    const previousClose = num(previous.close, close);
    const change = close !== null && previousClose !== null ? close - previousClose : 0;
    const changePct = previousClose ? (change / previousClose) * 100 : 0;
    const changeClass = change > 0 ? 'tv-positive' : change < 0 ? 'tv-negative' : 'tv-flat';
    const quote = data.current_price || {};
    const bid = num(quote.bid, null);
    const ask = num(quote.ask, null);
    const spread = quote.spread_pips ?? '--';

    container.innerHTML = `
      <strong>${escapeHtml(valuePair)}</strong>
      <span>${escapeHtml(data.timeframe || timeframe())}</span>
      <span>${escapeHtml(String(data.provider || 'provider').toUpperCase())}</span>
      <span>O <strong>${formatPrice(open, valuePair)}</strong></span>
      <span>H <strong>${formatPrice(high, valuePair)}</strong></span>
      <span>L <strong>${formatPrice(low, valuePair)}</strong></span>
      <span>C <strong>${formatPrice(close, valuePair)}</strong></span>
      <span class="${changeClass}">${change >= 0 ? '+' : ''}${formatPrice(change, valuePair)} (${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%)</span>
      <span>Bid <strong>${formatPrice(bid, valuePair)}</strong></span>
      <span>Ask <strong>${formatPrice(ask, valuePair)}</strong></span>
      <span>Spread <strong>${escapeHtml(spread)}</strong></span>
    `;
  }

  function renderLevels(container, data, trades) {
    const valuePair = data.pair || pair();
    const quote = data.current_price || {};
    const current = num(quote.price, num(quote.mid, num(quote.bid, num(quote.ask, null))));
    const openTrades = (trades || []).filter(t => String(t.pair || '').toUpperCase() === String(valuePair).toUpperCase());
    const rows = [];
    if (current !== null) rows.push(`<div class="chart-level-chip chart-level-current"><strong>Current</strong> ${formatPrice(current, valuePair)}</div>`);
    openTrades.forEach(t => {
      const n = tradeNumber(t);
      const entry = entryValue(t);
      const sl = slValue(t);
      const tp = tpValue(t);
      const dir = directionValue(t).toUpperCase();
      if (entry !== null) rows.push(`<div class="chart-level-chip chart-level-entry"><strong>${n} Entry</strong> ${formatPrice(entry, valuePair)} ${dir ? `· ${escapeHtml(dir)}` : ''}</div>`);
      if (sl !== null) rows.push(`<div class="chart-level-chip chart-level-sl"><strong>${n} SL</strong> ${formatPrice(sl, valuePair)} <span class="muted">· ${distanceText(current, sl, valuePair)}</span></div>`);
      if (tp !== null) rows.push(`<div class="chart-level-chip chart-level-tp"><strong>${n} TP</strong> ${formatPrice(tp, valuePair)} <span class="muted">· ${distanceText(current, tp, valuePair)}</span></div>`);
    });
    container.innerHTML = rows.join('');
  }

  async function renderOverlay() {
    if (rendering || !activeTradesTab()) return;
    const containers = ensureContainers();
    if (!containers) return;
    rendering = true;
    try {
      const valuePair = pair();
      const tf = timeframe();
      const [data, tradeData] = await Promise.all([
        api(`/api/agent/chart/candles?pair=${encodeURIComponent(valuePair)}&timeframe=${encodeURIComponent(tf)}&count=180`),
        api('/api/agent/trades/open').catch(() => ({ open_trades: [] })),
      ]);
      renderStrip(containers.strip, data);
      renderLevels(containers.levels, data, tradeData.open_trades || tradeData.trades || []);
    } catch (e) {
      const containersAfterError = ensureContainers();
      if (containersAfterError) containersAfterError.strip.innerHTML = `<span class="tv-negative">Chart info unavailable: ${escapeHtml(e.message || e)}</span>`;
    } finally {
      rendering = false;
    }
  }

  function patchLoadAgentChart() {
    if (typeof window.loadAgentChart !== 'function' || window.loadAgentChart.__chartInfoPatched) return false;
    const original = window.loadAgentChart;
    window.loadAgentChart = async function loadAgentChartWithInfo(...args) {
      const result = await original.apply(this, args);
      setTimeout(renderOverlay, 180);
      return result;
    };
    window.loadAgentChart.__chartInfoPatched = true;
    setTimeout(renderOverlay, 250);
    return true;
  }

  function start() {
    injectStyles();
    if (!patchLoadAgentChart()) {
      installTimer = setInterval(() => {
        if (patchLoadAgentChart()) {
          clearInterval(installTimer);
          installTimer = null;
        }
      }, 250);
    }
    if (!refreshTimer) refreshTimer = setInterval(renderOverlay, 15000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
