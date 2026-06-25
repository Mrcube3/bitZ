const API = '';
let currentPage = 'dashboard';
let feedPage = 0;
let selectedSide = 'long';
let hoursChart = null;
let regimeChart = null;
let feedRefreshInterval = null;
let tickerInterval = null;

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[ch]));
}

function formatUSD(value) {
  const n = Number(value || 0);
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${Math.round(n).toLocaleString()}`;
}

function formatPrice(value) {
  const n = Number(value || 0);
  return n < 10 ? `$${n.toFixed(4)}` : `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatTime(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('en-US', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
}

function animateNumber(el, target, formatter = (v) => Math.round(v).toLocaleString(), duration = 800) {
  const start = performance.now();
  const value = Number(target || 0);
  function tick(now) {
    const pct = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - pct, 3);
    el.textContent = formatter(value * eased);
    if (pct < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

async function jsonFetch(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function setupNavigation() {
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.addEventListener('click', () => {
      const page = item.dataset.page;
      currentPage = page;
      document.querySelectorAll('.nav-item').forEach((nav) => nav.classList.remove('active'));
      item.classList.add('active');
      document.querySelectorAll('.page').forEach((panel) => panel.classList.remove('active'));
      $(`page-${page}`).classList.add('active');
      if (feedRefreshInterval && page !== 'feed') clearInterval(feedRefreshInterval);
      if (page === 'dashboard') initDashboard();
      if (page === 'feed') initFeed(0);
      if (page === 'graveyard') initGraveyard();
      if (page === 'scanner') initScanner();
      if (page === 'docs') initDocs();
    });
  });
}

async function initDashboard() {
  try {
    const stats = await jsonFetch('/api/v1/stats');
    animateNumber($('stat-total'), stats.total_count);
    animateNumber($('stat-volume'), stats.total_volume_usd, formatUSD);
    animateNumber($('stat-queries'), stats.api_queries_today);
    $('sidebar-db-count').textContent = Number(stats.total_count || 0).toLocaleString();
    $('sidebar-api-queries').textContent = Number(stats.api_queries_today || 0).toLocaleString();
    $('sidebar-last-sync').textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const dangerous = stats.top_symbols?.[0];
    $('stat-dangerous').textContent = dangerous ? `${dangerous.symbol} ${dangerous.most_dangerous_regime}` : '-';
    renderHoursChart(stats.by_hour || []);
    renderRegimeChart(stats.by_regime || {});
    renderSymbolsTable(stats.top_symbols || []);
  } catch (error) {
    $('stat-dangerous').textContent = 'API offline';
  }
}

function renderHoursChart(values) {
  if (hoursChart) hoursChart.destroy();
  const max = Math.max(...values, 0);
  const sorted = [...values].map((v, i) => ({ v, i })).sort((a, b) => b.v - a.v);
  const top = new Set(sorted.slice(0, 3).map((x) => x.i));
  const highest = sorted[0]?.i;
  if (!window.Chart) {
    drawFallbackBars($('chart-hours'), values, top, highest);
    return;
  }
  hoursChart = new Chart($('chart-hours'), {
    type: 'bar',
    data: {
      labels: values.map((_, i) => String(i).padStart(2, '0')),
      datasets: [{ data: values, borderWidth: 0, backgroundColor: values.map((_, i) => i === highest && max > 0 ? '#E74C3C' : top.has(i) ? '#F39C12' : '#333') }],
    },
    options: chartOptions({ yMoney: true }),
  });
}

function renderRegimeChart(regimes) {
  if (regimeChart) regimeChart.destroy();
  const colors = { trending_bull: '#27AE60', trending_bear: '#C0392B', ranging: '#2471A3', volatile: '#E67E22', crash: '#8E44AD', unknown: '#555' };
  const labels = Object.keys(regimes);
  if (!window.Chart) {
    drawFallbackDonut($('chart-regime'), labels, labels.map((k) => regimes[k]), labels.map((k) => colors[k] || '#555'));
    return;
  }
  regimeChart = new Chart($('chart-regime'), {
    type: 'doughnut',
    data: { labels, datasets: [{ data: labels.map((k) => regimes[k]), backgroundColor: labels.map((k) => colors[k] || '#555'), borderColor: '#131313', borderWidth: 2 }] },
    options: { responsive: true, plugins: { legend: { position: 'bottom', labels: { color: '#909090', boxWidth: 10, font: { family: 'JetBrains Mono', size: 9 } } } }, cutout: '68%' },
  });
}

function fitCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width || canvas.parentElement.clientWidth || 480));
  const height = Math.max(160, Math.floor(rect.height || Number(canvas.getAttribute('height')) || 180));
  canvas.width = width * window.devicePixelRatio;
  canvas.height = height * window.devicePixelRatio;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext('2d');
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  return { ctx, width, height };
}

