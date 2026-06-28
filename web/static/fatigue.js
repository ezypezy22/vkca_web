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
        <div class="fatigue-op" style="color:${col}">${op.operator || '—'}</div>
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
})();
