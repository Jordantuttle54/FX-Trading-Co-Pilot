/* agent_chart.js - clean live chart with cached account side panel */
'use strict';

(function () {
  const CHART_LIB_URL = 'https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js';
  const PAIRS = ['GBP/USD', 'EUR/USD', 'USD/JPY', 'EUR/GBP', 'GBP/JPY', 'XAU/USD'];
  const TIMEFRAMES = ['M1', 'M5', 'M15', 'H1', 'H4', 'D'];
  const TF_SECONDS = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400, D: 86400 };
  const ALL_TRADES_VALUE = '__all__';
  const TRADE_PALETTES = [
    { entry: '#facc15', sl: '#ef4444', tp: '#22c55e' },
    { entry: '#fb923c', sl: '#f472b6', tp: '#06b6d4' },
    { entry: '#a78bfa', sl: '#f97316', tp: '#10b981' },
    { entry: '#fde68a', sl: '#fb7185', tp: '#2dd4bf' },
  ];

  let chart = null;
  let candleSeries = null;
  let chartContainer = null;
  let currentPriceLine = null;
  let tradePriceLines = [];
  let refreshTimer = null;
  let liveTickTimer = null;
  let liveCandleEnabled = true;
  let chartExpanded = false;
  let currentCandles = [];
  let activeChartMeta = { pair: 'GBP/USD', timeframe: 'H1', provider: 'loading' };
  let openTradesCache = [];
  let allTradesCache = [];
  let latestPricesByPair = {};
  let openTradesLoadedAt = 0;
  let allTradesLoadedAt = 0;
  let chartLoadSeq = 0;

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  function num(value, fallback = null) {
    if (value === null || value === undefined || value === '') return fallback;
    const n = Number(String(value).replace(/[£$,]/g, ''));
    return Number.isFinite(n) ? n : fallback;
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

  function formatMoney(value) {
    const n = Number(value || 0);
    const sign = n < 0 ? '-' : '';
    return `${sign}£${Math.abs(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function formatPrice(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return n >= 100 ? n.toFixed(3) : n.toFixed(5);
  }

  function pnlClass(value) {
    const n = Number(value || 0);
    if (n > 0) return 'chart-money-positive';
    if (n < 0) return 'chart-money-negative';
    return 'chart-money-neutral';
  }

  function entryValue(trade) { return num(trade.entry, num(trade.entry_price, num(trade.open_price, null))); }
  function slValue(trade) { return num(trade.stop_loss, num(trade.sl, null)); }
  function tpValue(trade) { return num(trade.take_profit, num(trade.target, num(trade.tp, null))); }

  function injectChartStyles() {
    if (qs('agentChartStyles')) return;
    const style = document.createElement('style');
    style.id = 'agentChartStyles';
    style.textContent = `
      .chart-shell { margin-top:24px; }
      .chart-head-row { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; flex-wrap:wrap; }
      .chart-toolbar { display:flex; gap:12px; flex-wrap:wrap; align-items:end; margin:12px 0 16px; }
      .chart-toolbar label { display:flex; flex-direction:column; gap:4px; font-size:12px; color:var(--text-muted); }
      .chart-toolbar select { min-width:110px; }
      .chart-workspace { display:grid; grid-template-columns:minmax(0,1fr) minmax(320px,390px); gap:16px; align-items:start; }
      .chart-shell.chart-expanded .chart-workspace { grid-template-columns:1fr; }
      .chart-shell.chart-expanded .chart-account-panel { display:none; }
      .chart-frame { position:relative; min-height:520px; border:1px solid var(--border); border-radius:14px; background:#070d18; overflow:hidden; }
      .chart-shell.chart-expanded .chart-frame { min-height:720px; }
      #agentLiveChart { width:100%; height:520px; }
      .chart-shell.chart-expanded #agentLiveChart { height:720px; }
      .chart-loading { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; background:rgba(7,13,24,.78); color:var(--text-muted); z-index:4; }
      .chart-status-row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:10px; }
      .chart-pill { border:1px solid var(--border); background:var(--bg3); border-radius:999px; padding:5px 10px; font-size:12px; color:var(--text-muted); }
      .chart-pill strong { color:var(--text); }
      .chart-live-on { border-color:rgba(34,197,94,.5); color:#86efac; }
      .chart-live-off { border-color:rgba(239,68,68,.5); color:#fca5a5; }
      .chart-warning { color:var(--orange); font-size:12px; margin-top:8px; }
      .chart-trade-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:10px; margin-top:14px; }
      .chart-trade-chip { border:1px solid var(--border); background:var(--bg3); border-radius:10px; padding:10px; font-size:12px; }
      .chart-trade-chip strong { display:block; margin-bottom:6px; }
      .chart-swatch { display:inline-block; width:10px; height:10px; border-radius:999px; margin-right:6px; vertical-align:-1px; }
      .chart-account-panel { border:1px solid var(--border); background:linear-gradient(180deg, rgba(15,23,42,.92), rgba(7,13,24,.94)); border-radius:14px; padding:14px; min-height:520px; }
      .chart-account-top { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; margin-bottom:12px; }
      .chart-account-title { font-size:15px; font-weight:800; }
      .chart-account-sub { color:var(--text-muted); font-size:11px; margin-top:2px; }
      .chart-money-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:12px 0; }
      .chart-money-cell { border:1px solid var(--border); background:rgba(15,23,42,.76); border-radius:10px; padding:10px; }
      .chart-money-label { color:var(--text-muted); font-size:11px; margin-bottom:4px; }
      .chart-money-value { font-size:18px; font-weight:850; letter-spacing:.01em; }
      .chart-money-positive { color:#38bdf8; }
      .chart-money-negative { color:#fb7185; }
      .chart-money-neutral { color:var(--text); }
      .chart-position-list { border-top:1px solid var(--border); margin-top:12px; padding-top:10px; max-height:280px; overflow:auto; }
      .chart-position-row { display:grid; grid-template-columns:1fr auto; gap:10px; align-items:center; padding:9px 0; border-bottom:1px solid rgba(148,163,184,.16); }
      .chart-position-name { font-size:12px; font-weight:800; }
      .chart-position-meta { color:var(--text-muted); font-size:11px; margin-top:3px; }
      .chart-position-pnl { font-size:13px; font-weight:850; text-align:right; }
      .chart-account-note { margin-top:10px; color:var(--text-muted); font-size:11px; line-height:1.4; }
      @media (max-width:1100px) { .chart-workspace { grid-template-columns:1fr; } .chart-account-panel { min-height:auto; } }
      @media (max-width:760px) { .chart-frame { min-height:380px; } #agentLiveChart { height:380px; } .chart-shell.chart-expanded .chart-frame { min-height:520px; } .chart-shell.chart-expanded #agentLiveChart { height:520px; } .chart-money-grid { grid-template-columns:1fr; } }
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
      <div class="chart-head-row">
        <div>
          <h2>Live Trade Chart</h2>
          <p class="card-sub">Open paper trades are shown as horizontal Entry, SL and TP lines. Use Expand Chart for a full-size view.</p>
        </div>
        <button class="btn-secondary" id="chartSizeBtn" onclick="toggleAgentChartSize()">Expand Chart</button>
      </div>
      <div class="chart-toolbar">
        <label>Pair<select id="chartPair">${PAIRS.map(p => `<option value="${p}">${p}</option>`).join('')}</select></label>
        <label>Timeframe<select id="chartTimeframe">${TIMEFRAMES.map(tf => `<option value="${tf}" ${tf === 'H1' ? 'selected' : ''}>${tf}</option>`).join('')}</select></label>
        <label>Trade overlay<select id="chartTradeSelect"><option value="${ALL_TRADES_VALUE}">All open trades on pair</option></select></label>
        <button class="btn-primary" id="chartRefreshBtn" onclick="loadAgentChart()">Refresh Chart</button>
        <button class="btn-secondary" id="chartLiveBtn" onclick="toggleAgentLiveCandle()">Live Candle: On</button>
        <button class="btn-secondary" id="chartAutoBtn" onclick="toggleAgentChartAutoRefresh()">Full Refresh: Off</button>
      </div>
      <div class="chart-workspace">
        <div class="chart-main-panel">
          <div class="chart-frame"><div id="agentLiveChart"></div><div id="chartLoading" class="chart-loading" style="display:none">Loading chart...</div></div>
          <div id="chartStatus" class="chart-status-row"></div>
          <div id="chartWarnings"></div>
          <div id="chartTrades" class="chart-trade-list"></div>
        </div>
        <aside class="chart-account-panel" id="chartAccountPanel"><div class="muted small">Loading paper account...</div></aside>
      </div>
    `;
    const firstCard = tradesTab.querySelector('.agent-card');
    if (firstCard && firstCard.parentNode) firstCard.parentNode.insertBefore(card, firstCard.nextSibling);
    else tradesTab.prepend(card);
    qs('chartPair')?.addEventListener('change', () => window.loadAgentChart());
    qs('chartTimeframe')?.addEventListener('change', () => window.loadAgentChart());
    qs('chartTradeSelect')?.addEventListener('change', () => window.loadAgentChart({ keepTradesCache: true }));
  }

  function convertTime(value) {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return Math.floor(Date.now() / 1000);
    return Math.floor(d.getTime() / 1000);
  }

  function bucketTime(epochSeconds, timeframe) {
    const step = TF_SECONDS[timeframe || activeChartMeta.timeframe || 'H1'] || 3600;
    return Math.floor(epochSeconds / step) * step;
  }

  function chartData(candles) {
    return (candles || []).map(c => ({
      time: convertTime(c.time), open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close),
    })).filter(c => Number.isFinite(c.time) && Number.isFinite(c.open) && Number.isFinite(c.high) && Number.isFinite(c.low) && Number.isFinite(c.close));
  }

  function clearPriceLines() {
    if (!candleSeries) return;
    if (currentPriceLine) {
      try { candleSeries.removePriceLine(currentPriceLine); } catch (_) {}
      currentPriceLine = null;
    }
    tradePriceLines.forEach(line => { try { candleSeries.removePriceLine(line); } catch (_) {} });
    tradePriceLines = [];
  }

  function setCurrentPriceLine(price) {
    if (!candleSeries || !Number.isFinite(Number(price))) return;
    if (currentPriceLine) {
      try { candleSeries.removePriceLine(currentPriceLine); } catch (_) {}
      currentPriceLine = null;
    }
    currentPriceLine = candleSeries.createPriceLine({ price: Number(price), color: '#3b82f6', lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'Current' });
  }

  function addTradePriceLine(price, title, color, style, width = 2) {
    if (!candleSeries || !Number.isFinite(Number(price))) return;
    tradePriceLines.push(candleSeries.createPriceLine({ price: Number(price), color, lineWidth: width, lineStyle: style || 0, axisLabelVisible: true, title }));
  }

  function initChart() {
    chartContainer = qs('agentLiveChart');
    if (!chartContainer || !window.LightweightCharts) return;
    const height = chartExpanded ? 720 : 520;
    if (chart) {
      chart.resize(chartContainer.clientWidth || 900, chartContainer.clientHeight || height);
      return;
    }
    chart = window.LightweightCharts.createChart(chartContainer, {
      width: chartContainer.clientWidth || 900,
      height,
      layout: { background: { color: '#070d18' }, textColor: '#cbd5e1' },
      grid: { vertLines: { color: '#142033' }, horzLines: { color: '#142033' } },
      crosshair: { mode: window.LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#243244' },
      timeScale: { borderColor: '#243244', timeVisible: true, secondsVisible: false },
    });
    candleSeries = chart.addCandlestickSeries({ upColor: '#16a34a', downColor: '#dc2626', borderUpColor: '#16a34a', borderDownColor: '#dc2626', wickUpColor: '#16a34a', wickDownColor: '#dc2626' });
    window.addEventListener('resize', () => {
      if (chart && chartContainer) chart.resize(chartContainer.clientWidth || 900, chartContainer.clientHeight || (chartExpanded ? 720 : 520));
    });
  }

  function tradeOpenedTime(trade) { return new Date(trade.filled_at || trade.opened_at || trade.created_at || 0).getTime() || 0; }

  function tradeNumber(trade) {
    const fields = [trade.display_name, trade.friendly_name, trade.trade_name, trade.short_name, trade.friendly_id, trade.label, trade.id];
    for (const field of fields) {
      const match = String(field || '').match(/#\d+/);
      if (match) return match[0];
    }
    const id = String(trade.id || '');
    return id ? `#${id.slice(0, 4)}` : '#----';
  }

  function tradeLabel(trade) {
    const existing = trade.display_name || trade.friendly_name || trade.trade_name || trade.short_name || trade.label || '';
    if (existing) return String(existing);
    const origin = String(trade.trade_origin || trade.origin || trade.source || '').toLowerCase().includes('ai') ? 'AI' : 'Personal';
    const pair = trade.pair || activeChartMeta.pair || '';
    const raw = String(trade.direction || '').toLowerCase();
    const direction = raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : '';
    return `${origin} ${pair} ${direction} ${tradeNumber(trade)}`.replace(/\s+/g, ' ').trim();
  }

  function getOverlapThreshold(pair) {
    const p = String(pair || activeChartMeta.pair || '');
    if (p === 'XAU/USD') return 0.8;
    if (p.includes('JPY')) return 0.025;
    return 0.00025;
  }

  function assignTradePalettes(lines) {
    const used = [];
    return (lines || []).map(trade => {
      const pair = trade.pair || activeChartMeta.pair;
      const levels = [entryValue(trade), slValue(trade), tpValue(trade)].filter(v => v !== null);
      const threshold = getOverlapThreshold(pair);
      let paletteIndex = 0;
      for (const level of levels) {
        const overlap = used.find(item => item.pair === pair && Math.abs(item.level - level) <= threshold);
        if (overlap) { paletteIndex = (overlap.paletteIndex + 1) % TRADE_PALETTES.length; break; }
      }
      levels.forEach(level => used.push({ pair, level, paletteIndex }));
      return { ...trade, paletteIndex, palette: TRADE_PALETTES[paletteIndex] || TRADE_PALETTES[0] };
    });
  }

  function tradesForSelectedPair() {
    const pair = qs('chartPair')?.value || activeChartMeta.pair || 'GBP/USD';
    return openTradesCache.filter(t => String(t.pair || '').toUpperCase() === pair.toUpperCase());
  }

  function visibleTradeLines() {
    const selected = qs('chartTradeSelect')?.value || ALL_TRADES_VALUE;
    const rows = tradesForSelectedPair();
    if (selected === ALL_TRADES_VALUE) return assignTradePalettes(rows);
    return assignTradePalettes(rows.filter(t => String(t.id) === String(selected)));
  }

  async function refreshOpenTradesCache(force = false) {
    if (!force && Date.now() - openTradesLoadedAt < 8000 && openTradesCache.length) return openTradesCache;
    const data = await chartApi('/api/agent/trades/open');
    openTradesCache = data.open_trades || data.trades || data.items || [];
    openTradesLoadedAt = Date.now();
    return openTradesCache;
  }

  async function refreshAllTradesCache(force = false) {
    if (!force && Date.now() - allTradesLoadedAt < 60000 && allTradesCache.length) return allTradesCache;
    const data = await chartApi('/api/agent/trades');
    allTradesCache = Array.isArray(data) ? data : (data.trades || data.items || []);
    allTradesLoadedAt = Date.now();
    return allTradesCache;
  }

  function updateTradeDropdown() {
    const select = qs('chartTradeSelect');
    if (!select) return ALL_TRADES_VALUE;
    const pairRows = tradesForSelectedPair().sort((a, b) => tradeOpenedTime(b) - tradeOpenedTime(a));
    const current = select.value || ALL_TRADES_VALUE;
    if (!pairRows.length) {
      select.innerHTML = '<option value="">No open trades on pair</option>';
      select.value = '';
      return '';
    }
    select.innerHTML = `<option value="${ALL_TRADES_VALUE}">All open trades on pair</option>` + pairRows.map(t => `<option value="${escapeHtml(t.id)}">${escapeHtml(tradeLabel(t))}</option>`).join('');
    select.value = current === ALL_TRADES_VALUE || pairRows.some(t => String(t.id) === String(current)) ? current : ALL_TRADES_VALUE;
    return select.value;
  }

  function selectedOverlayMode() {
    const selected = qs('chartTradeSelect')?.value || ALL_TRADES_VALUE;
    if (selected === ALL_TRADES_VALUE) return 'All open trades';
    return qs('chartTradeSelect')?.selectedOptions?.[0]?.textContent || 'Selected trade';
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
    if (warningBox && !liveTick) warningBox.innerHTML = (data.warnings || []).length ? `<div class="chart-warning">${data.warnings.map(escapeHtml).join('<br>')}</div>` : '';
  }

  function renderTradeChips() {
    const el = qs('chartTrades');
    if (!el) return;
    const visible = visibleTradeLines();
    if (!visible.length) {
      el.innerHTML = '<div class="muted small">No open trade lines for this pair.</div>';
      return;
    }
    el.innerHTML = visible.map(t => `
      <div class="chart-trade-chip">
        <strong><span class="chart-swatch" style="background:${t.palette.entry}"></span>${escapeHtml(tradeLabel(t))}</strong>
        Entry: ${formatPrice(entryValue(t))}<br>
        SL: ${formatPrice(slValue(t))}<br>
        TP: ${formatPrice(tpValue(t))}<br>
        <span class="muted">${escapeHtml(t.setup_label || t.setup_type || '')}</span>
      </div>
    `).join('');
  }

  function applyOverlays(data) {
    clearPriceLines();
    const quote = data.current_price || {};
    if (quote.price) {
      latestPricesByPair[data.pair || activeChartMeta.pair] = Number(quote.price);
      setCurrentPriceLine(Number(quote.price));
    }
    visibleTradeLines().forEach(t => {
      const number = tradeNumber(t);
      addTradePriceLine(entryValue(t), tradeLabel(t), t.palette.entry, 0, 2);
      addTradePriceLine(slValue(t), `${number} SL`, t.palette.sl, 2, 2);
      addTradePriceLine(tpValue(t), `${number} TP`, t.palette.tp, 2, 2);
    });
    if (candleSeries) candleSeries.setMarkers([]);
  }

  function accountStartBalance() { return num(window.walletCashBalance, num(qs('quickTradeBalance')?.value, num(qs('scanBalance')?.value, 10000))) || 10000; }

  function tradeRiskMoney(trade) {
    const direct = num(trade.risk_amount, num(trade.risk_money, num(trade.money_risked, num(trade.risk_value, null))));
    if (direct !== null) return direct;
    const balance = num(trade.account_balance, accountStartBalance()) || accountStartBalance();
    const riskPct = num(trade.risk_pct, 0.5) || 0.5;
    return balance * (riskPct / 100);
  }

  function realisedMoney(trade) {
    const direct = num(trade.result_money, num(trade.pnl, num(trade.profit, num(trade.result_profit, null))));
    if (direct !== null) return direct;
    const r = num(trade.result_r, null);
    return r !== null ? r * tradeRiskMoney(trade) : 0;
  }

  function estimateOpenTradeMoney(trade) {
    const pair = trade.pair || activeChartMeta.pair;
    const current = num(latestPricesByPair[pair], null);
    const entry = entryValue(trade);
    const stop = slValue(trade);
    if (current === null || entry === null || stop === null || current === entry || stop === entry) return 0;
    const direction = String(trade.direction || '').toLowerCase();
    const move = direction === 'sell' ? (entry - current) : (current - entry);
    const riskDistance = Math.abs(entry - stop);
    return (riskDistance ? move / riskDistance : 0) * tradeRiskMoney(trade);
  }

  function renderPaperAccountPanel() {
    const panel = qs('chartAccountPanel');
    if (!panel) return;
    const startBalance = accountStartBalance();
    const closed = allTradesCache.filter(t => String(t.status || '').toLowerCase() === 'closed');
    const realised = closed.reduce((sum, t) => sum + realisedMoney(t), 0);
    const openPnl = openTradesCache.reduce((sum, t) => sum + estimateOpenTradeMoney(t), 0);
    const balance = startBalance + realised;
    const equity = balance + openPnl;
    const totalProfit = realised + openPnl;
    const rows = openTradesCache.length ? openTradesCache.map(t => {
      const pnl = estimateOpenTradeMoney(t);
      const current = latestPricesByPair[t.pair];
      return `
        <div class="chart-position-row">
          <div><div class="chart-position-name">${escapeHtml(tradeLabel(t))}</div><div class="chart-position-meta">${escapeHtml(t.pair || '')} ${escapeHtml(String(t.direction || '').toUpperCase())} | Current ${formatPrice(current)}</div></div>
          <div class="chart-position-pnl ${pnlClass(pnl)}">${formatMoney(pnl)}</div>
        </div>`;
    }).join('') : '<div class="muted small">No open paper positions.</div>';
    panel.innerHTML = `
      <div class="chart-account-top"><div><div class="chart-account-title">Paper Account</div><div class="chart-account-sub">Cached live estimate, paper mode only</div></div><button class="btn-secondary" style="font-size:11px;padding:6px 10px" onclick="refreshAgentAccountPanel()">Refresh</button></div>
      <div class="chart-money-grid">
        <div class="chart-money-cell"><div class="chart-money-label">Deposit</div><div class="chart-money-value">${formatMoney(startBalance)}</div></div>
        <div class="chart-money-cell"><div class="chart-money-label">Balance</div><div class="chart-money-value">${formatMoney(balance)}</div></div>
        <div class="chart-money-cell"><div class="chart-money-label">Realised Profit</div><div class="chart-money-value ${pnlClass(realised)}">${formatMoney(realised)}</div></div>
        <div class="chart-money-cell"><div class="chart-money-label">Open P&L</div><div class="chart-money-value ${pnlClass(openPnl)}">${formatMoney(openPnl)}</div></div>
        <div class="chart-money-cell"><div class="chart-money-label">Equity</div><div class="chart-money-value ${pnlClass(equity - startBalance)}">${formatMoney(equity)}</div></div>
        <div class="chart-money-cell"><div class="chart-money-label">Total Profit</div><div class="chart-money-value ${pnlClass(totalProfit)}">${formatMoney(totalProfit)}</div></div>
      </div>
      <div class="chart-position-list">${rows}</div>
      <div class="chart-account-note">Open P&L updates from the latest chart tick and cached open trades. Use Refresh after opening/closing trades.</div>`;
  }

  async function loadPaperAccountPanel(force = false) {
    const panel = qs('chartAccountPanel');
    if (!panel) return;
    try {
      await Promise.all([refreshOpenTradesCache(force), refreshAllTradesCache(force)]);
      renderPaperAccountPanel();
    } catch (e) {
      panel.innerHTML = `<span class="muted small">Account panel error: ${escapeHtml(e.message || e)}</span>`;
    }
  }

  function updateCurrentCandleFromTick(tick) {
    if (!candleSeries || !currentCandles.length) return;
    const price = Number(tick.price);
    if (!Number.isFinite(price)) return;
    latestPricesByPair[tick.pair || activeChartMeta.pair] = price;
    const candleTime = bucketTime(convertTime(tick.timestamp || tick.generated_at || new Date().toISOString()), activeChartMeta.timeframe);
    let last = currentCandles[currentCandles.length - 1];
    if (!last || candleTime > last.time) {
      const previousClose = last ? Number(last.close) : price;
      last = { time: candleTime, open: previousClose, high: Math.max(previousClose, price), low: Math.min(previousClose, price), close: price };
      currentCandles.push(last);
      if (currentCandles.length > 600) currentCandles = currentCandles.slice(-600);
    } else {
      last = { ...last, high: Math.max(Number(last.high), price), low: Math.min(Number(last.low), price), close: price };
      currentCandles[currentCandles.length - 1] = last;
    }
    candleSeries.update(last);
    setCurrentPriceLine(price);
    renderStatus(activeChartMeta, tick);
    renderPaperAccountPanel();
  }

  async function pollLiveTick() {
    if (!liveCandleEnabled || !candleSeries) return;
    const pair = qs('chartPair')?.value || activeChartMeta.pair || 'GBP/USD';
    try {
      const tick = await chartApi(`/api/agent/chart/tick?pair=${encodeURIComponent(pair)}`);
      updateCurrentCandleFromTick(tick);
    } catch (e) {
      const warningBox = qs('chartWarnings');
      if (warningBox) warningBox.innerHTML = `<div class="chart-warning">Live tick update failed: ${escapeHtml(e.message || e)}</div>`;
    }
  }

  function stopLiveTicks() { if (liveTickTimer) clearInterval(liveTickTimer); liveTickTimer = null; }

  function startLiveTicks() {
    stopLiveTicks();
    const btn = qs('chartLiveBtn');
    if (btn) btn.textContent = liveCandleEnabled ? 'Live Candle: On' : 'Live Candle: Off';
    if (!liveCandleEnabled) return;
    liveTickTimer = setInterval(pollLiveTick, 5000);
  }

  window.loadAgentChart = async function loadAgentChart(options = {}) {
    const seq = ++chartLoadSeq;
    injectChartPanel();
    stopLiveTicks();
    const loading = qs('chartLoading');
    const pair = qs('chartPair')?.value || 'GBP/USD';
    const timeframe = qs('chartTimeframe')?.value || 'H1';
    if (loading) loading.style.display = 'flex';
    try {
      await loadChartLibrary();
      initChart();
      if (!options.keepTradesCache) await refreshOpenTradesCache(true);
      updateTradeDropdown();
      const data = await chartApi(`/api/agent/chart/candles?pair=${encodeURIComponent(pair)}&timeframe=${encodeURIComponent(timeframe)}&count=180`);
      if (seq !== chartLoadSeq) return;
      const candles = chartData(data.candles);
      if (!candles.length) throw new Error('No candle data returned');
      currentCandles = candles;
      activeChartMeta = { ...data, pair: data.pair || pair, timeframe: data.timeframe || timeframe, provider: data.provider || 'unknown' };
      candleSeries.setData(candles);
      chart.timeScale().fitContent();
      applyOverlays(data);
      renderStatus(data);
      renderTradeChips();
      await loadPaperAccountPanel(false);
      startLiveTicks();
    } catch (e) {
      const status = qs('chartStatus');
      if (status) status.innerHTML = `<span class="chart-pill">Chart error: <strong>${escapeHtml(e.message || e)}</strong></span>`;
    } finally {
      if (loading) loading.style.display = 'none';
    }
  };

  window.toggleAgentChartSize = function toggleAgentChartSize() {
    chartExpanded = !chartExpanded;
    const shell = qs('agentChartPanel');
    const btn = qs('chartSizeBtn');
    if (shell) shell.classList.toggle('chart-expanded', chartExpanded);
    if (btn) btn.textContent = chartExpanded ? 'Split View' : 'Expand Chart';
    setTimeout(() => {
      if (chart && chartContainer) {
        chart.resize(chartContainer.clientWidth || 900, chartContainer.clientHeight || (chartExpanded ? 720 : 520));
        chart.timeScale().fitContent();
      }
    }, 120);
  };

  window.refreshAgentAccountPanel = async function refreshAgentAccountPanel() {
    await loadPaperAccountPanel(true);
    if (typeof window.loadAgentChart === 'function') window.loadAgentChart();
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
      if (name === 'trades') setTimeout(() => { injectChartPanel(); window.loadAgentChart(); }, 150);
      else stopLiveTicks();
      return result;
    };
    window.switchTab.__chartEnhanced = true;
  }

  function init() {
    injectChartPanel();
    enhanceTabSwitch();
    if (document.querySelector('#tab-trades.active')) window.loadAgentChart();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