function drawFallbackBars(canvas, values, top, highest) {
  const { ctx, width, height } = fitCanvas(canvas);
  const max = Math.max(...values, 1);
  ctx.clearRect(0, 0, width, height);
  const gap = 4;
  const barW = (width - gap * (values.length - 1)) / values.length;
  values.forEach((value, i) => {
    const h = (value / max) * (height - 28);
    ctx.fillStyle = i === highest ? '#E74C3C' : top.has(i) ? '#F39C12' : '#333';
    ctx.fillRect(i * (barW + gap), height - h - 18, barW, h);
  });
  ctx.fillStyle = '#707070';
  ctx.font = '9px JetBrains Mono, monospace';
  [0, 6, 12, 18, 23].forEach((hour) => ctx.fillText(String(hour).padStart(2, '0'), hour * (barW + gap), height - 4));
}

function drawFallbackDonut(canvas, labels, values, colors) {
  const { ctx, width, height } = fitCanvas(canvas);
  const total = values.reduce((sum, v) => sum + Number(v || 0), 0) || 1;
  const radius = Math.min(width, height) * 0.34;
  const cx = width / 2;
  const cy = height / 2 - 8;
  let start = -Math.PI / 2;
  ctx.clearRect(0, 0, width, height);
  values.forEach((value, i) => {
    const end = start + (Number(value || 0) / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, start, end);
    ctx.closePath();
    ctx.fillStyle = colors[i];
    ctx.fill();
    start = end;
  });
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.62, 0, Math.PI * 2);
  ctx.fillStyle = '#131313';
  ctx.fill();
  ctx.fillStyle = '#909090';
  ctx.font = '9px JetBrains Mono, monospace';
  labels.slice(0, 4).forEach((label, i) => ctx.fillText(label, 12 + (i % 2) * (width / 2), height - 24 + Math.floor(i / 2) * 14));
}

function chartOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => extra.yMoney ? formatUSD(ctx.raw) : ctx.raw } } },
    scales: {
      x: { ticks: { color: '#707070', font: { family: 'JetBrains Mono', size: 9 } }, grid: { color: '#1e1e1e' } },
      y: { ticks: { color: '#707070', font: { family: 'JetBrains Mono', size: 9 }, callback: (v) => extra.yMoney ? formatUSD(v) : v }, grid: { color: '#1e1e1e' } },
    },
  };
}

function renderSymbolsTable(rows) {
  $('symbols-table-body').innerHTML = rows.map((row, i) => `
    <tr style="animation-delay:${i * 50}ms">
      <td>${escapeHtml(row.symbol)}</td>
      <td>${Number(row.total_liquidations || 0).toLocaleString()}</td>
      <td>${formatUSD(row.volume_usd)}</td>
      <td>${Number(row.long_pct || 0).toFixed(1)}%</td>
      <td>${Number(row.short_pct || 0).toFixed(1)}%</td>
      <td><span class="badge badge-regime">${escapeHtml(row.most_dangerous_regime || 'unknown')}</span></td>
      <td><div class="risk-bar-cell"><div class="risk-bar-bg"><div class="risk-bar-fill-cell" style="width:${Math.round((row.risk_level || 0) * 100)}%"></div></div><span class="risk-label-cell">${Math.round((row.risk_level || 0) * 100)}%</span></div></td>
    </tr>
  `).join('');
}

