/**
 * rate.js — Rate Analysis tab: QSOs/hour bar chart + session summary table
 */
;(function () {
  'use strict';
  const C = { accent:'#00d4aa', accent2:'#ff6b35', accent3:'#f0c040',
               muted:'#8b949e', bg3:'#21262d', fg:'#e6edf3', green:'#2ed573' };
  const BAND_COLS = window.VKA.BAND_COLS;
  const BAND_ORDER = ['160M','80M','60M','40M','30M','20M','17M','15M','12M','10M','6M','2M'];

  let rateChart = null;
  let multsChart = null;
  let bandStackChart = null;

  // vka:snapshot fires on every WebSocket push — including the QRZ
  // background-lookup worker's own broadcasts, which happen every ~1.5s
  // while it drains a backlog of newly-loaded callsigns (e.g. right after
  // loading a log full of calls not yet in the QRZ cache) and carry no
  // QSO/points/mults data at all. Without this guard, every one of those
  // unrelated broadcasts still destroyed and rebuilt both charts from
  // scratch, which read as a constant flashing "redraw" that had nothing
  // to do with the rate data actually changing.
  let _lastRateJSON = null, _lastSessJSON = null;

  // force=true (tab-switch) always re-renders even if the data matches the
  // last render: the tab is `display:none` while inactive, so a chart
  // created/left stale while hidden can end up sized against a collapsed
  // canvas — the pre-existing behavior of always rebuilding on tabchange is
  // what makes switching to Rate reliably show correctly-sized charts, and
  // skipping that specifically would trade one bug for another.
  async function load(force) {
    const [rateRes, sessRes] = await Promise.all([
      fetch('/api/rate'), fetch('/api/sessions')
    ]);
    const rateJSON = await rateRes.text();
    const sessJSON = await sessRes.text();

    if (force || rateJSON !== _lastRateJSON) {
      _lastRateJSON = rateJSON;
      const rateData = JSON.parse(rateJSON);
      renderRateChart(rateData);
      renderMultsChart(rateData);
      // Piggybacks on the same "rate data actually changed" gate as the two
      // charts above — a new QSO is exactly the event that would also move
      // this chart, so there's no point fetching the (potentially large)
      // full QSO list on every idle snapshot tick.
      renderBandStackChart(rateData);
    }
    if (force || sessJSON !== _lastSessJSON) {
      _lastSessJSON = sessJSON;
      renderSessionTable(JSON.parse(sessJSON));
    }
  }

  // r.hour is a naive-UTC full datetime ("2025-07-19T08:00:00", not just an
  // hour-of-day — see /api/rate in server.py), so comparing it against the
  // real current UTC time correctly identifies "this bucket is still
  // accumulating live" across multi-day contests, and naturally comes back
  // false for every bucket once the contest (and page) is viewed after the
  // fact — no separate "is this replay/historical" check needed.
  function isCurrentHourBucket(d) {
    const now = new Date();
    return d.getUTCFullYear() === now.getUTCFullYear()
        && d.getUTCMonth()    === now.getUTCMonth()
        && d.getUTCDate()     === now.getUTCDate()
        && d.getUTCHours()    === now.getUTCHours();
  }

  function renderRateChart(data) {
    if (!data.length) return;
    const dates = data.map(r => new Date(r.hour+'Z'));   // server times are naive UTC
    const labels = dates.map(d => `${String(d.getUTCHours()).padStart(2,'0')}:00`);
    const values = data.map(r => r.qsos);
    const maxVal = Math.max(...values, 1);
    const isCurrent = dates.map(isCurrentHourBucket);
    // Colour bars by intensity: low=muted, high=accent
    const colours = values.map(v => {
      const t = v / maxVal;
      return t > 0.7 ? C.accent : t > 0.4 ? C.accent3 : C.muted + '88';
    });
    // The in-progress hour gets a bright green outline instead of relying
    // on fill intensity alone — otherwise a still-accumulating hour that
    // just started looks identical to a genuinely quiet finished one.
    const borderColours = isCurrent.map(c => c ? C.green : 'transparent');
    const borderWidths   = isCurrent.map(c => c ? 3 : 0);

    const canvas = document.getElementById('chart-rate');
    if (!canvas) return;
    if (rateChart) { rateChart.destroy(); rateChart = null; }

    rateChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'QSOs',
          data: values,
          backgroundColor: colours,
          borderColor: borderColours,
          borderWidth: borderWidths,
          borderRadius: 3,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 500, easing: 'easeOutQuart' },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: C.bg3, bodyColor: C.fg,
            titleColor: C.accent, borderColor: C.bg3, borderWidth: 1,
            callbacks: {
              title: i => `Hour ${i[0].label}` + (isCurrent[i[0].dataIndex] ? ' (in progress)' : ''),
              label: i => ` ${i.raw} QSOs`,
            },
          },
        },
        scales: {
          x: { ticks:{color:C.muted,font:{size:9},maxRotation:45},
               grid:{color:C.bg3+'80'} },
          y: { ticks:{color:C.muted,font:{size:9}},
               grid:{color:C.bg3+'80'}, beginAtZero:true,
               title:{display:true,text:'QSOs / hour',color:C.muted,font:{size:9}} },
        },
      },
    });
  }

  function renderMultsChart(data) {
    if (!data.length) return;
    const labels = data.map(r => {
      const d = new Date(r.hour+'Z');   // server times are naive UTC
      return `${String(d.getUTCHours()).padStart(2,'0')}:00`;
    });
    const values = data.map(r => r.mults || 0);

    const canvas = document.getElementById('chart-rate-mults');
    if (!canvas) return;
    if (multsChart) { multsChart.destroy(); multsChart = null; }

    // Same glowing-sparkline technique as overview.js's makeSparkline():
    // canvas drop-shadow filter + gradient fill under a monotone line,
    // hidden y-axis, only the peak hour gets a visible point — just a
    // larger panel than the Overview tab's compact 90px inline version.
    canvas.style.filter = `drop-shadow(0 0 6px ${C.accent3}80)`;
    const ctx = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, canvas.height || 220);
    grad.addColorStop(0,    C.accent3 + '59');
    grad.addColorStop(0.65, C.accent3 + '14');
    grad.addColorStop(1,    C.accent3 + '00');

    const peak = Math.max(...values, 0);
    const pi   = values.lastIndexOf(peak);
    const pointRadius = values.map((_, i) => (i === pi && peak > 0) ? 5 : 0);
    const pointColour = values.map((_, i) => (i === pi && peak > 0) ? C.accent3 : 'transparent');
    const pointBorder  = values.map((_, i) => (i === pi && peak > 0) ? '#fff' : 'transparent');

    multsChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'New mults',
          data: values,
          borderColor: C.accent3,
          borderWidth: 3,
          backgroundColor: grad,
          fill: true,
          tension: 0,
          cubicInterpolationMode: 'monotone',
          borderCapStyle: 'round',
          borderJoinStyle: 'round',
          pointRadius,
          pointBackgroundColor: pointColour,
          pointBorderColor: pointBorder,
          pointBorderWidth: values.map((_, i) => (i === pi && peak > 0) ? 2 : 0),
          pointHoverRadius: 6,
          pointHoverBackgroundColor: C.accent3,
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 2,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 500, easing: 'easeOutQuart' },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: C.bg3, bodyColor: C.fg,
            titleColor: C.accent3, borderColor: C.accent3, borderWidth: 1,
            displayColors: false,
            callbacks: { title: i => `Hour ${i[0].label}`, label: i => ` ${i.raw} new mults` }
          },
        },
        scales: {
          x: { ticks:{color:C.muted,font:{size:9},maxRotation:45},
               grid:{display:false}, border:{display:false} },
          y: { display:false, beginAtZero:true },
        },
      },
    });
  }

  // ── QSOs per hour, stacked by band — same hour buckets as renderRateChart
  // (r.hour from /api/rate), just split per-band instead of just totalled,
  // so a good hour's actual source band is visible instead of hidden inside
  // one flat bar. Computed client-side from the full QSO list rather than a
  // new backend endpoint — one pass over the array, via the shared cache
  // (see app.js's window.VKA.fetchQsos) other tabs already populate.
  let _bandStackGen = 0;
  async function renderBandStackChart(rateData) {
    const canvas = document.getElementById('chart-rate-bands');
    if (!canvas || !rateData.length) return;
    const gen = ++_bandStackGen;
    let qsos;
    try {
      qsos = await window.VKA.fetchQsos();
    } catch (e) { return; }
    if (gen !== _bandStackGen) return;   // a newer call already superseded this one

    const hourKeys = rateData.map(r => r.hour.substring(0, 13));   // "YYYY-MM-DDTHH"
    const hourIndex = new Map(hourKeys.map((h, i) => [h, i]));
    const bandsSeen = new Set();
    const counts = {};   // band -> array parallel to rateData, QSO count per hour
    qsos.forEach(q => {
      if (q.dupe || !q.time || !q.band) return;
      const idx = hourIndex.get(String(q.time).substring(0, 13));
      if (idx === undefined) return;
      const band = q.band.toUpperCase();
      bandsSeen.add(band);
      if (!counts[band]) counts[band] = new Array(rateData.length).fill(0);
      counts[band][idx]++;
    });

    const bands = BAND_ORDER.filter(b => bandsSeen.has(b))
      .concat([...bandsSeen].filter(b => !BAND_ORDER.includes(b)).sort());
    const labels = rateData.map(r => {
      const d = new Date(r.hour + 'Z');
      return `${String(d.getUTCHours()).padStart(2,'0')}:00`;
    });
    const datasets = bands.map(b => ({
      label: b.toLowerCase(),
      data: counts[b],
      backgroundColor: (BAND_COLS[b] || C.muted) + 'cc',
      borderColor: BAND_COLS[b] || C.muted,
      borderWidth: 1,
      stack: 'bands',
    }));

    if (bandStackChart) {
      bandStackChart.data.labels = labels;
      bandStackChart.data.datasets = datasets;
      bandStackChart.update();
      return;
    }

    bandStackChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 500, easing: 'easeOutQuart' },
        plugins: {
          legend: { display: true, position: 'bottom',
            labels: { color: C.muted, font: { size: 9 }, boxWidth: 10, padding: 8 } },
          tooltip: {
            backgroundColor: C.bg3, bodyColor: C.fg,
            titleColor: C.accent, borderColor: C.bg3, borderWidth: 1,
            callbacks: { title: i => `Hour ${i[0].label}`, label: i => ` ${i.dataset.label}: ${i.raw} QSOs` },
          },
        },
        scales: {
          x: { stacked: true, ticks:{color:C.muted,font:{size:9},maxRotation:45},
               grid:{color:C.bg3+'80'} },
          y: { stacked: true, ticks:{color:C.muted,font:{size:9}},
               grid:{color:C.bg3+'80'}, beginAtZero:true },
        },
      },
    });
  }

  function renderSessionTable(sessions) {
    const tbody = document.getElementById('rate-sess-tbody');
    if (!tbody || !sessions.length) return;
    tbody.innerHTML = '';
    const totalQsos = sessions.reduce((sum, s) => sum + (s.qsos || 0), 0);
    const bestQsos   = Math.max(...sessions.map(s => s.qsos || 0));
    const frag = document.createDocumentFragment();
    sessions.forEach(s => {
      const tr = document.createElement('tr');
      const score   = (s.running_score || 0).toLocaleString();
      const pctQsos = totalQsos > 0 ? (s.qsos / totalQsos * 100).toFixed(1) + '%' : '—';
      const isBest  = s.qsos > 0 && s.qsos === bestQsos;
      if (isBest) tr.style.borderLeft = '2px solid var(--green)';
      tr.innerHTML = `
        <td style="color:var(--accent)">${s.label || s.session}${isBest ? ' 🔥' : ''}</td>
        <td>${s.qsos}</td>
        <td style="color:${isBest ? 'var(--green)' : 'var(--muted)'}">${pctQsos}</td>
        <td>${s.new_mults}</td>
        <td>${s.cum_mults}</td>
        <td>${(s.pts||0).toLocaleString()}</td>
        <td style="color:var(--accent3);font-weight:bold">${score}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  window.addEventListener('vka:snapshot', () => load(false));
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab==='rate') load(true); });
})();
