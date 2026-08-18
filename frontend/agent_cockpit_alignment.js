/* agent_cockpit_alignment.js - fine-tune Trades cockpit layout */
'use strict';

(function () {
  if (window.__agentCockpitAlignmentInstalled) return;
  window.__agentCockpitAlignmentInstalled = true;

  function qs(id) { return document.getElementById(id); }

  function injectAlignmentStyles() {
    if (qs('agentCockpitAlignmentStyles')) return;
    const style = document.createElement('style');
    style.id = 'agentCockpitAlignmentStyles';
    style.textContent = `
      @media (min-width: 1181px) {
        #tab-trades #agentChartPanel #chartAccountPanel,
        #tab-trades #agentChartPanel #quickTradePanel {
          transform: translateY(-86px) !important;
        }

        #tab-trades #agentChartPanel .chart-workspace {
          gap: 12px !important;
        }
      }

      @media (max-width: 1180px) {
        #tab-trades #agentChartPanel #chartAccountPanel,
        #tab-trades #agentChartPanel #quickTradePanel {
          transform: none !important;
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
      }
    `;
    document.head.appendChild(style);
  }

  function alignCockpit() {
    injectAlignmentStyles();
    const panel = qs('agentChartPanel');
    const button = qs('chartSizeBtn');
    const autoButton = qs('chartAutoBtn');
    const toolbar = panel?.querySelector('.chart-toolbar');

    if (panel && button && autoButton && toolbar && button.parentElement !== toolbar) {
      autoButton.insertAdjacentElement('afterend', button);
    }
  }

  function start() {
    alignCockpit();
    const observer = new MutationObserver(alignCockpit);
    observer.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('resize', alignCockpit);
    setTimeout(alignCockpit, 150);
    setTimeout(alignCockpit, 600);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
