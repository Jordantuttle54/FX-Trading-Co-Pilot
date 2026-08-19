/* agent_chart_label_fix.js - compact full-precision chart line labels */
'use strict';

(function () {
  if (window.__agentChartLabelFixInstalled) return;
  window.__agentChartLabelFixInstalled = true;

  function qs(id) { return document.getElementById(id); }

  function currentPair() {
    return qs('chartPair')?.value || 'GBP/USD';
  }

  function formatChartPrice(price, pair) {
    const n = Number(price);
    if (!Number.isFinite(n)) return '--';
    const p = String(pair || currentPair()).toUpperCase();
    if (p.includes('XAU') || p.includes('XAG')) return n.toFixed(2);
    if (p.includes('JPY')) return n.toFixed(3);
    return n.toFixed(5);
  }

  function tradeNumberFromTitle(title) {
    const text = String(title || '');
    const match = text.match(/#\d{1,6}/);
    if (match) return match[0];
    return '';
  }

  function compactTitle(originalTitle, price) {
    const title = String(originalTitle || '').trim();
    const priceText = formatChartPrice(price, currentPair());
    const number = tradeNumberFromTitle(title);
    const lower = title.toLowerCase();

    if (lower.startsWith('current')) return `Current ${priceText}`;
    if (number && /\bsl\b/i.test(title)) return `${number} SL ${priceText}`;
    if (number && /\btp\b/i.test(title)) return `${number} TP ${priceText}`;
    if (number) return `${number} Entry ${priceText}`;
    if (title) return `${title} ${priceText}`;
    return priceText;
  }

  function patchSeries(series) {
    if (!series || series.__agentChartLabelFixSeriesPatched) return series;
    if (typeof series.createPriceLine !== 'function') return series;
    const originalCreatePriceLine = series.createPriceLine.bind(series);
    series.createPriceLine = function createPriceLineWithCompactLabel(options) {
      const next = { ...(options || {}) };
      next.title = compactTitle(next.title, next.price);
      return originalCreatePriceLine(next);
    };
    series.__agentChartLabelFixSeriesPatched = true;
    return series;
  }

  function patchChart(chart) {
    if (!chart || chart.__agentChartLabelFixChartPatched) return chart;
    ['addCandlestickSeries', 'addLineSeries', 'addAreaSeries', 'addBaselineSeries', 'addHistogramSeries'].forEach((method) => {
      if (typeof chart[method] !== 'function') return;
      const original = chart[method].bind(chart);
      chart[method] = function patchedAddSeries(...args) {
        return patchSeries(original(...args));
      };
    });
    chart.__agentChartLabelFixChartPatched = true;
    return chart;
  }

  function patchLightweightCharts(lib) {
    if (!lib || lib.__agentChartLabelFixLibPatched || typeof lib.createChart !== 'function') return lib;
    const originalCreateChart = lib.createChart.bind(lib);
    lib.createChart = function patchedCreateChart(...args) {
      return patchChart(originalCreateChart(...args));
    };
    lib.__agentChartLabelFixLibPatched = true;
    return lib;
  }

  function installSetter() {
    const descriptor = Object.getOwnPropertyDescriptor(window, 'LightweightCharts');
    if (descriptor && descriptor.configurable === false) {
      patchLightweightCharts(window.LightweightCharts);
      return;
    }

    let stored = window.LightweightCharts;
    Object.defineProperty(window, 'LightweightCharts', {
      configurable: true,
      enumerable: true,
      get() { return stored; },
      set(value) {
        stored = patchLightweightCharts(value);
      },
    });
    if (stored) stored = patchLightweightCharts(stored);
  }

  installSetter();
})();