async function initFeed(page = 0) {
  feedPage = page;
  const params = new URLSearchParams({ limit: '50', offset: String(feedPage * 50) });
  ['symbol', 'side', 'regime'].forEach((key) => {
    const value = $(`feed-${key}`).value;
    if (value) params.set(key, value);
  });
  const rows = await jsonFetch(`/api/v1/liquidations?${params.toString()}`);
  renderFeed(rows);
  renderFeedPagination(rows.length);
  if (feedRefreshInterval) clearInterval(feedRefreshInterval);
  feedRefreshInterval = setInterval(() => { if (currentPage === 'feed') initFeed(feedPage); }, 60000);
}

function renderFeed(rows) {
  $('feed-table-body').innerHTML = rows.map((row, i) => {
    const fundingClass = row.funding_rate == null ? '' : row.funding_rate >= 0 ? 'positive' : 'negative';
    const rsiClass = row.rsi_at_event > 70 ? 'negative' : row.rsi_at_event < 30 ? 'positive' : '';
    return `
      <tr style="animation-delay:${i * 25}ms">
        <td>${formatTime(row.timestamp)}</td>
        <td>${escapeHtml(row.symbol)}</td>
        <td><span class="badge badge-${row.side}">${escapeHtml(row.side).toUpperCase()}</span></td>
        <td>${formatUSD(row.size_usd)}</td>
        <td>${row.leverage ? `${row.leverage}x` : '-'}</td>
        <td>${formatPrice(row.price)}</td>
        <td><span class="badge badge-regime">${escapeHtml(row.regime || 'unknown')}</span></td>
        <td class="${fundingClass}">${row.funding_rate == null ? '-' : `${row.funding_rate >= 0 ? '+' : ''}${(row.funding_rate * 100).toFixed(3)}%`}</td>
        <td class="${rsiClass}">${row.rsi_at_event == null ? '-' : Number(row.rsi_at_event).toFixed(1)}</td>
      </tr>
    `;
  }).join('');
}

function renderFeedPagination(rowCount) {
  $('feed-pagination').innerHTML = `
    <button class="page-btn" id="feed-prev" ${feedPage === 0 ? 'disabled' : ''}>PREV</button>
    <button class="page-btn active">PAGE ${feedPage + 1}</button>
    <button class="page-btn" id="feed-next" ${rowCount < 50 ? 'disabled' : ''}>NEXT</button>
  `;
  $('feed-prev').addEventListener('click', () => initFeed(Math.max(0, feedPage - 1)));
  $('feed-next').addEventListener('click', () => initFeed(feedPage + 1));
}

