/* agent_perf_mode.js - lightweight frontend throttle for Hobby/serverless testing */
'use strict';

(function () {
  if (window.__agentPerfModeInstalled) return;
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
})();
