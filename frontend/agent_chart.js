/* agent_chart.js - Phase 1.6 live MetaTrader-style candle updates */
'use strict';

(function () {
  const CHART_LIB_URL = 'https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js';
  const PAIRS = ['GBP/USD', 'EUR/USD', 'USD/JPY', 'EUR/GBP', 'GBP/JPY', 'XAU/USD'];
  const TIMEFRAMES = ['M1', 'M5', 'M15', 'H1', 'H4', 'D'];
  const TF_SECONDS = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400, D: 86400 };
  const ALL_TRADES_VALUE = '__all__';

  let chart = null;
  let candleSeries = null;
  let chartContainer = null;
  let currentPriceLine = null;
  let tradePriceLines = [];
  let refreshTimer = null;
  let liveTickTimer = null;
  let liveCandleEnabled = true;
  let currentCandles = [];
  let activeChartMeta = { pair: 'GBP/USD', timeframe: 'H1', provider: 'loading' };

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
      .chart-live-on { border-color:rgba(34,197,94,.5); color:#86efac; }
      .chart-live-off { border-color:rgba(239,68,68,.5); color:#fca5a5; }
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
      <p class="card-sub">Clean paper-trading chart. By default it shows the latest open trade only, with live-money trading locked.</p>
      <div class="chart-toolbar">
        <label>Pair
          <select id="chartPair">${PAIRS.map(p => `<option value="${p}">${p}</option>`).join('')}</select>
        </label>
        <label>Timeframe
          <select id="chartTimeframe">${TIMEFRAMES.map(tf => `<option value="${tf}" ${tf === 'H1' ? 'selected' : ''}>${tf}</option>`).join('')}</select>
        </label>
        <label>Trade overlay
          <select id="chartTradeSelect"><option value="">No open trades on pair</option></select>
        </label>
        <button class="btn-primary" id="chartRefreshBtn" onclick="loadAgentChart()">Refresh Chart</button>
        <button class="btn-secondary" id="chartLiveBtn" onclick="toggleAgentLiveCandle()">Live Candle: On</button>
        <button class="btn-secondary" id="chartAutoBtn" onclick="toggleAgentChartAutoRefresh()">Full Refresh: Off</button>
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

  function bucketTime(epochSeconds, timeframe) {
    const tf = timeframe || activeChartMeta.timeframe || 'H1';
    const step = TF_SECONDS[tf] || 3600;
    return Math.floor(epochSeconds / step) * step;
  }

  function chartData(candles) {
    return (candles || []).map(c => ({
      time: convertTime(c.time),
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),
    })).filter(c => Number.isFinite(c.time) && Number.isFinite(c.open) && Number.isFinite(c.high) && Number.isFinite(c.low) && Number.isFinite(c.close));
  }

  function clearPriceLines() {
    if (!candleSeries) return;
    if (currentPriceLine) {
      try { candleSeries.removePriceLine(currentPriceLine); } catch (_) {}
      currentPriceLine = null;
    }
    tradePriceLines.forEach(line => {
      try { candleSeries.removePriceLine(line); } catch (_) {}
    });
    tradePriceLines = [];
  }

  function setCurrentPriceLine(price) {
    if (!candleSeries || !Number.isFinite(Number(price))) return;
    if (currentPriceLine) {
      try { candleSeries.removePriceLine(currentPriceLine); } catch (_) {}
      currentPriceLine = null;
    }
    currentPriceLine = candleSeries.createPriceLine({
      price: Number(price),
      color: '#eab308',
      lineWidth: 2,
      lineStyle: 2,
      axisLabelVisible: true,
      title: 'Current',
    });
  }

  function addTradePriceLine(price, title, color, style) {
    if (!candleSeries || !Number.isFinite(Number(price))) return;
    tradePriceLines.push(candleSeries.createPriceLine({
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

  function tradeOpenedTime(trade) {
    return new Date(trade.filled_at || trade.opened_at || trade.created_at || 0).getTime() || 0;
  }

  function tradeLabel(trade) {
    const name = trade.display_name || trade.friendly_name || trade.trade_name || '';
    if (name) return name;
    const direction = String(trade.direction || '').toUpperCase();
    const shortId = String(trade.id || '').slice(0, 8);
    return `${direction || 'TRADE'} ${shortId}`.trim();
  }

  function selectedOverlayMode() {
    const selected = qs('chartTradeSelect')?.value || '';
    if (!selected) return 'None';
    if (selected === ALL_TRADES_VALUE) return 'All open trades';
    const selectedText = qs('chartTradeSelect')?.selectedOptions?.[0]?.textContent || 'Selected trade';
    return selectedText.replace('Latest: ', 'Latest trade');
  }

  function visibleTradeLines(lines) {
    const selected = qs('chartTradeSelect')?.value || '';
    const all = selected === ALL_TRADES_VALUE;
    if (!selected || all) return lines || [];
    return (lines || []).filter(t => String(t.id) === String(selected));
  }

  async function updateTradeDropdown(selectedPair) {
    const select = qs('chartTradeSelect');
    if (!select) return '';
    try {
      const data = await chartApi('/api/agent/trades/open');
      const open = (data.open_trades || [])
        .filter(t => t.pair === selectedPair)
        .sort((a, b) => tradeOpenedTime(b) - tradeOpenedTime(a));
      const current = select.value;
      if (!open.length) {
        select.innerHTML = '<option value="">No open trades on pair</option>';
        select.value = '';
        return '';
      }
      const latest = open[0];
      const latestId = String(latest.id || '');
      const specificOptions = open
        .filter(t => String(t.id || '') !== latestId)
        .map(t => `<option value="${escapeHtml(t.id)}">${escapeHtml(tradeLabel(t))}</option>`)
        .join('');
      select.innerHTML = `
        <option value="${escapeHtml(latestId)}">Latest: ${escapeHtml(tradeLabel(latest))}</option>
        <option value="${ALL_TRADES_VALUE}">All open trades on pair</option>
        ${specificOptions}
      `;
      if (current === ALL_TRADES_VALUE || open.some(t => String(t.id) === String(current))) {
        select.value = current;
      } else {
        select.value = latestId;
      }
      return select.value;
    } catch (_) {
      select.innerHTML = '<option value="">No open trades on pair</option>';
      select.value = '';
      return '';
    }
  }

  function renderStatus(data, liveTick) {
    const quote = liveTick || data.current_price || {};
    const status = qs('chartStatus');
    if (!status) return;
    const liveClass = liveCandleEnabled ? 'chart-live-on' : 'chart-live-off';
    const liveLabel = liveCandleEnabled ? 'On' : 'Off';
    status.innerHTML = `
      <span class="chart-pill">Pair: <strong>${escapeHtml(data.pair || activeChartMeta.pair)}</strong></span>
      <span class="chart-pill">Timeframe: <strong>${escapeHtml(data.timeframe || activeChartMeta.timeframe)}</strong></span>
      <span class="chart-pill">Overlay: <strong>${escapeHtml(selectedOverlayMode())}</strong></span>
      <span class="chart-pill">Provider: <strong>${escapeHtml(data.provider || activeChartMeta.provider)}</strong></span>
      <span class="chart-pill">Price: <strong>${quote.price ?? '--'}</strong></span>
      <span class="chart-pill">Bid/Ask: <strong>${quote.bid ?? '--'} / ${quote.ask ?? '--'}</strong></span>
      <span class="chart-pill">Spread: <strong>${quote.spread_pips ?? '--'} pips</strong></span>
      <span class="chart-pill ${liveClass}">Live candle: <strong>${liveLabel}</strong></span>
      <span class="chart-pill">Paper only: <strong>Live locked</strong></span>
    `;

    const warningBox = qs('chartWarnings');
    if (warningBox && !liveTick) {
      warningBox.innerHTML = (data.warnings || []).length ? `<div class="chart-warning">${data.warnings.map(escapeHtml).join('<br>')}</div>` : '';
    }
  }

  function renderTradeChips(lines) {
    const el = qs('chartTrades');
    if (!el) return;
    const visible = visibleTradeLines(lines);
    if (!visible || !visible.length) {
      el.innerHTML = '<div class="muted small">No open trade overlay for this pair.</div>';
      return;
    }
    el.innerHTML = visible.map(t => `
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
    if (quote.price) setCurrentPriceLine(Number(quote.price));
    visibleTradeLines(data.trade_lines || []).forEach(t => {
      const direction = String(t.direction || '').toUpperCase();
      addTradePriceLine(Number(t.entry), `${direction} Entry`, '#60a5fa', 0);
      addTradePriceLine(Number(t.stop_loss), 'Stop Loss', '#ef4444', 1);
      addTradePriceLine(Number(t.take_profit), 'Take Profit', '#22c55e', 1);
    });
  }

  function applyMarkers(data) {
    if (!candleSeries) return;
    const selected = qs('chartTradeSelect')?.value || '';
    const visibleIds = new Set(visibleTradeLines(data.trade_lines || []).map(t => String(t.id)));
    const showAll = selected === ALL_TRADES_VALUE;
    const sourceMarkers = (data.trade_markers || []).filter(m => {
      const tradeId = String(m.trade_id || '');
      if (selected && !showAll) return tradeId === String(selected);
      if (showAll) return visibleIds.has(tradeId) && m.type === 'entry';
      return false;
    }).slice(-8);

    const markers = sourceMarkers.map(m => {
      const isExit = m.type === 'exit';
      const isBuy = String(m.direction || '').toLowerCase() === 'buy';
      return {
        time: convertTime(m.time),
        position: isExit ? 'aboveBar' : (isBuy ? 'belowBar' : 'aboveBar'),
        color: isExit ? '#f59e0b' : (isBuy ? '#22c55e' : '#ef4444'),
        shape: isExit ? 'circle' : (isBuy ? 'arrowUp' : 'arrowDown'),
        text: isExit ? 'Exit' : 'Entry',
      };
    }).filter(m => Number.isFinite(m.time));
    candleSeries.setMarkers(markers);
  }

  function updateCurrentCandleFromTick(tick) {
    if (!candleSeries || !currentCandles.length) return;
    const price = Number(tick.price);
    if (!Number.isFinite(price)) return;

    const tickTime = convertTime(tick.timestamp || tick.generated_at || new Date().toISOString());
    const candleTime = bucketTime(tickTime, activeChartMeta.timeframe);
    let last = currentCandles[currentCandles.length - 1];

    if (!last || candleTime > last.time) {
      const previousClose = last ? Number(last.close) : price;
      last = { time: candleTime, open: previousClose, high: Math.max(previousClose, price), low: Math.min(previousClose, price), close: price };
      currentCandles.push(last);
      if (currentCandles.length > 600) currentCandles = currentCandles.slice(-600);
    } else if (candleTime === last.time) {
      last = {
        ...last,
        high: Math.max(Number(last.high), price),
        low: Math.min(Number(last.low), price),
        close: price,
      };
      currentCandles[currentCandles.length - 1] = last;
    } else {
      last = { ...last, close: price, high: Math.max(Number(last.high), price), low: Math.min(Number(last.low), price) };
      currentCandles[currentCandles.length - 1] = last;
    }

    candleSeries.update(last);
    setCurrentPriceLine(price);
    renderStatus(activeChartMeta, tick);
  }

  async function pollLiveTick() {
    if (!liveCandleEnabled || !candleSeries) return;
    const pair = qs('chartPair')?.value || activeChartMeta.pair || 'GBP/USD';
    try {
      const tick = await chartApi(`/api/agent/chart/tick?pair=${encodeURIComponent(pair)}`);
      updateCurrentCandleFromTick(tick);
      if (tick.trade_lines) renderTradeChips(tick.trade_lines);
    } catch (e) {
      const warningBox = qs('chartWarnings');
      if (warningBox) warningBox.innerHTML = `<div class="chart-warning">Live tick update failed: ${escapeHtml(e.message || e)}</div>`;
    }
  }

  function stopLiveTicks() {
    if (liveTickTimer) clearInterval(liveTickTimer);
    liveTickTimer = null;
  }

  function startLiveTicks() {
    stopLiveTicks();
    const btn = qs('chartLiveBtn');
    if (btn) btn.textContent = liveCandleEnabled ? 'Live Candle: On' : 'Live Candle: Off';
    if (!liveCandleEnabled) return;
    pollLiveTick();
    liveTickTimer = setInterval(pollLiveTick, 5000);
  }

  window.loadAgentChart = async function loadAgentChart() {
    injectChartPanel();
    stopLiveTicks();
    const loading = qs('chartLoading');
    const pair = qs('chartPair')?.value || 'GBP/USD';
    const timeframe = qs('chartTimeframe')?.value || 'H1';
    if (loading) loading.style.display = 'flex';

    try {
      await loadChartLibrary();
      initChart();
      const selectedTradeId = await updateTradeDropdown(pair);
      const showAll = selectedTradeId === ALL_TRADES_VALUE;
      const tradeParam = selectedTradeId && !showAll ? `&trade_id=${encodeURIComponent(selectedTradeId)}` : '';
      const url = `/api/agent/chart/candles?pair=${encodeURIComponent(pair)}&timeframe=${encodeURIComponent(timeframe)}&count=180${tradeParam}`;
      const data = await chartApi(url);
      const candles = chartData(data.candles);
      if (!candles.length) throw new Error('No candle data returned');
      currentCandles = candles;
      activeChartMeta = { ...data, pair: data.pair || pair, timeframe: data.timeframe || timeframe, provider: data.provider || 'unknown' };
      candleSeries.setData(candles);
      chart.timeScale().fitContent();
      applyOverlays(data);
      applyMarkers(data);
      renderStatus(data);
      renderTradeChips(data.trade_lines || []);
      startLiveTicks();
    } catch (e) {
      const status = qs('chartStatus');
      if (status) status.innerHTML = `<span class="chart-pill">Chart error: <strong>${escapeHtml(e.message || e)}</strong></span>`;
    } finally {
      if (loading) loading.style.display = 'none';
    }
  };

  window.toggleAgentLiveCandle = function toggleAgentLiveCandle() {
    liveCandleEnabled = !liveCandleEnabled;
    const btn = qs('chartLiveBtn');
    if (btn) btn.textContent = liveCandleEnabled ? 'Live Candle: On' : 'Live Candle: Off';
    renderStatus(activeChartMeta);
    if (liveCandleEnabled) startLiveTicks();
    else stopLiveTicks();
  };

  window.toggleAgentChartAutoRefresh = function toggleAgentChartAutoRefresh() {
    const btn = qs('chartAutoBtn');
    if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
      if (btn) btn.textContent = 'Full Refresh: Off';
      return;
    }
    refreshTimer = setInterval(() => window.loadAgentChart(), 30000);
    if (btn) btn.textContent = 'Full Refresh: 30s';
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
      } else {
        stopLiveTicks();
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
