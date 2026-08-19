/* agent_cockpit_alignment.js - fine-tune Trades cockpit layout */
'use strict';

(function () {
  if (window.__agentCockpitAlignmentInstalled) return;
  window.__agentCockpitAlignmentInstalled = true;

  function qs(id) { return document.getElementById(id); }

  function injectAlignmentStyles() {
    let style = qs('agentCockpitAlignmentStyles');
    if (!style) {
      style = document.createElement('style');
      style.id = 'agentCockpitAlignmentStyles';
      style.textContent = `
        @media (min-width: 1181px) {
          #tab-trades #agentChartPanel .chart-workspace {
            display: grid !important;
            grid-template-columns: minmax(0, 1.58fr) minmax(360px, .92fr) !important;
            grid-template-rows: auto auto !important;
            gap: 12px !important;
            align-items: start !important;
          }

          #tab-trades #agentChartPanel .chart-main-panel {
            grid-column: 1 !important;
            grid-row: 1 / span 2 !important;
            min-width: 0 !important;
            align-self: start !important;
          }

          #tab-trades #agentChartPanel #quickTradePanel {
            grid-column: 2 !important;
            grid-row: 1 !important;
            align-self: start !important;
            position: static !important;
            transform: none !important;
            margin: 0 !important;
            width: 100% !important;
            min-width: 0 !important;
          }

          #tab-trades #agentChartPanel #chartAccountPanel {
            grid-column: 2 !important;
            grid-row: 2 !important;
            align-self: start !important;
            position: static !important;
            transform: none !important;
            margin: 0 !important;
            width: 100% !important;
            min-width: 0 !important;
          }
        }

        @media (max-width: 1180px) {
          #tab-trades #agentChartPanel .chart-main-panel,
          #tab-trades #agentChartPanel #quickTradePanel,
          #tab-trades #agentChartPanel #chartAccountPanel {
            grid-column: 1 !important;
            grid-row: auto !important;
            position: static !important;
            transform: none !important;
            width: 100% !important;
          }
        }

        #tab-trades #agentChartPanel .chart-head-row #chartSizeBtn {
          display: none !important;
        }

        #tab-trades #agentChartPanel .chart-toolbar #chartSizeBtn {
          display: inline-flex !important;
          align-items: center;
          justify-content: center;
          white-space: nowrap;
          height: 34px !important;
          min-height: 34px !important;
        }
      `;
    }

    // Keep this style block last so it overrides older compact/right-rail rules.
    document.head.appendChild(style);
  }

  function alignCockpit() {
    injectAlignmentStyles();
    const panel = qs('agentChartPanel');
    const button = qs('chartSizeBtn');
    const autoButton = qs('chartAutoBtn');
    const toolbar = panel?.querySelector('.chart-toolbar');
    const quickPanel = qs('quickTradePanel');
    const accountPanel = qs('chartAccountPanel');

    if (panel && button && autoButton && toolbar && button.parentElement !== toolbar) {
      autoButton.insertAdjacentElement('afterend', button);
    }

    if (quickPanel && accountPanel && quickPanel.nextElementSibling !== accountPanel) {
      quickPanel.insertAdjacentElement('afterend', accountPanel);
    }
  }

  function start() {
    alignCockpit();
    const observer = new MutationObserver(alignCockpit);
    observer.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('resize', alignCockpit);
    setTimeout(alignCockpit, 150);
    setTimeout(alignCockpit, 600);
    setTimeout(alignCockpit, 1200);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
