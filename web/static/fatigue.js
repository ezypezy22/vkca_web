/**
 * fatigue.js — Operator Fatigue Analysis
 * Matches original: per-hour rate chart with dead-zone shading,
 * nap schedule advisory, and per-operator on/off time cards.
 */
;(function () {
  'use strict';
  const C = {
    accent:'#00d4aa', accent2:'#ff6b35', accent3:'#f0c040',
    green:'#2ed573',  red:'#ff4757',     muted:'#8b949e',
    bg3:'#21262d',    fg:'#e6edf3',
  };
  const OP_PALETTE = ['#00d4aa','#f0c040','#ff6b35','#a78bfa',
                      '#60a5fa','#34d399','#f87171','#fbbf24'];

  let rateChart   = null;
  let opChart     = null;

  function update(snap) {
    if (!snap) return;
    renderOpCards(snap.operator_times || []);
    renderRateChart(snap);
    renderAdvice(snap);
  }

  // ── Per-operator stat cards ────────────────────────────────────────────────
  function fmtH(m) {
    const h = Math.floor(m/60), mm = Math.round(m%60);
    return h ? `${h}h ${mm}m` : `${mm}m`;
  }

  function renderOpCards(ops) {
    const wrap = document.getElementById('fatigue-cards'); if (!wrap) return;
    wrap.innerHTML = '';
    if (!ops.length) {
      wrap.innerHTML = `<div style="color:var(--muted);font-family:var(--font-mono);font-size:0.85em;padding:8px">
        No operator time data available.</div>`;
      return;
    }
    ops.forEach((op, i) => {
      const col    = OP_PALETTE[i % OP_PALETTE.length];
      const onPct  = op.span_minutes > 0
        ? ((op.on_minutes / op.span_minutes) * 100).toFixed(0) : 0;
      const rate   = op.on_minutes > 0
        ? ((op.qsos || 0) / (op.on_minutes / 60)).toFixed(1) : '—';

      const div = document.createElement('div');
      div.className = 'fatigue-card';
      div.style.borderTopColor = col;
      div.innerHTML = `
        <div class="fatigue-op" style="color:${col}">${escapeHtmlF(op.operator || '—')}</div>
        <div class="fatigue-stat-row">
          <div class="fatigue-stat">
            <div class="fatigue-stat-val">${(op.qsos||0).toLocaleString()}</div>
            <div class="fatigue-stat-label">QSOs</div>
          </div>
          <div class="fatigue-stat">
            <div class="fatigue-stat-val" style="color:${C.green}">${fmtH(op.on_minutes||0)}</div>
            <div class="fatigue-stat-label">On Air</div>
          </div>
          <div class="fatigue-stat">
            <div class="fatigue-stat-val" style="color:${C.muted}">${fmtH(op.off_minutes||0)}</div>
            <div class="fatigue-stat-label">Off / Break</div>
          </div>
          <div class="fatigue-stat">
            <div class="fatigue-stat-val" style="color:${C.accent3}">${rate}</div>
            <div class="fatigue-stat-label">Q/hr on-air</div>
          </div>
        </div>
        <div class="fatigue-prog-wrap">
          <div class="fatigue-prog-bar" style="width:${onPct}%;background:${col}"></div>
        </div>
        <div class="fatigue-prog-label">${onPct}% on-air efficiency (${op.sessions||0} sessions)</div>`;
      wrap.appendChild(div);
    });
  }

  // ── Hourly rate chart with dead-zone shading ───────────────────────────────
  function renderRateChart(snap) {
    const canvas = document.getElementById('chart-fatigue'); if (!canvas) return;
    const sl     = snap.sparklines || {};
    const qsos   = sl.qsos || [];
    if (!qsos.length) return;

    // Compute dead zones: hours where rate < 50% of average
    const nonZero  = qsos.filter(v => v > 0);
    const avg      = nonZero.length ? nonZero.reduce((a,b)=>a+b,0)/nonZero.length : 0;
    const thresh   = avg * 0.5;
    const deadZone = qsos.map((v, i) => (v > 0 && v < thresh) ? v : null);

    const labels = qsos.map((_, i) => String(i).padStart(2,'0'));

    if (rateChart) { rateChart.destroy(); rateChart = null; }

    rateChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'QSOs / hr',
            data: qsos,
            backgroundColor: qsos.map((v, i) => {
              if (v === 0) return C.bg3;
              if (v < thresh && v > 0) return C.red + '88';
              const t = Math.min(v / (avg * 2), 1);
              return v >= avg ? C.accent + 'cc' : C.accent3 + '88';
            }),
            borderRadius: 2,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 500 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: C.bg3, bodyColor: C.fg,
            titleColor: C.accent, borderColor: C.bg3, borderWidth: 1,
            callbacks: {
              title:  items => `Hour ${items[0].label}`,
              label:  item  => ` ${item.raw} QSOs`,
              afterLabel: item => {
                const v = item.raw;
                if (v === 0)       return ' (no QSOs)';
                if (v < thresh)    return ` ⚠ Below threshold (avg: ${avg.toFixed(0)})`;
                if (v >= avg*1.5)  return ` ★ High rate hour`;
                return '';
              },
            },
          },
          // Dead zone annotation via custom afterDraw
        },
        scales: {
          x: { ticks: { color: qsos.map((v,i) => v < thresh && v > 0 ? C.red : C.muted),
                         font: { size: 9 } }, grid: { color: C.bg3+'60' } },
          y: { ticks: { color: C.muted, font: { size: 9 } },
               grid: { color: C.bg3+'60' }, beginAtZero: true,
               title: { display: true, text: 'QSOs / hour', color: C.muted, font: { size: 9 } } },
        },
      },
      plugins: [{
        // Draw average line and ZZZ annotations
        id: 'fatigue-overlay',
        afterDraw(chart) {
          const { ctx, scales: { x, y } } = chart;
          if (!avg) return;

          // Average line
          const yAvg = y.getPixelForValue(avg);
          ctx.save();
          ctx.strokeStyle = C.accent3 + 'cc';
          ctx.lineWidth   = 1.5;
          ctx.setLineDash([5, 3]);
          ctx.beginPath();
          ctx.moveTo(x.left,  yAvg);
          ctx.lineTo(x.right, yAvg);
          ctx.stroke();
          ctx.fillStyle = C.accent3;
          ctx.font      = '9px Consolas';
          ctx.fillText(`avg ${avg.toFixed(0)} Q/hr`, x.right - 80, yAvg - 4);

          // Threshold line
          const yThr = y.getPixelForValue(thresh);
          ctx.strokeStyle = C.red + '66';
          ctx.lineWidth   = 1;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(x.left,  yThr);
          ctx.lineTo(x.right, yThr);
          ctx.stroke();

          // ZZZ labels on dead zones
          ctx.setLineDash([]);
          ctx.fillStyle = C.red;
          ctx.font      = 'bold 9px Consolas';
          ctx.textAlign = 'center';
          qsos.forEach((v, i) => {
            if (v > 0 && v < thresh) {
              const px = x.getPixelForValue(i);
              ctx.fillText('ZZZ', px, y.top + 12);
            }
          });
          ctx.restore();
        },
      }],
    });
  }

  // ── Nap-schedule advisory ──────────────────────────────────────────────────
  function renderAdvice(snap) {
    const el = document.getElementById('fatigue-advice'); if (!el) return;
    const sl = snap.sparklines || {};
    const qsos = sl.qsos || [];
    if (!qsos.length) { el.textContent = 'Load a contest log to generate fatigue advice.'; return; }

    const nonZero = qsos.filter(v => v > 0);
    const avg     = nonZero.length ? nonZero.reduce((a,b)=>a+b,0)/nonZero.length : 0;
    const thresh  = avg * 0.5;

    // Find consecutive dead-zone runs
    const deadHours = qsos.reduce((acc, v, i) => { if (v > 0 && v < thresh) acc.push(i); return acc; }, []);
    const runs = [];
    let runStart = null, runEnd = null;
    deadHours.forEach(h => {
      if (runStart === null) { runStart = h; runEnd = h; }
      else if (h === runEnd + 1) { runEnd = h; }
      else { runs.push([runStart, runEnd]); runStart = h; runEnd = h; }
    });
    if (runStart !== null) runs.push([runStart, runEnd]);

    const sigRuns  = runs.filter(([s, e]) => e - s + 1 >= 2);
    const soloRuns = runs.filter(([s, e]) => e - s + 1 === 1);

    // Best hours
    const sortedHours = qsos
      .map((v, i) => ({ h: i, v }))
      .filter(x => x.v > 0)
      .sort((a, b) => b.v - a.v);
    const bestHours = sortedHours.slice(0, 3).map(x => `${String(x.h).padStart(2,'0')}:00 UTC (${x.v} Q/hr)`);

    let advice = '';
    if (sigRuns.length) {
      const runStrs = sigRuns.map(([s,e]) => `${String(s).padStart(2,'0')}:00–${String(e+1).padStart(2,'0')}:00 UTC`);
      advice += `⚠ Consistent crash windows: ${runStrs.join(', ')}. Consider scheduling a nap to cover these.  `;
    }
    if (soloRuns.length) {
      const soloStrs = soloRuns.map(([s]) => `${String(s).padStart(2,'0')}:00`);
      advice += `Single-hour dips at ${soloStrs.join(', ')} UTC — worth watching.  `;
    }
    if (!runs.length) {
      advice = 'No significant dead zones detected. Your rate is consistent — great operating!  ';
    }
    if (bestHours.length) {
      advice += `★ Peak hours: ${bestHours.join(',  ')}.`;
    }

    el.textContent = advice;
  }

  window.addEventListener('vka:snapshot', e => update(e.detail));
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab === 'fatigue') {
      const snap = window.VKA.lastSnap();
      if (snap) update(snap);
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // ── Cross-year fatigue profile (UTC-hour-of-day, multi-contest) ────────
  // Mirrors the old desktop app's Fatigue tab: per-year hourly rate lines
  // plus a bold cross-year mean, dead-zone shading, and a nap advisory.
  // ═══════════════════════════════════════════════════════════════════════
  const FATIGUE_PALETTE = ['#00d4aa','#ff6b35','#f0c040','#2ed573','#64b5f6',
                            '#e040fb','#ff5252','#69f0ae','#ea80fc','#80d8ff'];
  const BAND_ORDER = ["160M","80M","60M","40M","30M","20M","17M","15M","12M","10M","6M","2M","70CM"];

  let _fContests       = [];
  let _fLoaded         = false;
  let yoyFatigueChart  = null;

  const escapeHtmlF = window.VKA.escapeHtml;

  async function loadFatigueYoy() {
    const msg     = document.getElementById('fatigue-yoy-msg');
    const content = document.getElementById('fatigue-yoy-content');
    try {
      const res  = await fetch('/api/fatigue');
      const data = await res.json();
      _fContests = data.contests || [];
      _fLoaded   = true;
      if (!_fContests.length) {
        if (content) content.style.display = 'none';
        if (msg) {
          msg.style.display = 'block';
          msg.textContent = "Load a log file to begin. Use '+ Add Log File' to add more years for cross-year analysis.";
        }
        return;
      }
      if (msg)     msg.style.display = 'none';
      if (content) content.style.display = '';
      populateFatigueContestSelect();
      redrawFatigueYoy();
    } catch (e) {
      if (msg) { msg.style.display = 'block'; msg.textContent = 'Failed to load fatigue data: ' + e.message; }
    }
  }

  function populateFatigueContestSelect() {
    const sel = document.getElementById('fatigue-contest-select');
    if (!sel) return;
    const names = [...new Set(_fContests.map(c => c.name))].sort();
    const current = sel.value;
    sel.innerHTML = '<option value="__all__">— all —</option>' +
      names.map(n => `<option value="${escapeHtmlF(n)}">${escapeHtmlF(n)}</option>`).join('');
    if (names.length === 1) sel.value = names[0];
    else if ([...sel.options].some(o => o.value === current)) sel.value = current;
    else sel.value = '__all__';
  }

  function fatigueFilteredContests() {
    const sel = document.getElementById('fatigue-contest-select');
    const val = sel ? sel.value : '__all__';
    return val === '__all__' ? _fContests : _fContests.filter(c => c.name === val);
  }

  function populateFatigueBandSelect(filtered) {
    const sel = document.getElementById('fatigue-band-select');
    if (!sel) return;
    const bands = new Set();
    filtered.forEach(c => Object.keys(c.hour_by_band || {}).forEach(b => bands.add(b)));
    const sorted = [...bands].sort((a, b) => {
      const ia = BAND_ORDER.indexOf(a.toUpperCase()), ib = BAND_ORDER.indexOf(b.toUpperCase());
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
    const current = sel.value;
    sel.innerHTML = '<option value="__all__">All bands</option>' +
      sorted.map(b => `<option value="${escapeHtmlF(b)}">${escapeHtmlF(b)}</option>`).join('');
    sel.value = [...sel.options].some(o => o.value === current) ? current : '__all__';
  }

  function ratesForContest(ct, bandFilter) {
    if (bandFilter === '__all__') return ct.hour_all.slice();
    return (ct.hour_by_band && ct.hour_by_band[bandFilter])
      ? ct.hour_by_band[bandFilter].slice() : new Array(24).fill(0);
  }

  function deadZoneHours(rates, avgRate, threshPct) {
    if (avgRate <= 0) return [];
    const thresh = avgRate * threshPct / 100;
    const out = [];
    for (let h = 0; h < 24; h++) if (rates[h] < thresh) out.push(h);
    return out;
  }

  function consecutiveBlocks(hours) {
    if (!hours.length) return [];
    const runs = [];
    let start = hours[0], prev = hours[0];
    for (let i = 1; i < hours.length; i++) {
      const h = hours[i];
      if (h === prev + 1) prev = h;
      else { runs.push([start, prev]); start = prev = h; }
    }
    runs.push([start, prev]);
    return runs;
  }

  function fatigueAdviceText(deadRuns) {
    if (!deadRuns.length) {
      return "No significant dead zones detected at the current threshold. Either your rate is " +
             "consistent across the clock or you haven't loaded enough contest years for a pattern to emerge.";
    }
    const sig  = deadRuns.filter(([s, e]) => (e - s + 1) >= 2);
    const solo = deadRuns.filter(([s, e]) => (e - s + 1) === 1);
    const parts = [];
    if (sig.length) {
      const strs = sig.map(([s, e]) => `${String(s).padStart(2,'0')}:00–${String(e+1).padStart(2,'0')}:00 UTC`);
      parts.push(`⚠ Consistent crash window${sig.length > 1 ? 's' : ''}: ${strs.join('  and  ')}. ` +
                 `Consider scheduling a nap to cover ${sig.length === 1 ? strs[0] : 'these windows'}.`);
    }
    if (solo.length) {
      const strs = solo.map(([s]) => `${String(s).padStart(2,'0')}:00`);
      parts.push(`Single-hour dips at ${strs.join(', ')} UTC — worth watching but may be contest-specific.`);
    }
    if (!parts.length) {
      parts.push('Dead zones found but none span ≥ 2 consecutive hours — no strong nap recommendation at the current threshold.');
    }
    return parts.join('   ');
  }

  function normaliseRates(rates, mode) {
    const active = rates.filter(v => v > 0);
    const avg = active.length ? active.reduce((a, b) => a + b, 0) / active.length : 1;
    if (mode === 'pct') return rates.map(v => v / avg * 100);
    if (mode === 'z') {
      const variance = active.length > 1
        ? active.reduce((a, b) => a + (b - avg) ** 2, 0) / active.length : 1;
      const std = Math.sqrt(variance) || 1;
      return rates.map(v => (v - avg) / std);
    }
    return rates.slice();
  }

  function redrawFatigueYoy() {
    const filtered = fatigueFilteredContests();
    populateFatigueBandSelect(filtered);
    const bandFilter = document.getElementById('fatigue-band-select')?.value || '__all__';
    const normMode    = document.getElementById('fatigue-norm-select')?.value || 'raw';
    const threshPct   = parseInt(document.getElementById('fatigue-thresh-input')?.value || '35', 10) || 35;

    const contestRates = filtered.map(ct => ({
      label: ct.label, year: ct.year, name: ct.name,
      rates: ratesForContest(ct, bandFilter),
    }));

    renderFatigueRoster(contestRates, threshPct);

    if (!contestRates.length) {
      if (yoyFatigueChart) { yoyFatigueChart.destroy(); yoyFatigueChart = null; }
      const el = document.getElementById('fatigue-yoy-advice');
      if (el) el.textContent = 'Load a log to generate advice.';
      return;
    }

    // Cross-year stack — raw (un-normalized) means drive dead-zone detection
    // regardless of display mode, matching the old app.
    const stacked = contestRates.map(c => c.rates);
    const activityMask = new Array(24).fill(false);
    for (let h = 0; h < 24; h++) activityMask[h] = stacked.some(r => r[h] > 0);
    const meanRatesRaw = new Array(24).fill(0);
    for (let h = 0; h < 24; h++) meanRatesRaw[h] = stacked.reduce((a, r) => a + r[h], 0) / stacked.length;

    const activeGlobal = [];
    for (let h = 0; h < 24; h++) if (activityMask[h]) activeGlobal.push(h);
    const overallAvg = activeGlobal.length
      ? activeGlobal.reduce((a, h) => a + meanRatesRaw[h], 0) / activeGlobal.length : 0;

    const deadHours = deadZoneHours(meanRatesRaw, overallAvg, threshPct).filter(h => activityMask[h]);
    const deadRuns  = consecutiveBlocks(deadHours.slice().sort((a, b) => a - b));

    const adviceEl = document.getElementById('fatigue-yoy-advice');
    if (adviceEl) adviceEl.textContent = fatigueAdviceText(deadRuns);

    renderFatigueChart(contestRates, activityMask, deadHours, deadRuns,
                        overallAvg, threshPct, normMode);
  }

  function renderFatigueRoster(contestRates, threshPct) {
    const tbody = document.getElementById('fatigue-yoy-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    contestRates.forEach((c, i) => {
      const col = FATIGUE_PALETTE[i % FATIGUE_PALETTE.length];
      const active = c.rates.filter(v => v > 0);
      const avg = active.length ? active.reduce((a, b) => a + b, 0) / active.length : 0;
      const dead = active.length ? deadZoneHours(c.rates, avg, threshPct).length : 0;
      const total = c.rates.reduce((a, b) => a + b, 0);
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:${col};font-weight:bold">${c.year || '?'}</td>
        <td>${escapeHtmlF(c.name)}</td>
        <td>${total.toLocaleString()}</td>
        <td>${avg.toFixed(1)}</td>
        <td style="color:${dead > 0 ? C.red : C.muted}">${dead}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  function renderFatigueChart(contestRates, activityMask, deadHours, deadRuns,
                               overallAvg, threshPct, normMode) {
    const canvas = document.getElementById('chart-fatigue-yoy');
    if (!canvas) return;
    if (yoyFatigueChart) { yoyFatigueChart.destroy(); yoyFatigueChart = null; }

    const yLabelMap  = { raw: 'QSOs / hour', pct: '% of personal avg', z: 'Z-score (σ)' };
    const yLabel      = yLabelMap[normMode] || 'QSOs / hour';
    const showLegend  = contestRates.length <= 10;

    // Normalize each year individually first (matches the old app), THEN
    // average the normalized arrays for the bold mean line.
    const normPerYear = contestRates.map(c => normaliseRates(c.rates, normMode));
    const datasets = contestRates.map((c, i) => {
      const col  = FATIGUE_PALETTE[i % FATIGUE_PALETTE.length];
      const norm = normPerYear[i];
      const data = norm.map((v, h) => (activityMask[h] || c.rates[h] > 0) ? v : null);
      return {
        label: String(c.year), borderColor: col + 'cc', data,
        borderWidth: 1, pointRadius: 0, tension: 0.25, fill: false,
      };
    });

    const meanNorm = [];
    for (let h = 0; h < 24; h++) {
      const vals = normPerYear.map(arr => arr[h]);
      meanNorm.push(vals.reduce((a, b) => a + b, 0) / vals.length);
    }
    datasets.push({
      label: 'Mean (all years)', borderColor: C.accent, backgroundColor: C.accent + '20',
      data: meanNorm.map((v, h) => activityMask[h] ? v : null),
      borderWidth: 3, pointRadius: 0, tension: 0.25, fill: 'origin',
    });

    const threshLine = normMode === 'pct' ? threshPct : (normMode === 'z' ? -1 : overallAvg * threshPct / 100);
    const avgLine     = normMode === 'pct' ? 100        : (normMode === 'z' ? 0  : overallAvg);

    yoyFatigueChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')), datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 300 }, spanGaps: false,
        interaction: { mode: 'nearest', intersect: false },
        plugins: {
          legend: { display: showLegend, position: 'top',
                    labels: { color: C.muted, font: { size: 8, family: 'Consolas' } } },
          tooltip: { backgroundColor: C.bg3, bodyColor: C.fg, titleColor: C.accent },
        },
        scales: {
          x: {
            ticks: {
              color: ctx => deadHours.includes(ctx.index) ? C.red : C.muted,
              font:  ctx => ({ size: 8, weight: deadHours.includes(ctx.index) ? 'bold' : 'normal' }),
            },
            grid: { color: C.bg3 + '60' },
            title: { display: true, text: 'UTC Hour', color: C.muted, font: { size: 9 } },
          },
          y: {
            ticks: { color: C.muted, font: { size: 8 } }, grid: { color: C.bg3 + '60' },
            title: { display: true, text: yLabel, color: C.muted, font: { size: 9 } },
          },
        },
      },
      plugins: [{
        id: 'fatigue-yoy-overlay',
        beforeDraw(chart) {
          const { ctx, chartArea: area, scales: { x } } = chart;
          const w = x.getPixelForValue(1) - x.getPixelForValue(0);
          ctx.save();
          const nightHours = [...Array(8).keys(), ...Array.from({ length: 4 }, (_, i) => 20 + i)];
          nightHours.forEach(h => {
            const cx = x.getPixelForValue(h);
            ctx.fillStyle = C.bg3 + '40';
            ctx.fillRect(cx - w / 2, area.top, w, area.bottom - area.top);
          });
          deadHours.forEach(h => {
            const cx = x.getPixelForValue(h);
            ctx.fillStyle = C.red + '1f';
            ctx.fillRect(cx - w / 2, area.top, w, area.bottom - area.top);
          });
          ctx.restore();
        },
        afterDraw(chart) {
          const { ctx, chartArea: area, scales: { x, y } } = chart;
          ctx.save();
          const yThresh = y.getPixelForValue(threshLine);
          ctx.strokeStyle = C.red; ctx.globalAlpha = 0.6; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
          ctx.beginPath(); ctx.moveTo(area.left, yThresh); ctx.lineTo(area.right, yThresh); ctx.stroke();
          const yAvg = y.getPixelForValue(avgLine);
          ctx.strokeStyle = C.green; ctx.globalAlpha = 0.5; ctx.lineWidth = 0.8; ctx.setLineDash([1, 3]);
          ctx.beginPath(); ctx.moveTo(area.left, yAvg); ctx.lineTo(area.right, yAvg); ctx.stroke();
          ctx.setLineDash([]); ctx.globalAlpha = 1;
          ctx.font = '7px Consolas'; ctx.textAlign = 'left';
          ctx.fillStyle = C.red;   ctx.fillText(`<${threshPct}%`, area.right - 32, yThresh - 3);
          ctx.fillStyle = C.green; ctx.fillText('avg', area.right - 32, yAvg - 3);

          ctx.font = 'bold 8px Consolas'; ctx.textAlign = 'center'; ctx.fillStyle = C.red;
          deadRuns.forEach(([s, e]) => {
            if (e - s + 1 >= 2) {
              const mid = (s + e) / 2;
              const px  = x.getPixelForValue(mid);
              ctx.fillText(`ZZZ ${String(s).padStart(2,'0')}–${String(e+1).padStart(2,'0')}`, px, area.top + 10);
            }
          });
          ctx.restore();
        },
      }],
    });
  }

  async function addFatigueLog() {
    const btn = document.getElementById('fatigue-add-log-btn');
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      const data = await window.VKA.browseFile();
      if (data.error || !data.path) return;
      const res2  = await fetch('/api/fatigue/add_log', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: data.path }),
      });
      const data2 = await res2.json();
      if (data2.error) { console.warn('Add fatigue log:', data2.error); return; }
      _fContests = data2.contests || [];
      _fLoaded   = true;
      const msg = document.getElementById('fatigue-yoy-msg');
      const content = document.getElementById('fatigue-yoy-content');
      if (msg)     msg.style.display = 'none';
      if (content) content.style.display = '';
      populateFatigueContestSelect();
      redrawFatigueYoy();
    } catch (e) { console.warn('Add fatigue log failed:', e); }
    finally { if (btn) { btn.disabled = false; btn.textContent = '+ Add Log File'; } }
  }

  async function clearFatigueLogs() {
    try {
      const res  = await fetch('/api/fatigue/clear_logs', { method: 'POST' });
      const data = await res.json();
      _fContests = data.contests || [];
      populateFatigueContestSelect();
      redrawFatigueYoy();
    } catch (e) { console.warn('Clear fatigue logs failed:', e); }
  }

  document.getElementById('fatigue-add-log-btn')?.addEventListener('click', addFatigueLog);
  document.getElementById('fatigue-clear-logs-btn')?.addEventListener('click', clearFatigueLogs);
  document.getElementById('fatigue-contest-select')?.addEventListener('change', redrawFatigueYoy);
  document.getElementById('fatigue-band-select')?.addEventListener('change', redrawFatigueYoy);
  document.getElementById('fatigue-norm-select')?.addEventListener('change', redrawFatigueYoy);
  document.getElementById('fatigue-thresh-input')?.addEventListener('change', redrawFatigueYoy);

  window.addEventListener('vka:loaded', () => { _fLoaded = false; loadFatigueYoy(); });
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab === 'fatigue' && !_fLoaded) loadFatigueYoy(); });
})();
