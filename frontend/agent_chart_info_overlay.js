/* agent_chart_info_overlay.js - TradingView-style chart info strip, using app styling */
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
      #chartLevelStack,
      .chart-level-stack { display: none !important; }
      @media (max-width: 900px) {
        .chart-tv-strip { right: 12px; font-size: 10px; }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureStrip() {
    const frame = document.querySelector('#agentLiveChart')?.closest('.chart-frame');
    if (!frame) return null;
    const oldLevels = qs('chartLevelStack');
    if (oldLevels) oldLevels.remove();
    let strip = qs('chartTvStrip');
    if (!strip) {
      strip = document.createElement('div');
      strip.id = 'chartTvStrip';
      strip.className = 'chart-tv-strip';
      frame.appendChild(strip);
    }
    return strip;
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

  async function renderOverlay() {
    if (rendering || !activeTradesTab()) return;
    const strip = ensureStrip();
    if (!strip) return;
    rendering = true;
    try {
      const valuePair = pair();
      const tf = timeframe();
      const data = await api(`/api/agent/chart/candles?pair=${encodeURIComponent(valuePair)}&timeframe=${encodeURIComponent(tf)}&count=180`);
      renderStrip(strip, data);
    } catch (e) {
      const stripAfterError = ensureStrip();
      if (stripAfterError) stripAfterError.innerHTML = `<span class="tv-negative">Chart info unavailable: ${escapeHtml(e.message || e)}</span>`;
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
