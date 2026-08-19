/* agent_chart_precision_patch.js - full-precision Lightweight Charts price labels */
'use strict';

(function () {
  if (window.__agentChartPrecisionPatchInstalled) return;
  window.__agentChartPrecisionPatchInstalled = true;

  const CHART_LIB_MARKER = 'lightweight-charts';

  function currentPair() {
    return document.getElementById('chartPair')?.value || 'GBP/USD';
  }

  function precisionForPair(pair) {
    const p = String(pair || currentPair()).toUpperCase();
    if (p.includes('XAU') || p.includes('XAG')) return 2;
    if (p.includes('JPY')) return 3;
    return 5;
  }

  function priceFormatForPair(pair) {
    const precision = precisionForPair(pair);
    return {
      type: 'price',
      precision,
      minMove: precision === 2 ? 0.01 : precision === 3 ? 0.001 : 0.00001,
    };
  }

  function axisWidthForPair(pair) {
    const precision = precisionForPair(pair);
    if (precision === 5) return 96;
    if (precision === 3) return 82;
    return 76;
  }

  function applyChartAxis(chart, pair) {
    if (!chart || typeof chart.applyOptions !== 'function') return;
    try {
      chart.applyOptions({
        rightPriceScale: {
          borderColor: '#243244',
          alignLabels: true,
          minimumWidth: axisWidthForPair(pair),
        },
      });
    } catch (_) {}
  }

  function patchLibrary() {
    const lib = window.LightweightCharts;
    if (!lib || typeof lib.createChart !== 'function') return false;
    if (lib.__agentFullPrecisionPricePatched) return true;

    const originalCreateChart = lib.createChart.bind(lib);
    lib.createChart = function createChartWithFullPriceLabels(container, options = {}) {
      const initialPair = currentPair();
      const chart = originalCreateChart(container, {
        ...options,
        rightPriceScale: {
          ...(options.rightPriceScale || {}),
          minimumWidth: axisWidthForPair(initialPair),
          alignLabels: true,
        },
      });

      if (!chart || chart.__agentFullPrecisionChartPatched) return chart;

      const originalAddCandlestickSeries = typeof chart.addCandlestickSeries === 'function'
        ? chart.addCandlestickSeries.bind(chart)
        : null;

      if (originalAddCandlestickSeries) {
        chart.addCandlestickSeries = function addCandlestickSeriesWithFullPriceLabels(seriesOptions = {}) {
          const selectedPair = currentPair();
          const series = originalAddCandlestickSeries({
            ...seriesOptions,
            priceFormat: priceFormatForPair(selectedPair),
          });

          function applyPrecision() {
            const pair = currentPair();
            applyChartAxis(chart, pair);
            if (series && typeof series.applyOptions === 'function') {
              try { series.applyOptions({ priceFormat: priceFormatForPair(pair) }); } catch (_) {}
            }
          }

          applyPrecision();
          setTimeout(applyPrecision, 0);
          setTimeout(applyPrecision, 300);

          const pairSelect = document.getElementById('chartPair');
          if (pairSelect && !pairSelect.__agentFullPrecisionListener) {
            pairSelect.addEventListener('change', () => setTimeout(applyPrecision, 0));
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
    if (patchLibrary() || attempts++ > 200) clearInterval(timer);
  }, 25);
})();
