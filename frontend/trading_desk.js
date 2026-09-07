/* trading_desk.js - open positions and the news blackout, on the Trade tab.
 *
 * Two jobs:
 *   1. An MT4-style open positions table with a one-action close.
 *   2. The news guard, shown under the trade buttons rather than on a tab of
 *      its own - a blackout only matters in the second before you click.
 *
 * Every price here comes from the broker or is not shown. There is no fallback
 * row, no placeholder position and no invented quote: nine of the ten defects
 * found on 7 September were a value the app did not have, displayed as one it
 * did, and this file is the newest place that could happen.
 */
'use strict';

(function () {
  const REFRESH_MS = 15000;
  let timer = null;
  let quoteCache = {};

  function qs(id) { return document.getElementById(id); }

  function esc(v) {
    return String(v ?? '').replace(/[&<>'"]/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[c]));
  }

  function num(v, fallback = null) {
    if (v === null || v === undefined || v === '') return fallback;
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { 'Content-Type': 'application/json' }, ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }

  const isOpen = t => String(t.status || '').toLowerCase() === 'open';
  const side = t => String(t.direction || '').toLowerCase();
  const entryOf = t => num(t.entry_price, num(t.entry, null));
  const stopOf = t => num(t.stop_loss, num(t.sl, null));
  const targetOf = t => num(t.take_profit, num(t.target, null));

  function pipSize(pair) {
    const p = String(pair || '').toUpperCase();
    if (p.includes('XAU')) return 0.1;
    if (p.includes('JPY')) return 0.01;
    return 0.0001;
  }

  function precision(pair) {
    const p = String(pair || '').toUpperCase();
    if (p.includes('XAU')) return 2;
    if (p.includes('JPY')) return 3;
    return 5;
  }

  function price(pair, v) {
    const n = num(v, null);
    return n === null ? '--' : n.toFixed(precision(pair));
  }

  function money(v) {
    const n = num(v, 0);
    const sign = n > 0 ? '+' : n < 0 ? '-' : '';
    return `${sign}£${Math.abs(n).toLocaleString('en-GB', {
      minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function pnlClass(v) {
    if (v === null) return 'desk-flat';
    return v > 0 ? 'desk-up' : v < 0 ? 'desk-down' : 'desk-flat';
  }

  // Mirrors ORIGIN_LABELS in backend/paper_mvp_persistent.py.
  const ORIGIN_LABELS = {
    agent_auto: 'AGENT TRADE',
    scanner_manual_execute: 'Manual-Scanner',
    ai_quick_open: 'Manual-Scanner',
    personal_quick_open: 'Personal',
    manual_copilot: 'Personal',
  };
  const LEGACY_SETUP_ORIGINS = {
    live_data_trend_continuation: 'scanner_manual_execute',
    live_data_mean_reversion: 'scanner_manual_execute',
    personal_quick_paper_trade: 'personal_quick_open',
    manual_copilot_paper_trade: 'manual_copilot',
  };

  function originLabel(t) {
    if (t.trade_origin_label) return t.trade_origin_label;
    const o = String(t.trade_origin || t.origin || '').trim().toLowerCase();
    if (ORIGIN_LABELS[o]) return ORIGIN_LABELS[o];
    const legacy = LEGACY_SETUP_ORIGINS[String(t.setup_type || '').trim().toLowerCase()];
    return legacy ? ORIGIN_LABELS[legacy] : 'Unknown';
  }

  function originClass(label) {
    if (label === 'AGENT TRADE') return 'agent';
    if (label === 'Manual-Scanner') return 'scanner';
    return '';
  }

  /* ---- quotes ------------------------------------------------------------
   * A quote the backend flagged as invented is discarded rather than used.
   * Without a real price a position's running P&L is unknowable, and "--" is
   * the honest answer.
   */
  async function loadQuotes(pairs) {
    const out = {};
    await Promise.allSettled(pairs.map(async (pair) => {
      try {
        const tick = await api(`/api/agent/chart/tick?pair=${encodeURIComponent(pair)}`);
        const invented = /synthetic|failed|fallback/i.test(String(tick.provider || ''));
        if (invented) { out[pair] = { invented: true }; return; }
        const mid = num(tick.price, null);
        out[pair] = { invented: false, mid, bid: num(tick.bid, mid), ask: num(tick.ask, mid) };
      } catch (_) {
        out[pair] = null;   // unreachable is not the same as invented
      }
    }));
    return out;
  }

  // A long is closed by selling into the bid; a short by buying at the ask.
  function closeSide(trade, quote) {
    if (!quote || quote.invented) return null;
    return side(trade) === 'sell' ? num(quote.ask, quote.mid) : num(quote.bid, quote.mid);
  }

  function riskMoney(trade) {
    const direct = num(trade.risk_amount, num(trade.risk_money, null));
    if (direct !== null) return direct;
    const balance = num(trade.account_balance, num(window.walletCashBalance, 10000)) || 10000;
    return balance * ((num(trade.risk_pct, 0.5) || 0.5) / 100);
  }

  function liveResult(trade, current) {
    const entry = entryOf(trade);
    const stop = stopOf(trade);
    if (current === null || entry === null || stop === null || entry === stop) return { r: null, money: null };
    const move = side(trade) === 'sell' ? entry - current : current - entry;
    const r = move / Math.abs(entry - stop);
    return { r, money: r * riskMoney(trade) };
  }

  /* ---- positions table --------------------------------------------------- */
  function row(trade, quote) {
    const pair = trade.pair || '';
    const entry = entryOf(trade);
    const current = closeSide(trade, quote);
    const { r, money: pnl } = liveResult(trade, current);
    const units = num(trade.position_units, null);
    const pips = (entry !== null && current !== null)
      ? (side(trade) === 'sell' ? entry - current : current - entry) / pipSize(pair)
      : null;
    const label = originLabel(trade);
    const noPrice = current === null;

    return `<tr>
      <td><strong>${esc(pair)}</strong></td>
      <td><span class="desk-origin ${originClass(label)}">${esc(label)}</span></td>
      <td><span class="desk-side ${esc(side(trade))}">${esc(side(trade).toUpperCase() || '--')}</span></td>
      <td class="desk-num">${units === null ? '--' : units.toLocaleString('en-GB')}</td>
      <td class="desk-num">${price(pair, entry)}</td>
      <td class="desk-num">${price(pair, stopOf(trade))}</td>
      <td class="desk-num">${price(pair, targetOf(trade))}</td>
      <td class="desk-num">${noPrice ? '<span class="desk-noprice">no live price</span>' : price(pair, current)}</td>
      <td class="desk-num ${pnlClass(pips)}">${pips === null ? '--' : (pips > 0 ? '+' : '') + pips.toFixed(1)}</td>
      <td class="desk-num ${pnlClass(r)}">${r === null ? '--' : (r > 0 ? '+' : '') + r.toFixed(2) + 'R'}</td>
      <td class="desk-num ${pnlClass(pnl)}">${pnl === null ? '--' : money(pnl)}</td>
      <td><button class="btn-secondary desk-close-btn" data-desk-close="${esc(trade.id)}">Close</button></td>
    </tr>`;
  }

  function render(trades, quotes) {
    const panel = qs('deskPositionsPanel');
    if (!panel) return;
    const open = (trades || []).filter(isOpen);

    if (!open.length) {
      panel.innerHTML = '<div class="desk-empty">No open positions.</div>';
      return;
    }

    let totalMoney = 0;
    let priced = 0;
    open.forEach((t) => {
      const current = closeSide(t, quotes[t.pair]);
      const { money: pnl } = liveResult(t, current);
      if (pnl !== null) { totalMoney += pnl; priced += 1; }
    });

    // Only total what could actually be priced, and say so when some could not.
    const missing = open.length - priced;
    const totalCell = priced
      ? `<td class="desk-num ${pnlClass(totalMoney)}">${money(totalMoney)}</td>`
      : '<td class="desk-num desk-noprice">no live prices</td>';

    panel.innerHTML = `
      <table class="desk-table">
        <thead><tr>
          <th>Pair</th><th>Placed by</th><th>Side</th><th>Units</th>
          <th>Entry</th><th>SL</th><th>TP</th><th>Close now</th>
          <th>Pips</th><th>R</th><th>P&amp;L</th><th></th>
        </tr></thead>
        <tbody>${open.map(t => row(t, quotes[t.pair])).join('')}</tbody>
        <tfoot><tr>
          <td colspan="10">${open.length} open${missing ? ` &middot; ${missing} without a live price` : ''}</td>
          ${totalCell}
          <td></td>
        </tr></tfoot>
      </table>`;

    panel.querySelectorAll('[data-desk-close]').forEach((btn) => {
      btn.addEventListener('click', () => closePosition(btn));
    });
  }

  async function closePosition(btn) {
    const id = btn.getAttribute('data-desk-close');
    if (!id || !confirm('Close this paper trade at the current market price?')) return;
    btn.disabled = true;
    btn.textContent = 'Closing…';
    try {
      await api(`/api/agent/trades/${encodeURIComponent(id)}/quick-close`,
                { method: 'POST', body: JSON.stringify({ reason: 'Closed from the trade desk' }) });
      await refresh(true);
      if (typeof window.loadAllTrades === 'function') window.loadAllTrades();
      if (typeof window.loadAgentChart === 'function') window.loadAgentChart();
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'Close';
      alert(`Could not close that trade: ${err.message || err}`);
    }
  }

  async function refresh(force = false) {
    const panel = qs('deskPositionsPanel');
    if (!panel) return;
    try {
      const data = await api('/api/agent/trades/open');
      const trades = Array.isArray(data) ? data : (data.open_trades || data.trades || data.items || []);
      const pairs = Array.from(new Set(trades.filter(isOpen).map(t => t.pair).filter(Boolean)));
      quoteCache = pairs.length ? await loadQuotes(pairs) : {};
      render(trades, quoteCache);
    } catch (err) {
      panel.innerHTML = `<div class="desk-empty">Could not load open positions: ${esc(err.message || err)}</div>`;
    }
  }
  window.refreshDeskPositions = refresh;

  /* ---- news guard, under the trade buttons ------------------------------- */
  function selectedPair() {
    return qs('chartPair')?.value || qs('quickTradePair')?.value || 'GBP/USD';
  }

  async function renderNewsGuard() {
    const host = qs('quickTradePanel') || qs('agentChartPanel');
    if (!host) return;

    let box = qs('deskNewsGuard');
    if (!box) {
      box = document.createElement('div');
      box.id = 'deskNewsGuard';
      box.className = 'desk-news-guard off';
      host.appendChild(box);
    }

    try {
      const cal = await api('/api/calendar');
      if (!cal.news_guard_active) {
        box.className = 'desk-news-guard off';
        box.innerHTML = '<strong>No news blackout.</strong> No calendar provider is connected, '
          + 'so trades are not checked against high-impact releases.';
        return;
      }
      const pair = selectedPair();
      const mins = num(cal.blackout_minutes, 30);
      const legs = pair.replace('_', '/').split('/').map(s => s.trim().toUpperCase());
      const soon = (cal.events || []).filter((e) => {
        if (!legs.includes(e.currency) && !(legs.includes('XAU') && e.currency === 'USD')) return false;
        if (!(cal.blocked_impacts || ['high']).includes(String(e.impact || '').toLowerCase())) return false;
        const away = (new Date(e.time).getTime() - Date.now()) / 60000;
        return Math.abs(away) <= mins;
      });

      if (!soon.length) {
        box.className = 'desk-news-guard clear';
        box.innerHTML = `&#10003; No high-impact ${esc(legs.join('/'))} release within ${esc(mins)} minutes.`;
        return;
      }
      const next = soon[0];
      const away = Math.round((new Date(next.time).getTime() - Date.now()) / 60000);
      box.className = 'desk-news-guard blocked';
      box.innerHTML = `&#9888; <strong>Blocked &mdash; ${esc(next.currency)} ${esc(next.event)}</strong> `
        + (away >= 0 ? `in ${Math.abs(away)} min.` : `${Math.abs(away)} min ago.`)
        + ' New trades on this pair are refused until the blackout passes.';
    } catch (_) {
      /* The calendar being unreachable is reported by the backend when a trade
         is actually attempted; do not guess at it here. */
    }
  }

  /* ---- assemble the three columns ----------------------------------------
   * The four panels are built by four different files: the chart and the
   * running-P/L ledger by agent_chart.js, the ticket by agent_quick_trade.js,
   * the scanner by agent.html. A CSS grid can only lay out its own children,
   * so trading_desk.css can place them only once they are siblings inside
   * .chart-workspace. This is the one function that makes them siblings.
   *
   * appendChild, not insertBefore against a reference node: the previous
   * version assumed the ledger was already in the workspace and threw when it
   * was not, taking the rest of start() down with it. Order here does not
   * matter anyway - grid-template-areas decides what sits where, so the DOM
   * order is free to be whatever arrives first.
   */
  function ensureBox(id, workspace) {
    let box = qs(id);
    if (!box) {
      box = document.createElement('div');
      box.id = id;
    }
    if (box.parentElement !== workspace) workspace.appendChild(box);
    return box;
  }

  function placeWorkspacePanels() {
    const workspace = document.querySelector('#tradeDesk .chart-workspace');
    if (!workspace) return false;

    // The scanner card itself keeps the middle column - that is where you set
    // the balance and press Run Full Scan.
    const scanner = qs('deskScanner');
    if (scanner && scanner.parentElement !== workspace) workspace.appendChild(scanner);

    // Results go in their own row under the chart. Stacked in the middle
    // column they made one long narrow ribbon you had to scroll past the
    // chart to read, while the wide space under the chart sat empty. Down
    // here they lay out several across and the page simply gets longer as
    // setups come in.
    const results = ensureBox('deskScanResults', workspace);
    ['candidatesSection', 'rejectedSection', 'noSetupSection'].forEach((id) => {
      const el = qs(id);
      if (el && el.parentElement !== results) results.appendChild(el);
    });

    // The ledger and the ticket share one grid cell rather than taking a row
    // each. As two cells they set two row heights that the chart column had
    // to match, which is what left the gap under the chart; as one cell the
    // right-hand column is simply as tall as it needs to be.
    const right = ensureBox('deskRightColumn', workspace);
    ['chartAccountPanel', 'quickTradePanel'].forEach((id) => {
      const el = qs(id);
      if (el && el.parentElement !== right) right.appendChild(el);
    });

    return true;
  }

  /* ---- lifecycle ---------------------------------------------------------- */
  function onTradeTab() {
    return !!document.querySelector('#tab-trades.active');
  }

  function start() {
    if (!qs('deskPositionsPanel')) return;
    placeWorkspacePanels();
    refresh();
    renderNewsGuard();
    if (!timer) {
      timer = setInterval(() => {
        if (!onTradeTab()) return;
        // The ticket and the ledger are injected by other files and may not
        // exist yet the first time the tab opens. Re-asserting placement here
        // adopts whatever has appeared since; it is a no-op once each panel is
        // already in the workspace.
        placeWorkspacePanels();
        refresh();
        renderNewsGuard();
      }, REFRESH_MS);
    }
  }

  function init() {
    start();
    const previous = window.switchTab;
    if (typeof previous === 'function' && !previous.__deskEnhanced) {
      window.switchTab = function switchTabDeskEnhanced(name) {
        const result = previous.apply(this, arguments);
        if (name === 'trades') setTimeout(start, 150);
        return result;
      };
      window.switchTab.__deskEnhanced = true;
    }
    qs('chartPair')?.addEventListener('change', renderNewsGuard);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
