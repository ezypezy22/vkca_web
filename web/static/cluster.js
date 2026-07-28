/**
 * cluster.js — DX Cluster tab with WebSocket telnet bridge
 */
;(function () {
  'use strict';
  // Mutable (not const) — kept in sync with the active theme by onTheme()
  // below. "blue" has no equivalent in the server's theme palette (it's
  // this tab's own decorative NEW_BAND colour, not a shared UI colour), so
  // it never changes with the theme.
  let C = { accent:'#00d4aa', accent2:'#ff6b35', accent3:'#f0c040',
               green:'#2ed573', blue:'#64b5f6', red:'#ff4757', muted:'#8b949e',
               bg3:'#21262d', fg:'#e6edf3' };
  const BAND_COLS = window.VKA.BAND_COLS;
  const escapeHtml = window.VKA.escapeHtml;
  // Whether the active theme is light-background — a flat opacity tuned to
  // read well on a near-black background fades to near-invisible on a
  // near-white one, so the de-emphasis tiers below need a lighter-theme
  // variant rather than a single fixed value. Same "starts with #f/#e"
  // heuristic app.js's applyTheme() uses.
  let _isLightTheme = false;
  // Status -> row styling, mirrors the old desktop app's tree tags. Rebuilt
  // (not just declared once) by rebuildStatusStyle() so it tracks both C
  // and _isLightTheme across theme changes.
  let STATUS_STYLE = {};
  function rebuildStatusStyle() {
    const dim = _isLightTheme ? { WORKED: 0.8, NOT_MULT: 0.62 } : { WORKED: 0.6, NOT_MULT: 0.35 };
    STATUS_STYLE = {
      NEW_MULT: { color: C.green,  weight: 'bold',   opacity: 1 },
      NEW_BAND: { color: C.blue,   weight: 'bold',   opacity: 1 },
      WORKED:   { color: C.muted,  weight: 'normal',  opacity: dim.WORKED },
      NOT_MULT: { color: C.muted,  weight: 'normal',  opacity: dim.NOT_MULT },
      NO_LOG:   { color: C.fg,     weight: 'normal',  opacity: 1 },
    };
  }
  rebuildStatusStyle();

  // ── Theme sync — cluster.js keeps its own colour copy (used throughout
  // this file's inline-styled HTML) rather than reading CSS vars per
  // render, so it must be told about theme changes explicitly. Chains onto
  // whatever handler overview.js (loaded first) already registered, rather
  // than clobbering it — window.VKA.onTheme is a single slot shared by
  // every tab that needs one.
  function onThemeChange(palette) {
    if (!palette) return;
    C = { ...C,
      accent: palette.accent, accent2: palette.accent2, accent3: palette.accent3,
      green: palette.green, red: palette.red, muted: palette.muted,
      bg3: palette.bg3, fg: palette.fg,
    };
    _isLightTheme = !!(palette.bg && (palette.bg.startsWith('#f') || palette.bg.startsWith('#e')));
    rebuildStatusStyle();
    renderSpots();
    if (_lastRadioInfo) renderRadioBoard(_lastRadioInfo);
  }
  window.VKA = window.VKA || {};
  {
    const _prevOnTheme = window.VKA.onTheme;
    window.VKA.onTheme = function (palette) {
      if (_prevOnTheme) _prevOnTheme(palette);
      onThemeChange(palette);
    };
  }

  let ws         = null;
  let spots      = [];
  let bandsInLog = null;  // Set of bands this contest's rules allow, or null
  const MAX_SPOTS = 200;
  let filterBand = 'ALL';
  let filterCall = '';
  let filterMode = 'ALL';
  let _currentBand = null;   // radio_info.own.band, from the main app's snapshot stream
  let _lastRadioInfo = null; // full {own, all} radio_info, for Band Advisor occupancy notes

  // ── New-spot glow + spot-age fade ────────────────────────────────────────
  // renderSpots() rebuilds the whole tbody from scratch on every single new
  // spot (see below), so a burst of spots landing in the same tick would
  // destroy an earlier spot's freshly-flashed row before its animation ever
  // painted if "already flashed" were tracked as a one-shot flag. Using a
  // freshness *window* instead means the row a burst finally settles on
  // still gets its glow, however many rebuilds happened in between.
  const FLASH_WINDOW_MS = 1500;
  const FLASH_CLASS = { NEW_MULT: 'spot-flash-mult', NEW_BAND: 'spot-flash-band' };

  // Rows dim in two steps as spots age out of relevance — a spot from 20
  // minutes ago is much less actionable than one from 20 seconds ago.
  function ageOpacityMul(receivedAt) {
    const ageMin = (Date.now() - receivedAt) / 60000;
    if (ageMin > 8) return 0.5;
    if (ageMin > 2) return 0.75;
    return 1;
  }

  function applyRowAge(tr) {
    const base = parseFloat(tr.dataset.baseOpacity || '1');
    const receivedAt = parseInt(tr.dataset.receivedAt || '0', 10);
    tr.style.opacity = base * ageOpacityMul(receivedAt);
  }

  function tickSpotAges() {
    if (!spotTbody) return;
    for (const tr of spotTbody.children) applyRowAge(tr);
    // Band Advisor scores decay with spot age even when no new spot arrives
    // to trigger a re-render — keep it ticking down on its own.
    renderBandAdvisor();
  }
  setInterval(tickSpotAges, 15000);

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
  const rawToggle  = document.getElementById('cluster-raw-toggle');
  const rawArrow   = document.getElementById('cluster-raw-arrow');
  const spotTbody  = document.getElementById('cluster-spots-tbody');
  const spotCount  = document.getElementById('cluster-spot-count');
  const adviceBox  = document.getElementById('cluster-advice');
  const shdxInput  = document.getElementById('cluster-shdx-input');
  const shdxBtn    = document.getElementById('cluster-shdx-btn');
  const clearBtn   = document.getElementById('cluster-clear-btn');
  const chkNewMult = document.getElementById('cluster-show-newmult');
  const chkNewBand = document.getElementById('cluster-show-newband');
  const chkWorked  = document.getElementById('cluster-show-worked');
  const chkNotMult = document.getElementById('cluster-show-notmult');
  const chkBandsOnly = document.getElementById('cluster-bands-only');
  const modeFilterSelect = document.getElementById('cluster-mode-filter');
  const chkAlert    = document.getElementById('cluster-alert-toggle');
  const clusterGrid    = document.getElementById('cluster-grid');
  const resizeHandle    = document.getElementById('cluster-resize-handle');

  // ── Raw-feed column drag-resize ─────────────────────────────────────────
  const RAW_W_KEY = 'vka_cluster_raw_w';
  const RAW_W_MIN = 220;
  const RAW_W_MAX = 700;
  function setRawFeedWidth(px) {
    px = Math.max(RAW_W_MIN, Math.min(RAW_W_MAX, px));
    if (clusterGrid) clusterGrid.style.gridTemplateColumns = `1fr 8px ${px}px`;
    return px;
  }
  {
    const stored = parseInt(localStorage.getItem(RAW_W_KEY) || '300', 10);
    setRawFeedWidth(isNaN(stored) ? 300 : stored);
  }
  if (resizeHandle && clusterGrid) {
    resizeHandle.addEventListener('mousedown', e => {
      e.preventDefault();
      const startX = e.clientX;
      const rawPanel = resizeHandle.nextElementSibling;
      const startPanelW = rawPanel.getBoundingClientRect().width;
      resizeHandle.classList.add('dragging');
      function onMove(ev) {
        const dx = ev.clientX - startX;
        setRawFeedWidth(startPanelW - dx);
      }
      function onUp() {
        resizeHandle.classList.remove('dragging');
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        localStorage.setItem(RAW_W_KEY, clusterGrid.style.gridTemplateColumns.split(' ').pop().replace('px',''));
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  // ── Audio / desktop alert on a spotted needed mult or band ──────────────────
  const ALERT_KEY = 'vka_cluster_alert';
  if (chkAlert) {
    const stored = localStorage.getItem(ALERT_KEY);
    chkAlert.checked = stored === null ? true : stored === '1';
    chkAlert.addEventListener('change', () => {
      localStorage.setItem(ALERT_KEY, chkAlert.checked ? '1' : '0');
      if (chkAlert.checked && 'Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().catch(() => {});
      }
    });
  }

  let _audioCtx = null;
  function beep() {
    try {
      _audioCtx = _audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const osc  = _audioCtx.createOscillator();
      const gain = _audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.15, _audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, _audioCtx.currentTime + 0.25);
      osc.connect(gain).connect(_audioCtx.destination);
      osc.start();
      osc.stop(_audioCtx.currentTime + 0.25);
    } catch (e) { /* Web Audio unavailable — ignore */ }
  }

  function alertOnSpot(spot) {
    if (!chkAlert?.checked) return;
    if (spot.status !== 'NEW_MULT' && spot.status !== 'NEW_BAND') return;
    beep();
    if ('Notification' in window && Notification.permission === 'granted') {
      const kind = spot.status === 'NEW_MULT' ? 'New mult' : 'New band';
      try {
        new Notification(`${kind}: ${spot.dx}`, {
          body: `${spot.band}  ${spot.mult || ''}`.trim(),
          tag: 'vka-cluster-alert',
        });
      } catch (e) { /* Notification unavailable — ignore */ }
    }
  }

  function setStatus(connected, msg) {
    if (statusDot)  { statusDot.className = 'cluster-dot ' + (connected?'dot-conn':'dot-disc'); }
    if (statusText) statusText.textContent = msg;
    if (btnConnect) { btnConnect.disabled = connected; btnConnect.style.display = connected ? 'none' : ''; }
    if (btnDisconn) {
      btnDisconn.disabled = !connected;
      btnDisconn.style.display = connected ? '' : 'none';
      btnDisconn.classList.toggle('btn--green', connected);
      btnDisconn.classList.toggle('btn--ghost', !connected);
    }
    if (shdxBtn) {
      shdxBtn.classList.toggle('btn--green', connected);
      shdxBtn.classList.toggle('btn--ghost', !connected);
    }
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

  // ── Bands this contest's rules allow (for "Contest bands only" filter) ───
  function loadBandsInLog() {
    fetch('/api/plugin_meta').then(r=>r.json()).then(meta=>{
      bandsInLog = new Set(meta.bands || []);
    }).catch(()=>{ bandsInLog = null; });
  }
  loadBandsInLog();
  window.addEventListener('vka:loaded', () => {
    loadBandsInLog();
    spots = [];
    renderSpots();
  });

  // ── Live radio awareness — band-match highlighting + "who's on the air"
  // board ──────────────────────────────────────────────────────────────────
  // cluster.js runs its own separate /ws/cluster connection for spot data,
  // so it doesn't otherwise see the main app's snapshot stream (radio_info
  // rides on every vka:snapshot — see web/radio_udp.py / app.js's
  // window.VKA.formatRadio()).
  const radioBoardBox = document.getElementById('cluster-radios');
  function renderRadioBoard(radioInfo) {
    if (!radioBoardBox) return;
    const all = Object.values(radioInfo?.all || {});
    if (!all.length) { radioBoardBox.style.display = 'none'; return; }
    radioBoardBox.style.display = '';
    const parts = all
      .sort((a, b) => (a.radio_nr || '').localeCompare(b.radio_nr || ''))
      .map(r => {
        const fr = window.VKA.formatRadio(r);
        if (!fr) return '';
        const op = r.op_call ? escapeHtml(r.op_call) + ' — ' : '';
        return `<span${fr.stale ? ' style="opacity:.55"' : ''}>` +
          `<span class="band-chip" style="background:${fr.bandColor}30;color:${fr.bandColor}">${fr.band}</span> ` +
          `${op}${fr.freqStr} MHz${fr.modeStr ? ' ' + escapeHtml(fr.modeStr) : ''}</span>`;
      });
    radioBoardBox.innerHTML = `<span style="color:${C.accent}">&#9654; ON THE AIR —</span> ` + parts.join('  &middot;  ');
  }

  window.addEventListener('vka:snapshot', e => {
    renderRadioBoard(e.detail?.radio_info);
    _lastRadioInfo = e.detail?.radio_info || null;
    // Only rebuild the (potentially 100-row) spot table when the band
    // actually changes, not on every ~1.5-5s snapshot tick — band-hops are
    // infrequent, unlike snapshot ticks.
    const band = e.detail?.radio_info?.own?.band || null;
    if (band !== _currentBand) { _currentBand = band; renderSpots(); }
    // A teammate's radio (Multi-Multi) can change band without ours moving —
    // renderSpots() (and its trailing renderBandAdvisor() call) only fires
    // on our own band change above, so refresh the advisor's occupancy
    // notes here too.
    else renderBandAdvisor();
  });

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

  // SH/DX backfill — button label tracks the requested count.
  function shdxCount() {
    let n = parseInt(shdxInput?.value || '20', 10);
    if (isNaN(n)) n = 20;
    return Math.max(10, Math.min(200, n));
  }
  function updateShdxLabel() {
    if (shdxBtn) shdxBtn.textContent = `Show Last ${shdxCount()} Spots`;
  }
  shdxInput?.addEventListener('input', updateShdxLabel);
  updateShdxLabel();

  shdxBtn?.addEventListener('click', () => {
    if (!ws) return;
    const text = `SH/DX ${shdxCount()}`;
    ws.send(JSON.stringify({cmd:'send', text}));
    appendRaw('> '+text);
  });

  clearBtn?.addEventListener('click', () => {
    spots = [];
    renderSpots();
  });

  rawToggle?.addEventListener('click', () => {
    if (!rawFeed) return;
    const hidden = rawFeed.style.display === 'none';
    rawFeed.style.display = hidden ? '' : 'none';
    if (rawArrow) rawArrow.textContent = hidden ? '▼' : '▶';
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
    spot._receivedAt = Date.now();
    spots.unshift(spot);
    if (spots.length > MAX_SPOTS) spots = spots.slice(0, MAX_SPOTS);
    alertOnSpot(spot);
    renderSpots();
    // Lets other tabs react to a spot landing without polling this module's
    // own private `spots` array — Missing Mults only cares about NEW_MULT
    // ones (see window.VKA.getRecentSpottedMults() below for that read
    // side), but the World Map plots every spot with a resolved lat/lon
    // regardless of status, so this fires for all of them.
    window.dispatchEvent(new CustomEvent('vka:cluster_spot', { detail: spot }));
  }

  // Needed mults spotted recently (status NEW_MULT), most-recent win per
  // mult code — read by missing.js to flag a missing mult as "spotted just
  // now" instead of a plain static checklist entry. Same recency window as
  // the Band Advisor below (ADVISOR_WINDOW_MS) so "recent" means the same
  // thing everywhere on this tab.
  window.VKA = window.VKA || {};
  window.VKA.getRecentSpottedMults = function () {
    const out = {};
    const cutoff = Date.now() - ADVISOR_WINDOW_MS;
    for (const s of spots) {
      if (s.status !== 'NEW_MULT' || !s.mult || s._receivedAt < cutoff) continue;
      if (!out[s.mult] || out[s.mult]._receivedAt < s._receivedAt) out[s.mult] = s;
    }
    return out;
  };

  function passesStatusFilter(s) {
    switch (s.status) {
      case 'NEW_MULT': return !!chkNewMult?.checked;
      case 'NEW_BAND': return !!chkNewBand?.checked;
      case 'WORKED':   return !!chkWorked?.checked;
      case 'NOT_MULT': return !!chkNotMult?.checked;
      default:          return true; // NO_LOG — always show, nothing to filter on
    }
  }

  function passesModeFilter(s) {
    if (filterMode === 'ALL') return true;
    if (filterMode === '__NONE__') return !s.mode;
    return s.mode === filterMode;
  }

  function renderSpots() {
    if (!spotTbody) return;
    const q = filterCall.toUpperCase();
    const bandsOnly = !!chkBandsOnly?.checked;
    const filtered = spots.filter(s=>{
      if (filterBand !== 'ALL' && s.band !== filterBand) return false;
      if (q && !s.dx.toUpperCase().includes(q) && !s.spotter.toUpperCase().includes(q)) return false;
      if (bandsOnly && bandsInLog && bandsInLog.size && !bandsInLog.has(s.band)) return false;
      if (!passesModeFilter(s)) return false;
      if (!passesStatusFilter(s)) return false;
      return true;
    });
    if (spotCount) spotCount.textContent = `${filtered.length} of ${spots.length}`;
    spotTbody.innerHTML='';
    const frag=document.createDocumentFragment();
    filtered.slice(0,100).forEach(s=>{
      const col   = BAND_COLS[s.band]||C.muted;
      const style = STATUS_STYLE[s.status] || STATUS_STYLE.NO_LOG;
      const tr=document.createElement('tr');
      tr.dataset.baseOpacity = style.opacity;
      tr.dataset.receivedAt  = s._receivedAt || Date.now();
      tr.title = 'Double-click to copy callsign';
      tr.innerHTML=`
        <td style="color:${style.color};font-weight:${style.weight}">${escapeHtml(s.dx)}</td>
        <td style="color:${col}">${s.freq}</td>
        <td style="color:${col}">${s.band}</td>
        <td style="color:${C.muted}">${s.mode||''}</td>
        <td style="color:${style.color}">${escapeHtml(s.mult||'')}</td>
        <td style="color:${C.muted}">${escapeHtml(s.region||'')}</td>
        <td style="color:${C.muted}">${escapeHtml(s.spotter)}</td>
        <td style="color:${C.fg}">${escapeHtml(s.comment)}</td>
        <td style="color:${C.muted}">${s.time}</td>`;
      tr.addEventListener('dblclick', () => {
        navigator.clipboard?.writeText(s.dx).catch(()=>{});
      });
      applyRowAge(tr);
      if (s._receivedAt && Date.now() - s._receivedAt < FLASH_WINDOW_MS) {
        tr.classList.add(FLASH_CLASS[s.status] || 'spot-flash-plain');
      }
      // Needed multipliers are the single most actionable spot on the
      // board — a one-time arrival flash isn't enough to keep it visible
      // once other spots start rolling in above/below it, so it also gets
      // a continuous, gentle pulse for as long as it stays a needed mult
      // (naturally stops the next time this spot is worked and re-renders
      // with a different status).
      if (s.status === 'NEW_MULT') tr.classList.add('spot-pulse-mult');
      // Steady marker (not another pulse — a busy band would turn into
      // visual noise with every row animating at once) for spots on the
      // band the radio is currently tuned to (see the vka:snapshot
      // listener above, which only re-renders on an actual band change).
      if (_currentBand && s.band === _currentBand) tr.classList.add('spot-current-band');
      frag.appendChild(tr);
    });
    spotTbody.appendChild(frag);
    renderBandAdvisor();
  }

  // ── Band Advisor — which band to point the radio at right now ───────────
  // Turns the DX Cluster's already-classified spots and the radio UDP
  // occupancy board (both otherwise passive readouts) into one active
  // recommendation: score every band by its recent needed-mult/needed-band
  // spots, decayed by age so a 19-minute-old spot barely counts, then name
  // the best one — annotated with who (if anyone) is already sitting there,
  // from radio_info.all, so a Multi-Multi op doesn't get told to jump onto
  // a band a teammate is already running.
  const ADVISOR_WINDOW_MS = 20 * 60 * 1000;
  const ADVISOR_WEIGHT = { NEW_MULT: 3, NEW_BAND: 1.5 };

  function computeBandOpportunities() {
    const now = Date.now();
    const bandsOnly = !!chkBandsOnly?.checked;
    const byBand = {};
    for (const s of spots) {
      if (s.status !== 'NEW_MULT' && s.status !== 'NEW_BAND') continue;
      if (!passesModeFilter(s)) continue;
      if (bandsOnly && bandsInLog && bandsInLog.size && !bandsInLog.has(s.band)) continue;
      const age = now - (s._receivedAt || now);
      if (age > ADVISOR_WINDOW_MS) continue;
      const decay = 1 - age / ADVISOR_WINDOW_MS;
      const rec = byBand[s.band] || (byBand[s.band] = { score: 0, multCount: 0, bandCount: 0, top: s, topAge: age });
      rec.score += (ADVISOR_WEIGHT[s.status] || 0) * decay;
      if (s.status === 'NEW_MULT') rec.multCount++; else rec.bandCount++;
      if (age < rec.topAge) { rec.top = s; rec.topAge = age; }
    }
    return byBand;
  }

  // Who else (not us) is currently parked on a given band, per the live
  // RadioInfo UDP feed — see web/radio_udp.py for the "own"/"all" split.
  function bandOccupants(band) {
    if (!_lastRadioInfo) return [];
    const own = _lastRadioInfo.own;
    const ownKey = own ? `${own.source_ip}|${own.radio_nr}` : null;
    return Object.entries(_lastRadioInfo.all || {})
      .filter(([key, r]) => key !== ownKey && r.band === band)
      .map(([, r]) => r);
  }

  function renderBandAdvisor() {
    if (!adviceBox) return;
    const byBand = computeBandOpportunities();
    const bands = Object.keys(byBand).sort((a, b) => byBand[b].score - byBand[a].score);
    if (!bands.length) { adviceBox.style.display = 'none'; return; }
    adviceBox.style.display = '';

    const top = bands[0];
    const rec = byBand[top];
    const topOccupants = bandOccupants(top);
    const onTopAlready = _currentBand && top === _currentBand;

    const verb = onTopAlready
      ? `Stay on <b style="color:${BAND_COLS[top]||C.muted}">${top}</b> — you're already there`
      : `Switch to <b style="color:${BAND_COLS[top]||C.muted}">${top}</b>`;
    const tag = [
      rec.multCount ? `${rec.multCount} new mult${rec.multCount>1?'s':''}` : '',
      rec.bandCount ? `${rec.bandCount} new band${rec.bandCount>1?'s':''}` : '',
    ].filter(Boolean).join(' + ');
    const occNote = topOccupants.length
      ? ` <span style="color:${C.muted}">(${topOccupants.map(o=>escapeHtml(o.op_call||'?')).join(', ')} already there)</span>`
      : '';

    const rest = bands.slice(1, 4).map(band => {
      const r = byBand[band];
      const occ = bandOccupants(band);
      const t = r.multCount ? `${r.multCount} mult` : `${r.bandCount} band`;
      return `<span style="color:${BAND_COLS[band]||C.muted}">${band}</span>: ${t}` +
        (occ.length ? ` <span style="color:${C.muted}">(${escapeHtml(occ[0].op_call||'?')})</span>` : '');
    });

    adviceBox.innerHTML =
      `<span class="advisor-pick" style="color:${C.accent}">&#9654; BAND ADVISOR —</span> ${verb}, ` +
      `${escapeHtml(rec.top.dx)} (${tag})${occNote}` +
      (rest.length ? `  &middot;  ${rest.join('  &middot;  ')}` : '');
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

  // Mode filter — options are static in index.html
  if (modeFilterSelect) {
    modeFilterSelect.addEventListener('change', () => {
      filterMode = modeFilterSelect.value;
      renderSpots();
    });
  }

  [chkNewMult, chkNewBand, chkWorked, chkNotMult, chkBandsOnly].forEach(el=>{
    el?.addEventListener('change', renderSpots);
  });

  setStatus(false, 'Not connected');
})();
