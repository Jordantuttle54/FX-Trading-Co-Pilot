
const api = async (path, options = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text);
  }
  return res.json();
};

const $ = id => document.getElementById(id);

let config = null;
let latestSnapshot = null;
let latestAnalysis = null;
let latestCalendar = null;
let latestBriefing = null;
let freshness = {
  config: null,
  market: null,
  calendar: null,
  analysis: null,
  briefing: null
};

document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
    btn.classList.add("active");
    $(btn.dataset.tab).classList.add("active");
  });
});

function badge(text, tone="blue") {
  return `<span class="badge ${tone}">${text}</span>`;
}

function toneFromBias(bias) {
  if (bias === "Bullish") return "green";
  if (bias === "Bearish") return "red";
  return "amber";
}

function fmt(n, pair) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "-";
  const decimals = pair && pair.includes("JPY") ? 3 : pair === "XAU/USD" ? 2 : 5;
  return Number(n).toFixed(decimals);
}

function escapeHtml(str) {
  return String(str || "").replace(/[&<>"']/g, ch => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[ch]));
}

function fillSelects() {
  const ids = ["chartPair","scanPair","riskPair","jPair","pPair"];
  ids.forEach(id => {
    $(id).innerHTML = config.watchlist.map(p => `<option>${p}</option>`).join("");
  });
}

function warningsHtml(warnings) {
  if (!warnings || !warnings.length) return "";
  return `<ul class="warnlist">${warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("")}</ul>`;
}

function splitPair(pair) {
  if (pair === "XAU/USD") return ["XAU", "USD"];
  return String(pair || "").split("/");
}

function affectedPairsForCurrency(currency) {
  const c = String(currency || "").toUpperCase();
  if (!config) return [];
  return config.watchlist.filter(pair => {
    const parts = splitPair(pair);
    return parts.includes(c) || (c === "USD" && pair === "XAU/USD");
  });
}

function analyseNewsGuard() {
  const events = latestCalendar?.events || [];
  const highEvents = events.filter(e => String(e.impact || "").toLowerCase() === "high");
  const currencies = [...new Set(highEvents.map(e => String(e.currency || "").toUpperCase()).filter(Boolean))];
  const blockedPairs = [...new Set(currencies.flatMap(c => affectedPairsForCurrency(c)))];
  const mediumEvents = events.filter(e => String(e.impact || "").toLowerCase() === "medium");

  let tone = "green";
  let risk = "Normal";
  if (highEvents.length >= 2) { tone = "red"; risk = "High"; }
  else if (highEvents.length === 1 || mediumEvents.length >= 2) { tone = "amber"; risk = "Medium"; }

  return { highEvents, mediumEvents, currencies, blockedPairs, risk, tone };
}

function pairNewsInfo(pair) {
  const guard = analyseNewsGuard();
  const currencies = splitPair(pair);
  const linkedHigh = guard.highEvents.filter(e => currencies.includes(String(e.currency || "").toUpperCase()) || (pair === "XAU/USD" && e.currency === "USD"));
  const linkedMedium = guard.mediumEvents.filter(e => currencies.includes(String(e.currency || "").toUpperCase()) || (pair === "XAU/USD" && e.currency === "USD"));
  if (linkedHigh.length) return { tone: "red", label: "News watch", text: linkedHigh.slice(0,2).map(e => `${e.time} ${e.currency}`).join(", ") };
  if (linkedMedium.length) return { tone: "amber", label: "Medium news", text: linkedMedium.slice(0,2).map(e => `${e.time} ${e.currency}`).join(", ") };
  return { tone: "green", label: "Clear", text: "No linked high-impact event loaded" };
}

function markFresh(key) {
  freshness[key] = new Date();
  renderFreshness();
}

function timeAgo(date) {
  if (!date) return "not loaded";
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  return `${hours}h ago`;
}

function renderFreshness() {
  const el = $("freshnessBar");
  if (!el) return;
  const items = [
    ["Market", freshness.market],
    ["Calendar", freshness.calendar],
    ["Briefing", freshness.briefing],
    ["Analysis", freshness.analysis]
  ];
  el.innerHTML = items.map(([label, when]) => `<span class="freshness-pill">${label}: <strong>${timeAgo(when)}</strong></span>`).join("");
}

function pairPermission(pair) {
  const news = pairNewsInfo(pair);
  const analysis = (latestAnalysis?.pairs || []).find(p => p.pair === pair);
  const volatility = analysis?.volatility || "Unknown";
  const bias = analysis?.bias || "Neutral";

  if (news.tone === "red") {
    return {
      status: "Blocked",
      bucket: "blocked",
      tone: "red",
      reason: `${news.text} linked high-impact news`
    };
  }

  if (volatility === "Very High") {
    return {
      status: "Blocked",
      bucket: "blocked",
      tone: "red",
      reason: "Very high volatility"
    };
  }

  if (news.tone === "amber" || bias === "Neutral") {
    return {
      status: "Watch",
      bucket: "watch",
      tone: "amber",
      reason: news.tone === "amber" ? `${news.text} medium news` : "Mixed or neutral bias"
    };
  }

  return {
    status: "Assess",
    bucket: "assess",
    tone: "green",
    reason: "No linked high-impact news loaded; still requires 85+ scanner score"
  };
}

function renderDecisionBar() {
  const el = $("decisionBar");
  if (!el || !config || !latestCalendar || !latestAnalysis) return;

  const guard = analyseNewsGuard();
  const allPairs = config.watchlist || [];
  const permissions = allPairs.map(pair => ({ pair, ...pairPermission(pair) }));
  const assess = permissions.filter(p => p.bucket === "assess");
  const watch = permissions.filter(p => p.bucket === "watch");
  const blocked = permissions.filter(p => p.bucket === "blocked");

  let tone = "green";
  let headline = "CONTROLLED — ASSESS ONLY";
  let action = "Only score planned setups. No live execution.";
  if (guard.risk === "High" || blocked.length >= Math.max(2, Math.ceil(allPairs.length / 2))) {
    tone = "red";
    headline = "HIGH RISK — PAPER ONLY";
    action = "Monitor markets. Only review planned setups after news risk clears.";
  } else if (guard.risk === "Medium" || watch.length) {
    tone = "amber";
    headline = "CAUTION — WAIT FOR CLEAN SETUPS";
    action = "Use the scanner. Do not proceed unless confidence is 85+ and hard blockers are clear.";
  }

  el.className = `decision-bar ${tone}`;
  el.innerHTML = `
    <div class="decision-main">
      <span class="eyebrow">System decision</span>
      <strong>${headline}</strong>
      <em>${action}</em>
    </div>
    <div class="decision-actions">
      <div class="decision-chip"><span>Confidence gate</span><strong>${config.rules.min_confidence_score || 85}+</strong></div>
      <div class="decision-chip"><span>Execution</span><strong>LOCKED</strong></div>
      <div class="decision-chip"><span>Assessable pairs</span><strong>${assess.length}</strong></div>
      <div class="decision-chip"><span>Blocked / watch</span><strong>${blocked.length} / ${watch.length}</strong></div>
    </div>
  `;
}

function renderPairPermissions() {
  const el = $("pairPermissionPanel");
  if (!el || !config || !latestAnalysis || !latestCalendar) return;

  const permissions = (config.watchlist || []).map(pair => ({ pair, ...pairPermission(pair) }));
  const groups = [
    { key: "assess", title: "Allowed to assess", tone: "green", empty: "No clean pairs loaded yet." },
    { key: "watch", title: "Watch only", tone: "amber", empty: "No caution pairs." },
    { key: "blocked", title: "Blocked by risk", tone: "red", empty: "No hard blocks loaded." }
  ];

  const groupHtml = groups.map(g => {
    const items = permissions.filter(p => p.bucket === g.key);
    return `
      <div class="permission-column">
        <h3>${badge(g.title, g.tone)}</h3>
        <div class="permission-list">
          ${items.length ? items.map(p => `
            <div class="permission-item">
              <div><strong>${p.pair}</strong><span>${escapeHtml(p.reason)}</span></div>
              ${badge(p.status, p.tone)}
            </div>
          `).join("") : `<div class="permission-empty">${g.empty}</div>`}
        </div>
      </div>
    `;
  }).join("");

  el.innerHTML = `
    <div class="panel-head">
      <div>
        <h2>Pair Permission Map</h2>
        <p class="muted small">This is not a trade signal. It tells you which pairs are clean enough to send to the 85+ scanner.</p>
      </div>
    </div>
    <div class="permission-grid">${groupHtml}</div>
  `;
}

function renderDailyChecklist() {
  const el = $("dailyChecklistPanel");
  if (!el || !config || !latestCalendar) return;
  const guard = analyseNewsGuard();

  const checks = [
    {
      label: "Market feed",
      detail: config.configured.oanda ? "OANDA connected" : "OANDA missing",
      tone: config.configured.oanda ? "green" : "red"
    },
    {
      label: "Calendar loaded",
      detail: latestCalendar.provider ? `${latestCalendar.provider} active` : "No calendar provider",
      tone: latestCalendar.provider ? "green" : "red"
    },
    {
      label: "News risk reviewed",
      detail: `${guard.highEvents.length} high-impact events loaded`,
      tone: guard.highEvents.length ? "amber" : "green"
    },
    {
      label: "Confidence gate",
      detail: `${config.rules.min_confidence_score || 85}+ required`,
      tone: "green"
    },
    {
      label: "Live trading",
      detail: "Locked / paper only",
      tone: "green"
    },
    {
      label: "Next action",
      detail: guard.risk === "High" ? "Monitor and wait for clean conditions" : "Score only planned setups",
      tone: guard.risk === "High" ? "amber" : "green"
    }
  ];

  el.innerHTML = `
    <div class="panel-head">
      <div>
        <h2>Daily Control Checklist</h2>
        <p class="muted small">Quick safety checks before any setup is assessed.</p>
      </div>
    </div>
    <div class="checklist">
      ${checks.map(c => `
        <div class="check-row">
          <div><strong>${escapeHtml(c.label)}</strong><span>${escapeHtml(c.detail)}</span></div>
          <div class="check-dot ${c.tone}">${c.tone === "red" ? "!" : "✓"}</div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderV51Panels() {
  renderDecisionBar();
  renderPairPermissions();
  renderDailyChecklist();
}


function renderSystemStatus() {
  if (!config) return;
  const calProvider = config.configured.calendar_provider || "unknown";
  const manualFile = config.configured.manual_calendar_file || "data/economic_calendar.csv";
  const confidenceGate = config.rules.min_confidence_score || 85;
  $("systemStatus").innerHTML = `
    <div class="v51-status-grid">
      <div class="v51-status-item good"><span>Market feed</span><strong>${escapeHtml(config.selected_provider)}</strong></div>
      <div class="v51-status-item ${config.configured.oanda ? "good" : "amber"}"><span>OANDA</span><strong>${config.configured.oanda ? "connected" : "not set"}</strong></div>
      <div class="v51-status-item good"><span>Calendar</span><strong>${escapeHtml(calProvider)}</strong></div>
      <div class="v51-status-item ${config.configured.manual_calendar ? "good" : "amber"}"><span>Manual file</span><strong>${config.configured.manual_calendar ? "found" : "missing"}</strong></div>
      <div class="v51-status-item red"><span>Live trading</span><strong>LOCKED</strong></div>
      <div class="v51-status-item good"><span>Risk / trade</span><strong>${config.rules.max_risk_per_trade_pct}%</strong></div>
      <div class="v51-status-item good"><span>Confidence gate</span><strong>${confidenceGate}+</strong></div>
      <div class="v51-status-item good"><span>Monitor mode</span><strong>24/7</strong></div>
    </div>
    <div class="v51-status-foot">Monitor mode: ${escapeHtml(config.rules.trading_window || "24/7 monitor")} · Calendar file: ${escapeHtml(manualFile)}</div>
  `;
}

function renderControlCards() {
  if (!config || !latestCalendar) return;
  const guard = analyseNewsGuard();
  const calendarProvider = latestCalendar.provider || config.configured.calendar_provider || "unknown";
  const cards = [
    { label: "Market Feed", value: config.selected_provider.toUpperCase(), detail: config.configured.oanda ? "OANDA connected" : "Check provider settings", tone: config.configured.oanda ? "green" : "amber" },
    { label: "Calendar Source", value: calendarProvider.replace("_", " ").toUpperCase(), detail: config.configured.manual_calendar ? "Manual CSV active" : "Calendar file missing", tone: config.configured.manual_calendar ? "green" : "amber" },
    { label: "Today’s Risk", value: guard.risk.toUpperCase(), detail: `${guard.highEvents.length} high-impact events loaded`, tone: guard.tone },
    { label: "Confidence Gate", value: `${config.rules.min_confidence_score}+`, detail: "Strict paper/manual review", tone: "amber" },
    { label: "Execution", value: "LOCKED", detail: "Paper trading only", tone: "red" },
  ];
  $("controlCards").innerHTML = cards.map(c => `
    <div class="control-card ${c.tone}">
      <span>${c.label}</span>
      <strong>${c.value}</strong>
      <em>${c.detail}</em>
    </div>
  `).join("");
}

function renderNewsGuard() {
  if (!latestCalendar) return;
  const guard = analyseNewsGuard();
  const events = guard.highEvents.slice(0, 5);
  const eventList = events.length
    ? events.map(e => `<li><strong>${escapeHtml(e.time || "")}</strong> ${escapeHtml(e.currency || "")} — ${escapeHtml(e.event || "")}</li>`).join("")
    : `<li>No high-impact events loaded in the manual calendar.</li>`;
  const blocked = guard.blockedPairs.length ? guard.blockedPairs.map(p => badge(p, "red")).join(" ") : badge("No blocked pairs loaded", "green");

  const windows = events.length ? events.map(e => `
    <div class="news-window">
      <strong>${escapeHtml(e.currency || "")} ${escapeHtml(e.time || "")} — ${escapeHtml(e.event || "")}</strong>
      <span>Guard rule: avoid linked pairs for at least ${config.rules.news_guard_minutes || 30} minutes either side, then reassess only if confidence is ${config.rules.min_confidence_score || 85}+.</span>
    </div>
  `).join("") : "";
  $("newsGuardPanel").innerHTML = `
    <div class="panel-head">
      <div>
        <h2>Today’s News Guard</h2>
        <p class="muted small">Conservative view based on your manual calendar. High-impact currencies flag matching watchlist pairs.</p>
      </div>
      ${badge(`${guard.risk} risk`, guard.tone)}
    </div>
    <div class="grid2 compact">
      <div class="mini-panel">
        <h3>High-impact events</h3>
        <ul class="news-list">${eventList}</ul>
        <div class="news-window-list">${windows}</div>
      </div>
      <div class="mini-panel">
        <h3>News-affected pairs</h3>
        <div class="badge-wrap">${blocked}</div>
        <p class="muted small">Use this as a permission filter before opening the Setup Scanner. It is not an automatic trade signal.</p>
      </div>
    </div>
  `;
}

async function loadConfig() {
  config = await api("/api/config");
  markFresh("config");
  fillSelects();
  renderSystemStatus();
}

async function loadSnapshot() {
  latestSnapshot = await api("/api/market/snapshot");
  markFresh("market");
  $("marketWarnings").innerHTML = warningsHtml(latestSnapshot.warnings);
}

async function loadCalendar() {
  latestCalendar = await api("/api/calendar");
  markFresh("calendar");
  $("calendarWarnings").innerHTML = warningsHtml(latestCalendar.warnings);
  $("calendarTable").innerHTML = `
    <tr><th>Date</th><th>Time</th><th>Currency</th><th>Event</th><th>Impact</th></tr>
    ${(latestCalendar.events || []).map(e => `
      <tr>
        <td>${escapeHtml(e.date || "")}</td>
        <td>${escapeHtml(e.time || "")}</td>
        <td>${escapeHtml(e.currency || "")}</td>
        <td>${escapeHtml(e.event || "")}</td>
        <td>${badge(escapeHtml(e.impact || "Medium"), String(e.impact).toLowerCase() === "high" ? "red" : "amber")}</td>
      </tr>
    `).join("")}
  `;
  renderControlCards();
  renderNewsGuard();
  renderV51Panels();
}

async function loadAnalysis() {
  latestAnalysis = await api("/api/market/analysis?interval=1h");
  markFresh("analysis");
  const quotesByPair = {};
  (latestSnapshot?.quotes || []).forEach(q => quotesByPair[q.pair] = q);
  $("pairs").innerHTML = latestAnalysis.pairs.map(p => {
    const q = quotesByPair[p.pair] || {};
    const news = pairNewsInfo(p.pair);
    const permission = pairPermission(p.pair);
    return `<div class="card pair-card ${news.tone === "red" ? "news-hot" : ""}">
      <div class="pair-head"><h3>${p.pair}</h3>${badge(permission.status, permission.tone)}</div>
      <div class="row"><span>Price</span><strong>${fmt(q.price || p.price, p.pair)}</strong></div>
      <div class="row"><span>Bias</span>${badge(p.bias, toneFromBias(p.bias))}</div>
      <div class="row"><span>Trend</span><strong>${p.trend}</strong></div>
      <div class="row"><span>Volatility</span><strong>${p.volatility}</strong></div>
      <div class="row"><span>Source</span><strong>${q.source || "analysis"}</strong></div>
      <p class="muted small"><strong>Permission:</strong> ${escapeHtml(permission.reason)}</p>
      <p class="muted small"><strong>News:</strong> ${escapeHtml(news.text)}</p>
      <p class="muted small">${p.zone}</p>
      <p class="muted small">${p.note}</p>
    </div>`;
  }).join("");
  renderV51Panels();
}

async function loadBriefing() {
  const data = await api("/api/briefing");
  latestBriefing = data;
  markFresh("briefing");
  $("briefing").innerHTML = data.summary
    .split("\n\n")
    .map(line => `<p>${escapeHtml(line)}</p>`)
    .join("");
}

async function loadChart() {
  const pair = encodeURIComponent($("chartPair").value);
  const interval = $("chartInterval").value;
  const data = await api(`/api/market/candles?pair=${pair}&interval=${interval}&count=120`);
  drawLineChart(data.candles || [], $("chartCanvas"), data.pair);
  $("chartInfo").innerText = `Provider: ${data.provider}. ${data.warning || ""}`;
}

function drawLineChart(candles, canvas, pair) {
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * devicePixelRatio;
  canvas.height = rect.height * devicePixelRatio;
  ctx.scale(devicePixelRatio, devicePixelRatio);

  const w = rect.width, h = rect.height;
  ctx.clearRect(0,0,w,h);

  if (!candles.length) {
    ctx.fillStyle = "rgba(255,255,255,.7)";
    ctx.fillText("No candle data", 20, 30);
    return;
  }

  const values = candles.map(c => Number(c.close));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = 16;
  const x = i => pad + i * ((w - pad * 2) / Math.max(1, values.length - 1));
  const y = v => h - pad - ((v - min) / Math.max(0.000001, max - min)) * (h - pad * 2);

  ctx.strokeStyle = "rgba(255,255,255,.12)";
  ctx.lineWidth = 1;
  for (let i=0; i<4; i++) {
    const yy = pad + i * ((h-pad*2)/3);
    ctx.beginPath(); ctx.moveTo(pad, yy); ctx.lineTo(w-pad, yy); ctx.stroke();
  }

  ctx.strokeStyle = "rgba(212,175,55,.95)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((v,i) => {
    if (i === 0) ctx.moveTo(x(i), y(v));
    else ctx.lineTo(x(i), y(v));
  });
  ctx.stroke();

  ctx.fillStyle = "rgba(255,255,255,.75)";
  ctx.font = "12px system-ui";
  ctx.fillText(`${pair} close: ${fmt(values[values.length-1], pair)}`, 18, 24);
}

async function scanSetup() {
  const payload = {
    pair: $("scanPair").value,
    direction: $("scanDirection").value,
    timeframe: $("scanTf").value,
    risk_reward: Number($("scanRR").value),
    checklist: {
      trend_alignment: $("chkTrend").checked,
      planned_zone: $("chkZone").checked,
      stop_defined: $("chkStop").checked,
      emotional_control: $("chkEmotion").checked,
      no_news_risk: $("chkNews").checked
    }
  };
  const r = await api("/api/scan", { method: "POST", body: JSON.stringify(payload) });
  const blockers = (r.hard_blockers || []).length ? r.hard_blockers.map(b => `- ${b}`).join("\n") : "none";
  const components = (r.components || []).map(c => `${c.name}: ${c.points}/${c.max_points} - ${c.note}`).join("\n");
  $("scanResult").innerHTML = `
${badge(r.verdict, r.tone)} Confidence: ${r.confidence_score || r.score}/100
Minimum required: ${r.min_confidence_score || config.rules.min_confidence_score}/100

${r.message}

Hard blockers:
${blockers}

Confidence components:
${components}

Trend aligned: ${r.trend_ok ? "yes" : "no"}
Risk/reward acceptable: ${r.risk_reward_ok ? "yes" : "no"}
Linked high-impact news: ${r.linked_high_news.length ? r.linked_high_news.map(e => `${e.time} ${e.currency} ${e.event}`).join("; ") : "none loaded"}

Pair analysis:
${r.analysis.bias} | ${r.analysis.trend}
Zone: ${r.analysis.zone}

Mode: ${r.mode || "paper/manual review only"}
  `;
}

async function calculateRisk() {
  const payload = {
    account_balance: Number($("riskBalance").value),
    risk_pct: Number($("riskPct").value),
    pair: $("riskPair").value,
    entry: Number($("entry").value),
    stop_loss: Number($("stop").value),
    target: Number($("target").value),
    pip_value_per_standard_lot: Number($("pipValue").value)
  };
  const r = await api("/api/risk", { method: "POST", body: JSON.stringify(payload) });
  $("riskOutput").innerHTML = `
${badge(r.verdict, r.tone)}

Risk amount: ${r.risk_amount.toFixed(2)}
Stop distance: ${r.stop_pips.toFixed(1)} pips
Reward distance: ${r.reward_pips.toFixed(1)} pips
Risk/reward: ${r.risk_reward.toFixed(2)}:1
Standard lots: ${r.standard_lots.toFixed(3)}
Position units: ${Math.round(r.position_units).toLocaleString()}

${r.notes}
  `;
  $("pPair").value = payload.pair;
  $("pEntry").value = payload.entry;
  $("pStop").value = payload.stop_loss;
  $("pTarget").value = payload.target;
  $("pRiskPct").value = payload.risk_pct;
  $("pRiskAmount").value = r.risk_amount.toFixed(2);
  $("pUnits").value = Math.round(r.position_units);
}

async function loadJournal() {
  const data = await api("/api/journal");
  $("statTrades").innerText = data.stats.trades;
  $("statWin").innerText = `${data.stats.win_rate_pct}%`;
  $("statR").innerText = data.stats.total_r;

  let coach = "Start logging trades. After 10+ trades, patterns become more useful.";
  if (data.stats.trades >= 5) {
    coach = data.stats.avg_r > 0
      ? `Average R is ${data.stats.avg_r}. Keep risk small and grow the sample before increasing size.`
      : `Average R is ${data.stats.avg_r}. Pause any automation ideas and review trade selection, timing and emotional triggers.`;
  }
  $("coachText").innerText = coach;

  $("journalTable").innerHTML = `
    <tr><th>Date</th><th>Pair</th><th>Dir</th><th>R</th><th>Reason</th><th>Lesson</th></tr>
    ${data.rows.map(r => `<tr>
      <td>${escapeHtml(r.date)}</td>
      <td>${escapeHtml(r.pair)}</td>
      <td>${escapeHtml(r.direction)}</td>
      <td>${badge(`${r.result_r}R`, r.result_r > 0 ? "green" : r.result_r < 0 ? "red" : "amber")}</td>
      <td>${escapeHtml(r.reason)}</td>
      <td>${escapeHtml(r.lesson)}</td>
    </tr>`).join("")}
  `;
}

async function saveJournal() {
  const payload = {
    date: $("jDate").value || new Date().toISOString().slice(0,10),
    pair: $("jPair").value,
    direction: $("jDirection").value,
    result_r: Number($("jR").value || 0),
    reason: $("jReason").value,
    lesson: $("jLesson").value
  };
  await api("/api/journal", { method: "POST", body: JSON.stringify(payload) });
  $("jR").value = ""; $("jReason").value = ""; $("jLesson").value = "";
  await loadJournal();
}

async function clearJournal() {
  if (!confirm("Clear all journal entries?")) return;
  await api("/api/journal", { method: "DELETE" });
  await loadJournal();
}

async function loadPaperTrades() {
  const data = await api("/api/paper-trades");
  $("paperTable").innerHTML = `
    <tr><th>ID</th><th>Status</th><th>Pair</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Risk</th><th>Units</th><th>Result</th></tr>
    ${data.rows.map(r => `<tr>
      <td>${r.id}</td>
      <td>${badge(r.status, r.status === "OPEN" ? "green" : "blue")}</td>
      <td>${escapeHtml(r.pair)}</td>
      <td>${escapeHtml(r.direction)}</td>
      <td>${fmt(r.entry, r.pair)}</td>
      <td>${fmt(r.stop_loss, r.pair)}</td>
      <td>${fmt(r.target, r.pair)}</td>
      <td>${r.risk_pct}% / ${Number(r.risk_amount).toFixed(2)}</td>
      <td>${Math.round(r.position_units).toLocaleString()}</td>
      <td>${r.result_r === null ? "-" : `${r.result_r}R`}</td>
    </tr>`).join("")}
  `;
}

async function openPaperTrade() {
  const payload = {
    pair: $("pPair").value,
    direction: $("pDirection").value,
    entry: Number($("pEntry").value),
    stop_loss: Number($("pStop").value),
    target: Number($("pTarget").value),
    risk_pct: Number($("pRiskPct").value),
    risk_amount: Number($("pRiskAmount").value),
    position_units: Number($("pUnits").value),
    notes: $("pNotes").value
  };
  await api("/api/paper-trades", { method: "POST", body: JSON.stringify(payload) });
  $("pNotes").value = "";
  await loadPaperTrades();
}

async function checkAutomation() {
  const payload = {
    backtested_trades: Number($("aBack").value),
    forward_trades: Number($("aForward").value),
    win_rate_pct: Number($("aWin").value),
    avg_r: Number($("aAvgR").value),
    max_drawdown_pct: Number($("aDD").value),
    max_daily_loss_pct: Number($("aDaily").value)
  };
  const r = await api("/api/automation-readiness", { method: "POST", body: JSON.stringify(payload) });
  $("autoResult").innerHTML = `
${badge(r.ready_for_demo_automation ? "READY FOR DEMO AUTOMATION ONLY" : "NOT READY", r.ready_for_demo_automation ? "green" : "red")}

${r.message}
Passed: ${r.passed}/${r.total}
Live trading locked: ${r.live_trading_locked ? "yes" : "no"}

${r.gates.map(g => `${g.pass ? "PASS" : "FAIL"} — ${g.name}`).join("\n")}
  `;
}

async function refreshAll() {
  try {
    await loadSnapshot();
    await loadCalendar();
    await loadAnalysis();
    await loadBriefing();
    await loadChart();
    await loadJournal();
    await loadPaperTrades();
    renderSystemStatus();
    renderControlCards();
    renderNewsGuard();
    renderV51Panels();
  } catch (err) {
    console.error(err);
    alert("Error: " + err.message);
  }
}

async function init() {
  $("jDate").value = new Date().toISOString().slice(0,10);
  await loadConfig();
  await refreshAll();
  await calculateRisk();
}

init();
