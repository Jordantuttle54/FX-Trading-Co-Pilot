/* agent_chart.js - clean live chart with account side panel */
'use strict';

(function () {
  const CHART_LIB_URL = 'https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js';
  const PAIRS = ['GBP/USD', 'EUR/USD', 'USD/JPY', 'EUR/GBP', 'GBP/JPY', 'XAU/USD'];
  const TIMEFRAMES = ['M1', 'M5', 'M15', 'H1', 'H4', 'D'];
  const TF_SECONDS = { M1: 60, M5: 300, M