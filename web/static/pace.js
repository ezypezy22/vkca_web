/**
 * pace.js — Pace Tracker: cumulative QSO trajectory + rate chart + targets + alarm
 * Matches the original tkinter implementation: shows live vs historical pace.
 */
;(function () {
  'use strict';
  const C = { accent:'#00d4aa', accent2:'#ff6b35', accent3:'#f0c040',
               green:'#2ed573', red:'#ff4757', muted:'#8b949e',
               bg3:'#21262d', fg:'#e6edf3' };

  let trajChart = null;
  let rateChart = null;
  let _snap     = null;

  function update(snap) {
    if (!snap) return;
    _snap = snap;
    updateKPIs(snap);
    updateTrajectory(snap);
    updateTargets(snap);
    updateMyTarget(snap);
    refreshBandAdvice();
  }

  // ── Band-value advisory (best band right now, when the plugin supports it) ─
  let _bandAdvice = null;
  let _bandAdviceFetching = false;

  async function refreshBandAdvice() {
    if (_bandAdviceFetching) return;
    _bandAdviceFetching = true;
    try {
      const r = await fetch('/api/band_advice');
      _bandAdvice = await r.json();
    } catch (e) { /* keep stale value */ }
    _bandAdviceFetching = false;
    renderBandAdvice();
  }

  function renderBandAdvice() {
    const el = document.getElementById('pace-band-advice');
    if (!el) return;
    if (!_bandAdvice || !_bandAdvice.recommended_band) { el.style.display = 'none'; return; }
    el.style.display = '';
    el.textContent = `💡 Best band right now: ${_bandAdvice.recommended_band} — ${_bandAdvice.reason}`;
  }

  // ── KPI cards ──────────────────────────────────────────────────────────────
  function set(id, v) { const el=document.getElementById(id); if(el) el.textContent=v; }

  function updateKPIs(snap) {
    const pb   = snap.personal_bests || {};
    const ss   = snap.session_status || {};
    const rem  = ss.total_remaining_mins ?? ss.remaining_mins ?? 0;
    const remH = (rem / 60).toFixed(1);
    const cur  = pb.current_hour_rate || 0;
    const prev = pb.prev_hour_rate    || 0;
    const best = pb.best_hour_rate    || 0;

    // Projected QSOs at current rate
    const valid       = snap.valid || 0;
    const projQsos    = valid + cur * (rem / 60);
    const multRatio   = valid > 0 ? ((snap.worked||0) / valid) : 0;
    const projMults   = Math.round((snap.worked||0) + multRatio * (projQsos - valid));
    const ptsPerQso   = valid > 0 ? (snap.score||0) / valid : 0;
    const projScore   = Math.round(ptsPerQso * projQsos);

    set('pace-cur-rate',  cur);
    set('pace-prev-rate', prev);
    set('pace-best-rate', best);
    set('pace-rem-hrs',   remH + 'h');
    set('pace-proj-qsos', Math.round(projQsos).toLocaleString());
    set('pace-proj-mults',projMults.toLocaleString());
    set('pace-proj-score',projScore.toLocaleString());

    // Alarm banner
    const alarm = document.getElementById('pace-alarm');
    if (alarm) {
      const bandHint = (_bandAdvice && _bandAdvice.recommended_band)
        ? ` (${_bandAdvice.recommended_band} is currently your best value band.)` : '';
      if (cur < prev * 0.7 && cur > 0 && rem > 0) {
        alarm.style.display = 'block';
        alarm.textContent   = `⚠ Rate dropping — ${cur} Q/hr vs ${prev} Q/hr last hour. Consider changing bands or calling CQ more aggressively.${bandHint}`;
        alarm.style.borderColor = C.red;
        alarm.style.color       = C.red;
      } else if (cur === 0 && valid > 0 && rem > 30) {
        alarm.style.display = 'block';
        alarm.textContent   = `⚠ No QSOs in the current hour. Check propagation or try a new band.${bandHint}`;
        alarm.style.borderColor = C.accent3;
        alarm.style.color       = C.accent3;
      } else {
        alarm.style.display = 'none';
      }
    }
  }

  // ── Trajectory + projection chart ─────────────────────────────────────────
  function updateTrajectory(snap) {
    const canvas = document.getElementById('chart-pace-proj'); if (!canvas) return;
    const sl     = snap.sparklines || {};
    const ss     = snap.session_status || {};
    const pb     = snap.personal_bests || {};

    const historical = sl.running_score || [];
    if (!historical.length) return;

    const curRate  = pb.current_hour_rate || 0;
    const remMins  = ss.total_remaining_mins ?? ss.remaining_mins ?? 0;
    const remBuckets = Math.ceil(remMins / 60);
    const ptsPerQso  = (snap.valid||0) > 0 ? (snap.score||0) / (snap.valid||0) : 0;
    const multRatio  = (snap.valid||0) > 0 ? (snap.worked||0) / (snap.valid||0) : 0;

    // Build projected series (continues from last historical point)
    const lastScore = snap.score || 0;
    const projScores = [];
    let running = lastScore;
    for (let i = 0; i < remBuckets; i++) {
      // Scale by the bucket's actual fractional remaining minutes, matching
      // updateKPIs()'s projQsos calculation — previously every bucket added
      // a full hour of curRate even for a partial final bucket, so with
      // e.g. 1 minute left in the contest the trajectory line jumped by a
      // whole hour's worth of points while the KPI tile right next to it
      // barely moved (see issue #58).
      const bucketMins = Math.min(60, remMins - i * 60);
      const addQsos  = curRate * (bucketMins / 60);
      const addMults = Math.round(addQsos * multRatio);
      running += addQsos * ptsPerQso;
      projScores.push(Math.round(running));
    }

    const histLabels = historical.map((_, i) => String(i).padStart(2,'0'));
    const projLabels = Array.from({length: remBuckets}, (_, i) =>
      `+${i+1}h`);
    const allLabels  = [...histLabels, ...projLabels];

    // Same glowing-sparkline technique as overview.js's makeSparkline() /
    // rate.js's Mults-per-hour chart: canvas drop-shadow filter + gradient
    // fill under a monotone line. Score only ever climbs, so the last
    // actual-data point doubles as both "peak" and "current position" —
    // one glowing dot showing exactly where "now" is on the trajectory.
    canvas.style.filter = `drop-shadow(0 0 6px ${C.accent}80)`;
    const ctx  = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, canvas.height || 260);
    grad.addColorStop(0,    C.accent + '59');
    grad.addColorStop(0.65, C.accent + '14');
    grad.addColorStop(1,    C.accent + '00');

    const lastIdx = historical.length - 1;
    const actualData = [...historical, ...Array(remBuckets).fill(null)];
    const nowPointRadius = actualData.map((_, i) => i === lastIdx ? 5 : 0);
    const nowPointColour = actualData.map((_, i) => i === lastIdx ? C.accent : 'transparent');
    const nowPointBorder = actualData.map((_, i) => i === lastIdx ? '#fff' : 'transparent');
    const projData = [...Array(historical.length - 1).fill(null), lastScore, ...projScores];

    // Fixed 2-dataset shape (Actual/Projected) every redraw — mutate the
    // existing instance instead of destroy+recreate on every ~1.5s snapshot
    // tick (see issue #73).
    if (trajChart) {
      trajChart.data.labels = allLabels;
      const dsA = trajChart.data.datasets[0];
      dsA.data = actualData;
      dsA.backgroundColor = grad;
      dsA.pointRadius = nowPointRadius;
      dsA.pointBackgroundColor = nowPointColour;
      dsA.pointBorderColor = nowPointBorder;
      dsA.pointBorderWidth = actualData.map((_, i) => i === lastIdx ? 2 : 0);
      const dsB = trajChart.data.datasets[1];
      dsB.label = `Projected @ ${curRate}/hr`;
      dsB.data = projData;
      trajChart.update();
      return;
    }

    trajChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: allLabels,
        datasets: [
          {
            label: 'Actual Score',
            data: actualData,
            borderColor: C.accent,
            backgroundColor: grad,
            borderWidth: 2.5, fill: true, tension: 0,
            cubicInterpolationMode: 'monotone',
            borderCapStyle: 'round', borderJoinStyle: 'round',
            pointRadius: nowPointRadius,
            pointBackgroundColor: nowPointColour,
            pointBorderColor: nowPointBorder,
            pointBorderWidth: actualData.map((_, i) => i === lastIdx ? 2 : 0),
            pointHoverRadius: 6,
            pointHoverBackgroundColor: C.accent,
            pointHoverBorderColor: '#fff',
            pointHoverBorderWidth: 2,
          },
          {
            label: `Projected @ ${curRate}/hr`,
            data: projData,
            borderColor: C.accent3,
            borderDash: [6, 4],
            borderWidth: 2, fill: false, tension: 0.3,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: true, position: 'top',
            labels: { color: C.muted, font: { size: 9, family: 'Consolas' }, boxWidth: 12 } },
          tooltip: {
            mode: 'index', intersect: false,
            backgroundColor: C.bg3, bodyColor: C.fg,
            titleColor: C.accent, borderColor: C.bg3, borderWidth: 1,
            callbacks: {
              label: item => ` ${item.dataset.label}: ${(item.raw||0).toLocaleString()}`,
            },
          },
        },
        scales: {
          x: { ticks: { color: C.muted, font: { size: 9 }, maxTicksLimit: 12 },
               grid: { color: C.bg3 + '60' } },
          y: { ticks: { color: C.muted, font: { size: 9 } },
               grid: { color: C.bg3 + '60' }, beginAtZero: true,
               title: { display: true, text: 'Score', color: C.muted, font: { size: 9 } } },
        },
      },
    });
  }

  // ── Score targets table ────────────────────────────────────────────────────
  function updateTargets(snap) {
    const tbody  = document.getElementById('pace-targets-tbody'); if (!tbody) return;
    const ss     = snap.session_status || {};
    const pb     = snap.personal_bests || {};
    const score  = snap.score    || 0;
    const valid  = snap.valid    || 0;
    const remMins = ss.total_remaining_mins ?? ss.remaining_mins ?? 0;
    const remHrs  = remMins / 60;
    const curRate = pb.current_hour_rate || 0;
    const ptsPerQso = valid > 0 ? score / valid : 0;

    // Milestones
    const milestones = [];
    [1e4, 5e4, 1e5, 5e5, 1e6, 2e6, 5e6, 1e7].forEach(t => {
      if (score < t) milestones.push(t);
    });

    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    milestones.slice(0, 6).forEach(t => {
      const needed    = t - score;
      const addQsos   = ptsPerQso > 0 ? Math.ceil(needed / ptsPerQso) : null;
      const hoursNeed = curRate > 0 && addQsos !== null ? (addQsos / curRate) : null;
      const feasible  = hoursNeed !== null && hoursNeed <= remHrs;
      const fc = feasible ? C.green : C.muted;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:${fc};font-weight:bold">${t.toLocaleString()}</td>
        <td style="color:${fc}">${needed.toLocaleString()}</td>
        <td>${addQsos !== null ? addQsos.toLocaleString() : '?'}</td>
        <td style="color:${feasible ? C.green : C.red}">
          ${hoursNeed !== null ? hoursNeed.toFixed(1)+'h' : '?'}</td>
        <td style="color:${feasible ? C.green : C.red}">
          ${hoursNeed !== null ? (feasible ? '✓ Reachable' : '✗ Unlikely') : '—'}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  // ── My Target Score (operator-entered goal, persisted locally) ─────────────
  const MYTARGET_KEY = 'vka_pace_target';

  function updateMyTarget(snap) {
    const status = document.getElementById('pace-mytarget-status');
    if (!status) return;
    const raw    = localStorage.getItem(MYTARGET_KEY);
    const target = raw ? parseFloat(raw) : null;
    if (!target || target <= 0) { status.textContent = ''; return; }

    const ss      = snap.session_status || {};
    const pb      = snap.personal_bests || {};
    const score   = snap.score || 0;
    const valid   = snap.valid || 0;
    const remMins = ss.total_remaining_mins ?? ss.remaining_mins ?? 0;
    const remHrs  = remMins / 60;
    const curRate = pb.current_hour_rate || 0;
    const ptsPerQso = valid > 0 ? score / valid : 0;
    const needed  = target - score;

    if (needed <= 0) {
      status.style.color = C.green;
      status.textContent = `✅ Target ${target.toLocaleString()} reached! (+${Math.abs(needed).toLocaleString()} over)`;
      return;
    }
    if (ptsPerQso <= 0) {
      status.style.color = C.muted;
      status.textContent = `Target ${target.toLocaleString()}: ${needed.toLocaleString()} points to go — log some QSOs to see pace.`;
      return;
    }
    const addQsos = needed / ptsPerQso;
    if (remHrs <= 0) {
      status.style.color = C.red;
      status.textContent = `Target ${target.toLocaleString()}: ${needed.toLocaleString()} points short at contest end.`;
      return;
    }
    const reqRate    = addQsos / remHrs;
    const hoursNeeded = curRate > 0 ? addQsos / curRate : null;
    const onPace = hoursNeeded !== null && hoursNeeded <= remHrs;
    status.style.color = onPace ? C.green : C.red;
    status.textContent = onPace
      ? `✅ On pace for ${target.toLocaleString()} — need ${reqRate.toFixed(1)} Q/hr (currently ${curRate}/hr)`
      : `⚠ Behind pace for ${target.toLocaleString()} — need ${reqRate.toFixed(1)} Q/hr, currently ${curRate}/hr`;
  }

  document.getElementById('pace-mytarget-btn')?.addEventListener('click', () => {
    const inp = document.getElementById('pace-mytarget-input');
    const v   = parseFloat(inp?.value || '');
    if (!isNaN(v) && v > 0) {
      localStorage.setItem(MYTARGET_KEY, String(v));
      if (_snap) updateMyTarget(_snap);
    }
  });
  document.getElementById('pace-mytarget-clear-btn')?.addEventListener('click', () => {
    localStorage.removeItem(MYTARGET_KEY);
    const inp = document.getElementById('pace-mytarget-input');
    if (inp) inp.value = '';
    const status = document.getElementById('pace-mytarget-status');
    if (status) status.textContent = '';
  });
  (function initMyTarget() {
    const raw = localStorage.getItem(MYTARGET_KEY);
    const inp = document.getElementById('pace-mytarget-input');
    if (raw && inp) inp.value = raw;
  })();

  window.addEventListener('vka:snapshot', e => update(e.detail));
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab === 'pace') {
      const snap = window.VKA.lastSnap();
      if (snap) update(snap);
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // ── Year-over-year pace comparison (reference logs + alarm) ────────────
  // Mirrors the old desktop app's Pace Tracker: cumulative-QSO trajectory
  // for the live contest vs reference years, with a polling alarm banner.
  // ═══════════════════════════════════════════════════════════════════════
  const PALETTE = ['#00d4aa','#ff6b35','#f0c040','#2ed573','#64b5f6',
                    '#e040fb','#ff5252','#69f0ae','#ea80fc','#80d8ff'];

  let _refs        = [];
  let _live         = null;
  let _hidden       = new Set();
  let _refsLoaded   = false;
  let _flash        = true;
  let refTrajChart  = null;
  let refRateChart  = null;
  let _pollHandle   = null;

  function colourFor(key) {
    const idx = _refs.findIndex(r => r.key === key);
    return PALETTE[Math.max(idx, 0) % PALETTE.length];
  }
  const escapeHtml = window.VKA.escapeHtml;

  // Mirrors report.js's own isTabActive() — gates the self-rescheduling
  // poll chain below so it stops once the Pace tab isn't visible instead
  // of running for the lifetime of the session (see issue #59).
  function isTabActive() {
    return document.getElementById('tab-pace')?.classList.contains('active');
  }
  function escapeAttr(s) { return escapeHtml(s); }

  const refAtElapsed = window.VKA.refAtElapsed;

  function visibleRefs() { return _refs.filter(r => !_hidden.has(r.key)); }

  function threshVal() {
    const v = parseInt(document.getElementById('pace-thresh-input')?.value || '5', 10);
    return isNaN(v) ? 5 : Math.max(1, Math.min(50, v));
  }

  // ── Load ────────────────────────────────────────────────────────────────
  async function loadRefs() {
    try {
      const res  = await fetch('/api/pace');
      const data = await res.json();
      _refs       = data.refs || [];
      _live       = data.live || null;
      _refsLoaded = true;
      populateTargetSelect();
      redrawRefs();
    } catch (e) { console.warn('Pace refs load failed:', e); }
  }

  function populateTargetSelect() {
    const sel = document.getElementById('pace-target-select');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="__best__">Best year</option>' +
      _refs.map(r => `<option value="${escapeAttr(r.key)}">${escapeHtml(r.label)}</option>`).join('');
    if ([...sel.options].some(o => o.value === current)) sel.value = current;
    else sel.value = '__best__';
  }

  function redrawRefs() {
    const vis = visibleRefs();
    renderRefTable(_refs);
    renderRefCharts(vis);
    renderRefInsight(vis);
    updateRefAlarm(vis);
  }

  // ── Roster table ────────────────────────────────────────────────────────
  function renderRefTable(allRefs) {
    const tbody = document.getElementById('pace-ref-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    [...allRefs].sort((a, b) => (a.year||0) - (b.year||0)).forEach(r => {
      const col     = colourFor(r.key);
      const visible = !_hidden.has(r.key);
      const avgRate = r.total_hrs > 0 ? (r.final_qsos / r.total_hrs) : 0;
      const tr = document.createElement('tr');
      tr.style.cursor  = 'pointer';
      tr.style.opacity = visible ? '1' : '0.4';
      tr.innerHTML = `
        <td><span style="color:${col}">${visible ? '●' : '○'}</span></td>
        <td style="color:${col};font-weight:bold">${r.year || '?'}</td>
        <td>${escapeHtml(r.display_name || r.contest_name)}</td>
        <td>${(r.final_qsos||0).toLocaleString()}</td>
        <td>${avgRate.toFixed(1)}</td>
        <td style="color:${C.muted}">${r.source === 'auto' ? 'auto (same contest)' : 'manual'}</td>`;
      tr.addEventListener('click', () => {
        if (_hidden.has(r.key)) _hidden.delete(r.key); else _hidden.add(r.key);
        redrawRefs();
      });
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  // ── Trajectory + rate charts ────────────────────────────────────────────
  function renderRefCharts(refs) {
    const canvas = document.getElementById('chart-pace-traj');
    if (!canvas) return;
    if (refTrajChart) { refTrajChart.destroy(); refTrajChart = null; }
    if (refRateChart) { refRateChart.destroy(); refRateChart = null; }

    const datasets = refs.map(r => ({
      label: r.label, borderColor: colourFor(r.key), borderDash: [6, 4],
      data: r.elapsed_hrs.map((x, i) => ({ x, y: r.cum_qsos[i] })),
      borderWidth: 1.6, pointRadius: 0, tension: 0.1, fill: false,
    }));
    const haveLive = _live && _live.elapsed_hrs && _live.elapsed_hrs.length;
    if (haveLive) {
      datasets.push({
        label: '▶ This contest (live)', borderColor: C.accent,
        data: _live.elapsed_hrs.map((x, i) => ({ x, y: _live.cum_qsos[i] })),
        borderWidth: 3, pointRadius: 0, tension: 0, fill: false,
      });
    }

    if (!datasets.length) {
      refTrajChart = new Chart(canvas.getContext('2d'), { type: 'line', data: { datasets: [] },
        options: { responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: { type: 'linear', ticks: { color: C.muted, font: { size: 8 } } },
                    y: { ticks: { color: C.muted, font: { size: 8 } } } } } });
      const rc = document.getElementById('chart-pace-rate');
      if (rc) refRateChart = new Chart(rc.getContext('2d'), { type: 'line', data: { datasets: [] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } } });
      return;
    }

    refTrajChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
        interaction: { mode: 'nearest', intersect: false },
        plugins: {
          legend: { display: true, position: 'top',
                    labels: { color: C.muted, font: { size: 9, family: 'Consolas' } } },
          tooltip: { backgroundColor: C.bg3, bodyColor: C.fg, titleColor: C.accent },
        },
        scales: {
          x: { type: 'linear', min: 0,
               title: { display: true, text: 'Hours since contest start', color: C.muted, font: { size: 9 } },
               ticks: { color: C.muted, font: { size: 8 } }, grid: { color: C.bg3 + '80' } },
          y: { title: { display: true, text: 'Cumulative QSOs', color: C.muted, font: { size: 9 } },
               ticks: { color: C.muted, font: { size: 8 } }, grid: { color: C.bg3 + '80' } },
        },
      },
    });

    // Deficit connector between live point and the chosen target reference.
    if (haveLive && refs.length) {
      const targetSel = document.getElementById('pace-target-select');
      const targetKey = targetSel ? targetSel.value : '__best__';
      const nowE       = _live.elapsed_hrs[_live.elapsed_hrs.length - 1];
      const liveTotal  = _live.cum_qsos[_live.cum_qsos.length - 1];
      let targetRef = null;
      if (targetKey === '__best__') {
        targetRef = refs.reduce((best, r) =>
          refAtElapsed(r, nowE) > refAtElapsed(best, nowE) ? r : best, refs[0]);
      } else {
        targetRef = refs.find(r => r.key === targetKey) || null;
      }
      if (targetRef) {
        const refAtNow = refAtElapsed(targetRef, nowE);
        const deficit  = refAtNow - liveTotal;
        if (Math.abs(deficit) >= threshVal()) {
          const origDraw = refTrajChart.draw.bind(refTrajChart);
          refTrajChart.draw = function () {
            origDraw();
            const area = refTrajChart.chartArea;
            if (!area) return;
            const ctx = canvas.getContext('2d');
            const px  = refTrajChart.scales.x.getPixelForValue(nowE);
            if (px < area.left || px > area.right) return;
            const py1 = refTrajChart.scales.y.getPixelForValue(liveTotal);
            const py2 = refTrajChart.scales.y.getPixelForValue(refAtNow);
            ctx.save();
            ctx.strokeStyle = deficit > 0 ? C.red : C.green;
            ctx.lineWidth = 1.8;
            ctx.beginPath(); ctx.moveTo(px, py1); ctx.lineTo(px, py2); ctx.stroke();
            ctx.fillStyle = deficit > 0 ? C.red : C.green;
            ctx.font = 'bold 10px Consolas, monospace';
            ctx.fillText(`${Math.abs(deficit)} ${deficit > 0 ? 'behind' : 'ahead'}`,
                         px + 5, (py1 + py2) / 2);
            ctx.restore();
          };
          refTrajChart.update();
        }
      }
    }

    const rateCanvas = document.getElementById('chart-pace-rate');
    if (!rateCanvas) return;
    const rateDatasets = refs.map(r => ({
      label: r.label, borderColor: colourFor(r.key),
      data: r.rate_hrs.map((x, i) => ({ x, y: r.rate_counts[i] })),
      borderWidth: 1, pointRadius: 0, stepped: 'middle', fill: false,
    }));
    if (haveLive) {
      rateDatasets.push({
        label: 'live', borderColor: C.accent,
        data: _live.rate_hrs.map((x, i) => ({ x, y: _live.rate_counts[i] })),
        borderWidth: 1.6, pointRadius: 0, stepped: 'middle', fill: false,
      });
    }
    refRateChart = new Chart(rateCanvas.getContext('2d'), {
      type: 'line', data: { datasets: rateDatasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: true } },
        scales: {
          x: { type: 'linear', min: 0, ticks: { color: C.muted, font: { size: 7 } }, grid: { display: false } },
          y: { ticks: { color: C.muted, font: { size: 7 } }, grid: { color: C.bg3 + '80' },
               title: { display: true, text: 'QSOs/hr', color: C.muted, font: { size: 8 } } },
        },
      },
    });
  }

  // ── Insight bar ─────────────────────────────────────────────────────────
  function renderRefInsight(refs) {
    const el = document.getElementById('pace-ref-insight');
    if (!el) return;
    const haveLive = _live && _live.elapsed_hrs && _live.elapsed_hrs.length;
    if (!refs.length && !haveLive) {
      el.textContent = 'Load a reference log to see pace insights.'; return;
    }
    if (!refs.length) {
      const lastE = haveLive ? _live.elapsed_hrs[_live.elapsed_hrs.length-1] : 0;
      const lastC = haveLive ? _live.cum_qsos[_live.cum_qsos.length-1] : 0;
      el.textContent = `Live: ${lastC} QSOs at ${lastE.toFixed(1)}h — no reference loaded yet.`;
      return;
    }
    if (!haveLive) {
      el.textContent = `${refs.length} reference year(s) loaded — waiting for live log data.`;
      return;
    }
    const nowE      = _live.elapsed_hrs[_live.elapsed_hrs.length-1];
    const liveTotal = _live.cum_qsos[_live.cum_qsos.length-1];
    const tv = threshVal();
    const parts = refs.map(r => {
      const deficit = refAtElapsed(r, nowE) - liveTotal;
      if (deficit > tv)  return `⚠ ${Math.abs(deficit)} behind ${r.year}`;
      if (deficit < -tv) return `🚀 ${Math.abs(deficit)} ahead of ${r.year}`;
      return `✅ within ±${tv} of ${r.year}`;
    });
    el.textContent = parts.join('  |  ');
  }

  // ── Alarm banner + self-rescheduling poll ──────────────────────────────
  function updateRefAlarm(refs) {
    const box = document.getElementById('pace-ref-alarm');
    let interval = 30000;
    if (box) {
      const haveLive = _live && _live.elapsed_hrs && _live.elapsed_hrs.length;
      if (!haveLive) {
        box.style.background = C.bg3; box.style.color = C.muted; box.style.borderColor = C.bg3;
        box.textContent = '📊 Load a log file to start tracking.';
      } else if (!refs.length) {
        box.style.background = C.bg3; box.style.color = C.muted; box.style.borderColor = C.bg3;
        box.textContent = "📊 Load a reference log to compare pace. Use '+ Add Reference Log' above.";
      } else {
        const nowE      = _live.elapsed_hrs[_live.elapsed_hrs.length-1];
        const liveTotal = _live.cum_qsos[_live.cum_qsos.length-1];
        const tv = threshVal();
        const deficits = refs.map(r => ({
          year: r.year, refAtT: refAtElapsed(r, nowE),
          deficit: refAtElapsed(r, nowE) - liveTotal,
        }));
        const worst = deficits.reduce((a, b) => b.deficit > a.deficit ? b : a);
        const best  = deficits.reduce((a, b) => b.deficit < a.deficit ? b : a);
        if (worst.deficit >= tv) {
          _flash = !_flash;
          box.style.background  = _flash ? C.red : C.bg3;
          box.style.color       = _flash ? C.fg  : C.red;
          box.style.borderColor = C.red;
          box.textContent = `⚠ PACE ALARM — You are ${worst.deficit} QSOs behind your ${worst.year} pace right now! ` +
                             `(${worst.refAtT} QSOs at this point in ${worst.year})`;
          interval = 5000;
        } else if (best.deficit <= -tv) {
          _flash = true;
          box.style.background = C.bg3; box.style.color = C.green; box.style.borderColor = C.green;
          box.textContent = `🚀 ON PACE — You are ${Math.abs(best.deficit)} QSOs AHEAD of your ${best.year} pace! Keep it up!`;
        } else {
          _flash = true;
          box.style.background = C.bg3; box.style.color = C.accent3; box.style.borderColor = C.accent3;
          box.textContent = `✅ WITHIN TARGET — Tracking within ±${tv} QSOs of reference pace ` +
                             `(${worst.deficit <= 0 ? 'ahead' : 'behind'} by ${Math.abs(worst.deficit)} QSOs vs ${worst.year})`;
        }
      }
    }
    if (_pollHandle) clearTimeout(_pollHandle);
    // Only keep the chain alive while the Pace tab is actually visible —
    // previously this polled /api/pace/live every 5-30s indefinitely for
    // the lifetime of the session, even after navigating away (see issue
    // #59). The vka:tabchange listener below resumes it on return.
    _pollHandle = isTabActive() ? setTimeout(pollLive, interval) : null;
  }

  async function pollLive() {
    try {
      const r = await fetch('/api/pace/live');
      _live = await r.json();
    } catch (e) { /* keep stale _live, try again next tick */ }
    const vis = visibleRefs();
    renderRefCharts(vis);
    renderRefInsight(vis);
    updateRefAlarm(vis);
  }

  // ── Add / clear reference logs ─────────────────────────────────────────
  async function addRefLog() {
    const btn = document.getElementById('pace-add-log-btn');
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      const data = await window.VKA.browseFile();
      if (data.error || !data.path) return;
      const res2  = await fetch('/api/pace/add_log', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: data.path }),
      });
      const data2 = await res2.json();
      if (data2.error) { console.warn('Add reference log:', data2.error); return; }
      _refs       = data2.refs || [];
      _live       = data2.live || _live;
      _refsLoaded = true;
      populateTargetSelect();
      redrawRefs();
    } catch (e) { console.warn('Add reference log failed:', e); }
    finally { if (btn) { btn.disabled = false; btn.textContent = '+ Add Reference Log'; } }
  }

  async function clearRefs() {
    try {
      const res  = await fetch('/api/pace/clear_refs', { method: 'POST' });
      const data = await res.json();
      _refs = data.refs || [];
      _hidden.clear();
      populateTargetSelect();
      redrawRefs();
    } catch (e) { console.warn('Clear references failed:', e); }
  }

  document.getElementById('pace-add-log-btn')?.addEventListener('click', addRefLog);
  document.getElementById('pace-clear-refs-btn')?.addEventListener('click', clearRefs);
  document.getElementById('pace-target-select')?.addEventListener('change', redrawRefs);
  document.getElementById('pace-thresh-input')?.addEventListener('change', redrawRefs);

  window.addEventListener('vka:loaded', () => { _refsLoaded = false; _hidden.clear(); loadRefs(); });
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab !== 'pace') return;
    if (!_refsLoaded) loadRefs();
    // Resume the poll chain updateRefAlarm() stopped while this tab was
    // inactive (see issue #59) — loadRefs() already resumes it via
    // redrawRefs()->updateRefAlarm() when refs weren't loaded yet.
    else if (!_pollHandle) pollLive();
  });
})();