async function initGraveyard() {
  const patterns = await jsonFetch('/api/v1/liquidations/patterns');
  $('graveyard-grid').innerHTML = patterns.map((pattern, i) => `
    <div class="tombstone" style="animation-delay:${i * 80}ms; animation: fadeIn 400ms ease forwards; opacity:0">
      <div class="tombstone-rank">PATTERN #${pattern.rank}</div>
      <div class="tombstone-cross">+</div>
      <div class="tombstone-title">${escapeHtml(pattern.side).toUpperCase()} . ${escapeHtml(pattern.leverage_bucket)}</div>
      <div class="tombstone-regime">REGIME: ${escapeHtml(pattern.regime).toUpperCase().replace('_', ' ')}</div>
      <div class="tombstone-stats">
        <div class="tombstone-stat"><span class="tombstone-stat-label">FUNDING</span><span class="tombstone-stat-value">${pattern.avg_funding == null ? '-' : `${pattern.avg_funding >= 0 ? '+' : ''}${(pattern.avg_funding * 100).toFixed(3)}%`}</span></div>
        <div class="tombstone-stat"><span class="tombstone-stat-label">AVG RSI</span><span class="tombstone-stat-value">${pattern.avg_rsi == null ? '-' : Number(pattern.avg_rsi).toFixed(1)}</span></div>
      </div>
      <div class="tombstone-bar-wrapper">
        <div class="tombstone-bar-label"><span class="tombstone-stat-label">LIQUIDATIONS</span><span class="tombstone-stat-value">${Number(pattern.count || 0).toLocaleString()}</span></div>
        <div class="tombstone-bar"><div class="tombstone-bar-fill" style="width:0%" data-target="${Math.max(4, pattern.pct_of_total * 100)}%"></div></div>
      </div>
      <div class="tombstone-insight">"${escapeHtml(pattern.insight)}"</div>
    </div>
  `).join('');
  setTimeout(() => document.querySelectorAll('.tombstone-bar-fill').forEach((el) => { el.style.width = el.dataset.target; }), 200);
}

function initScanner() {
  selectSide(selectedSide);
}

function selectSide(side) {
  selectedSide = side;
  $('side-long').className = `side-btn${side === 'long' ? ' active-long' : ''}`;
  $('side-short').className = `side-btn${side === 'short' ? ' active-short' : ''}`;
}

function adjustLeverage(delta) {
  const el = $('scan-leverage');
  el.value = Math.max(1, Math.min(125, parseInt(el.value || 10, 10) + delta));
}

function readOptionalNumber(id) {
  const value = $(id).value.trim();
  return value === '' ? null : Number(value);
}

async function runAutopsy() {
  const required = [$('scan-symbol'), $('scan-leverage')];
  required.forEach((el) => el.classList.remove('input-error'));
  const leverage = parseInt($('scan-leverage').value, 10);
  if (!$('scan-symbol').value || !Number.isFinite(leverage)) {
    required.forEach((el) => { if (!el.value) el.classList.add('input-error'); });
    return;
  }
  const query = {
    symbol: $('scan-symbol').value,
    side: selectedSide,
    leverage,
    funding_rate: readOptionalNumber('scan-funding'),
    rsi: readOptionalNumber('scan-rsi'),
    fear_greed: readOptionalNumber('scan-fg'),
    long_short_ratio: readOptionalNumber('scan-ls'),
  };
  const button = $('scan-submit');
  button.disabled = true;
  $('report-content').innerHTML = '<div class="spinner"></div>';
  try {
    const data = await jsonFetch('/api/v1/risk-score', { method: 'POST', body: JSON.stringify(query) });
    renderReport(data, query);
    initDashboard();
  } catch (error) {
    $('report-content').innerHTML = `<div class="report-placeholder"><div class="report-placeholder-text">Request Failed</div><div class="report-placeholder-sub">${escapeHtml(error.message)}</div></div>`;
  } finally {
    button.disabled = false;
  }
}

