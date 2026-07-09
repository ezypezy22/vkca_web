/**
 * bands.js — Band Breakdown panel
 * Horizontal bar chart (efficiency) + detail table.
 */

;(function () {
  'use strict';

  const BAND_COLS = window.VKA.BAND_COLS;

  const C = {
    bg3: '#21262d', muted: '#8b949e', fg: '#e6edf3', green: '#2ed573',
  };

  let bandChart = null;
  let _be = [];   // current band_efficiency rows — kept in sync for tooltip callbacks

  function update(snap) {
    const be = snap?.band_efficiency;
    if (!be || !be.length) return;

    const labels  = be.map(r => r.band.toLowerCase());
    const effic   = be.map(r => r.efficiency || 0);
    const qsos    = be.map(r => r.qsos || 0);
    const mults   = be.map(r => r.new_shires || 0);
    const colours = labels.map(b => BAND_COLS[b] || C.muted);

    // Total score for % contribution calculation
    const totalScore = snap?.score || 0;

    updateChart(labels, effic, colours, qsos, mults, be);
    updateTable(be, colours, totalScore);
  }

  function updateChart(labels, effic, colours, qsos, mults, be) {
    _be = be || [];   // keep in sync so the tooltip callback always reads latest values
    const canvas = document.getElementById('chart-band-eff');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (bandChart) {
      bandChart.data.labels = labels;
      bandChart.data.datasets[0].data = effic;
      bandChart.data.datasets[0].backgroundColor = colours.map(c => c + 'cc');
      bandChart.data.datasets[0].borderColor = colours;
      bandChart.update();
      return;
    }

    bandChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Mult efficiency (new mults / QSO)',
          data: effic,
          backgroundColor: colours.map(c => c + 'cc'),
          borderColor: colours,
          borderWidth: 1,
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 600, easing: 'easeOutQuart' },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: C.bg3,
            bodyColor: C.fg,
            borderWidth: 1,
            callbacks: {
              title: items => items[0].label.toUpperCase(),
              label: item => {
                const i = item.dataIndex;
                return [
                  ` Efficiency: ${effic[i].toFixed(3)}`,
                  ` QSOs: ${qsos[i]}`,
                  ` New mults: ${mults[i]}`,
                  ` Best hr rate: ${_be[i]?.best_hour_rate ?? '—'} Q/hr`,
                ];
              },
            },
          },
        },
        scales: {
          x: {
            ticks: { color: C.muted, font: { size: 9 } },
            grid: { color: C.bg3 + '80' },
            title: {
              display: true,
              text: 'New mults / QSO',
              color: C.muted,
              font: { size: 9 },
            },
          },
          y: {
            ticks: {
              color: colours,
              font: { size: 11, weight: 'bold', family: 'Consolas' },
            },
            grid: { display: false },
          },
        },
      },
    });
  }

  function updateTable(be, colours, totalScore) {
    const tbody = document.getElementById('bands-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    const now = new Date();
    be.forEach((r, i) => {
      const col = colours[i] || C.muted;
      const pts = r.pts || 0;
      const scorePct = totalScore > 0 ? (pts / totalScore * 100).toFixed(1) + '%' : '—';
      const bestRate = r.best_hour_rate ? r.best_hour_rate + '/hr' : '—';

      // Band temperature — time since last QSO on this band
      let lastStr = '—';
      let tempCol = C.muted;
      if (r.last_qso_utc) {
        const last = new Date(r.last_qso_utc + 'Z');   // force UTC interpretation
        const minAgo = Math.floor((now - last) / 60000);
        if (minAgo < 60)        { lastStr = minAgo + 'm ago'; tempCol = C.green; }
        else if (minAgo < 180)  { lastStr = Math.floor(minAgo/60) + 'h ago'; tempCol = '#f0c040'; }
        else                    { lastStr = Math.floor(minAgo/60) + 'h ago'; tempCol = C.muted; }
      }

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:${col};font-weight:bold">${r.band.toLowerCase()}</td>
        <td>${r.qsos || 0}</td>
        <td style="color:${col}">${pts.toLocaleString()}</td>
        <td style="color:${C.muted}">${scorePct}</td>
        <td>${r.new_shires || 0}</td>
        <td>${(r.efficiency || 0).toFixed(3)}</td>
        <td style="color:${C.muted}">${bestRate}</td>
        <td style="color:${tempCol}">${lastStr}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  function reset() {
    _be = [];
    if (bandChart) { bandChart.destroy(); bandChart = null; }
    const tbody = document.getElementById('bands-tbody');
    if (tbody) tbody.innerHTML = '';
    _bandeffLoaded = false;
  }

  window.addEventListener('vka:snapshot', e => update(e.detail));
  window.addEventListener('vka:loaded', reset);
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab === 'bands') {
      const snap = window.VKA.lastSnap();
      if (snap) update(snap);
      if (!_bandeffLoaded) loadBandeffYoy();
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // ── Band efficiency year-over-year (same contest series) ───────────────
  // ═══════════════════════════════════════════════════════════════════════
  const BANDEFF_PALETTE = ['#00d4aa','#ff6b35','#f0c040','#2ed573','#64b5f6',
                            '#e040fb','#ff5252','#69f0ae','#ea80fc','#80d8ff'];
  const KNOWN_BANDS = ["160M","80M","60M","40M","30M","20M","17M","15M","12M","10M","6M","2M","70CM"];

  let _bandeffContests = [];
  let _bandeffLoaded   = false;
  let bandeffYoyChart  = null;

  async function loadBandeffYoy() {
    const msg     = document.getElementById('bandeff-yoy-msg');
    const content = document.getElementById('bandeff-yoy-content');
    try {
      const res  = await fetch('/api/bandeff_yoy');
      const data = await res.json();
      _bandeffContests = data.contests || [];
      _bandeffLoaded   = true;
      if (!_bandeffContests.length) {
        if (content) content.style.display = 'none';
        if (msg) msg.style.display = 'block';
        return;
      }
      if (msg)     msg.style.display = 'none';
      if (content) content.style.display = '';
      renderBandeffYoy();
    } catch (e) { console.warn('BandEff YoY load failed:', e); }
  }

  function renderBandeffYoy() {
    const canvas = document.getElementById('chart-bandeff-yoy');
    if (!canvas) return;
    const contests = [...(_bandeffContests || [])].sort((a, b) => (a.year||0) - (b.year||0));

    // Only real bands, in canonical order — some plugins (arrl10m, hasprnt)
    // repurpose the "band" field to hold a mode name for single-band contests;
    // those rows aren't meaningful on a per-band chart, so they're excluded.
    const bandsPresent = new Set();
    contests.forEach(c => (c.bands||[]).forEach(r => {
      if (KNOWN_BANDS.includes((r.band||'').toUpperCase())) bandsPresent.add(r.band.toUpperCase());
    }));
    const labels = KNOWN_BANDS.filter(b => bandsPresent.has(b));

    const datasets = contests.map((c, i) => {
      const byBand = {};
      (c.bands||[]).forEach(r => { byBand[(r.band||'').toUpperCase()] = r.efficiency || 0; });
      return {
        label: c.label,
        data: labels.map(b => byBand[b] ?? 0),
        backgroundColor: BANDEFF_PALETTE[i % BANDEFF_PALETTE.length] + 'cc',
        borderColor: BANDEFF_PALETTE[i % BANDEFF_PALETTE.length],
        borderWidth: 1,
      };
    });

    if (bandeffYoyChart) { bandeffYoyChart.destroy(); bandeffYoyChart = null; }
    bandeffYoyChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { labels: labels.map(b => b.toLowerCase()), datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: true, position: 'top',
            labels: { color: C.muted, font: { size: 9, family: 'Consolas' }, boxWidth: 12 } },
          tooltip: { backgroundColor: C.bg3, bodyColor: C.fg, borderWidth: 1 },
        },
        scales: {
          x: { ticks: { color: C.muted, font: { size: 10, family: 'Consolas' } }, grid: { display: false } },
          y: { ticks: { color: C.muted, font: { size: 9 } }, grid: { color: C.bg3 + '80' },
               title: { display: true, text: 'Efficiency', color: C.muted, font: { size: 9 } } },
        },
      },
    });

    const footnote = document.getElementById('bandeff-yoy-footnote');
    if (footnote) {
      const labelsUsed = new Set(contests.map(c => c.efficiency_label || 'mults/qso'));
      const perYear = contests.map(c => `${c.year} (${c.efficiency_label || 'mults/qso'})`).join(', ');
      footnote.textContent = labelsUsed.size > 1
        ? `⚠ Mixed efficiency metrics across years — compare with care: ${perYear}`
        : `Efficiency metric: ${[...labelsUsed][0]}  —  years shown: ${perYear}`;
    }
  }

  async function addBandeffLog() {
    const btn = document.getElementById('bandeff-add-log-btn');
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      const data = await window.VKA.browseFile();
      if (data.error || !data.path) return;
      const res2  = await fetch('/api/bandeff_yoy/add_log', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: data.path }),
      });
      const data2 = await res2.json();
      if (data2.error) { console.warn('Add band-efficiency log:', data2.error); return; }
      _bandeffContests = data2.contests || [];
      _bandeffLoaded   = true;
      const msg = document.getElementById('bandeff-yoy-msg');
      const content = document.getElementById('bandeff-yoy-content');
      if (msg)     msg.style.display = 'none';
      if (content) content.style.display = '';
      renderBandeffYoy();
    } catch (e) { console.warn('Add band-efficiency log failed:', e); }
    finally { if (btn) { btn.disabled = false; btn.textContent = '+ Add Log File'; } }
  }

  async function clearBandeffLogs() {
    try {
      const res  = await fetch('/api/bandeff_yoy/clear_logs', { method: 'POST' });
      const data = await res.json();
      _bandeffContests = data.contests || [];
      if (_bandeffContests.length) renderBandeffYoy();
      else {
        const msg = document.getElementById('bandeff-yoy-msg');
        const content = document.getElementById('bandeff-yoy-content');
        if (content) content.style.display = 'none';
        if (msg) msg.style.display = 'block';
      }
    } catch (e) { console.warn('Clear band-efficiency logs failed:', e); }
  }

  document.getElementById('bandeff-add-log-btn')?.addEventListener('click', addBandeffLog);
  document.getElementById('bandeff-clear-logs-btn')?.addEventListener('click', clearBandeffLogs);

})();
