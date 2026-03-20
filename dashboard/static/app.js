/* ============================================
   LiteLLM Dashboard — App Logic
   ============================================ */

(function () {
  'use strict';

  // ── Constants ──────────────────────────────────────────
  const REFRESH_INTERVAL = 60; // seconds
  const AGENT_COLORS = {
    NanoSE: '#22c55e',
    NanoBa: '#3b82f6',
    NanoPAW: '#f59e0b',
    unknown: '#6b7280',
  };
  const CHART_INPUT_COLOR = 'rgba(99, 102, 241, 0.8)';
  const CHART_INPUT_BORDER = '#6366f1';
  const CHART_OUTPUT_COLOR = 'rgba(167, 139, 250, 0.8)';
  const CHART_OUTPUT_BORDER = '#a78bfa';
  const CHART_LATENCY_COLOR = 'rgba(251, 191, 36, 0.8)';
  const CHART_LATENCY_BORDER = '#fbbf24';
  const CHART_REQUESTS_COLOR = 'rgba(34, 197, 94, 0.8)';
  const CHART_REQUESTS_BORDER = '#22c55e';
  const CHART_CUMULATIVE_COLOR = 'rgba(99, 102, 241, 0.8)';
  const CHART_CUMULATIVE_BORDER = '#6366f1';
  const CHART_COST_COLOR = 'rgba(16, 185, 129, 0.8)';
  const CHART_COST_BORDER = '#10b981';

  const MODEL_COLORS = {};
  function getModelColor(name) {
    const lower = (name || '').toLowerCase();
    if (lower.includes('opus')) return '#a78bfa';
    if (lower.includes('sonnet')) return '#818cf8';
    if (lower.includes('haiku')) return '#2dd4bf';
    return '#6b7280';
  }

  // ── State ──────────────────────────────────────────────
  let countdown = REFRESH_INTERVAL;
  let countdownTimer = null;
  let refreshTimer = null;
  let barChart = null;
  let donutChart = null;
  let latencyChart = null;
  let requestsChart = null;
  let modelDonutChart = null;
  let ioRatioChart = null;
  let cumulativeChart = null;
  let currentRange = '24h';
  let activeAgentFilter = null;
  let cachedTimeSeriesData = null;
  let cachedModelData = null;
  let costChart = null;
  let costModelDonutChart = null;
  let costAgentDonutChart = null;
  let cachedCostModelData = null;
  let cachedCostAgentData = null;

  // ── DOM References ─────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const dom = {
    countdown: $('#countdown'),
    btnRefresh: $('#btnRefresh'),
    filterBanner: $('#filterBanner'),
    filterAgentName: $('#filterAgentName'),
    btnClearFilter: $('#btnClearFilter'),
    totalTokens: $('#totalTokens'),
    totalInput: $('#totalInput'),
    totalOutput: $('#totalOutput'),
    requestsToday: $('#requestsToday'),
    topAgent: $('#topAgent'),
    topAgentTokens: $('#topAgentTokens'),
    topModel: $('#topModel'),
    topModelTokens: $('#topModelTokens'),
    barChartCanvas: $('#barChart'),
    donutChartCanvas: $('#donutChart'),
    barChartLoading: $('#barChartLoading'),
    donutChartLoading: $('#donutChartLoading'),
    donutLegend: $('#donutLegend'),
    modelTableBody: $('#modelTableBody'),
    alltimeTokens: $('#alltimeTokens'),
    alltimeInput: $('#alltimeInput'),
    alltimeOutput: $('#alltimeOutput'),
    alltimeRequests: $('#alltimeRequests'),
    alltimeLatency: $('#alltimeLatency'),
    alltimeSince: $('#alltimeSince'),
    latencyChartCanvas: $('#latencyChart'),
    requestsChartCanvas: $('#requestsChart'),
    modelDonutChartCanvas: $('#modelDonutChart'),
    modelDonutLegend: $('#modelDonutLegend'),
    ioRatioChartCanvas: $('#ioRatioChart'),
    cumulativeChartCanvas: $('#cumulativeChart'),
    timeToggle: $('#timeToggle'),
    errorToast: $('#errorToast'),
    errorMessage: $('#errorMessage'),
    btnDismissError: $('#btnDismissError'),
    costToday: $('#costToday'),
    costTodayInput: $('#costTodayInput'),
    costTodayOutput: $('#costTodayOutput'),
    costAlltime: $('#costAlltime'),
    costAlltimeInput: $('#costAlltimeInput'),
    costAlltimeOutput: $('#costAlltimeOutput'),
    costChartCanvas: $('#costChart'),
    costModelDonutCanvas: $('#costModelDonutChart'),
    costModelDonutLegend: $('#costModelDonutLegend'),
    costAgentDonutCanvas: $('#costAgentDonutChart'),
    costAgentDonutLegend: $('#costAgentDonutLegend'),
  };

  // ── Number Formatting ──────────────────────────────────
  function formatNumber(n) {
    if (n == null) return '—';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 10_000) return (n / 1_000).toFixed(1) + 'K';
    return n.toLocaleString('en-US');
  }

  function formatNumberFull(n) {
    if (n == null) return '—';
    return n.toLocaleString('en-US');
  }

  function formatCost(n) {
    if (n == null || n === 0) return '$0.00';
    if (n < 0.01) return '<$0.01';
    return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // ── API Fetching ───────────────────────────────────────
  async function apiFetch(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`API ${path} returned ${res.status}`);
    return res.json();
  }

  // ── Error Handling ─────────────────────────────────────
  let errorTimeout = null;
  function showError(msg) {
    dom.errorMessage.textContent = msg || 'Failed to load data. Retrying...';
    dom.errorToast.classList.add('visible');
    clearTimeout(errorTimeout);
    errorTimeout = setTimeout(() => {
      dom.errorToast.classList.remove('visible');
    }, 6000);
  }

  function hideError() {
    dom.errorToast.classList.remove('visible');
    clearTimeout(errorTimeout);
  }

  // ── Summary Cards ──────────────────────────────────────
  async function loadSummary() {
    try {
      const data = await apiFetch('/api/summary');
      dom.totalTokens.textContent = formatNumber(data.total_tokens_today);
      dom.totalInput.textContent = formatNumber(data.total_input_today);
      dom.totalOutput.textContent = formatNumber(data.total_output_today);
      dom.requestsToday.textContent = formatNumberFull(data.requests_today);

      if (data.top_agent) {
        dom.topAgent.textContent = data.top_agent.name || '—';
        dom.topAgentTokens.textContent = formatNumber(data.top_agent.tokens) + ' tokens';
      } else {
        dom.topAgent.textContent = '—';
        dom.topAgentTokens.textContent = '';
      }

      if (data.top_model) {
        dom.topModel.textContent = data.top_model.name || '—';
        dom.topModelTokens.textContent = formatNumber(data.top_model.tokens) + ' tokens';
      } else {
        dom.topModel.textContent = '—';
        dom.topModelTokens.textContent = '';
      }
    } catch (err) {
      console.error('Summary fetch error:', err);
      showError('Failed to load summary data');
    }
  }

  function getRangeConfig(range) {
    switch (range) {
      case '24h': return { endpoint: '/api/hourly', param: 'days=1', mode: 'hourly' };
      case '7d':  return { endpoint: '/api/daily',  param: 'days=7',  mode: 'daily' };
      case '30d': return { endpoint: '/api/daily',  param: 'days=30', mode: 'daily' };
      case 'all': return { endpoint: '/api/daily',  param: 'days=9999', mode: 'daily' };
      default:    return { endpoint: '/api/hourly', param: 'days=1', mode: 'hourly' };
    }
  }

  async function loadAllTimeSummary() {
    try {
      const data = await apiFetch('/api/alltime');
      dom.alltimeTokens.textContent = formatNumber(data.total_tokens);
      dom.alltimeInput.textContent = formatNumber(data.total_input);
      dom.alltimeOutput.textContent = formatNumber(data.total_output);
      dom.alltimeRequests.textContent = formatNumberFull(data.total_requests);
      const avgMs = data.avg_duration_ms;
      dom.alltimeLatency.textContent = avgMs != null ? (avgMs / 1000).toFixed(1) + 's' : '—';
      if (data.first_seen) {
        const d = new Date(data.first_seen);
        dom.alltimeSince.textContent = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      } else {
        dom.alltimeSince.textContent = '—';
      }
    } catch (err) {
      console.error('Alltime fetch error:', err);
    }
  }

  async function loadCostSummary() {
    try {
      const data = await apiFetch('/api/cost/summary');
      dom.costToday.textContent = formatCost(data.today_cost);
      dom.costTodayInput.textContent = formatCost(data.today_input_cost);
      dom.costTodayOutput.textContent = formatCost(data.today_output_cost);
      dom.costAlltime.textContent = formatCost(data.alltime_cost);
      dom.costAlltimeInput.textContent = formatCost(data.alltime_input_cost);
      dom.costAlltimeOutput.textContent = formatCost(data.alltime_output_cost);
    } catch (err) {
      console.error('Cost summary fetch error:', err);
    }
  }

  async function loadTimeSeriesData() {
    const config = getRangeConfig(currentRange);
    const agentParam = activeAgentFilter ? '&agent=' + encodeURIComponent(activeAgentFilter) : '';
    const data = await apiFetch(config.endpoint + '?' + config.param + agentParam);
    cachedTimeSeriesData = data.data || [];
    return cachedTimeSeriesData;
  }

  async function fetchModelData() {
    var data = await apiFetch('/api/models');
    cachedModelData = data.models || [];
    return cachedModelData;
  }
  function getBarChartConfig(labels, inputData, outputData, mode) {
    return {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Input Tokens',
            data: inputData,
            backgroundColor: CHART_INPUT_COLOR,
            borderColor: CHART_INPUT_BORDER,
            borderWidth: 1,
            borderRadius: 4,
            borderSkipped: false,
          },
          {
            label: 'Output Tokens',
            data: outputData,
            backgroundColor: CHART_OUTPUT_COLOR,
            borderColor: CHART_OUTPUT_BORDER,
            borderWidth: 1,
            borderRadius: 4,
            borderSkipped: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            align: 'end',
            labels: {
              color: 'rgba(255,255,255,0.6)',
              font: { family: 'Inter', size: 11 },
              boxWidth: 12,
              boxHeight: 12,
              borderRadius: 3,
              useBorderRadius: true,
              padding: 16,
            },
          },
          tooltip: {
            backgroundColor: 'rgba(10, 10, 26, 0.9)',
            titleColor: '#f1f5f9',
            bodyColor: '#94a3b8',
            borderColor: 'rgba(255,255,255,0.1)',
            borderWidth: 1,
            cornerRadius: 8,
            padding: 10,
            titleFont: { family: 'Inter', weight: '600' },
            bodyFont: { family: 'Inter' },
            callbacks: {
              label: function (ctx) {
                return ctx.dataset.label + ': ' + formatNumberFull(ctx.parsed.y);
              },
            },
          },
        },
        scales: {
          x: {
            stacked: true,
            grid: {
              color: 'rgba(255,255,255,0.04)',
              drawBorder: false,
            },
            ticks: {
              color: 'rgba(255,255,255,0.4)',
              font: { family: 'Inter', size: 10 },
              maxRotation: 45,
              autoSkip: true,
              maxTicksLimit: mode === 'hourly' ? 12 : 15,
            },
            border: { display: false },
          },
          y: {
            stacked: true,
            grid: {
              color: 'rgba(255,255,255,0.04)',
              drawBorder: false,
            },
            ticks: {
              color: 'rgba(255,255,255,0.4)',
              font: { family: 'Inter', size: 10 },
              callback: function (val) {
                return formatNumber(val);
              },
            },
            border: { display: false },
          },
        },
      },
    };
  }

  function formatBarLabel(raw, mode) {
    if (mode === 'hourly') {
      const d = new Date(raw);
      return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    }
    const d = new Date(raw);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function renderBarChart() {
    dom.barChartLoading.classList.add('visible');
    try {
      const items = cachedTimeSeriesData || [];
      const mode = getRangeConfig(currentRange).mode;

      const labels = items.map((d) =>
        formatBarLabel(d.hour || d.date, mode)
      );
      const inputData = items.map((d) => d.input_tokens || 0);
      const outputData = items.map((d) => d.output_tokens || 0);

      if (barChart) {
        barChart.data.labels = labels;
        barChart.data.datasets[0].data = inputData;
        barChart.data.datasets[1].data = outputData;
        barChart.options.scales.x.ticks.maxTicksLimit = mode === 'hourly' ? 12 : 15;
        barChart.update('none');
      } else {
        const ctx = dom.barChartCanvas.getContext('2d');
        barChart = new Chart(ctx, getBarChartConfig(labels, inputData, outputData, mode));
      }
    } catch (err) {
      console.error('Bar chart render error:', err);
      showError('Failed to load usage chart');
    } finally {
      dom.barChartLoading.classList.remove('visible');
    }
  }

  // ── Donut Chart (Agents) ───────────────────────────────
  function getAgentColor(name) {
    return AGENT_COLORS[name] || AGENT_COLORS.unknown;
  }

  async function loadDonutChart() {
    dom.donutChartLoading.classList.add('visible');
    try {
      const data = await apiFetch('/api/agents');
      const agents = data.agents || [];

      const labels = agents.map((a) => a.agent);
      const values = agents.map((a) => a.total_tokens);
      const colors = agents.map((a) => getAgentColor(a.agent));

      if (donutChart) {
        donutChart.data.labels = labels;
        donutChart.data.datasets[0].data = values;
        donutChart.data.datasets[0].backgroundColor = colors;
        donutChart.data.datasets[0].borderColor = colors.map((c) => c);
        donutChart.update('none');
      } else {
        const ctx = dom.donutChartCanvas.getContext('2d');
        donutChart = new Chart(ctx, {
          type: 'doughnut',
          data: {
            labels: labels,
            datasets: [
              {
                data: values,
                backgroundColor: colors,
                borderColor: colors,
                borderWidth: 2,
                hoverBorderColor: '#fff',
                hoverBorderWidth: 2,
                spacing: 2,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
              legend: { display: false },
              tooltip: {
                backgroundColor: 'rgba(10, 10, 26, 0.9)',
                titleColor: '#f1f5f9',
                bodyColor: '#94a3b8',
                borderColor: 'rgba(255,255,255,0.1)',
                borderWidth: 1,
                cornerRadius: 8,
                padding: 10,
                titleFont: { family: 'Inter', weight: '600' },
                bodyFont: { family: 'Inter' },
                callbacks: {
                  label: function (ctx) {
                    const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                    const pct = total > 0 ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                    return ctx.label + ': ' + formatNumber(ctx.parsed) + ' (' + pct + '%)';
                  },
                },
              },
            },
            onClick: function (_evt, elements) {
              if (elements.length > 0) {
                const idx = elements[0].index;
                const agentName = labels[idx];
                setAgentFilter(agentName);
              }
            },
          },
        });
      }

      // Build custom legend
      buildDonutLegend(agents);
    } catch (err) {
      console.error('Donut chart fetch error:', err);
      showError('Failed to load agent breakdown');
    } finally {
      dom.donutChartLoading.classList.remove('visible');
    }
  }

  function buildDonutLegend(agents) {
    const costMap = {};
    if (cachedCostAgentData) {
      cachedCostAgentData.forEach(function (a) { costMap[a.agent] = a.cost; });
    }
    dom.donutLegend.innerHTML = '';
    agents.forEach((a) => {
      const cost = costMap[a.agent];
      const costStr = cost ? ' · ' + formatCost(cost) : '';
      const item = document.createElement('div');
      item.className = 'legend-item';
      item.innerHTML =
        '<span class="legend-dot" style="background:' +
        getAgentColor(a.agent) +
        '"></span>' +
        '<span>' + escapeHtml(a.agent) + '</span>' +
        '<span style="color:var(--text-muted);margin-left:2px">' + formatNumber(a.total_tokens) + costStr + '</span>';
      item.addEventListener('click', () => setAgentFilter(a.agent));
      dom.donutLegend.appendChild(item);
    });
  }

  // ── Agent Filter ───────────────────────────────────────
  function setAgentFilter(agentName) {
    activeAgentFilter = agentName;
    dom.filterAgentName.textContent = agentName;
    dom.filterBanner.classList.add('visible');
    refreshTimeSeries();
  }

  function clearAgentFilter() {
    activeAgentFilter = null;
    dom.filterBanner.classList.remove('visible');
    refreshTimeSeries();
  }

  async function refreshTimeSeries() {
    await loadTimeSeriesData();
    renderBarChart();
    renderRequestsChart();
    loadLatencyChart();
    loadCumulativeChart();
    loadCostChart();
  }

  // ── Model Table ────────────────────────────────────────
  function renderModelTable() {
    try {
      const models = cachedModelData || [];
      const costMap = {};
      if (cachedCostModelData) {
        cachedCostModelData.forEach(function (m) { costMap[m.model] = m.cost; });
      }

      if (models.length === 0) {
        dom.modelTableBody.innerHTML =
          '<tr><td colspan="6"><div class="empty-state">' +
          '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">' +
          '<path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>' +
          '</svg><span>No model data available</span></div></td></tr>';
        return;
      }

      dom.modelTableBody.innerHTML = models
        .map(
          (m) =>
            '<tr>' +
            '<td><span class="model-name"><span class="model-badge">' +
            escapeHtml(getModelShortName(m.model)) +
            '</span> ' +
            escapeHtml(m.model) +
            '</span></td>' +
            '<td>' + formatNumberFull(m.input_tokens) + '</td>' +
            '<td>' + formatNumberFull(m.output_tokens) + '</td>' +
            '<td><strong>' + formatNumberFull(m.total_tokens) + '</strong></td>' +
            '<td>' + formatCost(costMap[m.model] || 0) + '</td>' +
            '<td>' + formatNumberFull(m.requests) + '</td>' +
            '</tr>'
        )
        .join('');
    } catch (err) {
      console.error('Model table fetch error:', err);
      showError('Failed to load model data');
    }
  }

  function getModelShortName(name) {
    if (!name) return '?';
    // Extract provider hint: "claude-..." → "CL", "gpt-..." → "GP", etc.
    const lower = name.toLowerCase();
    if (lower.startsWith('claude')) return 'CL';
    if (lower.startsWith('gpt')) return 'GP';
    if (lower.startsWith('gemini')) return 'GE';
    if (lower.startsWith('mistral')) return 'MI';
    if (lower.startsWith('llama')) return 'LL';
    if (lower.startsWith('command')) return 'CO';
    return name.substring(0, 2).toUpperCase();
  }

  function getCommonTooltipConfig() {
    return {
      backgroundColor: 'rgba(10, 10, 26, 0.9)',
      titleColor: '#f1f5f9',
      bodyColor: '#94a3b8',
      borderColor: 'rgba(255,255,255,0.1)',
      borderWidth: 1,
      cornerRadius: 8,
      padding: 10,
      titleFont: { family: 'Inter', weight: '600' },
      bodyFont: { family: 'Inter' },
    };
  }

  function getCommonGridConfig() {
    return {
      color: 'rgba(255,255,255,0.04)',
      drawBorder: false,
    };
  }

  function getCommonTickConfig() {
    return {
      color: 'rgba(255,255,255,0.4)',
      font: { family: 'Inter', size: 10 },
    };
  }

  function renderRequestsChart() {
    try {
      const items = cachedTimeSeriesData || [];
      const mode = getRangeConfig(currentRange).mode;

      const labels = items.map((d) => formatBarLabel(d.hour || d.date, mode));
      const reqData = items.map((d) => d.requests || 0);

      const canvas = dom.requestsChartCanvas;
      if (requestsChart) {
        requestsChart.data.labels = labels;
        requestsChart.data.datasets[0].data = reqData;
        requestsChart.update('none');
      } else {
        const ctx = canvas.getContext('2d');
        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 280);
        gradient.addColorStop(0, 'rgba(34, 197, 94, 0.15)');
        gradient.addColorStop(1, 'rgba(34, 197, 94, 0.01)');

        requestsChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [{
              label: 'Requests',
              data: reqData,
              borderColor: CHART_REQUESTS_BORDER,
              backgroundColor: gradient,
              borderWidth: 2,
              fill: true,
              tension: 0.3,
              pointRadius: 3,
              pointHoverRadius: 5,
              pointBackgroundColor: CHART_REQUESTS_BORDER,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              legend: { display: false },
              tooltip: Object.assign({}, getCommonTooltipConfig(), {
                callbacks: {
                  label: function (ctx) {
                    return 'Requests: ' + formatNumberFull(ctx.parsed.y);
                  },
                },
              }),
            },
            scales: {
              x: {
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), { maxRotation: 45, autoSkip: true, maxTicksLimit: 15 }),
                border: { display: false },
              },
              y: {
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), {
                  callback: function (val) { return Number.isInteger(val) ? val : ''; },
                }),
                border: { display: false },
              },
            },
          },
        });
      }
    } catch (err) {
      console.error('Requests chart render error:', err);
    }
  }

  async function loadLatencyChart() {
    try {
      const config = getRangeConfig(currentRange);
      const agentParam = activeAgentFilter ? '&agent=' + encodeURIComponent(activeAgentFilter) : '';
      const data = await apiFetch('/api/latency?' + config.param + agentParam);
      const items = data.data || [];

      const labels = items.map((d) => formatBarLabel(d.hour || d.date, config.mode));
      const latencyData = items.map((d) => d.avg_duration_ms || 0);

      if (latencyChart) {
        latencyChart.data.labels = labels;
        latencyChart.data.datasets[0].data = latencyData;
        latencyChart.update('none');
      } else {
        const ctx = dom.latencyChartCanvas.getContext('2d');
        latencyChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [{
              label: 'Avg Latency',
              data: latencyData,
              borderColor: CHART_LATENCY_BORDER,
              backgroundColor: CHART_LATENCY_COLOR,
              borderWidth: 2,
              fill: false,
              tension: 0.3,
              pointRadius: 3,
              pointHoverRadius: 5,
              pointBackgroundColor: CHART_LATENCY_BORDER,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              legend: { display: false },
              tooltip: Object.assign({}, getCommonTooltipConfig(), {
                callbacks: {
                  label: function (ctx) {
                    const item = items[ctx.dataIndex];
                    const reqCount = item ? (item.requests || 0) : 0;
                    return 'Latency: ' + ctx.parsed.y.toFixed(0) + 'ms (' + reqCount + ' reqs)';
                  },
                },
              }),
            },
            scales: {
              x: {
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), { maxRotation: 45, autoSkip: true, maxTicksLimit: 15 }),
                border: { display: false },
              },
              y: {
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), {
                  callback: function (val) { return val + 'ms'; },
                }),
                border: { display: false },
              },
            },
          },
        });
      }
    } catch (err) {
      console.error('Latency chart fetch error:', err);
    }
  }

  function renderModelDonutChart() {
    try {
      const models = cachedModelData || [];
      if (models.length === 0) return;

      const labels = models.map((m) => m.model);
      const values = models.map((m) => m.total_tokens);
      const colors = models.map((m) => getModelColor(m.model));

      if (modelDonutChart) {
        modelDonutChart.data.labels = labels;
        modelDonutChart.data.datasets[0].data = values;
        modelDonutChart.data.datasets[0].backgroundColor = colors;
        modelDonutChart.data.datasets[0].borderColor = colors.map((c) => c);
        modelDonutChart.update('none');
      } else {
        const ctx = dom.modelDonutChartCanvas.getContext('2d');
        modelDonutChart = new Chart(ctx, {
          type: 'doughnut',
          data: {
            labels: labels,
            datasets: [{
              data: values,
              backgroundColor: colors,
              borderColor: colors,
              borderWidth: 2,
              hoverBorderColor: '#fff',
              hoverBorderWidth: 2,
              spacing: 2,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
              legend: { display: false },
              tooltip: Object.assign({}, getCommonTooltipConfig(), {
                callbacks: {
                  label: function (ctx) {
                    const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                    const pct = total > 0 ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                    return ctx.label + ': ' + formatNumber(ctx.parsed) + ' (' + pct + '%)';
                  },
                },
              }),
            },
          },
        });
      }

      buildModelDonutLegend(models);
    } catch (err) {
      console.error('Model donut chart render error:', err);
    }
  }

  function buildModelDonutLegend(models) {
    dom.modelDonutLegend.innerHTML = '';
    models.forEach((m) => {
      const item = document.createElement('div');
      item.className = 'legend-item';
      item.innerHTML =
        '<span class="legend-dot" style="background:' +
        getModelColor(m.model) +
        '"></span>' +
        '<span>' + escapeHtml(m.model) + '</span>' +
        '<span style="color:var(--text-muted);margin-left:2px">' + formatNumber(m.total_tokens) + '</span>';
      dom.modelDonutLegend.appendChild(item);
    });
  }

  function renderIORatioChart() {
    try {
      const models = cachedModelData || [];
      if (models.length === 0) return;

      const sorted = models.slice().sort((a, b) => (b.total_tokens || 0) - (a.total_tokens || 0));
      const labels = sorted.map((m) => m.model.length > 30 ? m.model.substring(0, 27) + '...' : m.model);
      const inputData = sorted.map((m) => m.input_tokens || 0);
      const outputData = sorted.map((m) => m.output_tokens || 0);

      if (ioRatioChart) {
        ioRatioChart.data.labels = labels;
        ioRatioChart.data.datasets[0].data = inputData;
        ioRatioChart.data.datasets[1].data = outputData;
        ioRatioChart.update('none');
      } else {
        const ctx = dom.ioRatioChartCanvas.getContext('2d');
        ioRatioChart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: labels,
            datasets: [
              {
                label: 'Input Tokens',
                data: inputData,
                backgroundColor: '#6366f1',
                borderRadius: 4,
                borderSkipped: false,
              },
              {
                label: 'Output Tokens',
                data: outputData,
                backgroundColor: '#a78bfa',
                borderRadius: 4,
                borderSkipped: false,
              },
            ],
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              legend: {
                display: true,
                position: 'top',
                align: 'end',
                labels: {
                  color: 'rgba(255,255,255,0.6)',
                  font: { family: 'Inter', size: 11 },
                  boxWidth: 12,
                  boxHeight: 12,
                  borderRadius: 3,
                  useBorderRadius: true,
                  padding: 16,
                },
              },
              tooltip: Object.assign({}, getCommonTooltipConfig(), {
                callbacks: {
                  label: function (ctx) {
                    return ctx.dataset.label + ': ' + formatNumberFull(ctx.parsed.x);
                  },
                },
              }),
            },
            scales: {
              x: {
                stacked: true,
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), {
                  callback: function (val) { return formatNumber(val); },
                }),
                border: { display: false },
              },
              y: {
                stacked: true,
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), { font: { family: 'Inter', size: 9 } }),
                border: { display: false },
              },
            },
          },
        });
      }
    } catch (err) {
      console.error('IO ratio chart render error:', err);
    }
  }

  async function loadCumulativeChart() {
    try {
      const config = getRangeConfig(currentRange);
      const agentParam = activeAgentFilter ? '&agent=' + encodeURIComponent(activeAgentFilter) : '';
      const data = await apiFetch('/api/cumulative?' + config.param + agentParam);
      const items = data.data || [];

      const labels = items.map((d) => formatBarLabel(d.date || d.hour, config.mode));
      const cumData = items.map((d) => d.cumulative_tokens || 0);

      const canvas = dom.cumulativeChartCanvas;
      if (cumulativeChart) {
        cumulativeChart.data.labels = labels;
        cumulativeChart.data.datasets[0].data = cumData;
        cumulativeChart.update('none');
      } else {
        const ctx = canvas.getContext('2d');
        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 240);
        gradient.addColorStop(0, 'rgba(99, 102, 241, 0.3)');
        gradient.addColorStop(1, 'rgba(99, 102, 241, 0.02)');

        cumulativeChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [{
              label: 'Cumulative Tokens',
              data: cumData,
              borderColor: CHART_CUMULATIVE_BORDER,
              backgroundColor: gradient,
              borderWidth: 2,
              fill: true,
              tension: 0.3,
              pointRadius: 2,
              pointHoverRadius: 5,
              pointBackgroundColor: CHART_CUMULATIVE_BORDER,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              legend: { display: false },
              tooltip: Object.assign({}, getCommonTooltipConfig(), {
                callbacks: {
                  label: function (ctx) {
                    return 'Total: ' + formatNumber(ctx.parsed.y);
                  },
                },
              }),
            },
            scales: {
              x: {
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), { maxRotation: 45, autoSkip: true, maxTicksLimit: 15 }),
                border: { display: false },
              },
              y: {
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), {
                  callback: function (val) { return formatNumber(val); },
                }),
                border: { display: false },
              },
            },
          },
        });
      }
    } catch (err) {
      console.error('Cumulative chart fetch error:', err);
    }
  }

  async function loadCostChart() {
    try {
      const config = getRangeConfig(currentRange);
      const data = await apiFetch('/api/cost/daily?' + config.param);
      const items = data.data || [];

      const labels = items.map(function (d) { return formatBarLabel(d.hour || d.date, config.mode); });
      const costData = items.map(function (d) { return d.cost || 0; });

      const canvas = dom.costChartCanvas;
      if (costChart) {
        costChart.data.labels = labels;
        costChart.data.datasets[0].data = costData;
        costChart.update('none');
      } else {
        const ctx = canvas.getContext('2d');
        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 240);
        gradient.addColorStop(0, 'rgba(16, 185, 129, 0.2)');
        gradient.addColorStop(1, 'rgba(16, 185, 129, 0.01)');

        costChart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: labels,
            datasets: [{
              label: 'Cost',
              data: costData,
              backgroundColor: CHART_COST_COLOR,
              borderColor: CHART_COST_BORDER,
              borderWidth: 1,
              borderRadius: 4,
              borderSkipped: false,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              legend: { display: false },
              tooltip: Object.assign({}, getCommonTooltipConfig(), {
                callbacks: {
                  label: function (ctx) {
                    var item = items[ctx.dataIndex];
                    return [
                      'Total: ' + formatCost(ctx.parsed.y),
                      'Input: ' + formatCost(item ? item.input_cost : 0),
                      'Output: ' + formatCost(item ? item.output_cost : 0),
                    ];
                  },
                },
              }),
            },
            scales: {
              x: {
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), { maxRotation: 45, autoSkip: true, maxTicksLimit: 15 }),
                border: { display: false },
              },
              y: {
                grid: getCommonGridConfig(),
                ticks: Object.assign({}, getCommonTickConfig(), {
                  callback: function (val) { return '$' + val.toFixed(2); },
                }),
                border: { display: false },
              },
            },
          },
        });
      }
    } catch (err) {
      console.error('Cost chart fetch error:', err);
    }
  }

  async function loadCostModelDonut() {
    try {
      const data = await apiFetch('/api/cost/models');
      cachedCostModelData = data.models || [];
      const models = cachedCostModelData.filter(function (m) { return m.cost > 0; });
      if (models.length === 0) return;

      const labels = models.map(function (m) { return m.model; });
      const values = models.map(function (m) { return m.cost; });
      const colors = models.map(function (m) { return getModelColor(m.model); });

      if (costModelDonutChart) {
        costModelDonutChart.data.labels = labels;
        costModelDonutChart.data.datasets[0].data = values;
        costModelDonutChart.data.datasets[0].backgroundColor = colors;
        costModelDonutChart.data.datasets[0].borderColor = colors;
        costModelDonutChart.update('none');
      } else {
        const ctx = dom.costModelDonutCanvas.getContext('2d');
        costModelDonutChart = new Chart(ctx, {
          type: 'doughnut',
          data: {
            labels: labels,
            datasets: [{
              data: values,
              backgroundColor: colors,
              borderColor: colors,
              borderWidth: 2,
              hoverBorderColor: '#fff',
              hoverBorderWidth: 2,
              spacing: 2,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
              legend: { display: false },
              tooltip: Object.assign({}, getCommonTooltipConfig(), {
                callbacks: {
                  label: function (tooltipCtx) {
                    const total = tooltipCtx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                    const pct = total > 0 ? ((tooltipCtx.parsed / total) * 100).toFixed(1) : 0;
                    return tooltipCtx.label + ': ' + formatCost(tooltipCtx.parsed) + ' (' + pct + '%)';
                  },
                },
              }),
            },
          },
        });
      }

      const legendEl = dom.costModelDonutLegend;
      legendEl.innerHTML = '';
      models.forEach(function (m) {
        const item = document.createElement('div');
        item.className = 'legend-item';
        item.innerHTML = '<span class="legend-dot" style="background:' + getModelColor(m.model) + '"></span>' +
          '<span>' + escapeHtml(m.model) + '</span>' +
          '<span style="color:var(--text-muted);margin-left:2px">' + formatCost(m.cost) + '</span>';
        legendEl.appendChild(item);
      });
    } catch (err) {
      console.error('Cost model donut error:', err);
    }
  }

  async function loadCostAgentDonut() {
    try {
      const data = await apiFetch('/api/cost/agents');
      cachedCostAgentData = data.agents || [];
      const agents = cachedCostAgentData.filter(function (a) { return a.cost > 0; });
      if (agents.length === 0) return;

      const labels = agents.map(function (a) { return a.agent; });
      const values = agents.map(function (a) { return a.cost; });
      const colors = agents.map(function (a) { return getAgentColor(a.agent); });

      if (costAgentDonutChart) {
        costAgentDonutChart.data.labels = labels;
        costAgentDonutChart.data.datasets[0].data = values;
        costAgentDonutChart.data.datasets[0].backgroundColor = colors;
        costAgentDonutChart.data.datasets[0].borderColor = colors;
        costAgentDonutChart.update('none');
      } else {
        const ctx = dom.costAgentDonutCanvas.getContext('2d');
        costAgentDonutChart = new Chart(ctx, {
          type: 'doughnut',
          data: {
            labels: labels,
            datasets: [{
              data: values,
              backgroundColor: colors,
              borderColor: colors,
              borderWidth: 2,
              hoverBorderColor: '#fff',
              hoverBorderWidth: 2,
              spacing: 2,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
              legend: { display: false },
              tooltip: Object.assign({}, getCommonTooltipConfig(), {
                callbacks: {
                  label: function (tooltipCtx) {
                    const total = tooltipCtx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                    const pct = total > 0 ? ((tooltipCtx.parsed / total) * 100).toFixed(1) : 0;
                    return tooltipCtx.label + ': ' + formatCost(tooltipCtx.parsed) + ' (' + pct + '%)';
                  },
                },
              }),
            },
          },
        });
      }

      const legendEl = dom.costAgentDonutLegend;
      legendEl.innerHTML = '';
      agents.forEach(function (a) {
        const item = document.createElement('div');
        item.className = 'legend-item';
        item.innerHTML = '<span class="legend-dot" style="background:' + getAgentColor(a.agent) + '"></span>' +
          '<span>' + escapeHtml(a.agent) + '</span>' +
          '<span style="color:var(--text-muted);margin-left:2px">' + formatCost(a.cost) + '</span>';
        legendEl.appendChild(item);
      });
    } catch (err) {
      console.error('Cost agent donut error:', err);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Time Toggle ────────────────────────────────────────
  function initTimeToggle() {
    dom.timeToggle.addEventListener('click', (e) => {
      const btn = e.target.closest('.toggle-btn');
      if (!btn || btn.classList.contains('active')) return;

      dom.timeToggle.querySelectorAll('.toggle-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentRange = btn.dataset.range;
      refreshTimeSeries();
    });
  }

  // ── Refresh Cycle ──────────────────────────────────────
  function startCountdown() {
    countdown = REFRESH_INTERVAL;
    dom.countdown.textContent = countdown;

    clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
      countdown--;
      dom.countdown.textContent = Math.max(0, countdown);
      if (countdown <= 0) {
        clearInterval(countdownTimer);
      }
    }, 1000);
  }

  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      refreshAll();
    }, REFRESH_INTERVAL * 1000);
  }

  async function refreshAll() {
    dom.btnRefresh.classList.add('spinning');
    hideError();

    await Promise.allSettled([
      loadTimeSeriesData(),
      fetchModelData(),
    ]);

    await Promise.allSettled([
      loadAllTimeSummary(),
      loadCostSummary(),
      loadSummary(),
      renderBarChart(),
      renderRequestsChart(),
      loadDonutChart(),
      renderModelDonutChart(),
      renderIORatioChart(),
      renderModelTable(),
      loadLatencyChart(),
      loadCumulativeChart(),
      loadCostChart(),
      loadCostModelDonut(),
      loadCostAgentDonut(),
    ]);

    dom.btnRefresh.classList.remove('spinning');
    startCountdown();
    scheduleRefresh();
  }

  // ── Event Listeners ────────────────────────────────────
  function initEvents() {
    dom.btnRefresh.addEventListener('click', () => {
      refreshAll();
    });

    dom.btnClearFilter.addEventListener('click', () => {
      clearAgentFilter();
    });

    dom.btnDismissError.addEventListener('click', () => {
      hideError();
    });

    initTimeToggle();
  }

  // ── Init ───────────────────────────────────────────────
  function init() {
    initEvents();
    refreshAll();
  }

  // Wait for Chart.js to load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
