/* agent_scanner_polish.js - scanner-only visual layout and card renderer */
'use strict';

(function () {
  if (window.__agentScannerPolishInstalled) return;
  window.__agentScannerPolishInstalled = true;

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  function num(value, fallback = null) {
    if (value === null || value === undefined || value === '') return fallback;
    const parsed = Number(String(value).replace(/[£$,R%]/g, ''));
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function pairId(pair) {
    return String(pair || '').replace('/', '').toUpperCase();
  }

  function prettyPair(pair) {
    return String(pair || '').replace('_', '/').toUpperCase();
  }

  function precision(pair, value) {
    const p = String(pair || '').toUpperCase();
    if (p.includes('XAU') || p.includes('XAG')) return 2;
    if (p.includes('JPY')) return 3;
    const n = Number(value);
    return Number.isFinite(n) && Math.abs(n) >= 100 ? 3 : 5;
  }

  function formatPrice(pair, value) {
    const n = num(value, null);
    if (n === null) return '--';
    return n.toFixed(precision(pair, n));
  }

  function confidence(item) {
    const c = num(item?.confidence, null);
    if (c === null) return '--';
    return Math.round(c);
  }

  function direction(item) {
    const d = String(item?.direction || item?.side || '').toLowerCase();
    if (d === 'buy' || d === 'sell') return d;
    return 'buy';
  }

  function trend(item) {
    const raw = item?.trend || item?.trend_label || item?.trend_direction || '';
    if (raw) return String(raw);
    return direction(item) === 'sell' ? 'Down' : 'Up';
  }

  function trendArrow(item) {
    return /down|bear|sell/i.test(trend(item)) ? '↓' : '↑';
  }

  function session(item) {
    return item?.session || item?.trading_session || 'Off-session';
  }

  function rr(item) {
    const r = num(item?.rr_estimate, num(item?.risk_reward, null));
    return r === null ? '--' : `${r.toFixed(1)}R`;
  }

  function thesis(item) {
    return item?.entry_reason || item?.reason || item?.setup_label || item?.setup_type || 'Approved by the current scanner rules.';
  }

  function rejectionReason(item) {
    return item?.rejection_reason || item?.entry_reason || item?.reason || 'Scanner conditions were not strong enough for a clean setup.';
  }

  function statusLine() {
    const status = qs('scannerStatus');
    if (!status || status.dataset.scannerPolished) return;
    status.dataset.scannerPolished = 'true';
  }

  function installStyles() {
    if (qs('agentScannerPolishStyles')) return;
    const style = document.createElement('style');
    style.id = 'agentScannerPolishStyles';
    style.textContent = `
      #tab-scanner.active {
        display: grid !important;
        grid-template-columns: minmax(310px, 410px) minmax(0, 1fr);
        grid-template-areas:
          "scan approved"
          "history approved"
          "rejected rejected"
          "nosetup nosetup";
        gap: 14px 18px !important;
        align-items: start !important;
      }

      #tab-scanner > .agent-card:first-child {
        grid-area: scan !important;
        margin: 0 !important;
        padding: 18px 20px !important;
        border: 1px solid rgba(148,163,184,.24) !important;
        background:
          radial-gradient(circle at 0% 0%, rgba(88,166,255,.13), transparent 34%),
          radial-gradient(circle at 96% 0%, rgba(227,179,65,.08), transparent 30%),
          linear-gradient(180deg, rgba(255,255,255,.060), rgba(255,255,255,.018)),
          rgba(15,23,42,.72) !important;
        box-shadow: 0 22px 55px rgba(0,0,0,.30) !important;
        backdrop-filter: blur(14px) saturate(125%);
      }

      #tab-scanner > .agent-card:last-child {
        grid-area: history !important;
        margin: 0 !important;
        padding: 16px 18px !important;
        border: 1px solid rgba(148,163,184,.22) !important;
        background:
          linear-gradient(180deg, rgba(255,255,255,.050), rgba(255,255,255,.014)),
          rgba(15,23,42,.68) !important;
        backdrop-filter: blur(12px) saturate(120%);
      }

      #tab-scanner #candidatesSection,
      #tab-scanner #rejectedSection,
      #tab-scanner #noSetupSection {
        min-width: 0 !important;
        width: 100% !important;
        margin: 0 !important;
      }

      #tab-scanner #candidatesSection {
        grid-area: approved !important;
        padding: 16px 18px !important;
        border: 1px solid rgba(88,166,255,.18);
        border-radius: 18px;
        background: linear-gradient(180deg, rgba(88,166,255,.035), rgba(2,6,23,.10));
      }

      #tab-scanner #rejectedSection,
      #tab-scanner #noSetupSection {
        padding: 14px 16px !important;
        border: 1px solid rgba(148,163,184,.18);
        border-radius: 18px;
        background: linear-gradient(180deg, rgba(15,23,42,.72), rgba(2,6,23,.18));
      }

      #tab-scanner #rejectedSection { grid-area: rejected !important; }
      #tab-scanner #noSetupSection { grid-area: nosetup !important; }

      #tab-scanner .scanner-section-head {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
        margin: 0 0 14px;
      }

      #tab-scanner .scanner-section-title {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 0;
        font-size: 17px;
        font-weight: 950;
        letter-spacing: -.02em;
      }

      #tab-scanner .scanner-section-sub {
        margin: 4px 0 0;
        color: var(--muted);
        font-size: 12px;
      }

      #tab-scanner .scanner-section-icon {
        width: 20px;
        height: 20px;
        display: inline-grid;
        place-items: center;
        border-radius: 50%;
        border: 1px solid currentColor;
        font-size: 12px;
        line-height: 1;
      }

      #tab-scanner .scanner-icon-approved { color: var(--accent, #58a6ff); }
      #tab-scanner .scanner-icon-rejected { color: var(--red, #f85149); }

      #tab-scanner .scanner-view-btn {
        appearance: none;
        border: 1px solid rgba(148,163,184,.28);
        background: rgba(15,23,42,.76);
        color: var(--text);
        padding: 8px 12px;
        border-radius: 10px;
        font-size: 11px;
        font-weight: 850;
        white-space: nowrap;
      }

      #tab-scanner .scanner-controls { gap: 12px !important; }
      #tab-scanner .scanner-controls input { min-height: 38px !important; }
      #tab-scanner .scanner-controls .btn-primary,
      #tab-scanner .scanner-controls button { width: 100%; min-height: 42px; font-weight: 950; }

      #tab-scanner .scan-status {
        background: rgba(15,23,42,.74) !important;
        border: 1px solid rgba(148,163,184,.22) !important;
        border-radius: 12px !important;
        padding: 11px 13px !important;
        min-height: 42px !important;
        font-size: 12px !important;
      }

      #tab-scanner .candidates-grid {
        display: grid !important;
        grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)) !important;
        gap: 14px !important;
        align-items: stretch !important;
      }

      #tab-scanner .scanner-approved-card {
        position: relative;
        display: flex;
        flex-direction: column;
        min-width: 0;
        min-height: 342px;
        padding: 18px;
        border-radius: 16px;
        border: 1px solid rgba(88,166,255,.23);
        background:
          radial-gradient(circle at 85% 0%, rgba(88,166,255,.12), transparent 28%),
          linear-gradient(180deg, rgba(15,23,42,.85), rgba(8,13,24,.86));
        box-shadow: 0 18px 42px rgba(0,0,0,.22);
        overflow: hidden;
      }

      #tab-scanner .scanner-star {
        position: absolute;
        top: 14px;
        right: 16px;
        color: #facc15;
        font-size: 23px;
        line-height: 1;
      }

      #tab-scanner .scanner-card-pair {
        font-size: 24px;
        font-weight: 950;
        letter-spacing: -.04em;
        margin: 0 30px 8px 0;
      }

      #tab-scanner .scanner-dir {
        display: inline-flex;
        align-items: center;
        width: fit-content;
        border-radius: 8px;
        padding: 5px 10px;
        font-size: 13px;
        font-weight: 950;
        line-height: 1;
        text-transform: uppercase;
      }

      #tab-scanner .scanner-dir.buy { color: #4ade80; background: rgba(34,197,94,.20); border: 1px solid rgba(34,197,94,.35); }
      #tab-scanner .scanner-dir.sell { color: #fb7185; background: rgba(248,81,73,.20); border: 1px solid rgba(248,81,73,.35); }

      #tab-scanner .scanner-card-main {
        display: grid;
        grid-template-columns: .8fr 1fr;
        gap: 10px;
        align-items: end;
        margin: 12px 0 13px;
      }

      #tab-scanner .scanner-confidence strong {
        display: block;
        font-size: 28px;
        line-height: 1;
        font-weight: 950;
        color: var(--text);
      }

      #tab-scanner .scanner-confidence span,
      #tab-scanner .scanner-meta span,
      #tab-scanner .scanner-levels span {
        display: block;
        color: var(--muted);
        font-size: 11px;
      }

      #tab-scanner .scanner-meta {
        display: grid;
        gap: 4px;
        font-size: 12px;
      }

      #tab-scanner .scanner-meta strong { color: var(--text); font-weight: 750; }
      #tab-scanner .scanner-meta .up { color: #4ade80; font-size: 16px; }
      #tab-scanner .scanner-meta .down { color: #fb7185; font-size: 16px; }

      #tab-scanner .scanner-levels {
        display: grid;
        grid-template-columns: repeat(2, minmax(0,1fr));
        gap: 8px 10px;
        margin: 0 0 13px;
        padding: 10px 11px;
        border-radius: 11px;
        background: rgba(2,6,23,.32);
        border: 1px solid rgba(148,163,184,.17);
        font-size: 11px;
      }

      #tab-scanner .scanner-levels div {
        min-width: 0;
      }

      #tab-scanner .scanner-levels strong {
        display: block;
        color: var(--text);
        font-size: 12px;
        font-weight: 850;
        white-space: nowrap;
        overflow: visible;
        text-overflow: clip;
      }

      #tab-scanner .scanner-thesis {
        color: #b6c4d8;
        font-size: 12px;
        line-height: 1.55;
        margin: 0 0 14px;
        overflow-wrap: anywhere;
      }

      #tab-scanner .scanner-place-btn {
        margin-top: auto;
        width: 100%;
        min-height: 43px;
        border-radius: 11px;
        font-weight: 950;
      }

      #tab-scanner .rejected-list,
      #tab-scanner .no-setup-list {
        display: grid !important;
        grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)) !important;
        gap: 12px !important;
        align-items: stretch !important;
      }

      #tab-scanner .scanner-reject-card {
        position: relative;
        min-width: 0;
        min-height: 156px;
        padding: 15px 15px 14px;
        border-radius: 14px;
        border: 1px solid rgba(148,163,184,.20);
        background:
          radial-gradient(circle at 84% 18%, rgba(248,81,73,.08), transparent 24%),
          linear-gradient(180deg, rgba(15,23,42,.82), rgba(7,13,24,.82));
        overflow: hidden;
      }

      #tab-scanner .scanner-reject-x {
        position: absolute;
        top: 10px;
        right: 12px;
        width: 20px;
        height: 20px;
        display: grid;
        place-items: center;
        border-radius: 50%;
        border: 1px solid rgba(148,163,184,.35);
        color: var(--muted);
        font-size: 14px;
      }

      #tab-scanner .scanner-reject-top {
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 10px;
        padding-right: 22px;
        align-items: start;
      }

      #tab-scanner .scanner-reject-pair {
        font-size: 16px;
        font-weight: 950;
      }

      #tab-scanner .scanner-reject-score strong {
        display: block;
        font-size: 22px;
        line-height: 1;
      }

      #tab-scanner .scanner-reject-score span,
      #tab-scanner .scanner-reject-trend {
        display: block;
        color: var(--muted);
        font-size: 11px;
      }

      #tab-scanner .scanner-sparkline {
        width: 78px;
        height: 26px;
        opacity: .9;
      }

      #tab-scanner .scanner-reject-divider {
        height: 1px;
        margin: 10px 0 8px;
        background: linear-gradient(90deg, rgba(148,163,184,.22), transparent);
      }

      #tab-scanner .scanner-reason-label {
        color: #fb7185;
        font-size: 11px;
        font-weight: 950;
        margin-bottom: 4px;
      }

      #tab-scanner .scanner-reject-card p {
        margin: 0;
        color: #b6c4d8;
        font-size: 12px;
        line-height: 1.45;
        overflow-wrap: anywhere;
      }

      #tab-scanner .rejected-row,
      #tab-scanner .nosetup-row {
        display: block !important;
        min-height: auto !important;
        white-space: normal !important;
      }

      @media (max-width: 1180px) {
        #tab-scanner.active {
          grid-template-columns: 1fr !important;
          grid-template-areas:
            "scan"
            "approved"
            "history"
            "rejected"
            "nosetup" !important;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function installSectionChrome() {
    const tab = qs('tab-scanner');
    if (!tab) return;
    const cards = Array.from(tab.children).filter(el => el.classList?.contains('agent-card'));
    if (cards[0]) cards[0].classList.add('scanner-control-card');
    if (cards[cards.length - 1]) cards[cards.length - 1].classList.add('scanner-history-card');

    const candidateSection = qs('candidatesSection');
    const rejectedSection = qs('rejectedSection');
    const noSetupSection = qs('noSetupSection');
    if (candidateSection) candidateSection.classList.add('scanner-approved-section');
    if (rejectedSection) rejectedSection.classList.add('scanner-rejected-section');
    if (noSetupSection) noSetupSection.classList.add('scanner-nosetup-section');
    statusLine();
  }

  function setApprovedHeader() {
    const section = qs('candidatesSection');
    if (!section) return;
    const heading = section.querySelector('.section-heading');
    if (!heading) return;
    heading.innerHTML = `
      <div class="scanner-section-head">
        <div>
          <div class="scanner-section-title"><span class="scanner-section-icon scanner-icon-approved">✓</span>Approved Setups</div>
          <div class="scanner-section-sub">High-probability trade candidates approved by the AI model</div>
        </div>
        <button type="button" class="scanner-view-btn">View All Approved Setups</button>
      </div>
    `;
  }

  function setRejectedHeader(title, subtitle) {
    const section = title === 'No Setup Found' ? qs('noSetupSection') : qs('rejectedSection');
    if (!section) return;
    const heading = section.querySelector('.section-heading');
    if (!heading) return;
    heading.innerHTML = `
      <div class="scanner-section-head">
        <div>
          <div class="scanner-section-title"><span class="scanner-section-icon scanner-icon-rejected">×</span>${escapeHtml(title)}</div>
          <div class="scanner-section-sub">${escapeHtml(subtitle)}</div>
        </div>
        <button type="button" class="scanner-view-btn">View All ${escapeHtml(title)}</button>
      </div>
    `;
  }

  function approvedCard(item) {
    const pair = prettyPair(item.pair);
    const dir = direction(item);
    const conf = confidence(item);
    const tr = trend(item);
    const arrow = trendArrow(item);
    return `
      <article class="scanner-approved-card">
        <div class="scanner-star">☆</div>
        <h4 class="scanner-card-pair">${escapeHtml(pairId(pair))}</h4>
        <span class="scanner-dir ${dir}">${dir.toUpperCase()}</span>
        <div class="scanner-card-main">
          <div class="scanner-confidence"><strong>${escapeHtml(conf)}%</strong><span>Confidence</span></div>
          <div class="scanner-meta">
            <div><span>Trend</span><strong>${escapeHtml(tr)} <b class="${/down|bear|sell/i.test(tr) ? 'down' : 'up'}">${arrow}</b></strong></div>
            <div><span>Session</span><strong>${escapeHtml(session(item))}</strong></div>
          </div>
        </div>
        <div class="scanner-levels">
          <div><span>Entry</span><strong>${formatPrice(pair, item.entry)}</strong></div>
          <div><span>SL</span><strong>${formatPrice(pair, item.stop_loss)}</strong></div>
          <div><span>TP</span><strong>${formatPrice(pair, item.take_profit)}</strong></div>
          <div><span>RR</span><strong>${escapeHtml(rr(item))}</strong></div>
        </div>
        <p class="scanner-thesis">${escapeHtml(thesis(item))}</p>
        <button type="button" class="btn-primary scanner-place-btn" data-pair="${escapeHtml(item.pair || '')}">Place Paper Trade ›</button>
      </article>
    `;
  }

  function rejectCard(item, noSetup = false) {
    const pair = prettyPair(item.pair);
    const conf = confidence(item);
    const reason = noSetup ? `No clear setup. ${rejectionReason(item)}` : rejectionReason(item);
    const trendLabel = noSetup ? 'No setup' : (/trend/i.test(reason) ? 'Trend: Weak' : 'Trend: Sideways');
    return `
      <article class="scanner-reject-card">
        <span class="scanner-reject-x">×</span>
        <div class="scanner-reject-top">
          <div>
            <div class="scanner-reject-pair">${escapeHtml(pairId(pair))}</div>
            <div class="scanner-reject-score"><strong>${escapeHtml(conf)}%</strong><span>Confidence</span></div>
          </div>
          <div>
            <svg class="scanner-sparkline" viewBox="0 0 90 28" aria-hidden="true"><polyline points="2,12 12,18 22,10 33,15 43,12 54,19 65,14 77,17 88,13" fill="none" stroke="#f85149" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity=".9"/></svg>
            <span class="scanner-reject-trend">${escapeHtml(trendLabel)}</span>
          </div>
        </div>
        <div class="scanner-reject-divider"></div>
        <div class="scanner-reason-label">Reason</div>
        <p>${escapeHtml(reason)}</p>
      </article>
    `;
  }

  function wirePlaceButtons() {
    document.querySelectorAll('#candidatesList .scanner-place-btn').forEach(btn => {
      if (btn.dataset.wired) return;
      btn.dataset.wired = 'true';
      btn.addEventListener('click', () => {
        const pair = btn.dataset.pair;
        if (pair && typeof window.executeTrade === 'function') window.executeTrade(pair);
      });
    });
  }

  window.renderCandidates = function renderCandidatesPolished(candidates) {
    installStyles();
    installSectionChrome();
    setApprovedHeader();
    const el = qs('candidatesList');
    if (!el) return;
    if (!candidates || !candidates.length) {
      el.innerHTML = '<div class="muted small">No approved setups yet. Run a scan to find trade candidates.</div>';
      return;
    }
    el.innerHTML = candidates.map(approvedCard).join('');
    wirePlaceButtons();
  };

  window.renderRejected = function renderRejectedPolished(rejected) {
    installStyles();
    installSectionChrome();
    setRejectedHeader('Rejected Setups', 'Trade setups that did not meet the AI model\'s criteria');
    const el = qs('rejectedList');
    if (!el) return;
    if (!rejected || !rejected.length) {
      el.innerHTML = '<div class="muted small">No rejected setups from this scan.</div>';
      return;
    }
    el.innerHTML = rejected.map(item => rejectCard(item, false)).join('');
  };

  window.renderNoSetup = function renderNoSetupPolished(noSetup) {
    installStyles();
    installSectionChrome();
    setRejectedHeader('No Setup Found', 'Pairs with no clean pattern or structure right now');
    const el = qs('noSetupList');
    if (!el) return;
    if (!noSetup || !noSetup.length) {
      el.innerHTML = '<div class="muted small">No no-setup pairs from this scan.</div>';
      return;
    }
    el.innerHTML = noSetup.map(item => rejectCard(item, true)).join('');
  };

  function init() {
    installStyles();
    installSectionChrome();
    setApprovedHeader();
    setRejectedHeader('Rejected Setups', 'Trade setups that did not meet the AI model\'s criteria');
    setRejectedHeader('No Setup Found', 'Pairs with no clean pattern or structure right now');
    if (window.lastScanResults) {
      if (window.lastScanResults.candidates) window.renderCandidates(window.lastScanResults.candidates || []);
      if (window.lastScanResults.rejected) window.renderRejected(window.lastScanResults.rejected || []);
      if (window.lastScanResults.no_setup) window.renderNoSetup(window.lastScanResults.no_setup || []);
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
