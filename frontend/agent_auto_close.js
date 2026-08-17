/* agent_auto_close.js - TP/SL paper auto-close notifier + lightweight performance guard */
'use strict';

(function () {
  if (!window.__agentPerfModeInstalled) {
    window.__agentPerfModeInstalled = true;
    const nativeSetInterval = window.setInterval.bind(window);
    const nativeFetch = window.fetch.bind(window);
    const responseCache = new Map();
    const inflight = new Map();

    function urlOf(input) {
      return typeof input === 'string' ? input : (input && input.url) || '';
    }

    function methodOf(init) {
      return String((init && init.method) || 'GET').toUpperCase();
    }

    function cacheKey(input, init) {
      return `${methodOf(init)} ${urlOf(input)}`;
    }

    function cloneResponse(res) {
      try { return res.clone(); } catch (_) { return res; }
    }

    function invalidateTradeCaches() {
      for (const key of Array.from(responseCache.keys())) {
        if (key.includes('/api/agent/trades')) responseCache.delete(key);
      }
      for (const key of Array.from(inflight.keys())) {
        if (key.includes('/api/agent/trades')) inflight.delete(key);
      }
    }

    function ttlFor(url, method) {
      if (method !== 'GET') return 0;
      if (url.includes('/api/agent/trades/open')) return 3500;
      if (url.match(/\/api\/agent\/trades($|\?)/)) return 30000;
      if (url.includes('/api/agent/trades/auto-close-check')) return 25000;
      return 0;
    }

    window.fetch = function agentPerfFetch(input, init) {
      const url = urlOf(input);
      const method = methodOf(init);

      if (method !== 'GET' && url.includes('/api/agent/trades')) {
        invalidateTradeCaches();
        return nativeFetch(input, init).finally(invalidateTradeCaches);
      }

      const ttl = ttlFor(url, method);
      if (!ttl) return nativeFetch(input, init);

      const key = cacheKey(input, init);
      const cached = responseCache.get(key);
      const now = Date.now();
      if (cached && now - cached.time < ttl) return Promise.resolve(cloneResponse(cached.response));
      if (inflight.has(key)) return inflight.get(key).then(cloneResponse);

      const request = nativeFetch(input, init).then(res => {
        try { responseCache.set(key, { time: Date.now(), response: res.clone() }); } catch (_) {}
        return res;
      }).finally(() => inflight.delete(key));
      inflight.set(key, request);
      return request;
    };

    window.setInterval = function agentPerfSetInterval(callback, delay, ...args) {
      let newDelay = delay;
      try {
        const name = typeof callback === 'function' ? callback.name || '' : '';
        const src = typeof callback === 'function' ? String(callback) : '';
        if (Number(delay) === 5000 && (name === 'pollLiveTick' || src.includes('pollLiveTick'))) newDelay = 15000;
        if (Number(delay) === 10000 && src.includes('runAutoCloseCheck')) newDelay = 30000;
      } catch (_) {}
      return nativeSetInterval(callback, newDelay, ...args);
    };

    window.agentPerfInvalidateTradeCaches = invalidateTradeCaches;
  }

  const seenAutoCloseIds = new Set();
  let checking = false;
  let timeframeReloadTimer = null;
  let lastTimeframeHandledAt = 0;
  let lastChartTriggeredCheckAt = 0;

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }

  function selectedPair() {
    return qs('chartPair')?.value || '';
  }

  function addStyles() {
    if (qs('autoCloseStyles')) return;
    const style = document.createElement('style');
    style.id = 'autoCloseStyles';
    style.textContent = `
      .auto-close-notice { border:1px solid var(--green); background:rgba(34,197,94,0.10); border-radius:10px; padding:10px 12px; margin:10px 0; font-size:12px; line-height:1.5; }
      .auto-close-loss { border-color:var(--red); background:rgba(239,68,68,0.10); }
      .auto-close-notice strong { display:block; margin-bottom:3px; }
    `;
    document.head.appendChild(style);
  }

  function resultLabel(action) {
    const reason = action.reason === 'take_profit_hit' ? 'Take Profit hit' : 'Stop Loss hit';
    const name = action.display_name || action.trade_id || 'Paper trade';
    const r = Number(action.result_r || 0);
    const money = Number(action.result_money || 0);
    return `${name} - ${reason} at ${action.close_price}. Result: ${r >= 0 ? '+' : ''}${r.toFixed(2)}R / ${money >= 0 ? '+' : ''}${money.toFixed(2)}`;
  }

  function showAutoCloseNotice(actions) {
    if (!actions || !actions.length) return;
    addStyles();
    const host = qs('quickTradeResult') || qs('manageResult') || qs('tradeJournalPanel');
    if (!host) return;
    const fresh = actions.filter(a => {
      const key = `${a.trade_id || ''}-${a.reason || ''}-${a.close_price || ''}`;
      if (seenAutoCloseIds.has(key)) return false;
      seenAutoCloseIds.add(key);
      return true;
    });
    if (!fresh.length) return;
    const loss = fresh.some(a => a.reason === 'stop_loss_hit');
    const html = `<div class="auto-close-notice ${loss ? 'auto-close-loss' : ''}"><strong>Paper trade auto-closed</strong>${fresh.map(a => `<div>${escapeHtml(resultLabel(a))}</div>`).join('')}</div>`;
    host.innerHTML = html + (host.innerHTML || '');
  }

  async function refreshTradingUi() {
    if (typeof window.agentPerfInvalidateTradeCaches === 'function') window.agentPerfInvalidateTradeCaches();
    if (typeof window.loadStatus === 'function') await window.loadStatus();
    if (typeof window.loadOpenTradesDetail === 'function') await window.loadOpenTradesDetail();
    if (typeof window.loadAllTrades === 'function') await window.loadAllTrades();
    if (typeof window.loadAgentChart === 'function') await window.loadAgentChart();
  }

  async function runAutoCloseCheck(pair) {
    if (checking) return;
    checking = true;
    try {
      const suffix = pair ? `?pair=${encodeURIComponent(pair)}` : '';
      const data = await api(`/api/agent/trades/auto-close-check${suffix}`);
      const actions = data.actions || [];
      if (actions.length) {
        showAutoCloseNotice(actions);
        await refreshTradingUi();
      }
    } catch (_) {
      // Keep this silent so a temporary quote/feed issue does not interrupt the dashboard.
    } finally {
      checking = false;
    }
  }

  function hookChartResponses() {
    const oldLoadChart = window.loadAgentChart;
    if (typeof oldLoadChart === 'function' && !oldLoadChart.__autoCloseHooked) {
      window.loadAgentChart = async function loadAgentChartAutoCloseHooked(...args) {
        const result = await oldLoadChart.apply(this, args);
        const now = Date.now();
        if (now - lastChartTriggeredCheckAt > 30000) {
          lastChartTriggeredCheckAt = now;
          runAutoCloseCheck(selectedPair());
        }
        return result;
      };
      window.loadAgentChart.__autoCloseHooked = true;
    }
  }

  function scheduleStableTimeframeReload() {
    clearTimeout(timeframeReloadTimer);
    timeframeReloadTimer = setTimeout(async () => {
      if (typeof window.loadAgentChart !== 'function') return;
      try {
        await window.loadAgentChart({ keepTradesCache: true });
      } catch (_) {
        // Main chart module handles visible errors.
      }
    }, 120);
  }

  function hookTimeframeChange() {
    if (document.__agentTimeframeOverlayHooked) return;
    document.__agentTimeframeOverlayHooked = true;
    document.addEventListener('change', event => {
      const target = event.target;
      if (!target || target.id !== 'chartTimeframe') return;
      const now = Date.now();
      if (now - lastTimeframeHandledAt < 250) return;
      lastTimeframeHandledAt = now;
      event.stopImmediatePropagation();
      scheduleStableTimeframeReload();
    }, true);
  }

  function init() {
    addStyles();
    hookChartResponses();
    hookTimeframeChange();
    setTimeout(() => runAutoCloseCheck(''), 4500);
    setInterval(() => {
      hookChartResponses();
      hookTimeframeChange();
      runAutoCloseCheck('');
    }, 30000);
  }

  window.checkPaperAutoClose = runAutoCloseCheck;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
