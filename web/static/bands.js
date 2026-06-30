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

  function update(snap) {
    const be = snap?.band_efficiency;
    if (!be || !be.length) return;

    const labels  = be.map(r => r.band.toLowerCase());
    const effic   = be.map(r => r.efficiency || 0);
    const qsos    = be.map(r => r.qsos || 0);
    const mults   = be.map(r => r.new_shires || 0);
    const colours = labels.map(b => BAND_COLS[b] || C.muted);

    updateChart(labels, effic, colours, qsos, mults);
    updateTable(be, colours);
  }

  function updateChart(labels, effic, colours, qsos, mults) {
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

  function updateTable(be, colours) {
    const tbody = document.getElementById('bands-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    be.forEach((r, i) => {
      const col = colours[i] || C.muted;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:${col};font-weight:bold">${r.band.toLowerCase()}</td>
        <td>${r.qsos || 0}</td>
        <td>${r.new_shires || 0}</td>
        <td>${(r.efficiency || 0).toFixed(3)}</td>`;
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
