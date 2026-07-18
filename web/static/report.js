/**
 * report.js — End-of-Contest Report: aggregated summary across the other tabs,
 * plus a standalone-HTML export of the rendered report.
 *
 * Live fields (KPIs, rate/score/band charts, missing-mult count) come straight
 * off the already-pushed snapshot object — no extra fetch — so a snapshot tick
 * only costs one network call (/api/dupes, which isn't part of the snapshot).
 * Reference data (YoY history, Pace reference logs) only changes when the user
 * adds/clears reference logs elsewhere, so it's fetched once per tab-visit /
 * log-load rather than on every snapshot tick (mirrors yoy.js's own reasoning).
 */
;(function () {
  'use strict';
  const C = { accent:'#00d4aa', accent2:'#ff6b35', accent3:'#f0c040',
              muted:'#8b949e', bg3:'#21262d', fg:'#e6edf3', green:'#2ed573' };
  const BAND_COLS  = window.VKA.BAND_COLS;
  const escapeHtml = window.VKA.escapeHtml;
  const refAtElapsed = window.VKA.refAtElapsed;

  let rateChart = null, scoreChart = null, bandChart = null, dupeChart = null;
  let _refLoaded  = false;
  let _liveReady  = false;   // true once the first dupes fetch has resolved
  // Retained source data so exportReport() builds from data, not from
  // already-rendered DOM (which would couple the export to live markup).
  let _lastDupes = null, _lastYoy = null, _lastPace = null;
  // Bumped on every new log load — lets updateLive()/loadReference() detect
  // and discard a fetch that was still in flight for the PREVIOUS log when a
  // new one loaded, instead of overwriting fresh state with stale data.
  let _loadGeneration = 0;

  function set(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }

  // ── Top-level state (loading / empty / error / content) ─────────────────
  function showState(state, msg) {
    const loading = document.getElementById('report-loading');
    const empty   = document.getElementById('report-empty');
    const error   = document.getElementById('report-error');
    const content = document.getElementById('report-content');
    if (loading) loading.style.display = state === 'loading' ? 'flex' : 'none';
    if (empty)   empty.style.display   = state === 'empty'   ? 'block' : 'none';
    if (error) {
      error.style.display = state === 'error' ? 'block' : 'none';
      if (state === 'error') error.textContent = '⚠ ' + (msg || 'Failed to load report.');
    }
    if (content) content.style.display = state === 'content' ? '' : 'none';
    if (state !== 'content') setExportEnabled(false);
  }

  function setExportEnabled(enabled) {
    _liveReady = enabled;
    const btn = document.getElementById('report-export-btn');
    if (btn) btn.disabled = !enabled;
  }

  function isTabActive() {
    return document.getElementById('tab-report')?.classList.contains('active');
  }

  // Empty placeholder snapshot is `{}` (server returns that, not null, when no
  // log is loaded) — `sparklines` is only present once a real log is computed.
  function hasLog(snap) { return !!(snap && snap.sparklines); }

  // ── Cheap per-snapshot-tick update (no fetch except /api/dupes) ─────────
  async function updateLive(snap) {
    // A server-side compute_snapshot() exception comes back as {"error":...}
    // (see STATE._safe_snapshot in server.py) — that shape also lacks
    // `sparklines`, so without this check it would be indistinguishable from
    // "no log loaded" and silently show the wrong empty state.
    if (snap && snap.error) { showState('error', snap.error); return; }
    if (!hasLog(snap)) { showState('empty'); return; }
    const gen = _loadGeneration;
    try {
      showState('content');
      set('report-generated', 'Generated ' + new Date().toLocaleString());
      renderKPIs(snap);
      renderRateChart(snap);
      renderScoreChart(snap);
      renderBandSection(snap.band_efficiency || [], snap.missing || 0);
      renderRegionTable(snap.region_heat || []);
      const dupes = await fetch('/api/dupes').then(r => r.json());
      // A new log may have loaded while the fetch above was in flight —
      // applying this response now would overwrite the new log's state with
      // data scraped from the log that's no longer open.
      if (gen !== _loadGeneration) return;
      _lastDupes = dupes;
      renderDupeSection(dupes);
      setExportEnabled(true);
    } catch (err) {
      console.warn('Report live update failed:', err);
      if (gen === _loadGeneration) showState('error', err.message);
    }
  }

  // ── One-shot reference data (YoY history + Pace reference logs) ─────────
  async function loadReference() {
    const gen = _loadGeneration;
    try {
      // ?same_contest=true (yoy) / source==='auto' (pace) both restrict to
      // other years of the SAME contest as the one currently loaded — this
      // tab is an end-of-contest summary, not a cross-contest browser, so it
      // should never mix in e.g. a CQWW year while a VK Shires log is open.
      const [yoy, paceRaw] = await Promise.all([
        fetch('/api/yoy?same_contest=true').then(r => r.json()),
        fetch('/api/pace').then(r => r.json()),
      ]);
      if (gen !== _loadGeneration) return;   // stale — a new log loaded meanwhile
      const pace = { ...paceRaw, refs: (paceRaw.refs || []).filter(r => r.source === 'auto') };
      _lastYoy = yoy; _lastPace = pace;
      renderComparison(yoy, pace, window.VKA.lastSnap());
      _refLoaded = true;
    } catch (err) {
      console.warn('Report reference data load failed:', err);
      if (gen !== _loadGeneration) return;
      const msg = document.getElementById('report-comparison-msg');
      if (msg) { msg.style.display = 'block'; msg.textContent = 'Failed to load comparison data: ' + err.message; }
    }
  }

  async function refresh() {
    const snap = window.VKA.lastSnap();
    if (snap && snap.error) { showState('error', snap.error); return; }
    if (!hasLog(snap)) { showState('empty'); return; }
    if (!_refLoaded) {
      showState('loading');
      // Independent network calls (different endpoints, no shared state) —
      // run concurrently instead of paying three serial round-trips.
      await Promise.all([updateLive(snap), loadReference()]);
    } else {
      await updateLive(snap);
    }
  }

  // ── KPIs ─────────────────────────────────────────────────────────────────
  // session_status.total_elapsed_mins (live) / elapsed_mins (pre=0, over=full
  // length) gives actual elapsed time — NOT sparklines.qsos.length, which is
  // sized to the contest's full *scheduled* duration regardless of how much
  // has actually elapsed, and would show e.g. "48h" two hours into a 48h contest.
  function elapsedHours(snap) {
    const ss = snap.session_status || {};
    const mins = ss.total_elapsed_mins ?? ss.elapsed_mins ?? 0;
    return mins / 60;
  }

  function computeKPIs(snap) {
    const total   = snap.total || 0;
    const valid   = snap.valid || 0;
    const dupePct = total > 0 ? Math.max(0, total - valid) / total * 100 : 0;
    const pb      = snap.personal_bests || {};
    return {
      score:    (snap.score  || 0).toLocaleString(),
      qsos:     valid.toLocaleString(),
      mults:    (snap.worked || 0).toLocaleString(),
      dupes:    dupePct.toFixed(1) + '%',
      besthr:   String(pb.best_hour_rate || 0),
      duration: elapsedHours(snap).toFixed(1) + 'h',
    };
  }

  const KPI_META = [
    ['score', 'Final Score'], ['qsos', 'Total QSOs'], ['mults', 'Total Mults'],
    ['dupes', 'Dupe Rate'], ['besthr', 'Best Hour Rate'], ['duration', 'Duration'],
  ];

  function renderKPIs(snap) {
    const k = computeKPIs(snap);
    KPI_META.forEach(([key]) => set('report-kpi-' + key, k[key]));
  }

  // ── QSO rate chart (from snapshot sparklines — no fetch) ────────────────
  function renderRateChart(snap) {
    const canvas = document.getElementById('chart-report-rate');
    const values = snap.sparklines?.qsos || [];
    if (!canvas || !values.length) { if (rateChart) { rateChart.destroy(); rateChart = null; } return; }
    const labels = values.map((_, i) => `h${i}`);
    // Fixed single-dataset shape for the lifetime of a loaded log — mutate
    // in place instead of destroy+recreate on every snapshot tick (see
    // issue #73, matches bands.js's existing pattern).
    if (rateChart) {
      rateChart.data.labels = labels;
      rateChart.data.datasets[0].data = values;
      rateChart.update();
      return;
    }
    rateChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { labels, datasets: [{ label: 'QSOs', data: values,
        backgroundColor: C.accent + 'cc', borderColor: C.accent, borderWidth: 1, borderRadius: 3 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: { legend: { display: false },
          tooltip: { backgroundColor: C.bg3, bodyColor: C.fg, titleColor: C.accent } },
        scales: {
          x: { ticks: { color: C.muted, font: { size: 9 }, maxTicksLimit: 12 }, grid: { color: C.bg3+'80' } },
          y: { ticks: { color: C.muted, font: { size: 9 } }, grid: { color: C.bg3+'80' }, beginAtZero: true },
        },
      },
    });
  }

  // ── Running score chart ──────────────────────────────────────────────────
  function renderScoreChart(snap) {
    const canvas = document.getElementById('chart-report-score');
    const hist   = snap.sparklines?.running_score || [];
    if (!canvas || !hist.length) { if (scoreChart) { scoreChart.destroy(); scoreChart = null; } return; }
    const labels = hist.map((_, i) => `h${i}`);
    // Fixed single-dataset shape for the lifetime of a loaded log — mutate
    // in place instead of destroy+recreate on every snapshot tick (see
    // issue #73, matches bands.js's existing pattern).
    if (scoreChart) {
      scoreChart.data.labels = labels;
      scoreChart.data.datasets[0].data = hist;
      scoreChart.update();
      return;
    }
    scoreChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels, datasets: [{ label: 'Score', data: hist,
        borderColor: C.accent3, backgroundColor: C.accent3 + '22',
        borderWidth: 2, fill: true, tension: 0.25, pointRadius: 0 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: { legend: { display: false },
          tooltip: { backgroundColor: C.bg3, bodyColor: C.fg, titleColor: C.accent3 } },
        scales: {
          x: { ticks: { color: C.muted, font: { size: 9 }, maxTicksLimit: 12 }, grid: { color: C.bg3+'80' } },
          y: { ticks: { color: C.muted, font: { size: 9 } }, grid: { color: C.bg3+'80' }, beginAtZero: true },
        },
      },
    });
  }

  // ── Shared row-builders: single source of truth for table content,
  // consumed by both the live DOM tables AND the HTML export, so a future
  // formatting/sort change only needs to happen in one place and the export
  // never drifts from what's on screen. A cell is either a plain value or
  // {text, color, bold} when it needs styling (e.g. per-band coloring).
  function cellHtml(c) {
    if (c && typeof c === 'object' && 'text' in c) {
      const style = [c.color ? `color:${c.color}` : '', c.bold ? 'font-weight:bold' : ''].filter(Boolean).join(';');
      return `<td${style ? ` style="${style}"` : ''}>${c.text}</td>`;
    }
    return `<td>${c}</td>`;
  }
  function renderRowsToTbody(tbody, rows, emptyHtml) {
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!rows.length) { tbody.innerHTML = emptyHtml; return; }
    const frag = document.createDocumentFragment();
    rows.forEach(cells => {
      const tr = document.createElement('tr');
      tr.innerHTML = cells.map(cellHtml).join('');
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  function bandRows(bands) {
    return (bands || []).map(r => {
      const col = BAND_COLS[(r.band||'').toLowerCase()] || C.muted;
      return [
        { text: (r.band||'').toLowerCase(), color: col, bold: true },
        r.qsos || 0, r.new_shires || 0, (r.efficiency || 0).toFixed(3),
      ];
    });
  }

  // ── Band & multiplier breakdown (from snapshot — no fetch) ──────────────
  function renderBandSection(bands, missingCount) {
    const canvas = document.getElementById('chart-report-bands');
    const tbody  = document.getElementById('report-bands-tbody');
    bands = bands || [];
    renderRowsToTbody(tbody, bandRows(bands), '');

    if (!canvas || !bands.length) { if (bandChart) { bandChart.destroy(); bandChart = null; } }
    else {
      const labels  = bands.map(r => (r.band||'').toLowerCase());
      const effic   = bands.map(r => r.efficiency || 0);
      const colours = labels.map(b => BAND_COLS[b] || C.muted);
      // Mutate in place instead of destroy+recreate on every snapshot tick
      // when a chart already exists (see issue #73).
      if (bandChart) {
        bandChart.data.labels = labels;
        bandChart.data.datasets[0].data = effic;
        bandChart.data.datasets[0].backgroundColor = colours.map(c => c+'cc');
        bandChart.data.datasets[0].borderColor = colours;
        bandChart.options.scales.y.ticks.color = colours;
        bandChart.update();
      } else {
        bandChart = new Chart(canvas.getContext('2d'), {
          type: 'bar',
          data: { labels, datasets: [{ label: 'Efficiency', data: effic,
            backgroundColor: colours.map(c => c+'cc'), borderColor: colours, borderWidth: 1, borderRadius: 4 }] },
          options: {
            indexAxis: 'y', responsive: true, maintainAspectRatio: false,
            animation: { duration: 400 },
            plugins: { legend: { display: false }, tooltip: { backgroundColor: C.bg3, bodyColor: C.fg } },
            scales: {
              x: { ticks: { color: C.muted, font: { size: 9 } }, grid: { color: C.bg3+'80' } },
              y: { ticks: { color: colours, font: { size: 11, weight: 'bold', family: 'Consolas' } }, grid: { display: false } },
            },
          },
        });
      }
    }

    const summary = document.getElementById('report-missing-summary');
    if (summary) summary.textContent = computeMissingSummary(missingCount);
  }

  function computeMissingSummary(missingCount) {
    const n = missingCount || 0;
    return n
      ? `${n} multiplier${n!==1?'s':''} still missing — see the Missing Mults tab for the full list.`
      : 'All multipliers worked — clean sweep!';
  }

  function dupeRows(dupes) {
    const entries = Object.entries(dupes?.by_call || {}).sort((a, b) => b[1] - a[1]);
    return entries.map(([call, n]) => [
      { text: escapeHtml(call), color: 'var(--accent2)', bold: true }, n,
    ]);
  }

  // ── Dupes & data quality ─────────────────────────────────────────────────
  function renderDupeSection(dupes) {
    const byBand = dupes?.by_band || {};
    const canvas = document.getElementById('chart-report-dupes');
    const tbody  = document.getElementById('report-dupes-tbody');
    renderRowsToTbody(tbody, dupeRows(dupes),
      '<tr><td colspan="2" style="color:var(--green);padding:10px">No duplicate QSOs — clean log!</td></tr>');

    if (canvas) {
      const bands  = Object.keys(byBand);
      const values = bands.map(b => byBand[b]);
      const cols   = bands.map(b => BAND_COLS[(b||'').toLowerCase()] || C.muted);
      canvas.style.display = bands.length ? '' : 'none';
      if (!bands.length) {
        if (dupeChart) { dupeChart.destroy(); dupeChart = null; }
      } else if (dupeChart) {
        // Mutate in place instead of destroy+recreate on every snapshot
        // tick when a chart already exists (see issue #73).
        dupeChart.data.labels = bands.map(b => b.toLowerCase());
        dupeChart.data.datasets[0].data = values;
        dupeChart.data.datasets[0].backgroundColor = cols.map(c => c+'cc');
        dupeChart.data.datasets[0].borderColor = cols;
        dupeChart.options.scales.x.ticks.color = cols;
        dupeChart.update();
      } else {
        dupeChart = new Chart(canvas.getContext('2d'), {
          type: 'bar',
          data: { labels: bands.map(b => b.toLowerCase()), datasets: [{ label: 'Dupes', data: values,
            backgroundColor: cols.map(c => c+'cc'), borderColor: cols, borderWidth: 1, borderRadius: 4 }] },
          options: {
            responsive: true, maintainAspectRatio: false,
            animation: { duration: 400 },
            plugins: { legend: { display: false }, tooltip: { backgroundColor: C.bg3, bodyColor: C.fg } },
            scales: {
              x: { ticks: { color: cols, font: { size: 11, weight: 'bold' } }, grid: { display: false } },
              y: { ticks: { color: C.muted, font: { size: 9 } }, grid: { color: C.bg3+'80' }, beginAtZero: true },
            },
          },
        });
      }
    } else if (dupeChart) {
      dupeChart.destroy(); dupeChart = null;
    }
  }

  function regionRows(regions) {
    return (regions || []).slice(0, 15).map(r => [
      escapeHtml(r.state || '—'), r.qsos || 0, `${r.worked || 0} / ${r.total || 0}`, `${(r.pct || 0).toFixed(0)}%`,
    ]);
  }

  // ── Top worked regions (propagation/activity proxy) ─────────────────────
  function renderRegionTable(regions) {
    const tbody = document.getElementById('report-regions-tbody');
    renderRowsToTbody(tbody, regionRows(regions),
      '<tr><td colspan="4" style="color:var(--muted);padding:10px">No regional data for this contest.</td></tr>');
  }

  // ── Pace vs goal & year-on-year comparison ───────────────────────────────
  function buildInsightParts(yoy, pace, snap) {
    const series = yoy?.series || [];
    const refs   = pace?.refs  || [];
    const parts  = [];
    if (series.length) {
      const best = series.reduce((a, b) => (b.final_score||0) > (a.final_score||0) ? b : a, series[0]);
      const cur  = snap?.score || 0;
      const diff = cur - (best.final_score || 0);
      parts.push(diff >= 0
        ? `🚀 ${diff.toLocaleString()} pts ahead of your best year (${best.year}).`
        : `${Math.abs(diff).toLocaleString()} pts behind your best year (${best.year}, ${(best.final_score||0).toLocaleString()} pts).`);
    }
    const live = pace?.live;
    if (refs.length && live?.elapsed_hrs?.length) {
      const nowE      = live.elapsed_hrs[live.elapsed_hrs.length - 1];
      const liveTotal = live.cum_qsos[live.cum_qsos.length - 1];
      const best      = refs.reduce((a, b) => refAtElapsed(b, nowE) > refAtElapsed(a, nowE) ? b : a, refs[0]);
      const deficit   = refAtElapsed(best, nowE) - liveTotal;
      parts.push(deficit > 0
        ? `⚠ ${deficit} QSOs behind ${best.year} pace at this point in the contest.`
        : `✅ ${Math.abs(deficit)} QSOs ahead of ${best.year} pace at this point in the contest.`);
    }
    return parts;
  }

  function yoyRows(series) {
    return [...(series || [])].sort((a, b) => (b.final_score||0) - (a.final_score||0)).map(s => [
      s.year || '?', escapeHtml(s.display_name || s.contest_name || ''),
      (s.final_score || 0).toLocaleString(), (s.final_qsos || 0).toLocaleString(), (s.final_mults || 0).toLocaleString(),
    ]);
  }

  function renderComparison(yoy, pace, snap) {
    const msg     = document.getElementById('report-comparison-msg');
    const content = document.getElementById('report-comparison-content');
    const series  = yoy?.series || [];
    const refs    = pace?.refs  || [];
    const tbody   = document.getElementById('report-yoy-tbody');
    const insight = document.getElementById('report-pace-insight');

    if (!series.length && !refs.length) {
      if (msg) {
        msg.style.display = 'block';
        msg.textContent = 'Load reference logs in the Pace or Year-on-Year tab to enable goal/history comparison.';
      }
      if (content) content.style.display = 'none';
      return;
    }
    if (msg) msg.style.display = 'none';
    if (content) content.style.display = '';

    renderRowsToTbody(tbody, yoyRows(series), '');

    if (insight) insight.textContent = buildInsightParts(yoy, pace, snap).join('   ') || 'No comparison data available yet.';
  }

  // ── Standalone HTML export — built from the SAME row-builders the live
  // tables use (bandRows/dupeRows/regionRows/yoyRows above), via the same
  // cellHtml() styling so per-band colors / bold callsigns survive into the
  // exported document instead of degrading to one flat accent color.
  function buildTable(headers, rows) {
    const thead = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>`;
    const tbody = `<tbody>${rows.map(r => `<tr>${r.map(cellHtml).join('')}</tr>`).join('')}</tbody>`;
    return `<table>${thead}${tbody}</table>`;
  }

  function exportBandsTable(snap) {
    const rows = bandRows(snap.band_efficiency);
    if (!rows.length) return '<p class="meta">No band data.</p>';
    return buildTable(['Band','QSOs','New Mults','Efficiency'], rows);
  }

  function exportDupesTable(dupes) {
    const rows = dupeRows(dupes);
    if (!rows.length) return '<p class="meta" style="color:#2ed573">No duplicate QSOs — clean log!</p>';
    return buildTable(['Callsign','Dupes'], rows);
  }

  function exportRegionTable(snap) {
    const rows = regionRows(snap.region_heat);
    if (!rows.length) return '<p class="meta">No regional data for this contest.</p>';
    return buildTable(['Region','QSOs','Mults Worked','% Complete'], rows);
  }

  function exportYoyTable(yoy) {
    const rows = yoyRows(yoy?.series);
    if (!rows.length) return '';
    return buildTable(['Year','Contest','Score','QSOs','Mults'], rows);
  }

  async function exportReport() {
    const btn = document.getElementById('report-export-btn');
    if (btn) { btn.disabled = true; btn.textContent = '⬇ …'; }
    try {
      const snap = window.VKA.lastSnap();
      if (!hasLog(snap)) throw new Error('No report data loaded yet.');

      // Only embed charts that actually have a live Chart.js instance — an
      // empty/never-rendered canvas still measures the browser's default
      // 300x150 backing store, so checking canvas.width alone can't tell
      // "never drawn into" from "really has content".
      const charts = [
        ['QSO Rate by Hour', rateChart],
        ['Running Score',    scoreChart],
        ['Band Efficiency',  bandChart],
        ['Dupes by Band',    dupeChart],
      ];
      const chartHtml = charts
        .filter(([, chart]) => chart)
        .map(([title, chart]) => `
          <div style="margin-bottom:24px">
            <h3 style="font-family:Consolas,monospace;color:${C.muted};font-size:13px;
                text-transform:uppercase;letter-spacing:.08em">${title}</h3>
            <img src="${chart.canvas.toDataURL('image/png')}" style="max-width:100%;background:#161b22;border-radius:6px">
          </div>`).join('');

      const k = computeKPIs(snap);
      const kpiHtml = KPI_META.map(([key, label]) => `<div style="background:#161b22;border:1px solid ${C.bg3};border-radius:6px;
            padding:10px;text-align:center;min-width:110px">
          <div style="font-family:Consolas,monospace;font-size:20px;font-weight:bold;color:${C.accent}">${k[key]}</div>
          <div style="font-family:Consolas,monospace;font-size:10px;color:${C.muted};
              text-transform:uppercase;letter-spacing:.06em">${label}</div>
        </div>`).join('');

      const missingText = computeMissingSummary(snap.missing || 0);
      const insightText = buildInsightParts(_lastYoy, _lastPace, snap).join('   ') || 'No comparison data available yet.';
      const generated    = document.getElementById('report-generated')?.textContent || '';

      const html = `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>VK Contest Analyzer — Report</title>
<style>
  body{background:#0d1117;color:${C.fg};font-family:Consolas,monospace;padding:28px;max-width:900px;margin:0 auto}
  h1{font-size:20px;color:${C.fg}}
  h2{font-size:14px;color:${C.muted};text-transform:uppercase;letter-spacing:.08em;
     border-top:2px solid ${C.accent};padding-top:10px;margin-top:30px}
  .meta{color:${C.muted};font-size:12px;margin-bottom:20px}
  .kpi-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
  table{width:100%;border-collapse:collapse;font-family:Consolas,monospace;font-size:13px;margin-bottom:10px}
  thead th{background:${C.bg3};color:${C.accent};text-align:left;padding:6px 10px;
    font-size:11px;letter-spacing:.08em;text-transform:uppercase}
  tbody tr{border-bottom:1px solid ${C.bg3}}
  tbody tr:nth-child(even){background:#1a1f26}
  tbody td{padding:5px 10px;color:${C.fg}}
  tbody td:first-child{color:${C.accent};font-weight:bold}
</style></head>
<body>
  <h1>⬡ VK CONTEST ANALYZER — End-of-Contest Report</h1>
  <div class="meta">${escapeHtml(generated)}</div>
  <div class="kpi-row">${kpiHtml}</div>
  <h2>QSO Rate &amp; Score</h2>
  ${chartHtml || '<p class="meta">No chart data yet.</p>'}
  <h2>Band &amp; Multiplier Breakdown</h2>
  ${exportBandsTable(snap)}
  <div class="meta">${escapeHtml(missingText)}</div>
  <h2>Dupes &amp; Data Quality</h2>
  ${exportDupesTable(_lastDupes)}
  <h2>Top Worked Regions</h2>
  ${exportRegionTable(snap)}
  <h2>Pace vs Goal &amp; Year-on-Year</h2>
  ${exportYoyTable(_lastYoy) || '<p class="meta">Load reference logs in the Pace or Year-on-Year tab to enable goal/history comparison.</p>'}
  <div class="meta">${escapeHtml(insightText)}</div>
</body></html>`;

      const blob  = new Blob([html], { type: 'text/html' });
      const fname = `vkcontest_report_${new Date().toISOString().slice(0,10)}.html`;
      await window.VKA.downloadBlob(blob, fname, '✓ Report Saved', '📑');
      if (btn) {
        btn.textContent = '✓';
        setTimeout(() => { btn.textContent = '⬇ Export Report (HTML)'; btn.disabled = !_liveReady; }, 2000);
      }
    } catch (err) {
      window.VKA?.showToast?.('Report Export Failed', err.message, '✗', true);
      if (btn) { btn.textContent = '⬇ Export Report (HTML)'; btn.disabled = !_liveReady; }
    }
  }

  document.getElementById('report-export-btn')?.addEventListener('click', exportReport);

  // Cheap live update on every snapshot tick (only while the tab is visible).
  window.addEventListener('vka:snapshot', e => { if (isTabActive()) updateLive(e.detail); });
  // Full refresh (live + reference data, if not already loaded) on tab open.
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab === 'report') refresh(); });
  // New log opened — reference data (YoY/Pace) needs to be refetched for it,
  // and any fetch still in flight for the PREVIOUS log must be invalidated.
  window.addEventListener('vka:loaded', () => {
    _loadGeneration++;
    _refLoaded = false; _lastDupes = null; _lastYoy = null; _lastPace = null;
    setExportEnabled(false);
  });
})();
