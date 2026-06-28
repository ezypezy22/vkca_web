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
      if (cur < prev * 0.7 && cur > 0 && rem > 0) {
        alarm.style.display = 'block';
        alarm.textContent   = `⚠ Rate dropping — ${cur} Q/hr vs ${prev} Q/hr last hour. Consider changing bands or calling CQ more aggressively.`;
        alarm.style.borderColor = C.red;
        alarm.style.color       = C.red;
      } else if (cur === 0 && valid > 0 && rem > 30) {
        alarm.style.display = 'block';
        alarm.textContent   = '⚠ No QSOs in the current hour. Check propagation or try a new band.';
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
      const addQsos  = curRate;
      const addMults = Math.round(addQsos * multRatio);
      running += addQsos * ptsPerQso;
      projScores.push(Math.round(running));
    }

    const histLabels = historical.map((_, i) => String(i).padStart(2,'0'));
    const projLabels = Array.from({length: remBuckets}, (_, i) =>
      `+${i+1}h`);
    const allLabels  = [...histLabels, ...projLabels];

    if (trajChart) { trajChart.destroy(); trajChart = null; }

    trajChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: allLabels,
        datasets: [
          {
            label: 'Actual Score',
            data: [...historical, ...Array(remBuckets).fill(null)],
            borderColor: C.accent,
            backgroundColor: C.accent + '22',
            borderWidth: 2.5, fill: true, tension: 0.3,
            pointRadius: 0,
          },
          {
            label: `Projected @ ${curRate}/hr`,
            data: [...Array(historical.length - 1).fill(null), lastScore, ...projScores],
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

  window.addEventListener('vka:snapshot', e => update(e.detail));
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab === 'pace') {
      const snap = window.VKA.lastSnap();
      if (snap) update(snap);
    }
  });
})();