function renderReport(data, query) {
  const probClass = data.liquidation_probability < 0.3 ? 'prob-low' : data.liquidation_probability < 0.6 ? 'prob-medium' : 'prob-high';
  const probPct = Math.round(data.liquidation_probability * 100);
  const riskLabel = probPct < 30 ? 'LOW RISK' : probPct < 60 ? 'ELEVATED RISK' : 'HIGH RISK';
  $('report-content').innerHTML = `
    <div class="report-content">
      <div class="report-header"><div class="report-title">Case File</div><div class="report-subject">${escapeHtml(query.symbol)} ${escapeHtml(query.side).toUpperCase()} . ${query.leverage}x</div><div class="report-timestamp">${new Date().toLocaleString()}</div></div>
      <div class="prob-display ${probClass}"><div class="prob-label">Liquidation Probability</div><div class="prob-number" id="report-prob">0%</div><div class="prob-bar"><div class="prob-bar-fill" id="report-prob-bar" style="width:0%"></div></div><div class="prob-risk-label">${riskLabel}</div><div class="prob-confidence">${escapeHtml(data.confidence).toUpperCase()} CONFIDENCE . ${data.similar_events_found} similar events</div></div>
      <div class="report-section"><div class="report-section-title">Time-To-Liquidation Profile</div><div class="report-section-content time-grid"><div><div class="time-item-label">MEDIAN</div><div class="time-item-value">${data.median_time_to_liquidation_hours ?? '-'}h</div></div><div><div class="time-item-label">WORST CASE</div><div class="time-item-value">${data.worst_case_hours ?? '-'}h</div></div></div></div>
      <div class="report-section"><div class="report-section-title">Risk Factors</div><div class="report-section-content">${data.top_risk_factors.map((factor) => `<div class="risk-factor"><span class="risk-factor-icon">!</span><span>${escapeHtml(factor)}</span></div>`).join('')}</div></div>
      <div class="report-section"><div class="report-section-title">Regime Warning</div><div class="report-section-content regime-warning">${escapeHtml(data.regime_warning || 'No current regime-specific warning detected.')}</div></div>
      <div class="report-section"><div class="report-section-title">Verdict</div><div class="report-section-content verdict-text" id="verdict-text"></div></div>
      <div class="report-footer">RETAIL AUTOPSY ENGINE . PATTERN INTELLIGENCE LAYER</div>
    </div>
  `;
  animateNumber($('report-prob'), probPct, (v) => `${Math.round(v)}%`, 700);
  setTimeout(() => { $('report-prob-bar').style.width = `${probPct}%`; }, 80);
  typeText($('verdict-text'), data.verdict);
}

function typeText(el, text) {
  el.textContent = '';
  let i = 0;
  const timer = setInterval(() => {
    el.textContent += text.charAt(i);
    i += 1;
    if (i >= text.length) clearInterval(timer);
  }, 20);
}

function initDocs() {
  const base = window.location.origin;
  $('api-base-url').textContent = base;
  const curl = (path) => `curl ${base}${path}`;
  const endpoints = [
    ['GET', '/health', 'Runtime heartbeat and event count.', curl('/health'), '{"status":"ok","version":"1.0.0","db_events":1500}'],
    ['POST', '/api/v1/risk-score', 'Score a proposed trade against historical liquidation patterns.', `curl -X POST ${base}/api/v1/risk-score -H "Content-Type: application/json" -d '{"symbol":"BTCUSDT","side":"long","leverage":20,"funding_rate":0.035,"rsi":74,"fear_greed":82}'`, '{"symbol":"BTCUSDT","side":"long","leverage":20,"liquidation_probability":0.41,"confidence":"medium","similar_events_found":38,"median_time_to_liquidation_hours":2.7,"worst_case_hours":0.12,"top_risk_factors":["Extreme leverage (20x+) - top liquidation tier"],"regime_warning":"Current regime resembles crash conditions; leveraged long entries are historically fragile.","verdict":"Historical autopsy finds a 41% liquidation probability..."}'],
    ['GET', '/api/v1/liquidations', 'Filterable liquidation event feed.', `curl "${base}/api/v1/liquidations?symbol=BTCUSDT&side=long&limit=5"`, '[{"id":1,"timestamp":"2026-06-01T12:00:00+00:00","symbol":"BTCUSDT","side":"long","size_usd":18450.22,"leverage":18,"price":94321.5,"regime":"volatile","funding_rate":0.041,"rsi_at_event":72.1,"fear_greed_at_event":78}]'],
    ['GET', '/api/v1/liquidations/clusters', 'Regime and side cluster summaries.', curl('/api/v1/liquidations/clusters'), '[{"regime":"volatile","side":"long","total_liquidations":214,"avg_leverage":14.2,"avg_funding_rate":0.044,"avg_rsi":61.4,"avg_size_usd":7820.4,"pct_of_total":0.1427}]'],
    ['GET', '/api/v1/liquidations/patterns', 'Top recurring liquidation patterns.', curl('/api/v1/liquidations/patterns'), '[{"rank":1,"regime":"crash","side":"long","leverage_bucket":"10-20x","avg_funding":-0.052,"avg_rsi":21.2,"count":96,"pct_of_total":0.064,"insight":"Buying the dip with leverage during a crash. Never works."}]'],
    ['GET', '/api/v1/regime/BTCUSDT', 'Current market regime snapshot for a symbol.', curl('/api/v1/regime/BTCUSDT'), '{"symbol":"BTCUSDT","regime":"volatile","rsi":68.3,"macd_signal":"bullish","funding_rate":0.028,"fear_greed":74,"long_short_ratio":1.18}'],
    ['GET', '/api/v1/stats', 'Dashboard totals, charts, and symbol leaderboard.', curl('/api/v1/stats'), '{"total_count":1500,"total_volume_usd":10942231.4,"api_queries_today":4,"top_symbols":[],"by_regime":{"volatile":310},"by_hour":[0,12000,88000]}'],
  ];
  $('api-docs-content').innerHTML = endpoints.map(([method, path, desc, curl, response], i) => `
    <div class="endpoint-card">
      <div class="endpoint-header"><span class="method-badge method-${method.toLowerCase()}">${method}</span><span class="endpoint-path">${path}</span></div>
      <div class="endpoint-desc">${desc}</div>
      <div class="code-block"><button class="copy-btn" data-copy="${i}">COPY</button><span class="code-block-label">Request</span>${escapeHtml(curl)}

<span class="code-block-label">Example Response</span>${escapeHtml(response)}</div>
    </div>
  `).join('');
  document.querySelectorAll('.copy-btn').forEach((btn) => btn.addEventListener('click', () => navigator.clipboard.writeText(endpoints[Number(btn.dataset.copy)][3])));
}

