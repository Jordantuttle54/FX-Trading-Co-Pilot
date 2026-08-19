/* agent_chart_precision_patch.js - full-precision Lightweight Charts price labels */
'use strict';

(function () {
  if (window.__agentChartPrecisionPatchInstalled) return;
  window.__agentChartPrecisionPatchInstalled = true;

  const CHART_LIB_MARKER = 'lightweight-charts';

  function currentPair() {
    return document.getElementById('chartPair')?.value || window.__agentCurrentChartPair || 'GBP/USD';
  }

  function precisionForPair(pair) {
    const p = String(pair || currentPair()).toUpperCase();
    if (p.includes('XAU') || p.includes('XAG')) return 2;
    if (p.includes('JPY')) return 3;
    return 5;
  }

  function minMoveForPrecision(precision) {
    if (precision === 2) return 0.01;
    if (precision === 3) return 0.001;
    return 0.00001;
  }

  function formatFullPrice(value, pair) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return n.toFixed(precisionForPair(pair));
  }

  function priceFormatForPair(pair) {
    const precision = precisionForPair(pair);
    return {
      type: 'custom',
      minMove: minMoveForPrecision(precision),
      formatter: price => formatFullPrice(price, currentPair()),
    };
  }

  function applyChartFormatting(chart, series, pair) {
    const resolvedPair = pair || currentPair();
    if (chart && typeof chart.applyOptions === 'function') {
      try {
        chart.applyOptions({
          localization: {
            priceFormatter: price => formatFullPrice(price, currentPair()),
          },
          rightPriceScale: {
            borderColor: '#243244',
            alignLabels: true,
            entireTextOnly: true,
          },
        });
      } catch (_) {}
    }
    if (series && typeof series.applyOptions === 'function') {
      try { series.applyOptions({ priceFormat: priceFormatForPair(resolvedPair) }); } catch (_) {}
    }
  }

  function patchLibrary() {
    const lib = window.LightweightCharts;
    if (!lib || typeof lib.createChart !== 'function') return false;
    if (lib.__agentFullPrecisionPricePatched) return true;

    const originalCreateChart = lib.createChart.bind(lib);
    lib.createChart = function createChartWithFullPriceLabels(container, options = {}) {
      const chart = originalCreateChart(container, {
        ...options,
        localization: {
          ...(options.localization || {}),
          priceFormatter: price => formatFullPrice(price, currentPair()),
        },
        rightPriceScale: {
          ...(options.rightPriceScale || {}),
          alignLabels: true,
          entireTextOnly: true,
        },
      });

      if (!chart || chart.__agentFullPrecisionChartPatched) return chart;

      const originalAddCandlestickSeries = typeof chart.addCandlestickSeries === 'function'
        ? chart.addCandlestickSeries.bind(chart)
        : null;

      if (originalAddCandlestickSeries) {
        chart.addCandlestickSeries = function addCandlestickSeriesWithFullPriceLabels(seriesOptions = {}) {
          const series = originalAddCandlestickSeries({
            ...seriesOptions,
            priceFormat: priceFormatForPair(currentPair()),
          });

          const applyPrecision = () => applyChartFormatting(chart, series, currentPair());
          applyPrecision();
          setTimeout(applyPrecision, 0);
          setTimeout(applyPrecision, 250);
          setTimeout(applyPrecision, 750);

          const pairSelect = document.getElementById('chartPair');
          if (pairSelect && !pairSelect.__agentFullPrecisionListener) {
            pairSelect.addEventListener('change', () => {
              window.__agentCurrentChartPair = pairSelect.value;
              setTimeout(applyPrecision, 0);
              setTimeout(applyPrecision, 300);
            });
            pairSelect.__agentFullPrecisionListener = true;
          }

          return series;
        };
      }

      chart.__agentFullPrecisionChartPatched = true;
      return chart;
    };

    lib.__agentFullPrecisionPricePatched = true;
    return true;
  }

  function installScriptLoadHook() {
    if (Node.prototype.__agentPrecisionAppendPatched) return;
    const originalAppendChild = Node.prototype.appendChild;
    Node.prototype.appendChild = function appendChildWithChartPrecisionHook(node) {
      if (node && node.tagName === 'SCRIPT' && String(node.src || '').includes(CHART_LIB_MARKER)) {
        node.addEventListener('load', () => patchLibrary(), { once: true, capture: true });
      }
      return originalAppendChild.call(this, node);
    };
    Node.prototype.__agentPrecisionAppendPatched = true;
  }

  installScriptLoadHook();
  patchLibrary();

  let attempts = 0;
  const timer = setInterval(() => {
    if (patchLibrary() || attempts++ > 240) clearInterval(timer);
  }, 25);
})();
