/**
 * rate.js — Rate Analysis tab: QSOs/hour bar chart + session summary table
 */
;(function () {
  'use strict';
  const C = { accent:'#00d4aa', accent2:'#ff6b35', accent3:'#f0c040',
               muted:'#8b949e', bg3:'#21262d', fg:'#e6edf3', green:'#2ed573' };

  let rateChart = null;
  let multsChart = null;

  async function load() {
    const [rateRes, sessRes] = await Promise.all([
      fetch('/api/rate'), fetch('/api/sessions')
    ]);
    const rateData = await rateRes.json();
    const sessData = await sessRes.json();
    renderRateChart(rateData);
    renderMultsChart(rateData);
    renderSessionTable(sessData);
  }

  function renderRateChart(data) {
    if (!data.length) return;
    const labels = data.map(r => {
      const d = new Date(r.hour);
      return `${String(d.getUTCHours()).padStart(2,'0')}:00`;
    });
    const values = data.map(r => r.qsos);
    const maxVal = Math.max(...values, 1);
    // Colour bars by intensity: low=muted, high=accent
    const colours = values.map(v => {
      const t = v / maxVal;
      return t > 0.7 ? C.accent : t > 0.4 ? C.accent3 : C.muted + '88';
    });

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
            callbacks: { title: i => `Hour ${i[0].label}`, label: i => ` ${i.raw} QSOs` }
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
      const d = new Date(r.hour);
      return `${String(d.getUTCHours()).padStart(2,'0')}:00`;
    });
    const values = data.map(r => r.mults || 0);

    const canvas = document.getElementById('chart-rate-mults');
    if (!canvas) return;
    if (multsChart) { multsChart.destroy(); multsChart = null; }

    multsChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'New mults',
          data: values,
          backgroundColor: C.accent3,
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
            titleColor: C.accent3, borderColor: C.bg3, borderWidth: 1,
            callbacks: { title: i => `Hour ${i[0].label}`, label: i => ` ${i.raw} new mults` }
          },
        },
        scales: {
          x: { ticks:{color:C.muted,font:{size:9},maxRotation:45},
               grid:{color:C.bg3+'80'} },
          y: { ticks:{color:C.muted,font:{size:9},precision:0},
               grid:{color:C.bg3+'80'}, beginAtZero:true,
               title:{display:true,text:'New mults / hour',color:C.muted,font:{size:9}} },
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

  window.addEventListener('vka:snapshot', load);
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab==='rate') load(); });
})();
