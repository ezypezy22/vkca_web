/**
 * yoy.js — Year on Year comparison tab
 * Cumulative score/QSO/mult trajectory overlay across contest-years, plus a
 * per-hour rate sub-chart, a roster table with deltas, and a plain-English
 * insight summary. Mirrors the old desktop app's "Year on Year" tab.
 */
;(function () {
  'use strict';

  const PALETTE = ['#00d4aa','#ff6b35','#f0c040','#2ed573','#64b5f6',
                    '#e040fb','#ff5252','#69f0ae','#ea80fc','#80d8ff'];
  const MUTED = '#8b949e', GRID = '#21262d80', FG = '#e6edf3';

  const METRIC_KEYS   = { score:'cum_score', qsos:'cum_qsos', mults:'cum_mults' };
  const METRIC_LABELS = { score:'Score', qsos:'Cumulative QSOs',
                           mults:'Cumulative Mults', rate:'QSOs/hr' };

  let _series  = [];          // raw series from the API
  let _hidden  = new Set();   // keys hidden by the user clicking a roster row
  let _loaded  = false;
  let trajChart = null, rateChart = null;

  function colourFor(key) {
    const idx = _series.findIndex(s => s.key === key);
    return PALETTE[Math.max(idx, 0) % PALETTE.length];
  }

  const escapeHtml = window.VKA.escapeHtml;

  function showMsg(text) {
    const el = document.getElementById('yoy-msg');
    if (el) { el.textContent = text; el.style.display = 'block'; }
  }

  // ── Load ──────────────────────────────────────────────────────────────────
  async function load() {
    const wrap    = document.getElementById('yoy-loading');
    const msg     = document.getElementById('yoy-msg');
    const content = document.getElementById('yoy-content');
    if (wrap) wrap.style.display = 'flex';
    if (msg)  msg.style.display  = 'none';
    try {
      const res  = await fetch('/api/yoy');
      const data = await res.json();
      _series = data.series || [];
      if (wrap) wrap.style.display = 'none';
      if (!_series.length) {
        if (content) content.style.display = 'none';
        showMsg('No contest history found. Click "+ Add Log File" to load other years for comparison.');
        return;
      }
      if (content) content.style.display = '';
      _loaded = true;
      populateContestFilter();
      redraw();
    } catch (e) {
      if (wrap) wrap.style.display = 'none';
      showMsg('Failed to load YOY data: ' + e.message);
    }
  }

  function populateContestFilter() {
    const sel = document.getElementById('yoy-contest-select');
    if (!sel) return;
    const nameToDisplay = {};
    _series.forEach(s => {
      if (!(s.contest_name in nameToDisplay)) nameToDisplay[s.contest_name] = s.display_name || s.contest_name;
    });
    const keys = Object.keys(nameToDisplay).sort((a, b) => nameToDisplay[a].localeCompare(nameToDisplay[b]));
    const current = sel.value;
    sel.innerHTML = '<option value="__all__">— all —</option>' +
      keys.map(k => `<option value="${escapeHtml(k)}">${escapeHtml(nameToDisplay[k])}</option>`).join('');
    if (keys.length === 1) sel.value = keys[0];
    else if ([...sel.options].some(o => o.value === current)) sel.value = current;
    else sel.value = '__all__';
  }

  function filteredSeries() {
    const sel = document.getElementById('yoy-contest-select');
    const val = sel ? sel.value : '__all__';
    const list = val === '__all__' ? _series : _series.filter(s => s.contest_name === val);
    return [...list].sort((a, b) => (a.year || 0) - (b.year || 0));
  }

  function redraw() {
    if (!_loaded) return;
    const filtered = filteredSeries();
    renderTable(filtered);
    renderCharts(filtered);
    renderInsight(filtered);
  }

  // ── Roster table ──────────────────────────────────────────────────────────
  function renderTable(filtered) {
    const tbody = document.getElementById('yoy-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    let prevScore = null, prevQsos = null;
    filtered.forEach(s => {
      const col     = colourFor(s.key);
      const visible = !_hidden.has(s.key);
      let dScore = '', dQsos = '';
      if (prevScore != null) {
        const ds = s.final_score - prevScore, dq = s.final_qsos - prevQsos;
        dScore = (ds >= 0 ? '+' : '−') + Math.abs(ds).toLocaleString();
        dQsos  = (dq >= 0 ? '+' : '−') + Math.abs(dq);
      }
      const tr = document.createElement('tr');
      tr.style.cursor  = 'pointer';
      tr.style.opacity = visible ? '1' : '0.4';
      tr.innerHTML = `
        <td><span style="color:${col}">${visible ? '●' : '○'}</span></td>
        <td style="color:${col};font-weight:bold">${s.year || '?'}</td>
        <td>${escapeHtml(s.display_name || s.contest_name)}</td>
        <td style="font-weight:bold">${(s.final_score || 0).toLocaleString()}</td>
        <td style="color:var(--muted)">${dScore}</td>
        <td>${(s.final_qsos || 0).toLocaleString()}</td>
        <td style="color:var(--muted)">${dQsos}</td>
        <td>${(s.final_mults || 0).toLocaleString()}</td>
        <td>${(s.total_hrs || 0).toFixed(1)}</td>`;
      tr.addEventListener('click', () => {
        if (_hidden.has(s.key)) _hidden.delete(s.key); else _hidden.add(s.key);
        redraw();
      });
      frag.appendChild(tr);
      prevScore = s.final_score; prevQsos = s.final_qsos;
    });
    tbody.appendChild(frag);
  }

  // ── Charts ────────────────────────────────────────────────────────────────
  function renderCharts(filtered) {
    const metric     = document.getElementById('yoy-metric-select')?.value || 'score';
    const xmode      = document.getElementById('yoy-xmode-select')?.value || 'elapsed';
    const normalize  = !!document.getElementById('yoy-normalize')?.checked;
    const annotate   = !!document.getElementById('yoy-annotate')?.checked;
    const useElapsed = xmode === 'elapsed';

    const visible  = filtered.filter(s => !_hidden.has(s.key));
    const emptyEl  = document.getElementById('yoy-chart-empty');
    const chartWrap = document.getElementById('yoy-chart-wrap');
    const rateWrap = document.getElementById('yoy-rate-wrap');

    if (trajChart) { trajChart.destroy(); trajChart = null; }
    if (rateChart) { rateChart.destroy(); rateChart = null; }

    if (!visible.length) {
      if (emptyEl)   emptyEl.style.display = '';
      if (chartWrap) chartWrap.style.display = 'none';
      return;
    }
    if (emptyEl)   emptyEl.style.display = 'none';
    if (chartWrap) chartWrap.style.display = '';

    const canvas = document.getElementById('chart-yoy-trajectory');
    if (!canvas) return;

    const datasets = visible.map(s => {
      const col = colourFor(s.key);
      let xs, ys;
      if (metric === 'rate') {
        xs = useElapsed ? s.rate_hrs : s.utc_rate_hrs;
        ys = useElapsed ? s.rate_counts : s.utc_rate_counts;
      } else {
        xs = useElapsed ? s.elapsed_hrs : s.utc_hrs;
        ys = s[METRIC_KEYS[metric]];
      }
      let yy = ys;
      if (normalize) {
        const denom = metric === 'rate' ? Math.max(...ys, 1) : (ys[ys.length - 1] || 1);
        yy = ys.map(v => v / denom * 100);
      }
      return {
        label: s.label, borderColor: col, backgroundColor: col + '18',
        data: xs.map((x, i) => ({ x, y: yy[i] })),
        borderWidth: 2, pointRadius: 0,
        tension: metric === 'rate' ? 0 : 0.15,
        stepped: metric === 'rate' ? 'middle' : false,
        fill: metric !== 'rate',
      };
    });

    const yLabel = METRIC_LABELS[metric] + (normalize ? ' (% of final)' : '');

    trajChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 350 },
        interaction: { mode: 'nearest', intersect: false },
        plugins: {
          legend: { display: true, position: 'top',
                    labels: { color: MUTED, font: { size: 9, family: 'Consolas' } } },
          tooltip: { backgroundColor: '#21262d', bodyColor: FG, titleColor: '#00d4aa' },
        },
        scales: {
          x: { type: 'linear',
               title: { display: true, text: useElapsed ? 'Hours elapsed' : 'UTC hour',
                        color: MUTED, font: { size: 9 } },
               ticks: { color: MUTED, font: { size: 8 } }, grid: { color: GRID },
               min: 0, max: useElapsed ? undefined : 24 },
          y: { ticks: { color: MUTED, font: { size: 8 } }, grid: { color: GRID },
               title: { display: true, text: yLabel, color: MUTED, font: { size: 9 } } },
        },
      },
    });

    // Endpoint annotations (year + final value) — drawn as a tiny overlay
    // plugin rather than per-point labels, kept simple via Chart.js afterDraw.
    if (annotate && metric !== 'rate') {
      trajChart.options.plugins.tooltip.enabled = true;
      const ctx = canvas.getContext('2d');
      const origDraw = trajChart.draw.bind(trajChart);
      trajChart.draw = function () {
        origDraw();
        const area = trajChart.chartArea;
        if (!area) return;
        ctx.save();
        ctx.font = '10px Consolas, monospace';
        ctx.textBaseline = 'middle';
        visible.forEach((s, i) => {
          const ds = trajChart.data.datasets[i];
          const last = ds.data[ds.data.length - 1];
          if (!last) return;
          const px = trajChart.scales.x.getPixelForValue(last.x);
          const py = trajChart.scales.y.getPixelForValue(last.y);
          if (px < area.left || px > area.right) return;
          ctx.fillStyle = ds.borderColor;
          const valTxt = last.y.toLocaleString(undefined, { maximumFractionDigits: 0 });
          ctx.fillText(` ${s.year}: ${valTxt}${normalize ? '%' : ''}`, px + 4, py);
        });
        ctx.restore();
      };
      trajChart.update();
    }

    // Rate sub-chart — skipped when the main metric already IS the rate view.
    const rateCanvas = document.getElementById('chart-yoy-rate');
    if (metric === 'rate' || !rateCanvas) {
      if (rateWrap) rateWrap.style.display = 'none';
      return;
    }
    if (rateWrap) rateWrap.style.display = '';

    const rateDatasets = visible.map(s => {
      const col = colourFor(s.key);
      const rx = useElapsed ? s.rate_hrs : s.utc_rate_hrs;
      const ry = useElapsed ? s.rate_counts : s.utc_rate_counts;
      return { label: s.label, borderColor: col, data: rx.map((x, i) => ({ x, y: ry[i] })),
               borderWidth: 1.3, pointRadius: 0, stepped: 'middle', fill: false };
    });
    rateChart = new Chart(rateCanvas.getContext('2d'), {
      type: 'line',
      data: { datasets: rateDatasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: true } },
        scales: {
          x: { type: 'linear', ticks: { color: MUTED, font: { size: 7 } }, grid: { display: false },
               min: 0, max: useElapsed ? undefined : 24 },
          y: { ticks: { color: MUTED, font: { size: 7 } }, grid: { color: GRID },
               title: { display: true, text: 'QSOs/hr', color: MUTED, font: { size: 8 } } },
        },
      },
    });
  }

  // ── Insight summary ───────────────────────────────────────────────────────
  function renderInsight(filtered) {
    const el = document.getElementById('yoy-insight-text');
    if (!el) return;
    const visible = filtered.filter(s => !_hidden.has(s.key));
    if (visible.length < 2) {
      el.textContent = 'Load two or more contest years (same contest) to compare trajectories.';
      return;
    }
    const sorted = [...visible].sort((a, b) => (a.year || 0) - (b.year || 0));
    const best  = sorted.reduce((a, b) => (b.final_score > a.final_score ? b : a));
    const first = sorted[0], last = sorted[sorted.length - 1];

    const parts = [];
    parts.push(`Best year: ${best.year} — ${best.display_name || best.contest_name} ` +
      `(${(best.final_score || 0).toLocaleString()} pts, ${best.final_qsos || 0} QSOs, ${best.final_mults || 0} mults).`);

    if (last.final_score !== first.final_score) {
      const up  = last.final_score > first.final_score;
      const pct = Math.abs(last.final_score - first.final_score) / Math.max(first.final_score, 1) * 100;
      parts.push(`Score trend ${up ? '↑ +' : '↓ −'}${pct.toFixed(0)}% from ${first.year} to ${last.year}.`);
    } else {
      parts.push(`Score unchanged from ${first.year} to ${last.year}.`);
    }

    const bestEff  = sorted.reduce((a, b) => (b.final_mults > a.final_mults ? b : a));
    const worstEff = sorted.reduce((a, b) => (b.final_mults < a.final_mults ? b : a));
    if (bestEff.year !== worstEff.year) {
      parts.push(`Multiplier range: ${worstEff.final_mults} (${worstEff.year}) → ${bestEff.final_mults} (${bestEff.year}).`);
    }

    const hrsList = sorted.filter(s => s.total_hrs > 0);
    if (hrsList.length) {
      const maxHr = hrsList.reduce((a, b) => (b.total_hrs > a.total_hrs ? b : a));
      const minHr = hrsList.reduce((a, b) => (b.total_hrs < a.total_hrs ? b : a));
      if (maxHr.total_hrs - minHr.total_hrs > 1) {
        parts.push(`Operating time varied: ${minHr.total_hrs.toFixed(1)} hrs (${minHr.year}) ` +
          `to ${maxHr.total_hrs.toFixed(1)} hrs (${maxHr.year}).`);
      }
    }
    el.textContent = parts.join('   ');
  }

  // ── Add / clear extra log files ──────────────────────────────────────────
  async function addLog() {
    const btn = document.getElementById('yoy-add-log-btn');
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      const data = await window.VKA.browseFile();
      if (data.error) { showMsg(data.error); return; }
      if (!data.path) return;
      const res2  = await fetch('/api/yoy/add_log', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: data.path }),
      });
      const data2 = await res2.json();
      if (data2.error) { showMsg(data2.error); return; }
      _series = data2.series || [];
      _loaded = true;
      const msg = document.getElementById('yoy-msg');
      const content = document.getElementById('yoy-content');
      if (msg) msg.style.display = 'none';
      if (content) content.style.display = '';
      populateContestFilter();
      redraw();
    } catch (e) {
      showMsg('Add log failed: ' + e.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '+ Add Log File'; }
    }
  }

  async function clearLogs() {
    try {
      const res  = await fetch('/api/yoy/clear_logs', { method: 'POST' });
      const data = await res.json();
      _series = data.series || [];
      _hidden.clear();
      populateContestFilter();
      redraw();
    } catch (e) { console.warn('YOY clear logs failed:', e); }
  }

  document.getElementById('yoy-add-log-btn')?.addEventListener('click', addLog);
  document.getElementById('yoy-clear-logs-btn')?.addEventListener('click', clearLogs);
  document.getElementById('yoy-contest-select')?.addEventListener('change', redraw);
  document.getElementById('yoy-metric-select')?.addEventListener('change', redraw);
  document.getElementById('yoy-xmode-select')?.addEventListener('change', redraw);
  document.getElementById('yoy-normalize')?.addEventListener('change', redraw);
  document.getElementById('yoy-annotate')?.addEventListener('change', redraw);

  // Reload from scratch whenever a new log is opened; lazily load the first
  // time the tab is visited. Deliberately NOT tied to vka:snapshot — trajectory
  // rebuilds are heavier than the old per-tick summary and only the current
  // year changes during a live session anyway (matches the old desktop app,
  // which only refreshed on log-load and tab-switch).
  window.addEventListener('vka:loaded', () => { _loaded = false; _hidden.clear(); load(); });
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab === 'yoy' && !_loaded) load(); });
})();
