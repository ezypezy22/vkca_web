/**
 * yoy.js — Year on Year comparison tab
 */
;(function () {
  'use strict';
  const C = { accent:'#00d4aa', accent2:'#ff6b35', accent3:'#f0c040',
               green:'#2ed573', muted:'#8b949e', bg3:'#21262d', fg:'#e6edf3' };

  let scoreChart = null;
  let qsoChart   = null;

  async function load() {
    const wrap = document.getElementById('yoy-loading');
    if (wrap) { wrap.style.display = 'flex'; }
    try {
      const res  = await fetch('/api/yoy');
      const data = await res.json();
      if (wrap) wrap.style.display = 'none';
      if (!data.length) {
        showMsg('No historical data found for this contest in your log.');
        return;
      }
      renderCharts(data);
      renderTable(data);
    } catch (e) {
      if (wrap) wrap.style.display = 'none';
      showMsg('Failed to load YOY data: ' + e.message);
    }
  }

  function showMsg(msg) {
    const el = document.getElementById('yoy-msg');
    if (el) { el.textContent = msg; el.style.display = 'block'; }
  }

  function renderCharts(data) {
    const labels = data.map(r => r.year || r.start_date);
    const scores = data.map(r => r.score || 0);
    const qsos   = data.map(r => r.qsos  || 0);
    const mults  = data.map(r => r.mults || 0);
    const isCur  = data.map(r => r.is_current);

    const barCols  = isCur.map(c => c ? C.accent  : C.accent  + '55');
    const barCols2 = isCur.map(c => c ? C.accent3 : C.accent3 + '55');

    // Score chart
    const sc = document.getElementById('chart-yoy-score');
    if (sc) {
      if (scoreChart) { scoreChart.destroy(); scoreChart = null; }
      scoreChart = new Chart(sc.getContext('2d'), {
        type: 'bar',
        data: {
          labels,
          datasets: [
            { label:'Score', data:scores, backgroundColor:barCols,
              borderColor:barCols.map(c=>c.slice(0,7)), borderWidth:1, borderRadius:4,
              yAxisID:'y' },
            { label:'Mults', data:mults, backgroundColor:barCols2,
              borderColor:barCols2.map(c=>c.slice(0,7)), borderWidth:1, borderRadius:4,
              yAxisID:'y2', type:'bar' },
          ],
        },
        options: {
          responsive:true, maintainAspectRatio:false,
          animation:{ duration:600, easing:'easeOutQuart' },
          plugins:{
            legend:{ display:true, position:'top',
              labels:{ color:C.muted, font:{size:9,family:'Consolas'} } },
            tooltip:{
              backgroundColor:C.bg3, bodyColor:C.fg, titleColor:C.accent,
              callbacks:{
                afterLabel: item => item.datasetIndex===0
                  ? `  Mults: ${mults[item.dataIndex]}` : ''
              }
            },
          },
          scales:{
            x:{ ticks:{color:isCur.map(c=>c?C.accent:C.muted),
                        font:{size:11,weight:'bold'}}, grid:{display:false} },
            y:{ position:'left', ticks:{color:C.accent,font:{size:9}},
                grid:{color:C.bg3+'80'},
                title:{display:true,text:'Score',color:C.accent,font:{size:9}} },
            y2:{ position:'right', ticks:{color:C.accent3,font:{size:9}},
                 grid:{display:false},
                 title:{display:true,text:'Mults',color:C.accent3,font:{size:9}} },
          },
        },
      });
    }

    // QSO trend line
    const qc = document.getElementById('chart-yoy-qsos');
    if (qc) {
      if (qsoChart) { qsoChart.destroy(); qsoChart = null; }
      qsoChart = new Chart(qc.getContext('2d'), {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label:'Valid QSOs', data:qsos,
            borderColor:C.green, backgroundColor:C.green+'22',
            borderWidth:2, fill:true, tension:0.3,
            pointRadius:5, pointBackgroundColor:isCur.map(c=>c?C.accent:C.green),
            pointBorderColor:isCur.map(c=>c?C.accent:C.green),
            pointBorderWidth:2,
          }],
        },
        options: {
          responsive:true, maintainAspectRatio:false,
          animation:{ duration:600 },
          plugins:{
            legend:{display:false},
            tooltip:{
              backgroundColor:C.bg3, bodyColor:C.fg, titleColor:C.green,
              callbacks:{ label: i=>`  ${i.raw.toLocaleString()} QSOs` }
            },
          },
          scales:{
            x:{ ticks:{color:isCur.map(c=>c?C.accent:C.muted),
                        font:{size:11,weight:'bold'}}, grid:{display:false} },
            y:{ ticks:{color:C.muted,font:{size:9}}, grid:{color:C.bg3+'80'},
                beginAtZero:true },
          },
        },
      });
    }
  }

  function renderTable(data) {
    const tbody = document.getElementById('yoy-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    // Sort newest first for the table
    [...data].reverse().forEach(r => {
      const tr = document.createElement('tr');
      tr.style.fontWeight = r.is_current ? 'bold' : '';
      const scoreCol = r.is_current ? 'var(--accent)' : 'var(--fg)';
      tr.innerHTML = `
        <td style="color:${scoreCol}">${r.year || r.start_date}</td>
        <td>${(r.qsos||0).toLocaleString()}</td>
        <td>${(r.mults||0).toLocaleString()}</td>
        <td>${(r.band_mults||0).toLocaleString()}</td>
        <td style="color:${scoreCol};font-weight:bold">${(r.score||0).toLocaleString()}</td>
        <td>${r.is_current ? '◀ current' : ''}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  window.addEventListener('vka:snapshot', load);
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab==='yoy') load(); });
})();
