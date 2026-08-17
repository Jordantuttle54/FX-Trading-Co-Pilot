/* agent_chart.js - Phase 1.5 MetaTrader-style paper-trading chart */
'use strict';

(function () {
  const CHART_LIB_URL = 'https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js';
  const PAIRS = ['GBP/USD', 'EUR/USD', 'USD/JPY', 'EUR/GBP', 'GBP/JPY', 'XAU/USD'];
  const TIMEFRAMES = ['M1', 'M5', 'M15', 'H1', 'H4', 'D'];

  let chart = null;
  let candleSeries = null;
  let chartContainer = null;
  let activePriceLines = [];
  let refreshTimer = null;

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  async function chartApi(path) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || data.message || res.statusText;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function injectChartStyles() {
    if (qs('agentChartStyles')) return;
    const style = document.createElement('style');
    style.id = 'agentChartStyles';
    style.textContent = `
      .chart-shell { margin-top: 24px; }
      .chart-toolbar { display:flex; gap:12px; flex-wrap:wrap; align-items:end; margin: 12px 0 16px; }
      .chart-toolbar label { display:flex; flex-direction:column; gap:4px; font-size:12px; color:var(--text-muted); }
      .chart-toolbar select { min-width:110px; }
      .chart-frame { position:relative; min-height:520px; border:1px solid var(--border); border-radius:14px; background:#070d18; overflow:hidden; }
      #agentLiveChart { width:100%; height:520px; }
      .chart-loading { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; background:rgba(7,13,24,.78); color:var(--text-muted); z-index:4; }
      .chart-status-row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:10px; }
      .chart-pill { border:1px solid var(--border); background:var(--bg3); border-radius:999px; padding:5px 10px; font-size:12px; color:var(--text-muted); }
      .chart-pill strong { color:var(--text); }
      .chart-warning { color:var(--orange); font-size:12px; margin-top:8px; }
      .chart-trade-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; margin-top:14px; }
      .chart-trade-chip { border:1px solid var(--border); background:var(--bg3); border-radius:10px; padding:10px; font-size:12px; }
      .chart-trade-chip strong { display:block; margin-bottom:6px; }
      @media (max-width: 760px) { .chart-frame { min-height:380px; } #agentLiveChart { height:380px; } }
    `;
    document.head.appendChild(style);
  }

  function loadChartLibrary() {
    if (window.LightweightCharts) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${CHART_LIB_URL}"]`);
      if (existing) {
        existing.addEventListener('load', resolve, { once: true });
        existing.addEventListener('error', reject, { once: true });
        return;
      }
      const script = document.createElement('script');
      script.src = CHART_LIB_URL;
      script.async = true;
      script.onload = resolve;
      script.onerror = () => reject(new Error('Chart library failed to load'));
      document.head.appendChild(script);
    });
  }

  function injectChartPanel() {
    injectChartStyles();
    const tradesTab = qs('tab-trades');
    if (!tradesTab || qs('agentChartPanel')) return;

    const card = document.createElement('div');
    card.className = 'agent-card chart-shell';
    card.id = 'agentChartPanel';
    card.innerHTML = `
      <h2>Live Trade Chart</h2>
      <p class="card-sub">MetaTrader-style paper-trading chart using OANDA practice candles where available. Live-money trading remains locked.</p>
      <div class="chart-toolbar">
        <label>Pair
          <select id="chartPair">${PAIRS.map(p => `<option value="${p}">${p}</option>`).join('')}</select>
        </label>
        <label>Timeframe
          <select id="chartTimeframe">${TIMEFRAMES.map(tf => `<option value="${tf}" ${tf === 'H1' ? 'selected' : ''}>${tf}</option>`).join('')}</select>
        </label>
        <label>Open trade overlay
          <select id="chartTradeSelect"><option value="">All open trades on pair</option></select>
        </label>
        <button class="btn-primary" id="chartRefreshBtn" onclick="loadAgentChart()">Refresh Chart</button>
        <button class="btn-secondary" id="chartAutoBtn" onclick="toggleAgentChartAutoRefresh()">Auto Refresh: Off</button>
      </div>
      <div class="chart-frame">
        <div id="agentLiveChart"></div>
        <div id="chartLoading" class="chart-loading" style="display:none">Loading chart...</div>
      </div>
      <div id="chartStatus" class="chart-status-row"></div>
      <div id="chartWarnings"></div>
      <div id="chartTrades" class="chart-trade-list"></div>
    `;

    const firstCard = tradesTab.querySelector('.agent-grid-2');
    if (firstCard && firstCard.parentNode) {
      firstCard.parentNode.insertBefore(card, firstCard.nextSibling);
    } else {
      tradesTab.prepend(card);
    }

    qs('chartPair')?.addEventListener('change', () => loadAgentChart());
    qs('chartTimeframe')?.addEventListener('change', () => loadAgentChart());
    qs('chartTradeSelect')?.addEventListener('change', () => loadAgentChart());
  }

  function convertTime(value) {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return Math.floor(Date.now() / 1000);
    return Math.floor(d.getTime() / 1000);
  }

  function chartData(candles) {
    return (candles || []).map(c => ({
      time: convertTime(c.time),
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),
    })).filter(c => Number.isFinite(c.open) && Number.isFinite(c.high) && Number.isFinite(c.low) && Number.isFinite(c.close));
  }

  function clearPriceLines() {
    if (!candleSeries) return;
    activePriceLines.forEach(line => {
      try { candleSeries.removePriceLine(line); } catch (_) {}
    });
    activePriceLines = [];
  }

  function addPriceLine(price, title, color, style) {
    if (!candleSeries || !Number.isFinite(Number(price))) return;
    activePriceLines.push(candleSeries.createPriceLine({
      price: Number(price),
      color,
      lineWidth: 2,
      lineStyle: style || 0,
      axisLabelVisible: true,
      title,
    }));
  }

  function initChart() {
    chartContainer = qs('agentLiveChart');
    if (!chartContainer || !window.LightweightCharts) return;
    if (chart) {
      chart.resize(chartContainer.clientWidth || 900, chartContainer.clientHeight || 520);
      return;
    }

    chart = window.LightweightCharts.createChart(chartContainer, {
      width: chartContainer.clientWidth || 900,
      height: chartContainer.clientHeight || 520,
      layout: { background: { color: '#070d18' }, textColor: '#cbd5e1' },
      grid: { vertLines: { color: '#142033' }, horzLines: { color: '#142033' } },
      crosshair: { mode: window.LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#243244' },
      timeScale: { borderColor: '#243244', timeVisible: true, secondsVisible: false },
    });

    candleSeries = chart.addCandlestickSeries({
      upColor: '#16a34a', downColor: '#dc2626', borderUpColor: '#16a34a', borderDownColor: '#dc2626', wickUpColor: '#16a34a', wickDownColor: '#dc2626',
    });

    window.addEventListener('resize', () => {
      if (chart && chartContainer) chart.resize(chartContainer.clientWidth || 900, chartContainer.clientHeight || 520);
    });
  }

  async function updateTradeDropdown(selectedPair) {
    const select = qs('chartTradeSelect');
    if (!select) return;
    try {
      const data = await chartApi('/api/agent/trades/open');
      const open = (data.open_trades || []).filter(t => t.pair === selectedPair);
      const current = select.value;
      select.innerHTML = '<option value="">All open trades on pair</option>' + open.map(t => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.direction || '')} ${escapeHtml(t.id || '').slice(0, 8)} - ${escapeHtml(t.setup_label || t.setup_type || 'paper trade')}</option>`).join('');
      if (open.some(t => String(t.id) === String(current))) select.value = current;
    } catch (_) {
      select.innerHTML = '<option value="">All open trades on pair</option>';
    }
  }

  function renderStatus(data) {
    const quote = data.current_price || {};
    const status = qs('chartStatus');
    if (!status) return;
    status.innerHTML = `
      <span class="chart-pill">Pair: <strong>${escapeHtml(data.pair)}</strong></span>
      <span class="chart-pill">Timeframe: <strong>${escapeHtml(data.timeframe)}</strong></span>
      <span class="chart-pill">Provider: <strong>${escapeHtml(data.provider)}</strong></span>
      <span class="chart-pill">Price: <strong>${quote.price ?? '--'}</strong></span>
      <span class="chart-pill">Spread: <strong>${quote.spread_pips ?? '--'} pips</strong></span>
      <span class="chart-pill">Paper only: <strong>Live locked</strong></span>
    `;

    const warningBox = qs('chartWarnings');
    if (warningBox) {
      warningBox.innerHTML = (data.warnings || []).length ? `<div class="chart-warning">${data.warnings.map(escapeHtml).join('<br>')}</div>` : '';
    }
  }

  function renderTradeChips(lines) {
    const el = qs('chartTrades');
    if (!el) return;
    if (!lines || !lines.length) {
      el.innerHTML = '<div class="muted small">No open trade lines for this pair. Choose a pair with an open paper trade to show entry, stop and target.</div>';
      return;
    }
    el.innerHTML = lines.map(t => `
      <div class="chart-trade-chip">
        <strong>${escapeHtml(t.pair)} ${escapeHtml(String(t.direction || '').toUpperCase())}</strong>
        Entry: ${t.entry ?? '?'}<br>
        Stop: ${t.stop_loss ?? '?'}<br>
        Target: ${t.take_profit ?? '?'}<br>
        <span class="muted">${escapeHtml(t.setup_label || '')}</span>
      </div>
    `).join('');
  }

  function applyOverlays(data) {
    clearPriceLines();
    const quote = data.current_price || {};
    if (quote.price) addPriceLine(Number(quote.price), 'Current', '#eab308', 2);
    (data.trade_lines || []).forEach(t => {
      addPriceLine(Number(t.entry), `${String(t.direction || '').toUpperCase()} Entry`, '#60a5fa', 0);
      addPriceLine(Number(t.stop_loss), 'Stop Loss', '#ef4444', 1);
      addPriceLine(Number(t.take_profit), 'Take Profit', '#22c55e', 1);
    });
  }

  function applyMarkers(data) {
    if (!candleSeries) return;
    const markers = (data.trade_markers || []).map(m => {
      const isExit = m.type === 'exit';
      const isBuy = String(m.direction || '').toLowerCase() === 'buy';
      return {
        time: convertTime(m.time),
        position: isExit ? 'aboveBar' : (isBuy ? 'belowBar' : 'aboveBar'),
        color: isExit ? '#f59e0b' : (isBuy ? '#22c55e' : '#ef4444'),
        shape: isExit ? 'circle' : (isBuy ? 'arrowUp' : 'arrowDown'),
        text: m.label || (isExit ? 'Exit' : 'Entry'),
      };
    }).filter(m => Number.isFinite(m.time));
    candleSeries.setMarkers(markers);
  }

  window.loadAgentChart = async function loadAgentChart() {
    injectChartPanel();
    const loading = qs('chartLoading');
    const pair = qs('chartPair')?.value || 'GBP/USD';
    const timeframe = qs('chartTimeframe')?.value || 'H1';
    const tradeId = qs('chartTradeSelect')?.value || '';
    if (loading) loading.style.display = 'flex';

    try {
      await loadChartLibrary();
      initChart();
      await updateTradeDropdown(pair);
      const url = `/api/agent/chart/candles?pair=${encodeURIComponent(pair)}&timeframe=${encodeURIComponent(timeframe)}&count=180${tradeId ? `&trade_id=${encodeURIComponent(tradeId)}` : ''}`;
      const data = await chartApi(url);
      const candles = chartData(data.candles);
      if (!candles.length) throw new Error('No candle data returned');
      candleSeries.setData(candles);
      chart.timeScale().fitContent();
      applyOverlays(data);
      applyMarkers(data);
      renderStatus(data);
      renderTradeChips(data.trade_lines || []);
    } catch (e) {
      const status = qs('chartStatus');
      if (status) status.innerHTML = `<span class="chart-pill">Chart error: <strong>${escapeHtml(e.message || e)}</strong></span>`;
    } finally {
      if (loading) loading.style.display = 'none';
    }
  };

  window.toggleAgentChartAutoRefresh = function toggleAgentChartAutoRefresh() {
    const btn = qs('chartAutoBtn');
    if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
      if (btn) btn.textContent = 'Auto Refresh: Off';
      return;
    }
    refreshTimer = setInterval(() => window.loadAgentChart(), 30000);
    if (btn) btn.textContent = 'Auto Refresh: 30s';
    window.loadAgentChart();
  };

  function enhanceTabSwitch() {
    const oldSwitch = window.switchTab;
    if (typeof oldSwitch !== 'function' || oldSwitch.__chartEnhanced) return;
    window.switchTab = function switchTabChartEnhanced(name) {
      const result = oldSwitch(name);
      if (name === 'trades') {
        setTimeout(() => {
          injectChartPanel();
          window.loadAgentChart();
        }, 150);
      }
      return result;
    };
    window.switchTab.__chartEnhanced = true;
  }

  function init() {
    injectChartPanel();
    enhanceTabSwitch();
    if (document.querySelector('#tab-trades.active')) {
      window.loadAgentChart();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
