/**
 * dupes.js — Dupe Checker: full breakdown with per-band chart + call table
 * Also handles case where no dupes exist (shows "clean log" message)
 */
;(function () {
  'use strict';
  const C = { accent:'#00d4aa', accent2:'#ff6b35', muted:'#8b949e',
               bg3:'#21262d', fg:'#e6edf3', accent3:'#f0c040', green:'#2ed573' };
  const BAND_COLS = window.VKA.BAND_COLS;
  const escapeHtml = window.VKA.escapeHtml;

  let bandChart = null;

  async function load() {
    try {
      const res  = await fetch('/api/dupes');
      const data = await res.json();
      const byBand = data.by_band || {};
      const byCall = data.by_call || {};
      const total  = Object.values(byBand).reduce((a,b)=>a+b, 0);

      // Update badge
      const el = document.getElementById('dupe-total');
      if (el) el.textContent = total;

      // Per-contest dupe rule description (e.g. ARRL 10M's "once per band
      // per mode" vs. the WPX-style "once per band" default) — see issue #8,
      // this used to be hardcoded to WPX's wording regardless of contest.
      const ruleEl = document.getElementById('dupe-rule-text');
      if (ruleEl && data.rule_text) ruleEl.textContent = data.rule_text;

      if (total === 0) {
        // Clean log — show positive message
        renderCleanLog(byBand, byCall);
      } else {
        renderBandChart(byBand);
        renderCallTable(byCall);
        renderDupeQsos();
      }
    } catch(e) {
      const tbody = document.getElementById('dupes-call-tbody');
      if (tbody) tbody.innerHTML = `<tr><td colspan="2" style="color:var(--red);padding:12px">Load failed: ${e.message}</td></tr>`;
    }
  }

  // Lazily creates (once) a sibling "clean log" message inside the chart's
  // wrapper, so toggling it never touches the <canvas> itself — destroying
  // the canvas via innerHTML used to permanently break renderBandChart's
  // later getElementById lookup once any dupes did show up.
  function getBandEmptyEl() {
    const canvas = document.getElementById('chart-dupes-band');
    if (!canvas) return null;
    const wrap = canvas.parentElement;
    let empty = document.getElementById('dupes-band-empty');
    if (!empty && wrap) {
      empty = document.createElement('div');
      empty.id = 'dupes-band-empty';
      empty.style.cssText = 'display:none;align-items:center;justify-content:center;' +
        'height:140px;font-family:var(--font-mono);font-size:0.85em;color:var(--green);' +
        'flex-direction:column;gap:8px';
      empty.innerHTML = '<span style="font-size:2em">✓</span>' +
        '<span>No duplicate QSOs detected — clean log!</span>';
      wrap.appendChild(empty);
    }
    return empty;
  }

  function renderCleanLog() {
    const canvas = document.getElementById('chart-dupes-band');
    if (canvas) canvas.style.display = 'none';
    const empty = getBandEmptyEl();
    if (empty) empty.style.display = 'flex';
    const tbody = document.getElementById('dupes-call-tbody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="2" style="color:var(--green);padding:12px;
      font-family:var(--font-mono)">All QSOs unique — no dupes found.</td></tr>`;
  }

  function renderBandChart(byBand) {
    const empty = getBandEmptyEl();
    if (empty) empty.style.display = 'none';

    // Normalise band keys: strip spaces, uppercase
    const normalised = {};
    Object.entries(byBand).forEach(([k,v]) => {
      normalised[k.trim().toUpperCase()] = v;
    });

    const bands  = Object.keys(normalised).sort((a,b) => {
      // Sort by frequency (160M first)
      const order = ['160M','80M','60M','40M','30M','20M','17M','15M','12M','10M','6M','2M'];
      return (order.indexOf(a)||99) - (order.indexOf(b)||99);
    });
    const values = bands.map(b => normalised[b]);
    const cols   = bands.map(b => BAND_COLS[b] || C.muted);
    const canvas = document.getElementById('chart-dupes-band');
    if (!canvas) return;
    if (bandChart) { bandChart.destroy(); bandChart = null; }

    if (!bands.length) {
      canvas.style.display = 'none';
      if (empty) empty.style.display = 'flex';
      return;
    }
    canvas.style.display = '';

    bandChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: bands.map(b=>b.toLowerCase()),
        datasets: [{ label:'Dupes', data:values,
          backgroundColor:cols.map(c=>c+'cc'),
          borderColor:cols, borderWidth:1, borderRadius:4 }],
      },
      options: {
        responsive:true, maintainAspectRatio:false,
        animation:{ duration:500, easing:'easeOutQuart' },
        plugins:{ legend:{display:false},
          tooltip:{ backgroundColor:C.bg3, bodyColor:C.fg, titleColor:C.accent2,
            callbacks:{
              title: i => i[0].label.toUpperCase(),
              label: i => ` ${i.raw} dupe${i.raw!==1?'s':''}`
            }}},
        scales:{
          x:{ ticks:{color:cols, font:{size:11,weight:'bold'}}, grid:{display:false} },
          y:{ ticks:{color:C.muted,font:{size:9}}, grid:{color:C.bg3+'80'},
              beginAtZero:true, precision:0 },
        },
      },
    });
  }

  function renderCallTable(byCall) {
    const tbody = document.getElementById('dupes-call-tbody');
    if (!tbody) return;
    const entries = Object.entries(byCall).sort((a,b)=>b[1]-a[1]);
    if (!entries.length) {
      tbody.innerHTML = '<tr><td colspan="2" style="color:var(--muted);padding:10px">No dupes by callsign</td></tr>';
      return;
    }
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    entries.forEach(([call, n]) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:var(--accent2);font-weight:bold">${call}</td>
        <td style="color:var(--accent2)">${n} dupe${n!==1?'s':''}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  // Show the actual dupe QSOs in a separate table
  async function renderDupeQsos() {
    const wrap = document.getElementById('dupes-qso-wrap');
    if (!wrap) return;
    try {
      const res  = await fetch('/api/qsos');
      const qsos = await res.json();
      const dupes = qsos.filter(q => q.dupe);
      if (!dupes.length) { wrap.style.display='none'; return; }
      wrap.style.display = '';

      const tbody = document.getElementById('dupes-qso-tbody');
      if (!tbody) return;
      tbody.innerHTML = '';
      const frag = document.createDocumentFragment();
      dupes.slice(0, 200).forEach(q => {
        const band = (q.band||'').toUpperCase();
        const col  = BAND_COLS[band]||C.muted;
        const tr   = document.createElement('tr');
        tr.style.opacity = '0.75';
        tr.innerHTML = `
          <td style="color:var(--accent2);font-weight:bold">${escapeHtml(q.call||'—')}</td>
          <td style="color:${col}">${band.toLowerCase()}</td>
          <td>${q.mode||'—'}</td>
          <td style="color:var(--muted);font-size:0.85em">${String(q.time||'').substring(0,19).replace('T',' ')} UTC</td>
          <td style="color:${col}">${escapeHtml(q.mult1||'—')}</td>
          <td style="color:var(--muted);font-size:0.85em">${q.dupe_reason||'Duplicate contact'}</td>`;
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
    } catch {}
  }

  window.addEventListener('vka:snapshot', load);
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab==='dupes') load(); });
})();
