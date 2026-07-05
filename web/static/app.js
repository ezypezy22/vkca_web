/**
 * app.js v3 — WebSocket, tab routing, load dialog, refresh, countdown, LIVE button
 */
;(function () {
  'use strict';

  function emit(name, detail) {
    window.dispatchEvent(new CustomEvent(name, { detail }));
  }

// ── Splash screen ─────────────────────────────────────────────────────────────
(function () {
  const MESSAGES = [
    "Initialising interface...",
    "Loading contest data...",
    "Preparing multiplier tables...",
    "Building band analysis...",
    "Ready — please read the notice below.",
  ];
  const DISCLAIMER = `⚠  DISCLAIMER

This software is provided on a best-effort basis and is intended as a supplemental tool only. While reasonable efforts have been made to ensure accuracy, the software may contain errors, omissions, or discrepancies.

Users should rely on N1MM Logger+ as the authoritative source for contest logging, scoring, and official results.

The developers of this software make no guarantees regarding the accuracy or completeness of any calculations, scores, or data presented.

Users are responsible for verifying all information against N1MM before making decisions or submitting contest entries.`;

  { if (location.pathname === '/hud' || location.pathname.startsWith('/popout/')) return; }
  try { if (localStorage.getItem('vkca_splash_accepted') === '1') return; } catch {}

  const el = document.createElement('div');
  el.id = 'splash-overlay';
  el.innerHTML = `
    <div id="splash-box">
      <canvas id="splash-canvas" width="620" height="214"></canvas>
      <div id="splash-bar-wrap">
        <div id="splash-bar"></div>
      </div>
      <div id="splash-msg">${MESSAGES[0]}</div>
      <div id="splash-disclaimer">${DISCLAIMER.replace(/\n/g,'<br>')}</div>
      <label id="splash-ack-wrap">
        <input type="checkbox" id="splash-ack">
        I have read and understood the above. I accept all risks.
      </label>
      <button id="splash-btn" disabled>Let's Get Started  ›</button>
    </div>`;
  document.body.appendChild(el);

  // ── Focus trap: keep Tab/Shift+Tab cycling within the splash only ─────────
  // The overlay is just a div over the page, so without this the browser's
  // natural tab order walks straight through into the app's nav tabs behind it.
  el.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const focusable = Array.from(el.querySelectorAll('input, button'))
      .filter(node => !node.disabled);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (e.shiftKey) {
      if (active === first || !el.contains(active)) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (active === last || !el.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    }
  });

  // ── Canvas header (hexagon + title) ───────────────────────────────────────
  const cv = document.getElementById('splash-canvas');
  const ctx = cv.getContext('2d');
  const W = 620, cy2 = 72, r = 36;
  ctx.strokeStyle = '#00d4aa'; ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = Math.PI/2 + (Math.PI/3)*i;
    i===0 ? ctx.moveTo(W/2+r*Math.cos(a), cy2+r*Math.sin(a))
           : ctx.lineTo(W/2+r*Math.cos(a), cy2+r*Math.sin(a));
  }
  ctx.closePath(); ctx.stroke();
  ctx.fillStyle='#00d4aa'; ctx.font='bold 28px Consolas,monospace';
  ctx.textAlign='center'; ctx.fillText('⬡', W/2, cy2+10);
  ctx.fillStyle='#e6edf3'; ctx.font='bold 24px Consolas,monospace';
  ctx.fillText('VK CONTEST ANALYZER', W/2, 135);
  ctx.fillStyle='#8b949e'; ctx.font='12px Consolas,monospace';
  ctx.fillText('N1MM+ LOG INTELLIGENCE', W/2, 156);
  ctx.fillStyle='#8b949e'; ctx.font='13px Consolas,monospace';
  ctx.fillText('by VK2YI', W/2, 178);
  ctx.fillStyle='#00d4aa'; ctx.font='bold 13px Consolas,monospace';
  ctx.fillText('v26.7.3', W/2, 202);

  // ── Progress bar animation ─────────────────────────────────────────────────
  const bar = document.getElementById('splash-bar');
  const msgEl = document.getElementById('splash-msg');
  let pct = 0, msgIdx = 0;
  const anim = setInterval(() => {
    const remaining = 100 - pct;
    pct = Math.min(pct + Math.max(0.5, remaining * 0.045), 100);
    bar.style.width = pct + '%';
    const tick = Math.min(Math.floor(pct / (100 / MESSAGES.length)), MESSAGES.length - 1);
    if (tick !== msgIdx) { msgIdx = tick; msgEl.textContent = MESSAGES[tick]; }
    if (pct >= 100) clearInterval(anim);
  }, 30);

  // ── Checkbox + button ─────────────────────────────────────────────────────
  const ack = document.getElementById('splash-ack');
  const btn = document.getElementById('splash-btn');
  const box = document.getElementById('splash-box');
  ack.addEventListener('change', () => { btn.disabled = !ack.checked; });
  btn.addEventListener('click', () => {
    try { localStorage.setItem('vkca_splash_accepted', '1'); } catch {}
    showSupportedPlugins();
  });
  ack.focus();

  // ── Second screen: supported contest plugins ───────────────────────────────
  async function showSupportedPlugins() {
    let plugins = [];
    try {
      const res = await fetch('/api/plugins');
      plugins = await res.json();
    } catch (e) { console.warn('plugin list fetch failed:', e); }

    const rows = plugins.length
      ? plugins.map(p => `
          <div class="splash-plugin-row">
            <span><span class="splash-plugin-bullet">&#9670;</span><span class="splash-plugin-name">${p.display_name}</span></span>
            <span class="splash-plugin-class">[${p.class_name}]</span>
          </div>`).join('')
      : `<div class="splash-plugin-row"><span class="splash-plugin-name">No plugins found.</span></div>`;

    const plugWord = plugins.length === 1 ? 'plugin' : 'plugins';

    box.classList.add('splash-box--plugins');
    box.innerHTML = `
      <div id="splash-plugins-title" style="margin-top:24px">SUPPORTED CONTEST PLUGINS</div>
      <div id="splash-plugins-sub">The following contests are recognised and scored automatically</div>
      <div id="splash-plugins-list">${rows}</div>
      <div id="splash-plugins-count">${plugins.length} contest ${plugWord} loaded</div>
      <button id="splash-launch-btn">Launch App &rsaquo;</button>`;

    const launchBtn = document.getElementById('splash-launch-btn');
    launchBtn.addEventListener('click', () => {
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 400);
    });
    launchBtn.focus();
  }
})();
 
  // ── Tab routing ───────────────────────────────────────────────────────────
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b===btn));
      document.querySelectorAll('.tab-panel').forEach(p =>
        p.classList.toggle('active', p.id===`tab-${btn.dataset.tab}`));
      emit('vka:tabchange', { tab: btn.dataset.tab });
    });
  });

  // ── Status helpers ────────────────────────────────────────────────────────
  const statusDot  = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');
  const liveBtn    = document.getElementById('live-btn');

  function setStatus(state, text) {
    if (statusDot)  statusDot.className = `dot dot--${state}`;
    if (statusText) statusText.textContent = text;
  }

  function setLive(on) {
    if (!liveBtn) return;
    liveBtn.className = 'live-badge ' + (on ? 'live--on' : 'live--off');
    liveBtn.title     = on ? 'WebSocket connected — receiving live updates' : 'WebSocket disconnected';
  }

  // ── WebSocket ─────────────────────────────────────────────────────────────
  let ws=null, wsRetry=0, _lastSnap=null;
  let _currentContestName = '';   // display_name of the contest the user picked

  // Builds the titlebar status text from a snapshot. Called for every
  // snapshot regardless of source (WS broadcast OR a manual /api/snapshot
  // refresh) so the status never gets stuck on "Loading contest data…" if a
  // WS broadcast is missed or arrives out of order.
  function statusFromSnapshot(d) {
    d = d || {};
    if (!Object.keys(d).length) return 'Connected — no data';
    const valid  = d.valid || d.total || 0;
    const score  = d.score || 0;
    const label  = _currentContestName || d._plugin_name || '';
    return `${label ? label+' · ' : ''}${valid.toLocaleString()} QSOs · ${score.toLocaleString()} pts`;
  }

  window.addEventListener('vka:snapshot', e => {
    setStatus('connected', statusFromSnapshot(e.detail));
  });

  function connectWS() {
    ws = new WebSocket(`ws://${location.host}/ws/live`);
    setStatus('loading','Connecting…');

    ws.onopen = () => { wsRetry=0; setLive(true); };

    ws.onmessage = ev => {
      let msg; try { msg=JSON.parse(ev.data); } catch { return; }
      if (msg.type==='ping') return;
      if (msg.type==='snapshot') {
        _lastSnap = msg.data;
        emit('vka:snapshot', msg.data);   // statusFromSnapshot listener above handles status text
        const hasSess = msg.data?.session_status?.state;
        document.body.classList.toggle('has-session-bar',!!hasSess);
      }
    };

    ws.onclose = () => {
      setLive(false);
      setStatus('disconnected','Disconnected — retrying…');
      setTimeout(connectWS, Math.min(500*2**wsRetry++, 8000));
    };
    ws.onerror = () => ws.close();
  }
  connectWS();

  window.VKA = window.VKA || {};
  window.VKA.lastSnap = () => _lastSnap;

  // Canonical band->colour map, shared by every tab that draws a band-colored
  // chart/table (bands, cluster, dupes, overview, worldmap, worked, report).
  // Includes both key casings since different tabs historically looked keys
  // up in different cases — safe superset, no consumer's lookup needs to change.
  window.VKA.BAND_COLS = {
    '160m':'#e040fb','160M':'#e040fb', '80m':'#ff6b35','80M':'#ff6b35',
    '60m':'#f0c040','60M':'#f0c040',   '40m':'#2ed573','40M':'#2ed573',
    '30m':'#00bcd4','30M':'#00bcd4',   '20m':'#00d4aa','20M':'#00d4aa',
    '17m':'#64b5f6','17M':'#64b5f6',   '15m':'#ff5252','15M':'#ff5252',
    '12m':'#ffab40','12M':'#ffab40',   '10m':'#69f0ae','10M':'#69f0ae',
    '6m':'#ea80fc','6M':'#ea80fc',     '2m':'#80d8ff','2M':'#80d8ff',
    '70cm':'#ccff90', '?':'#8b949e',
  };

  // Shared HTML-escaping helper for any tab that interpolates server/log data
  // (call signs, region/contest names) into innerHTML.
  window.VKA.escapeHtml = function (s) {
    return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  };

  // Shared pace-comparison lookup: cumulative QSOs a reference trajectory had
  // reached at a given elapsed-hours point. Used by both the Pace tab and the
  // Report tab's "ahead/behind pace" KPI so they always agree on the number.
  window.VKA.refAtElapsed = function (ref, nowE) {
    const e = ref.elapsed_hrs, c = ref.cum_qsos;
    if (!e || !e.length) return 0;
    if (nowE >= e[e.length - 1]) return c[c.length - 1];
    for (let i = 0; i < e.length; i++) if (e[i] >= nowE) return c[i];
    return c[c.length - 1];
  };

  // ── File browse (native dialog, with browser-upload fallback) ──────────────
  // /api/browse triggers pywebview's native OS file dialog. That only works
  // when running inside the embedded pywebview window — if pywebview failed
  // to start (e.g. a pythonnet/.NET issue on this machine) the app falls back
  // to opening in a plain browser tab, where there is no native dialog to
  // call. In that case, fall back to a normal <input type=file> upload so
  // loading a log still works; the file's bytes get POSTed to the server,
  // which saves them to a temp path and hands back that path — from the
  // caller's point of view the response shape is identical either way.
  let _uploadInput = null;
  function _getUploadInput() {
    if (_uploadInput) return _uploadInput;
    _uploadInput = document.createElement('input');
    _uploadInput.type = 'file';
    _uploadInput.style.display = 'none';
    _uploadInput.accept = '.s3db,.adi,.adif,.log,.cbr,.txt';
    document.body.appendChild(_uploadInput);
    return _uploadInput;
  }

  async function browseFile() {
    let data;
    try {
      const res = await fetch('/api/browse');
      data = await res.json();
      if (res.ok || res.status !== 503) return data;
    } catch (e) {
      return { error: `Browse failed: ${e.message}` };
    }
    // 503 PyWebView window not ready — no native dialog available, use upload.
    return new Promise(resolve => {
      const input = _getUploadInput();
      input.value = '';
      input.onchange = async () => {
        const file = input.files[0];
        if (!file) { resolve({ path: null }); return; }
        try {
          const fd = new FormData();
          fd.append('file', file);
          const res  = await fetch('/api/upload_log', { method: 'POST', body: fd });
          const data = await res.json();
          resolve(data);
        } catch (e) {
          resolve({ error: `Upload failed: ${e.message}` });
        }
      };
      input.click();
    });
  }
  window.VKA.browseFile = browseFile;

  // ── Manual refresh ────────────────────────────────────────────────────────
  const btnRefresh = document.getElementById('btn-refresh');
  let _refreshing  = false;

  async function doRefresh() {
    if (_refreshing) return;
    _refreshing = true;
    if (btnRefresh) { btnRefresh.textContent='↻ …'; btnRefresh.disabled=true; }
    try {
      const res  = await fetch('/api/snapshot');
      const snap = await res.json();
      if (snap && Object.keys(snap).length) {
        _lastSnap = snap;
        emit('vka:snapshot', snap);
      }
    } catch(e) { console.warn('Refresh failed:',e); }
    finally {
      _refreshing=false;
      if (btnRefresh) { btnRefresh.textContent='↻ Refresh'; btnRefresh.disabled=false; }
    }
  }

  btnRefresh?.addEventListener('click', ()=>{ doRefresh(); resetCountdown(); });

  // ── Auto-refresh + countdown timer ───────────────────────────────────────
  const autoSelect  = document.getElementById('auto-refresh-select');
  const cdArc       = document.getElementById('countdown-arc');
  const cdVal       = document.getElementById('countdown-val');
  const CIRCUMF     = 2 * Math.PI * 11;  // r=11 → 69.1px
  let _autoSecs     = 15;
  let _cdRemaining  = 0;
  let _cdTimer      = null;
  let _cdInterval   = null;

  function resetCountdown() {
    if (_cdInterval) clearInterval(_cdInterval);
    if (_cdTimer)    clearTimeout(_cdTimer);
    if (_autoSecs <= 0) {
      if (cdArc) cdArc.style.strokeDashoffset = '0';
      if (cdVal)  cdVal.textContent = '—';
      return;
    }
    _cdRemaining = _autoSecs;
    tick();
    _cdInterval = setInterval(()=>{ _cdRemaining--; tick(); }, 1000);
    _cdTimer    = setTimeout(()=>{
      doRefresh();
      resetCountdown();
    }, _autoSecs * 1000);
  }

  function tick() {
    if (!cdArc || !cdVal) return;
    const pct    = _cdRemaining / _autoSecs;
    const offset = CIRCUMF * (1 - pct);
    cdArc.style.strokeDashoffset = offset;
    cdVal.textContent = _cdRemaining > 0 ? _cdRemaining : '';
  }

  function setAutoRefresh(secs) {
    _autoSecs = secs;
    resetCountdown();
    try { localStorage.setItem('vkca_autorefresh', secs); } catch {}
  }

  if (autoSelect) {
    autoSelect.addEventListener('change', ()=>setAutoRefresh(parseInt(autoSelect.value,10)));
    try {
      const saved=localStorage.getItem('vkca_autorefresh');
      if (saved) { autoSelect.value=saved; setAutoRefresh(parseInt(saved,10)); }
      else setAutoRefresh(15);
    } catch { setAutoRefresh(15); }
  }

  // ── Zoom slider ───────────────────────────────────────────────────────────
  (function(){
    const slider=document.getElementById('zoom-slider');
    const label =document.getElementById('zoom-label');
    if (!slider) return;

    function applyZoom(pct) {
      pct = Math.max(70, Math.min(150, parseInt(pct,10)));
      document.documentElement.style.fontSize = pct+'%';
      if (label)  label.textContent = pct+'%';
      slider.value = pct;
      if (window.VKA?.setZoom) window.VKA.setZoom(pct);
      try { localStorage.setItem('vkca_zoom',pct); } catch {}
    }

    slider.addEventListener('input', ()=>applyZoom(slider.value));
    try { applyZoom(localStorage.getItem('vkca_zoom')||107); } catch { applyZoom(107); }
  })();

  // ── Load dialog ───────────────────────────────────────────────────────────
  const overlay     = document.getElementById('load-dialog');
  const stepPath    = document.getElementById('step-path');
  const stepPicker  = document.getElementById('step-picker');
  const pathInput   = document.getElementById('load-path-input');
  const errDiv      = document.getElementById('load-error');
  const contestList = document.getElementById('contest-list');
  const pickerLabel = document.getElementById('picker-path-label');
  const btnOpen     = document.getElementById('btn-load');
  const btnBrowse   = document.getElementById('btn-browse');
  const btnScan     = document.getElementById('btn-scan');
  const btnBack     = document.getElementById('btn-back');
  const btnCancel   = document.getElementById('btn-load-cancel');
  const btnConfirm  = document.getElementById('btn-load-confirm');
  const btnSwitch   = document.getElementById('btn-switch-contest');
  const switchLabel = document.getElementById('switch-contest-label');

  let _selectedContest=null, _scannedPath='', _scannedContests=[], _loadedContest=null;
  let _scanInFlight=false, _pickerRenderedAt=0;

  function _updateSwitchBtn(contests, current) {
    if (!btnSwitch) return;
    _loadedContest = current;
    const others = contests.filter(c => c.contest_nr !== current?.contest_nr);
    btnSwitch.style.display = others.length > 0 ? '' : 'none';
    if (current && switchLabel)
      switchLabel.textContent = current.display_name || current.contest_name || 'Switch';
  }

  btnSwitch?.addEventListener('click', () => {
    const existing = document.getElementById('contest-switch-menu');
    if (existing) { existing.remove(); return; }
    const btn = btnSwitch;
    const rect = btn.getBoundingClientRect();
    const menu = document.createElement('div');
    menu.id = 'contest-switch-menu';
    menu.style.cssText = `position:fixed;top:${rect.bottom+4}px;right:${window.innerWidth-rect.right}px;
      background:var(--bg2);border:1px solid var(--accent);border-radius:6px;z-index:9998;
      font-family:var(--font-mono);font-size:0.77em;box-shadow:0 8px 24px rgba(0,0,0,.6);
      min-width:280px;overflow:hidden;`;
    _scannedContests.forEach((ct, idx) => {
      if (ct.contest_nr === _loadedContest?.contest_nr) return;
      const row = document.createElement('div');
      row.style.cssText = `padding:8px 14px;cursor:pointer;transition:background .1s;
        ${idx < _scannedContests.length-1 ? 'border-bottom:1px solid var(--bg3)' : ''}`;
      row.innerHTML = `<div style="color:var(--fg);font-weight:bold">${ct.display_name||ct.contest_name}</div>
        <div style="color:var(--muted);font-size:0.85em">${ct.qso_count||0} QSOs · ${(ct.start_date||'').substring(0,10)}</div>`;
      row.addEventListener('mouseover', ()=>row.style.background='var(--bg3)');
      row.addEventListener('mouseout',  ()=>row.style.background='');
      row.addEventListener('click', async () => {
        menu.remove();
        try {
          _currentContestName = ct.display_name||'';
          await doLoad(_scannedPath, ct.contest_nr, ct.plugin);
          _updateSwitchBtn(_scannedContests, ct);
          emit('vka:loaded',{}); doRefresh(); resetCountdown();
        } catch(e) { console.warn('Switch contest failed:', e); }
      });
      menu.appendChild(row);
    });
    if (!menu.children.length) { menu.remove(); return; }
    document.body.appendChild(menu);
    setTimeout(() => {
      document.addEventListener('click', function closeMenu(ev) {
        if (!menu.contains(ev.target) && ev.target !== btn) {
          menu.remove(); document.removeEventListener('click', closeMenu);
        }
      });
    }, 50);
  });

  const detectedWrap = document.getElementById('detected-dbs-wrap');
  const detectedList = document.getElementById('detected-dbs-list');

  function fmtBytes(n) {
    if (!n) return '0 KB';
    const kb = n/1024;
    return kb < 1024 ? `${kb.toFixed(0)} KB` : `${(kb/1024).toFixed(1)} MB`;
  }
  function fmtAgo(epochSec) {
    const mins = Math.max(0, (Date.now()/1000 - epochSec) / 60);
    if (mins < 60)   return `${Math.round(mins)}m ago`;
    if (mins < 1440) return `${Math.round(mins/60)}h ago`;
    return `${Math.round(mins/1440)}d ago`;
  }

  async function scanKnownLocations() {
    if (!detectedWrap || !detectedList) return;
    try {
      const res  = await fetch('/api/scan_known_locations');
      const data = await res.json();
      const dbs  = data.databases || [];
      if (!dbs.length) { detectedWrap.classList.add('hidden'); return; }
      detectedList.innerHTML = '';
      dbs.forEach(db => {
        const row = document.createElement('div');
        row.className = 'contest-row';
        row.innerHTML = `<div class="contest-row-accent" style="background:var(--accent)"></div>
          <div class="contest-row-body">
            <div class="contest-row-name">${db.name}</div>
            <div class="contest-row-meta">
              <span>${fmtAgo(db.mtime)}</span>
              <span>${fmtBytes(db.size)}</span>
            </div>
          </div>
          <div class="contest-row-arrow">›</div>`;
        row.addEventListener('click', () => {
          pathInput.value = db.path;
          errDiv.classList.add('hidden');
          // Always show the contest picker for a detected database, even
          // when it contains only one contest — picking a .s3db from this
          // list is a distinct step from picking the contest inside it, so
          // it shouldn't silently skip straight to loading.
          doScan({ alwaysShowPicker: true });
        });
        detectedList.appendChild(row);
      });
      detectedWrap.classList.remove('hidden');
    } catch { detectedWrap.classList.add('hidden'); }
  }

  function showDialog() {
    overlay.classList.remove('hidden'); showStep('path');
    setTimeout(()=>pathInput?.focus(),50);
    scanKnownLocations();
  }
  function hideDialog() { overlay.classList.add('hidden'); errDiv.classList.add('hidden'); _selectedContest=null; btnConfirm.disabled=true; }
  function showStep(step) {
    stepPath.classList.toggle('hidden',step!=='path');
    stepPicker.classList.toggle('hidden',step!=='picker');
    btnConfirm.style.display=step==='picker'?'':'none';
  }
  function showError(msg) { errDiv.textContent=msg; errDiv.classList.remove('hidden'); }

  btnOpen?.addEventListener('click', showDialog);
  btnCancel?.addEventListener('click', hideDialog);
  btnBack?.addEventListener('click', ()=>showStep('path'));
  overlay?.addEventListener('click', e=>{ if(e.target===overlay) hideDialog(); });

  btnBrowse?.addEventListener('click', async ()=>{
    btnBrowse.disabled=true; btnBrowse.textContent='…';
    try {
      const data = await browseFile();
      if (data.error) { showError(data.error); return; }
      if (data.path)  { pathInput.value=data.path; errDiv.classList.add('hidden'); await doScan(); }
    } catch(e) { showError(`Browse failed: ${e.message}`); }
    finally { btnBrowse.disabled=false; btnBrowse.textContent='📁'; }
  });

  async function doScan(opts) {
    // Guards a rapid double-click on a detected-database row: without this,
    // the second click of the gesture re-enters doScan() while the first
    // fetch is still in flight, and if that first fetch resolves fast enough
    // (common on localhost) it can swap step-path's content for step-picker
    // mid-gesture — landing the second click on a freshly-rendered contest
    // row instead of the database row it was aimed at, which the browser can
    // still report as a dblclick and auto-load an unintended contest.
    if (_scanInFlight) return;
    _scanInFlight = true;
    const alwaysShowPicker = !!(opts && opts.alwaysShowPicker);
    const path=pathInput.value.trim();
    if (!path) { showError('Enter or browse to a .s3db file path.'); _scanInFlight=false; return; }
    errDiv.classList.add('hidden');
    btnScan.disabled=true; btnScan.textContent='Scanning…';
    try {
      const res=await fetch('/api/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
      const data=await res.json();
      if (data.error) { showError(data.error); return; }
      const contests=data.contests||[];
      if (!contests.length) { showError('No contests with QSOs found in this database.'); return; }
      _scannedContests=contests; _scannedPath=data.path;
	  if (!alwaysShowPicker && contests.length===1) { _currentContestName=contests[0].display_name||''; await doLoad(data.path,contests[0].contest_nr,contests[0].plugin); _updateSwitchBtn(contests,contests[0]); hideDialog(); emit('vka:loaded',{}); doRefresh(); resetCountdown(); return; }
      pickerLabel.textContent=data.path.split(/[\\\/]/).pop();
      buildContestList(contests);
      showStep('picker');
    } catch(e) { showError(`Scan failed: ${e.message}`); }
    finally { btnScan.disabled=false; btnScan.textContent='Scan for Contests →'; _scanInFlight=false; }
  }

  btnScan?.addEventListener('click', doScan);
  pathInput?.addEventListener('keydown', e=>{ if(e.key==='Enter') doScan(); });

  const PLUGIN_COLS={'CQ WPX':'#f0c040','VK Shires':'#00d4aa','CQWW':'#f0c040',
    'VK RD':'#ff6b35','Trans-Tasman':'#64b5f6','Oceania DX':'#2ed573',
    'WPX':'#e040fb','Generic':'#8b949e'};

  function buildContestList(contests) {
    contestList.innerHTML=''; _selectedContest=null; btnConfirm.disabled=true;
    // Record when this list was (re)built so the dblclick handler below can
    // reject a double-click gesture that started on different content (see
    // the doScan() comment) — a real double-click on a freshly-shown row
    // still needs the user to see it first, which takes longer than this.
    _pickerRenderedAt = Date.now();
    contests.forEach((ct,i)=>{
      const col=PLUGIN_COLS[ct.plugin]||'#8b949e';
      const row=document.createElement('div');
      row.className='contest-row';
      row.innerHTML=`<div class="contest-row-accent" style="background:${col}"></div>
        <div class="contest-row-body">
          <div class="contest-row-name">${ct.display_name}</div>
          <div class="contest-row-meta">
            <span style="color:${col};font-weight:bold">${ct.plugin}</span>
            <span>${ct.start_date}</span>
            <span>${ct.qso_count.toLocaleString()} QSOs</span>
          </div>
        </div>
        <div class="contest-row-arrow">›</div>`;
      row.addEventListener('click',()=>{
        document.querySelectorAll('.contest-row').forEach(r=>r.classList.remove('selected'));
        row.classList.add('selected'); _selectedContest=ct; btnConfirm.disabled=false;
      });
      row.addEventListener('dblclick', async()=>{
        if (Date.now() - _pickerRenderedAt < 400) return;   // carried-over click from prior content — ignore
        _selectedContest=ct; await confirmLoad();
      });
      contestList.appendChild(row);
      if (i===0) { row.classList.add('selected'); _selectedContest=ct; btnConfirm.disabled=false; }
    });
  }

  async function confirmLoad() {
    if (!_selectedContest) return;
    btnConfirm.disabled=true; btnConfirm.textContent='Loading…';
    try {
      _currentContestName = _selectedContest.display_name || '';
      await doLoad(_scannedPath||pathInput.value.trim(), _selectedContest.contest_nr, _selectedContest.plugin);
      _updateSwitchBtn(_scannedContests, _selectedContest);
      hideDialog(); emit('vka:loaded',{}); doRefresh(); resetCountdown();
    } catch {}
    finally { btnConfirm.disabled=false; btnConfirm.textContent='Load Selected'; }
  }

  btnConfirm?.addEventListener('click', confirmLoad);

  async function doLoad(path, contest_nr, plugin_name) {
    setStatus('loading','Loading contest data…');
    const res=await fetch('/api/load',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path,contest_nr,plugin_name})});
    const data=await res.json();
    if (data.error) { showError(data.error); throw new Error(data.error); }
    return data;
  }


  // ── Theme selector ────────────────────────────────────────────────────────
  (function(){
    const sel = document.getElementById('theme-select');
    if (!sel) return;

    // "System (OS default)" resolves to Dark or Light based on the OS preference,
    // live-updating whenever the user changes their system setting.
    const _osDark = window.matchMedia('(prefers-color-scheme: dark)');
    function resolveThemeName(name) {
      if (name === 'System (OS default)')
        return _osDark.matches ? 'Dark (Default)' : 'Light';
      return name;
    }

    async function applyTheme(name) {
      const resolved = resolveThemeName(name);
      try {
        const res     = await fetch('/api/themes');
        const data    = await res.json();
        const palette = data.palette?.[resolved];
        if (!palette) return;

        // Apply CSS variables to :root
        const root = document.documentElement;
        Object.entries(palette).forEach(([k, v]) => {
          if (typeof v === 'string') {
            root.style.setProperty(`--${k}`, v);
          }
        });

        // Special: light theme needs dark text on inputs etc.
        const isLight = palette.bg && (palette.bg.startsWith('#f') || palette.bg.startsWith('#e'));
        root.style.setProperty('--input-bg', isLight ? palette.bg3 : palette.bg3);

        // Notify canvas modules
        if (window.VKA?.onTheme) window.VKA.onTheme(palette);

        try { localStorage.setItem('vkca_theme', name); } catch {}
      } catch(e) { console.warn('Theme error:', e); }
    }

    // Re-apply when the OS flips dark↔light while "System" is selected
    _osDark.addEventListener('change', () => {
      if (sel.value === 'System (OS default)') applyTheme('System (OS default)');
    });

    sel.addEventListener('change', () => applyTheme(sel.value));

    // Restore saved theme (or default to Dark on first run)
    try {
      const saved = localStorage.getItem('vkca_theme') || 'Dark (Default)';
      sel.value = saved; applyTheme(saved);
    } catch {}
  })();

  // ── CSV Export + Snapshot — wired via event delegation on document
  //    (buttons live in #tb-row2 which is parsed before these scripts run,
  //     but getElementById at module-eval time can still return null in some
  //     WebView environments; delegation is rock-solid regardless) ────────────
  document.addEventListener('click', async function (e) {

    // ── CSV ────────────────────────────────────────────────────────────────
    if (e.target.closest('#btn-csv')) {
      // Show export menu near the button
      const existingMenu = document.getElementById('csv-export-menu');
      if (existingMenu) { existingMenu.remove(); return; }

      const btn  = e.target.closest('#btn-csv');
      const rect = btn.getBoundingClientRect();
      const menu = document.createElement('div');
      menu.id    = 'csv-export-menu';
      menu.style.cssText = `position:fixed;top:${rect.bottom+4}px;right:${window.innerWidth-rect.right}px;
        background:var(--bg2);border:1px solid var(--accent);border-radius:6px;z-index:9998;
        font-family:var(--font-mono);font-size:0.77em;box-shadow:0 8px 24px rgba(0,0,0,.6);
        min-width:220px;overflow:hidden;`;

      const options = [
        { label: '📋 All QSOs',       dataset: 'qsos',    desc: 'Full QSO log with scoring' },
        { label: '🎯 Missing Mults',  dataset: 'missing', desc: 'Unworked multipliers list' },
        { label: '📡 Band Breakdown', dataset: 'bands',   desc: 'Per-band efficiency stats' },
        { label: '⚡ Hourly Rate',    dataset: 'rate',    desc: 'QSO count per hour' },
        { label: '⚠️ Dupes',         dataset: 'dupes',   desc: 'Duplicate QSO analysis' },
      ];

      options.forEach((opt, idx) => {
        const row = document.createElement('div');
        row.style.cssText = `padding:8px 14px;cursor:pointer;transition:background .1s;
          ${idx < options.length-1 ? 'border-bottom:1px solid var(--bg3)' : ''}`;
        row.innerHTML = `<div style="color:var(--fg)">${opt.label}</div>
          <div style="color:var(--muted);font-size:0.85em">${opt.desc}</div>`;
        row.addEventListener('mouseover', ()=>row.style.background='var(--bg3)');
        row.addEventListener('mouseout',  ()=>row.style.background='');
        row.addEventListener('click', async () => {
          menu.remove();
          btn.textContent='⬇ …'; btn.disabled=true;
          try {
            const csvFname=`vkcontest_${opt.dataset}_${new Date().toISOString().slice(0,10)}.csv`;
            const res=await fetch(`/api/export/csv/${opt.dataset}`);
            if (!res.ok) {
              const errData=await res.json().catch(()=>({error:res.statusText}));
              throw new Error(errData.error||res.statusText);
            }
            const blob=await res.blob();
            await downloadBlob(blob, csvFname, '✓ CSV Saved', '📄');
            btn.textContent='✓'; setTimeout(()=>{btn.textContent='⬇ CSV';btn.disabled=false;},2000);
          } catch(err) {
            showToast('CSV Export Failed',err.message,'✗',true);
            btn.textContent='⬇ CSV'; btn.disabled=false;
          }
        });
        menu.appendChild(row);
      });
      document.body.appendChild(menu);
      setTimeout(()=>{
        document.addEventListener('click', function closeMenu(ev){
          if (!menu.contains(ev.target)&&ev.target!==btn){menu.remove();document.removeEventListener('click',closeMenu);}
        });
      }, 50);
    }

    // ── Snapshot ───────────────────────────────────────────────────────────
    if (e.target.closest('#btn-snapshot')) {
      const btn = e.target.closest('#btn-snapshot');
      const active = document.querySelector('.tab-panel.active');
      if (!active || typeof html2canvas !== 'function') {
        showToast('Snapshot Failed', 'Nothing to capture.', '✗', true);
        return;
      }
      const tabName = (document.querySelector('.tab-btn.active .tab-label')?.textContent || 'tab')
        .trim().toLowerCase().replace(/\s+/g, '_');
      btn.textContent = '📷 …'; btn.disabled = true;
      // html2canvas is async — lock tab switching for the duration so a
      // mid-capture click can't flip `active` to display:none (the
      // .tab-panel.active CSS rule) out from under the in-progress capture,
      // which would produce a blank/broken image.
      const tabBtns = Array.from(document.querySelectorAll('.tab-btn'));
      tabBtns.forEach(b => b.disabled = true);
      try {
        const bg = getComputedStyle(document.body).backgroundColor || '#0d1117';
        const out = await html2canvas(active, {
          backgroundColor: bg,
          scale: window.devicePixelRatio || 1,
          useCORS: true,
        });
        const blob = await new Promise(resolve => out.toBlob(resolve, 'image/png'));
        const fname = `vkcontest_${tabName}_${new Date().toISOString().slice(0,10)}.png`;
        await downloadBlob(blob, fname, '✓ Snapshot Saved', '📷');
        btn.textContent = '✓'; setTimeout(() => { btn.textContent = '📷 Snapshot'; btn.disabled = false; }, 2000);
      } catch (err) {
        showToast('Snapshot Failed', err.message, '✗', true);
        btn.textContent = '📷 Snapshot'; btn.disabled = false;
      } finally {
        tabBtns.forEach(b => b.disabled = false);
      }
    }

  });   // end document.addEventListener click

  // ── Toast notification ─────────────────────────────────────────────────────
  const _toast = document.createElement('div');
  _toast.id = 'save-toast';
  _toast.innerHTML = `<div class="toast-icon"></div>
    <div class="toast-body"><div class="toast-title"></div><div class="toast-path"></div></div>
    <div class="toast-close" onclick="this.closest('#save-toast').classList.remove('show')">✕</div>`;
  document.body.appendChild(_toast);
  let _toastTimer = null;

  function showToast(title, path, icon, isError) {
    isError = isError || false;
    _toast.querySelector('.toast-icon').textContent = icon || '✓';
    _toast.querySelector('.toast-title').textContent = title;
    _toast.querySelector('.toast-title').style.color = isError ? 'var(--red)' : 'var(--accent)';
    _toast.querySelector('.toast-path').textContent = path || '';
    _toast.style.borderColor = isError ? 'var(--red)' : 'var(--accent)';
    _toast.classList.add('show');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => _toast.classList.remove('show'), isError ? 8000 : 5000);
  }
  window.VKA.showToast = showToast;

  // ── Shared "save a Blob as a downloaded file" helper ─────────────────────
  // toDataURL()+<a href> gets silently cancelled by the download manager in
  // some WebView2/Chromium builds — toBlob()/Blob()+createObjectURL is the
  // reliable path. Used by CSV export, Snapshot, and the Report HTML export.
  async function downloadBlob(blob, filename, toastTitle, toastIcon) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
    const loc = await fetch('/api/save_location').then(r => r.json()).catch(() => ({}));
    showToast(toastTitle, (loc.folder || 'Downloads') + '\\' + filename, toastIcon);
  }
  window.VKA.downloadBlob = downloadBlob;

})();
