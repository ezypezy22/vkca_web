/**
 * cluster.js — DX Cluster tab with WebSocket telnet bridge
 */
;(function () {
  'use strict';
  const C = { accent:'#00d4aa', accent2:'#ff6b35', accent3:'#f0c040',
               green:'#2ed573', red:'#ff4757', muted:'#8b949e',
               bg3:'#21262d', fg:'#e6edf3' };
  const BAND_COLS = {
    '160M':'#e040fb','80M':'#ff6b35','60M':'#f0c040','40M':'#2ed573',
    '30M':'#00bcd4','20M':'#00d4aa','17M':'#64b5f6','15M':'#ff5252',
    '12M':'#ffab40','10M':'#69f0ae','6M':'#ea80fc','2M':'#80d8ff',
  };

  let ws       = null;
  let spots    = [];
  const MAX_SPOTS = 200;
  let filterBand = 'ALL';
  let filterCall = '';

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const statusDot  = document.getElementById('cluster-status-dot');
  const statusText = document.getElementById('cluster-status-text');
  const callInput  = document.getElementById('cluster-callsign');
  const hostSelect = document.getElementById('cluster-host-select');
  const hostInput  = document.getElementById('cluster-host-input');
  const portInput  = document.getElementById('cluster-port-input');
  const btnConnect = document.getElementById('cluster-connect-btn');
  const btnDisconn = document.getElementById('cluster-disconnect-btn');
  const cmdInput   = document.getElementById('cluster-cmd-input');
  const rawFeed    = document.getElementById('cluster-raw-feed');
  const spotTbody  = document.getElementById('cluster-spots-tbody');
  const spotCount  = document.getElementById('cluster-spot-count');

  function setStatus(connected, msg) {
    if (statusDot)  { statusDot.className = 'cluster-dot ' + (connected?'dot-conn':'dot-disc'); }
    if (statusText) statusText.textContent = msg;
    if (btnConnect) btnConnect.disabled  = connected;
    if (btnDisconn) btnDisconn.disabled  = !connected;
  }

  // Load presets
  fetch('/api/cluster/presets').then(r=>r.json()).then(presets=>{
    if (!hostSelect) return;
    presets.forEach(p=>{
      const opt=document.createElement('option');
      opt.value=`${p.host}:${p.port}`;
      opt.textContent=p.label;
      hostSelect.appendChild(opt);
    });
    // Set first preset
    if (presets.length && hostInput && portInput) {
      hostInput.value = presets[0].host;
      portInput.value = presets[0].port;
    }
  }).catch(()=>{});

  if (hostSelect) {
    hostSelect.addEventListener('change', ()=>{
      const [h,p] = (hostSelect.value||'').split(':');
      if (h && hostInput) hostInput.value = h;
      if (p && portInput) portInput.value = p;
    });
  }

  // ── Connect ───────────────────────────────────────────────────────────────
  function connect() {
    if (ws) { ws.close(); ws=null; }
    const url = `ws://${location.host}/ws/cluster`;
    ws = new WebSocket(url);
    setStatus(false, 'Connecting…');

    ws.onopen = () => {
      ws.send(JSON.stringify({
        cmd:'connect',
        host: hostInput?.value.trim() || 'vk2rcg.ampr.org',
        port: parseInt(portInput?.value||'7300'),
        callsign: callInput?.value.trim() || 'VK2YI',
      }));
    };

    ws.onmessage = ev=>{
      let msg; try { msg=JSON.parse(ev.data); } catch { return; }
      if (msg.type==='status') {
        setStatus(msg.connected, msg.msg);
      } else if (msg.type==='raw') {
        appendRaw(msg.line);
      } else if (msg.type==='spot') {
        addSpot(msg);
      }
    };

    ws.onclose = ()=>setStatus(false, 'Disconnected');
    ws.onerror = ()=>setStatus(false, 'Connection error');
  }

  function disconnect() {
    if (ws) { ws.send(JSON.stringify({cmd:'disconnect'})); ws.close(); ws=null; }
    setStatus(false, 'Disconnected');
  }

  btnConnect?.addEventListener('click', connect);
  btnDisconn?.addEventListener('click', disconnect);

  // Send raw command
  cmdInput?.addEventListener('keydown', e=>{
    if (e.key==='Enter' && ws && cmdInput.value.trim()) {
      ws.send(JSON.stringify({cmd:'send', text:cmdInput.value.trim()}));
      appendRaw('> '+cmdInput.value.trim());
      cmdInput.value='';
    }
  });

  // ── Raw feed ──────────────────────────────────────────────────────────────
  function appendRaw(line) {
    if (!rawFeed) return;
    const div=document.createElement('div');
    div.textContent = line;
    div.style.color = line.startsWith('DX de') ? C.accent : C.muted;
    rawFeed.appendChild(div);
    // Keep last 200 lines
    while (rawFeed.children.length > 200) rawFeed.removeChild(rawFeed.firstChild);
    rawFeed.scrollTop = rawFeed.scrollHeight;
  }

  // ── Spot list ─────────────────────────────────────────────────────────────
  function addSpot(spot) {
    spots.unshift(spot);
    if (spots.length > MAX_SPOTS) spots = spots.slice(0, MAX_SPOTS);
    renderSpots();
  }

  function renderSpots() {
    if (!spotTbody) return;
    const q = filterCall.toUpperCase();
    const filtered = spots.filter(s=>{
      if (filterBand !== 'ALL' && s.band !== filterBand) return false;
      if (q && !s.dx.toUpperCase().includes(q) && !s.spotter.toUpperCase().includes(q)) return false;
      return true;
    });
    if (spotCount) spotCount.textContent = filtered.length;
    spotTbody.innerHTML='';
    const frag=document.createDocumentFragment();
    filtered.slice(0,100).forEach(s=>{
      const col=BAND_COLS[s.band]||C.muted;
      const tr=document.createElement('tr');
      tr.innerHTML=`
        <td style="color:${C.accent};font-weight:bold">${s.dx}</td>
        <td style="color:${col}">${s.freq}</td>
        <td style="color:${col}">${s.band}</td>
        <td style="color:${C.muted}">${s.spotter}</td>
        <td style="color:${C.fg}">${s.comment}</td>
        <td style="color:${C.muted}">${s.time}</td>`;
      frag.appendChild(tr);
    });
    spotTbody.appendChild(frag);
  }

  // Band filter buttons
  document.querySelectorAll('.cluster-band-btn').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      document.querySelectorAll('.cluster-band-btn').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      filterBand = btn.dataset.band;
      renderSpots();
    });
  });

  // Call filter
  document.getElementById('cluster-filter')?.addEventListener('input', e=>{
    filterCall = e.target.value;
    renderSpots();
  });

  setStatus(false, 'Not connected');
})();
