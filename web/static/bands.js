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

  window.addEventListener('vka:snapshot', e => update(e.detail));
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab === 'bands') {
      const snap = window.VKA.lastSnap();
      if (snap) update(snap);
    }
  });

})();
