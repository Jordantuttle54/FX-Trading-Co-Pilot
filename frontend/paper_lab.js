(() => {
  const WEEK_KEY = "afx_paper_week_start";

  function localUser() {
    return localStorage.getItem("afx_auth_user") || "User";
  }

  function weekKey() {
    return `${WEEK_KEY}_${localUser()}`;
  }

  function getWeekStart() {
    let value = localStorage.getItem(weekKey());
    if (!value) {
      value = new Date().toISOString();
      localStorage.setItem(weekKey(), value);
    }
    return new Date(value);
  }

  function resetWeekStart() {
    localStorage.setItem(weekKey(), new Date().toISOString());
    loadPaperTrades();
  }

  function escapeCsv(value) {
    const text = String(value ?? "");
    if (/[",\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
    return text;
  }

  function formatMoney(value) {
    const n = Number(value || 0);
    return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function ensurePaperLabShell() {
    const section = document.getElementById("paper");
    if (!section || document.getElementById("paperLabDashboard")) return;

    const lab = document.createElement("div");
    lab.id = "paperLabDashboard";
    lab.className = "paper-lab-shell";
    lab.innerHTML = `
      <div class="paper-lab-hero">
        <div>
          <span class="eyebrow">Paper Test Lab</span>
          <h2>7-Day System Validation Sprint</h2>
          <p class="muted">Track every simulated setup, close trades with an R result, then review whether the system deserves more development.</p>
        </div>
        <div class="paper-lab-actions">
          <button type="button" onclick="refreshPaperLab()">Refresh test data</button>
          <button type="button" onclick="exportPaperTradesCsv()">Export CSV</button>
          <button type="button" class="danger" onclick="resetPaperTestWeek()">Reset week start</button>
        </div>
      </div>
      <div id="paperLabStats" class="paper-lab-stats"></div>
      <div class="paper-lab-rules">
        <div><strong>Rule 1</strong><span>Only paper trade if the setup passes the checklist and confidence gate.</span></div>
        <div><strong>Rule 2</strong><span>Record entry, stop, target and reason before taking the trade.</span></div>
        <div><strong>Rule 3</strong><span>Close every paper trade with a final R result.</span></div>
        <div><strong>Rule 4</strong><span>Review Total R, win rate and rule discipline after 7 days.</span></div>
      </div>
    `;
    section.insertBefore(lab, section.firstElementChild);
  }

  function calcWeekRows(rows) {
    const start = getWeekStart();
    return rows.filter(row => {
      const created = new Date(row.created_at || row.date || 0);
      return !Number.isNaN(created.getTime()) && created >= start;
    });
  }

  function calcStats(rows) {
    const closed = rows.filter(r => r.status === "CLOSED");
    const open = rows.filter(r => r.status === "OPEN");
    const wins = closed.filter(r => Number(r.result_r || 0) > 0);
    const losses = closed.filter(r => Number(r.result_r || 0) < 0);
    const breakeven = closed.filter(r => Number(r.result_r || 0) === 0);
    const totalR = closed.reduce((sum, r) => sum + Number(r.result_r || 0), 0);
    const pnl = closed.reduce((sum, r) => sum + Number(r.risk_amount || 0) * Number(r.result_r || 0), 0);
    return {
      rows: rows.length,
      open: open.length,
      closed: closed.length,
      wins: wins.length,
      losses: losses.length,
      breakeven: breakeven.length,
      winRate: closed.length ? (wins.length / closed.length) * 100 : 0,
      totalR,
      pnl,
    };
  }

  function renderPaperLab(rows, apiStats = {}) {
    ensurePaperLabShell();
    const allRows = rows || [];
    const weekRows = calcWeekRows(allRows);
    const stats = calcStats(weekRows);
    const start = getWeekStart();
    const day = Math.min(7, Math.max(1, Math.floor((Date.now() - start.getTime()) / 86400000) + 1));
    const statsEl = document.getElementById("paperLabStats");
    if (!statsEl) return;

    let verdict = "Not enough closed trades yet";
    let verdictTone = "amber";
    if (stats.closed >= 10 && stats.totalR > 0 && stats.winRate >= 40) {
      verdict = "Positive paper-test profile";
      verdictTone = "green";
    } else if (stats.closed >= 10 && stats.totalR <= 0) {
      verdict = "Do not automate — review rules";
      verdictTone = "red";
    }

    statsEl.innerHTML = `
      <div class="paper-kpi"><span>Test day</span><strong>${day}/7</strong><em>Started ${start.toISOString().slice(0,10)}</em></div>
      <div class="paper-kpi"><span>Week trades</span><strong>${stats.rows}</strong><em>${stats.open} open / ${stats.closed} closed</em></div>
      <div class="paper-kpi"><span>Win rate</span><strong>${stats.winRate.toFixed(1)}%</strong><em>${stats.wins}W / ${stats.losses}L / ${stats.breakeven}BE</em></div>
      <div class="paper-kpi"><span>Total R</span><strong>${stats.totalR.toFixed(2)}R</strong><em>Closed paper trades only</em></div>
      <div class="paper-kpi"><span>Est. P/L</span><strong>£${formatMoney(stats.pnl)}</strong><em>Risk amount × R result</em></div>
      <div class="paper-kpi ${verdictTone}"><span>Validation status</span><strong>${verdict}</strong><em>Minimum useful sample: 10+ closed trades</em></div>
    `;
  }

  function rowCloseControls(row) {
    if (row.status !== "OPEN") return `<span class="muted small">Closed</span>`;
    return `
      <div class="close-trade-controls">
        <input id="closePrice_${row.id}" type="number" step="0.00001" placeholder="Close price" />
        <input id="closeR_${row.id}" type="number" step="0.1" placeholder="Result R" />
        <button type="button" onclick="closePaperTrade(${row.id})">Close</button>
      </div>`;
  }

  window.loadPaperTrades = async function loadPaperTradesEnhanced() {
    const res = await fetch("/api/paper-trades");
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const rows = data.rows || [];
    renderPaperLab(rows, data.stats || {});

    const table = document.getElementById("paperTable");
    if (!table) return;
    table.innerHTML = `
      <tr>
        <th>ID</th><th>Status</th><th>Pair</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Risk</th><th>Units</th><th>Result</th><th>Close trade</th>
      </tr>
      ${rows.map(r => `<tr>
        <td>${r.id}</td>
        <td>${badge(r.status, r.status === "OPEN" ? "green" : "blue")}</td>
        <td>${escapeHtml(r.pair)}</td>
        <td>${escapeHtml(r.direction)}</td>
        <td>${fmt(r.entry, r.pair)}</td>
        <td>${fmt(r.stop_loss, r.pair)}</td>
        <td>${fmt(r.target, r.pair)}</td>
        <td>${Number(r.risk_pct).toFixed(2)}% / £${formatMoney(r.risk_amount)}</td>
        <td>${Math.round(Number(r.position_units || 0)).toLocaleString()}</td>
        <td>${r.result_r === null || r.result_r === undefined ? "-" : `${Number(r.result_r).toFixed(2)}R`}</td>
        <td>${rowCloseControls(r)}</td>
      </tr>`).join("")}
    `;
  };

  window.closePaperTrade = async function closePaperTrade(tradeId) {
    const closePrice = Number(document.getElementById(`closePrice_${tradeId}`)?.value);
    const resultR = Number(document.getElementById(`closeR_${tradeId}`)?.value);
    if (!Number.isFinite(closePrice) || closePrice <= 0) {
      alert("Enter a valid close price.");
      return;
    }
    if (!Number.isFinite(resultR)) {
      alert("Enter the trade result in R, for example 2, 1.2, 0, or -1.");
      return;
    }
    const params = new URLSearchParams({ close_price: String(closePrice), result_r: String(resultR) });
    const res = await fetch(`/api/paper-trades/${tradeId}/close?${params.toString()}`, { method: "POST" });
    if (!res.ok) {
      alert("Could not close paper trade: " + await res.text());
      return;
    }
    await loadPaperTrades();
  };

  window.refreshPaperLab = async function refreshPaperLab() {
    await loadPaperTrades();
  };

  window.resetPaperTestWeek = function resetPaperTestWeek() {
    if (!confirm("Reset the 7-day paper-test start date to today? This does not delete trades.")) return;
    resetWeekStart();
  };

  window.exportPaperTradesCsv = async function exportPaperTradesCsv() {
    const res = await fetch("/api/paper-trades");
    if (!res.ok) {
      alert("Could not export paper trades.");
      return;
    }
    const data = await res.json();
    const rows = data.rows || [];
    const headers = ["id","user","created_at","status","pair","direction","entry","stop_loss","target","risk_pct","risk_amount","position_units","closed_at","close_price","result_r","notes"];
    const csv = [headers.join(",")].concat(rows.map(row => headers.map(h => escapeCsv(row[h])).join(","))).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `paper-trades-${localUser()}-${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  document.addEventListener("DOMContentLoaded", () => {
    ensurePaperLabShell();
    setTimeout(() => {
      if (typeof loadPaperTrades === "function") loadPaperTrades().catch(console.error);
    }, 1200);
  });
})();
