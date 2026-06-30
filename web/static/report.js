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
  const BAND_COLS = {
    '160m':'#e040fb','80m':'#ff6b35','60m':'#f0c040','40m':'#2ed573',
    '30m':'#00bcd4', '20m':'#00d4aa','17m':'#64b5f6','15m':'#ff5252',
    '12m':'#ffab40', '10m':'#69f0ae','6m': '#ea80fc','2m': '#80d8ff',
    '70cm':'#ccff90',
  };

  let rateChart = null, scoreChart = null, bandChart = null, dupeChart = null;
  let _refLoaded = false;

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  }
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
  }

  function isTabActive() {
    return document.getElementById('tab-report')?.classList.contains('active');
  }

  // Empty placeholder snapshot is `{}` (server returns that, not null, when no
  // log is loaded) — `sparklines` is only present once a real log is computed.
  function hasLog(snap) { return !!(snap && snap.sparklines); }

  // ── Cheap per-snapshot-tick update (no fetch except /api/dupes) ─────────
  async function updateLive(snap) {
    if (!hasLog(snap)) { showState('empty'); return; }
    try {
      showState('content');
      set('report-generated', 'Generated ' + new Date().toLocaleString());
      renderKPIs(snap);
      renderRateChart(snap);
      renderScoreChart(snap);
      renderBandSection(snap.band_efficiency || [], snap.missing || 0);
      renderRegionTable(snap.region_heat || []);
      const dupes = await fetch('/api/dupes').then(r => r.json());
      renderDupeSection(dupes);
    } catch (err) {
      console.warn('Report live update failed:', err);
      showState('error', err.message);
    }
  }

  // ── One-shot reference data (YoY history + Pace reference logs) ─────────
  async function loadReference() {
    try {
      const [yoy, pace] = await Promise.all([
        fetch('/api/yoy').then(r => r.json()),
        fetch('/api/pace').then(r => r.json()),
      ]);
      renderComparison(yoy, pace, window.VKA.lastSnap());
      _refLoaded = true;
    } catch (err) {
      console.warn('Report reference data load failed:', err);
      const msg = document.getElementById('report-comparison-msg');
      if (msg) { msg.style.display = 'block'; msg.textContent = 'Failed to load comparison data: ' + err.message; }
    }
  }

  async function refresh() {
    const snap = window.VKA.lastSnap();
    if (!hasLog(snap)) { showState('empty'); return; }
    if (!_refLoaded) showState('loading');
    await updateLive(snap);
    if (!_refLoaded) await loadReference();
  }

  // ── KPIs ─────────────────────────────────────────────────────────────────
  function renderKPIs(snap) {
    const total   = snap.total || 0;
    const valid   = snap.valid || 0;
    const dupePct = total > 0 ? Math.max(0, total - valid) / total * 100 : 0;
    const pb      = snap.personal_bests || {};
    const hours   = (snap.sparklines?.qsos || []).length;

    set('report-kpi-score',    (snap.score  || 0).toLocaleString());
    set('report-kpi-qsos',     valid.toLocaleString());
    set('report-kpi-mults',    (snap.worked || 0).toLocaleString());
    set('report-kpi-dupes',    dupePct.toFixed(1) + '%');
    set('report-kpi-besthr',   pb.best_hour_rate || 0);
    set('report-kpi-duration', hours + 'h');
  }

  // ── QSO rate chart (from snapshot sparklines — no fetch) ────────────────
  function renderRateChart(snap) {
    const canvas = document.getElementById('chart-report-rate');
    const values = snap.sparklines?.qsos || [];
    if (!canvas || !values.length) return;
    const labels = values.map((_, i) => `h${i}`);
    if (rateChart) { rateChart.destroy(); rateChart = null; }
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
    if (!canvas || !hist.length) return;
    const labels = hist.map((_, i) => `h${i}`);
    if (scoreChart) { scoreChart.destroy(); scoreChart = null; }
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

  // ── Band & multiplier breakdown (from snapshot — no fetch) ──────────────
  function renderBandSection(bands, missingCount) {
    const canvas = document.getElementById('chart-report-bands');
    const tbody  = document.getElementById('report-bands-tbody');
    bands = bands || [];

    if (tbody) {
      tbody.innerHTML = '';
      const frag = document.createDocumentFragment();
      bands.forEach(r => {
        const col = BAND_COLS[(r.band||'').toLowerCase()] || C.muted;
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td style="color:${col};font-weight:bold">${(r.band||'').toLowerCase()}</td>
          <td>${r.qsos || 0}</td>
          <td>${r.new_shires || 0}</td>
          <td>${(r.efficiency || 0).toFixed(3)}</td>`;
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
    }

    if (canvas && bands.length) {
      const labels  = bands.map(r => (r.band||'').toLowerCase());
      const effic   = bands.map(r => r.efficiency || 0);
      const colours = labels.map(b => BAND_COLS[b] || C.muted);
      if (bandChart) { bandChart.destroy(); bandChart = null; }
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

    const summary = document.getElementById('report-missing-summary');
    if (summary) {
      const n = missingCount || 0;
      summary.textContent = n
        ? `${n} multiplier${n!==1?'s':''} still missing — see the Missing Mults tab for the full list.`
        : 'All multipliers worked — clean sweep!';
    }
  }

  // ── Dupes & data quality ─────────────────────────────────────────────────
  function renderDupeSection(dupes) {
    const byBand = dupes?.by_band || {};
    const byCall = dupes?.by_call || {};
    const canvas = document.getElementById('chart-report-dupes');
    const tbody  = document.getElementById('report-dupes-tbody');

    if (tbody) {
      const entries = Object.entries(byCall).sort((a, b) => b[1] - a[1]);
      tbody.innerHTML = entries.length ? '' :
        '<tr><td colspan="2" style="color:var(--green);padding:10px">No duplicate QSOs — clean log!</td></tr>';
      const frag = document.createDocumentFragment();
      entries.forEach(([call, n]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td style="color:var(--accent2);font-weight:bold">${escapeHtml(call)}</td><td>${n}</td>`;
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
    }

    if (canvas) {
      const bands  = Object.keys(byBand);
      const values = bands.map(b => byBand[b]);
      const cols   = bands.map(b => BAND_COLS[(b||'').toLowerCase()] || C.muted);
      if (dupeChart) { dupeChart.destroy(); dupeChart = null; }
      canvas.style.display = bands.length ? '' : 'none';
      if (bands.length) {
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
    }
  }

  // ── Top worked regions (propagation/activity proxy) ─────────────────────
  function renderRegionTable(regions) {
    const tbody = document.getElementById('report-regions-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!regions.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted);padding:10px">No regional data for this contest.</td></tr>';
      return;
    }
    const frag = document.createDocumentFragment();
    regions.slice(0, 15).forEach(r => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${escapeHtml(r.state || '—')}</td>
        <td>${r.qsos || 0}</td>
        <td>${r.worked || 0} / ${r.total || 0}</td>
        <td>${(r.pct || 0).toFixed(0)}%</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  // ── Pace vs goal & year-on-year comparison ───────────────────────────────
  function refAtElapsed(ref, nowE) {
    const e = ref.elapsed_hrs, c = ref.cum_qsos;
    if (!e || !e.length) return 0;
    if (nowE >= e[e.length - 1]) return c[c.length - 1];
    for (let i = 0; i < e.length; i++) if (e[i] >= nowE) return c[i];
    return c[c.length - 1];
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

    if (tbody) {
      tbody.innerHTML = '';
      const frag = document.createDocumentFragment();
      [...series].sort((a, b) => (b.final_score||0) - (a.final_score||0)).forEach(s => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${s.year || '?'}</td>
          <td>${escapeHtml(s.display_name || s.contest_name || '')}</td>
          <td>${(s.final_score || 0).toLocaleString()}</td>
          <td>${(s.final_qsos  || 0).toLocaleString()}</td>
          <td>${(s.final_mults || 0).toLocaleString()}</td>`;
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
    }

    const parts = [];
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
    if (insight) insight.textContent = parts.join('   ') || 'No comparison data available yet.';
  }

  // ── Standalone HTML export ───────────────────────────────────────────────
  async function exportReport() {
    const btn = document.getElementById('report-export-btn');
    if (btn) { btn.disabled = true; btn.textContent = '⬇ …'; }
    try {
      const charts = [
        ['QSO Rate by Hour', document.getElementById('chart-report-rate')],
        ['Running Score',    document.getElementById('chart-report-score')],
        ['Band Efficiency',  document.getElementById('chart-report-bands')],
        ['Dupes by Band',    document.getElementById('chart-report-dupes')],
      ];
      const chartHtml = charts
        .filter(([, c]) => c && c.style.display !== 'none' && c.width > 0)
        .map(([title, c]) => `
          <div style="margin-bottom:24px">
            <h3 style="font-family:Consolas,monospace;color:#8b949e;font-size:13px;
                text-transform:uppercase;letter-spacing:.08em">${title}</h3>
            <img src="${c.toDataURL('image/png')}" style="max-width:100%;background:#161b22;border-radius:6px">
          </div>`).join('');

      const kpiHtml = ['score','qsos','mults','dupes','besthr','duration'].map(k => {
        const el  = document.getElementById('report-kpi-' + k);
        const lbl = el?.parentElement?.querySelector('.pace-label')?.textContent || k;
        return `<div style="background:#161b22;border:1px solid #21262d;border-radius:6px;
            padding:10px;text-align:center;min-width:110px">
          <div style="font-family:Consolas,monospace;font-size:20px;font-weight:bold;color:#00d4aa">${el?.textContent || '—'}</div>
          <div style="font-family:Consolas,monospace;font-size:10px;color:#8b949e;
              text-transform:uppercase;letter-spacing:.06em">${lbl}</div>
        </div>`;
      }).join('');

      const bandsTable  = document.getElementById('report-bands-tbody')?.closest('.table-wrap')?.outerHTML || '';
      const dupesTable  = document.getElementById('report-dupes-tbody')?.closest('.table-wrap')?.outerHTML || '';
      const regionTable = document.getElementById('report-regions-tbody')?.closest('.table-wrap')?.outerHTML || '';
      const yoyTable    = document.getElementById('report-yoy-tbody')?.closest('.table-wrap')?.outerHTML || '';
      const insightText = document.getElementById('report-pace-insight')?.textContent || '';
      const missingText = document.getElementById('report-missing-summary')?.textContent || '';
      const generated   = document.getElementById('report-generated')?.textContent || '';

      const html = `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>VK Contest Analyzer — Report</title>
<style>
  body{background:#0d1117;color:#e6edf3;font-family:Consolas,monospace;padding:28px;max-width:900px;margin:0 auto}
  h1{font-size:20px;color:#e6edf3}
  h2{font-size:14px;color:#8b949e;text-transform:uppercase;letter-spacing:.08em;
     border-top:2px solid #00d4aa;padding-top:10px;margin-top:30px}
  .meta{color:#8b949e;font-size:12px;margin-bottom:20px}
  .kpi-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
  table{width:100%;border-collapse:collapse;font-family:Consolas,monospace;font-size:13px;margin-bottom:10px}
  thead th{background:#21262d;color:#00d4aa;text-align:left;padding:6px 10px;
    font-size:11px;letter-spacing:.08em;text-transform:uppercase}
  tbody tr{border-bottom:1px solid #21262d}
  tbody tr:nth-child(even){background:#1a1f26}
  tbody td{padding:5px 10px;color:#e6edf3}
  tbody td:first-child{color:#00d4aa;font-weight:bold}
</style></head>
<body>
  <h1>⬡ VK CONTEST ANALYZER — End-of-Contest Report</h1>
  <div class="meta">${escapeHtml(generated)}</div>
  <div class="kpi-row">${kpiHtml}</div>
  <h2>QSO Rate &amp; Score</h2>
  ${chartHtml}
  <h2>Band &amp; Multiplier Breakdown</h2>
  ${bandsTable}
  <div class="meta">${escapeHtml(missingText)}</div>
  <h2>Dupes &amp; Data Quality</h2>
  ${dupesTable}
  <h2>Top Worked Regions</h2>
  ${regionTable}
  <h2>Pace vs Goal &amp; Year-on-Year</h2>
  ${yoyTable}
  <div class="meta">${escapeHtml(insightText)}</div>
</body></html>`;

      const blob  = new Blob([html], { type: 'text/html' });
      const url   = URL.createObjectURL(blob);
      const fname = `vkcontest_report_${new Date().toISOString().slice(0,10)}.html`;
      const a = document.createElement('a');
      a.href = url; a.download = fname;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);

      const loc = await fetch('/api/save_location').then(r => r.json()).catch(() => ({}));
      window.VKA?.showToast?.('✓ Report Saved', (loc.folder || 'Downloads') + '\\' + fname, '📑');
      if (btn) {
        btn.textContent = '✓';
        setTimeout(() => { btn.textContent = '⬇ Export Report (HTML)'; btn.disabled = false; }, 2000);
      }
    } catch (err) {
      window.VKA?.showToast?.('Report Export Failed', err.message, '✗', true);
      if (btn) { btn.textContent = '⬇ Export Report (HTML)'; btn.disabled = false; }
    }
  }

  document.getElementById('report-export-btn')?.addEventListener('click', exportReport);

  // Cheap live update on every snapshot tick (only while the tab is visible).
  window.addEventListener('vka:snapshot', e => { if (isTabActive()) updateLive(e.detail); });
  // Full refresh (live + reference data, if not already loaded) on tab open.
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab === 'report') refresh(); });
  // New log opened — reference data (YoY/Pace) needs to be refetched for it.
  window.addEventListener('vka:loaded', () => { _refLoaded = false; });
})();