async function updateTickers() {
  try {
    const data = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true').then((r) => r.json());
    setTicker('btc', data.bitcoin?.usd, data.bitcoin?.usd_24h_change);
    setTicker('eth', data.ethereum?.usd, data.ethereum?.usd_24h_change);
    setTicker('sol', data.solana?.usd, data.solana?.usd_24h_change);
  } catch {
    setTicker('btc', 94120, -1.2);
    setTicker('eth', 3210, 0.8);
    setTicker('sol', 168, 2.4);
  }
  try {
    const regime = await jsonFetch('/api/v1/regime/BTCUSDT');
    $('fear-greed-badge').textContent = `F&G: ${regime.fear_greed ?? '-'}`;
  } catch {
    $('fear-greed-badge').textContent = 'F&G: -';
  }
}

function setTicker(prefix, price, change) {
  $(`${prefix}-price`).textContent = formatPrice(price);
  const el = $(`${prefix}-change`);
  const value = Number(change || 0);
  el.textContent = `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  el.className = `market-ticker-change ${value >= 0 ? 'up' : 'down'}`;
}

function setupControls() {
  ['feed-symbol', 'feed-side', 'feed-regime'].forEach((id) => $(id).addEventListener('change', () => initFeed(0)));
  $('side-long').addEventListener('click', () => selectSide('long'));
  $('side-short').addEventListener('click', () => selectSide('short'));
  $('lev-down').addEventListener('click', () => adjustLeverage(-1));
  $('lev-up').addEventListener('click', () => adjustLeverage(1));
  $('scan-submit').addEventListener('click', runAutopsy);
}

async function boot() {
  setupNavigation();
  setupControls();
  initDashboard();
  updateTickers();
  tickerInterval = setInterval(updateTickers, 10000);
  try {
    const health = await jsonFetch('/health');
    $('sidebar-db-count').textContent = Number(health.db_events || 0).toLocaleString();
  } catch {
    $('sidebar-db-count').textContent = 'offline';
  }
}

document.addEventListener('DOMContentLoaded', boot);
