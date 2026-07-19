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
  ctx.fillText('v26.7.19', W/2, 202);

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

  // pywebview's own built-in dragging (disabled here via easy_drag=False —
  // see server.py) sends its move calls tagged 'pywebviewMoveWindow', which
  // pywebview's bridge (webview/util.py's js_bridge_call) special-cases to
  // call window.move() directly and return — no thread spawn, no evaluate_js
  // round trip back into the page to resolve a promise, unlike every *other*
  // js_api call including our own move_to(). That's real overhead 30 times a
  // second (see DRAG_SEND_INTERVAL_MS below), on the same WebView2/GTK engine
  // that's simultaneously trying to repaint the window mid-drag — the likely
  // Windows-side counterpart to the GTK glib.idle_add bottleneck documented
  // in wireDragRegions() below. Tapping the same fast path pywebview uses
  // internally, while keeping our own delta/throttle math (needed for the
  // selective drag-region behaviour easy_drag can't do), should be a pure
  // latency win. Shared by the main window's titlebar drag and the Mini
  // HUD/Operator HUD glance windows' drag bar. window.pywebview._jsApiCallback
  // is what every api.xxx() wrapper calls under the hood (see
  // webview/js/api.js) — not officially public API, so this checks it exists
  // and falls back to the slower api.move_to() path if a future pywebview
  // version removes it.
  function fastMoveWindow(api, x, y) {
    if (typeof window.pywebview?._jsApiCallback === 'function') {
      window.pywebview._jsApiCallback('pywebviewMoveWindow', [Math.round(x), Math.round(y)], 'vka-drag');
    } else {
      api.move_to(x, y);
    }
  }

  // ── Frameless-window caption buttons (desktop app only) ────────────────────
  // #window-controls stays hidden until we know we're actually running inside
  // pywebview's main window — checking for pywebview.api.minimize specifically
  // (rather than just window.pywebview) also keeps it hidden in the Mini HUD
  // and tile pop-out windows, which are separate pywebview windows with no
  // js_api of their own.
  (function () {
    // Frameless windows have no OS border, so nothing resizes them by
    // default — these invisible edge/corner strips do it manually: mousedown
    // snapshots the current size (one round-trip via get_size), then every
    // mousemove computes an absolute new size from that snapshot + the mouse
    // delta and pushes it through resize_to(), which anchors the *opposite*
    // edge server-side (via pywebview's FixPoint) so e.g. dragging the left
    // edge grows the window leftward instead of the default top-left-anchored
    // growth. Throttled to one call per animation frame so a fast mouse
    // doesn't flood the js_api bridge.
    // Reflects the window's maximized/restored state on the caption button
    // (icon glyph + tooltip). Backend is the source of truth for _maximized
    // (see toggle_maximize()/is_maximized() in server.py) — this only ever
    // mirrors a value the backend already computed or is about to force,
    // it never decides maximized state on its own.
    const maximizeBtn = document.getElementById('btn-win-maximize');
    function setMaximizeIcon(isMax) {
      if (!maximizeBtn) return;
      maximizeBtn.textContent = isMax ? '❐' : '▢';
      maximizeBtn.title = isMax ? 'Restore' : 'Maximize';
    }

    function wireResizeHandles(api) {
      document.body.classList.add('pywebview-desktop');
      const MIN_W = 900, MIN_H = 600;
      document.querySelectorAll('.resize-handle').forEach(handle => {
        const edge = handle.dataset.edge;
        handle.addEventListener('mousedown', (e) => {
          e.preventDefault();
          const startX = e.screenX, startY = e.screenY;
          api.get_size().then(({width, height}) => {
            let pending = null, raf = null;
            function apply() {
              raf = null;
              // resize_to() always forces the backend out of the maximized
              // state (see server.py) — only mirror that once a resize
              // actually happens, not on mere mousedown, since a plain
              // click-without-drag never calls resize_to() at all.
              setMaximizeIcon(false);
              api.resize_to(pending.width, pending.height, edge);
            }
            function onMove(ev) {
              const dx = ev.screenX - startX, dy = ev.screenY - startY;
              let w = width, h = height;
              if (edge.includes('e')) w = width + dx;
              if (edge.includes('w')) w = width - dx;
              if (edge.includes('s')) h = height + dy;
              if (edge.includes('n')) h = height - dy;
              pending = {width: Math.max(MIN_W, w), height: Math.max(MIN_H, h)};
              if (!raf) raf = requestAnimationFrame(apply);
            }
            function onUp() {
              window.removeEventListener('mousemove', onMove);
              window.removeEventListener('mouseup', onUp);
              // Flush any final movement since the last animation frame —
              // same reasoning as wireDragRegions()'s onUp() below: without
              // this, releasing the mouse between a mousemove (which set
              // `pending` and scheduled `raf`) and that frame actually
              // firing cancels the resize entirely, silently dropping the
              // last bit of the drag (see issue #31).
              if (raf) { cancelAnimationFrame(raf); raf = null; }
              if (pending) apply();
            }
            window.addEventListener('mousemove', onMove);
            window.addEventListener('mouseup', onUp);
          });
        });
      });
    }

    // pywebview's own '.pywebview-drag-region' handling is unreliable on the
    // Linux GTK/WebKit2 backend (see get_position()'s docstring in
    // server.py's _WindowApi for why) — this replaces it with the same
    // get-snapshot-then-compute-deltas-ourselves pattern already used by
    // wireResizeHandles above. stopPropagation keeps pywebview's own built-in
    // listener (still injected regardless) from also firing and fighting us.
    //
    // Deltas MUST be accumulated incrementally frame-to-frame (last clientX
    // vs. current clientX), not as a running "total since mousedown" offset.
    // clientX/Y are measured relative to the window itself, and this handler
    // is what's moving that window — computing a fresh delta from a fixed
    // mousedown-time reading every frame turns the window's own movement
    // into feedback into the next frame's measurement (the reference frame
    // it's measured against keeps shifting), which converges to roughly
    // half-speed, stuttering motion instead of tracking the cursor.
    // Incremental deltas only ever compare two readings taken while the
    // window was stationary between them, so this feedback loop can't occur.
    // Each move_to() ends up as glib.idle_add(_move) on the GTK main loop
    // (see move() in webview/platforms/gtk.py) — it schedules the real move
    // and returns immediately, it does NOT wait for the window to actually
    // move. So gating the next call on the previous call's promise doesn't
    // give real backpressure: that promise resolves as soon as Python's
    // function returns (near-instantly), not when GTK has caught up, so we
    // were still enqueueing a move for nearly every mousemove event — same
    // problem as requestAnimationFrame pacing, just hidden behind a fake
    // ack. If the GTK main loop (busy with its own WebView rendering/event
    // handling) can only actually process window-moves at a fraction of
    // that rate, the window lags at roughly that fraction of the cursor's
    // speed — matching the ~30-50%-speed tracking actually observed.
    // Fix: throttle to a fixed, modest wall-clock interval instead of firing
    // on every mousemove/every promise resolution. Fewer, larger coalesced
    // updates means fewer glib.idle_add round trips competing with
    // WebView rendering, so GTK can actually keep up. Deltas still
    // accumulate every real mousemove regardless of the interval, so
    // nothing is lost — just batched.
    const DRAG_SEND_INTERVAL_MS = 33; // ~30 updates/sec
    function wireDragRegions(api) {
      document.querySelectorAll('.pywebview-drag-region').forEach(el => {
        // Standard titlebar convention: double-click toggles maximize.
        // toggle_maximize() returns the new state so the icon stays in
        // sync without a separate query round trip.
        el.addEventListener('dblclick', (e) => {
          if (e.button !== 0) return;
          api.toggle_maximize().then(setMaximizeIcon);
        });
        el.addEventListener('mousedown', (e) => {
          if (e.button !== 0) return;
          e.preventDefault();
          e.stopPropagation();
          // screenX/screenY (desktop-absolute) rather than clientX/clientY
          // (window-relative): clientX is measured against the window's own
          // position, which move_to() is itself changing mid-drag, so the
          // very next mousemove after each move_to() takes effect reads a
          // clientX shifted by however much the window just moved — not
          // because the mouse moved, injecting a periodic error every
          // throttle tick. screenX doesn't change when the window moves, so
          // it can't feed back on itself this way.
          let lastX = e.screenX, lastY = e.screenY;
          api.get_position().then(({x, y}) => {
            let curX = x, curY = y;
            let pendingDx = 0, pendingDy = 0;
            let timer = setInterval(apply, DRAG_SEND_INTERVAL_MS);
            function apply() {
              if (pendingDx === 0 && pendingDy === 0) return;
              curX += pendingDx; curY += pendingDy;
              pendingDx = 0; pendingDy = 0;
              // move_to() always forces the backend out of the maximized
              // state (see server.py) — only mirror that once a move
              // actually happens, not on mere mousedown, since a plain
              // click-without-drag never calls move_to() at all.
              setMaximizeIcon(false);
              fastMoveWindow(api, curX, curY);
            }
            function onMove(ev) {
              pendingDx += ev.screenX - lastX;
              pendingDy += ev.screenY - lastY;
              lastX = ev.screenX; lastY = ev.screenY;
            }
            function onUp() {
              clearInterval(timer);
              apply(); // flush any final movement since the last tick
              window.removeEventListener('mousemove', onMove);
              window.removeEventListener('mouseup', onUp);
            }
            window.addEventListener('mousemove', onMove);
            window.addEventListener('mouseup', onUp);
          });
        });
      });
    }

    function wireWindowControls() {
      const api = window.pywebview && window.pywebview.api;
      if (!api || !api.minimize) return;
      const wrap = document.getElementById('window-controls');
      if (wrap) wrap.style.display = 'flex';
      document.getElementById('btn-win-minimize')?.addEventListener('click', () => api.minimize());
      document.getElementById('btn-win-maximize')?.addEventListener('click', () => api.toggle_maximize().then(setMaximizeIcon));
      document.getElementById('btn-win-close')?.addEventListener('click', () => api.close());
      wireResizeHandles(api);
      wireDragRegions(api);
      // The window may already be maximized at load (restored from the
      // previous session — see launch_webview() in server.py), so sync the
      // icon once up front instead of assuming the default "restored" glyph.
      api.is_maximized?.().then(setMaximizeIcon);
    }
    if (window.pywebview) wireWindowControls();
    else window.addEventListener('pywebviewready', wireWindowControls);
  })();

  // ── Frameless glance windows (Mini HUD, Operator HUD — desktop app only) ───
  // Both are separate, tiny pywebview windows with their own dedicated API
  // classes (_HudApi / _OperatorHudApi, see server.py) — deliberately not the
  // same api as the main window's wireWindowControls() above (gated on
  // api.minimize, which neither has an equivalent of). Drag+close only: no
  // minimize/maximize/resize for a fixed-size glanceable window. The two
  // windows' client-side wiring is identical but for a pathname + a couple of
  // element IDs, so this is one parameterized helper rather than two
  // near-copies that could silently drift apart (e.g. a drag-jitter fix
  // landing in one but not the other).
  function wireGlanceWindow({pathname, barId, closeId, ignoreSelector}) {
    if (location.pathname !== pathname) return;

    document.getElementById(closeId)?.addEventListener('click', () => {
      const api = window.pywebview && window.pywebview.api;
      if (api && api.close) api.close();
      else window.close();   // browser-tab fallback (see btn-hud/btn-operator-hud in overview.js)
    });

    // Same get-snapshot-then-accumulate-deltas drag pattern as the main
    // window's wireDragRegions above (see its comments for why), thinned
    // down since there's no maximize state or drag-region class here — the
    // whole bar is draggable except the close (and, for the Mini HUD,
    // settings/menu) button(s).
    const DRAG_SEND_INTERVAL_MS = 33;
    function wireDrag(api) {
      if (!api || !api.move_to) return;   // browser-tab fallback — OS handles dragging
      const bar = document.getElementById(barId); if (!bar) return;
      bar.addEventListener('mousedown', (e) => {
        if (e.button !== 0 || e.target.closest(ignoreSelector)) return;
        e.preventDefault();
        let lastX = e.screenX, lastY = e.screenY;
        api.get_position().then(({x, y}) => {
          let curX = x, curY = y, pendingDx = 0, pendingDy = 0;
          const timer = setInterval(apply, DRAG_SEND_INTERVAL_MS);
          function apply() {
            if (!pendingDx && !pendingDy) return;
            curX += pendingDx; curY += pendingDy;
            pendingDx = 0; pendingDy = 0;
            fastMoveWindow(api, curX, curY);
          }
          function onMove(ev) {
            pendingDx += ev.screenX - lastX;
            pendingDy += ev.screenY - lastY;
            lastX = ev.screenX; lastY = ev.screenY;
          }
          function onUp() {
            clearInterval(timer);
            apply();
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
          }
          window.addEventListener('mousemove', onMove);
          window.addEventListener('mouseup', onUp);
        });
      });
    }
    if (window.pywebview) wireDrag(window.pywebview.api);
    else window.addEventListener('pywebviewready', () => wireDrag(window.pywebview.api));

    // Double-click brings the main window to the front — useful since the
    // whole point of these windows is staying visible while some other
    // window (the radio's logging software, etc.) has focus.
    function wireFocusMain(api) {
      if (!api || !api.focus_main) return;   // browser-tab fallback — no such concept
      const bar = document.getElementById(barId); if (!bar) return;
      bar.addEventListener('dblclick', (e) => {
        if (e.target.closest(ignoreSelector)) return;
        api.focus_main();
      });
    }
    if (window.pywebview) wireFocusMain(window.pywebview.api);
    else window.addEventListener('pywebviewready', () => wireFocusMain(window.pywebview.api));
  }

  wireGlanceWindow({pathname: '/hud', barId: 'hud-bar', closeId: 'hud-close',
                     ignoreSelector: '#hud-close,#hud-settings,#hud-menu'});
  wireGlanceWindow({pathname: '/operator_hud', barId: 'operator-hud-bar', closeId: 'operator-hud-close',
                     ignoreSelector: '#operator-hud-close'});

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

  // Titlebar radio-frequency chip — reads d.radio_info.own (see
  // web/radio_udp.py / AppState._own_and_all_radios()). Hidden entirely
  // when nothing is broadcasting (N1MM+'s RadioInfo broadcast not enabled,
  // or N1MM+/the rig isn't running) rather than showing a confusing
  // placeholder in the titlebar's tight space.
  const radioBadge = document.getElementById('radio-freq-badge');
  function updateRadioBadge(d) {
    if (!radioBadge) return;
    const r = window.VKA.formatRadio(d && d.radio_info && d.radio_info.own);
    if (!r) { radioBadge.classList.add('hidden'); return; }
    radioBadge.classList.remove('hidden');
    radioBadge.innerHTML =
      `<span class="dot" style="background:${r.bandColor};color:${r.bandColor}"></span>` +
      `<span class="band-chip" style="background:${r.bandColor}30;color:${r.bandColor}">${r.band}</span>` +
      `<b>${r.freqStr}</b><span style="color:var(--muted)">MHz${r.modeStr ? ' &middot; '+window.VKA.escapeHtml(r.modeStr) : ''}</span>`;
  }

  window.addEventListener('vka:snapshot', e => {
    setStatus('connected', statusFromSnapshot(e.detail));
    updateRadioBadge(e.detail);
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

  // N1MM+ RadioInfo live readout — shared by the titlebar chip, Mini HUD
  // tile, Overview panel, and Operator HUD card badge, so frequency/band
  // formatting and staleness detection is only written once. `entry` is
  // one item from snapshot.radio_info.own / .all (see web/radio_udp.py's
  // module docstring for the packet format, and AppState._own_and_all_radios()
  // for the shape). Returns null for a missing/falsy entry.
  window.VKA.RADIO_STALE_MS = 20000;   // matches web/radio_udp.py's STALE_AFTER_SECS
  window.VKA.formatRadio = function (entry) {
    if (!entry) return null;
    const band = (entry.band || '?').toUpperCase();
    const freqMhz = (entry.freq_hz || 0) / 1000000;
    const stale = (Date.now() - (entry.updated_at || 0) * 1000) > window.VKA.RADIO_STALE_MS;
    return {
      band,
      bandColor: window.VKA.BAND_COLS[band] || window.VKA.BAND_COLS['?'],
      // Plain fixed-decimal, not toLocaleString — ham-radio frequency
      // convention doesn't use a thousands separator (e.g. "3.601", not
      // "3,601" or "3,601.000").
      freqStr: freqMhz.toFixed(3),
      modeStr: entry.mode || '',
      opCall: entry.op_call || '',
      radioNr: entry.radio_nr || '1',
      stale,
    };
  };

  // Open an external (http/https) URL. window.open() from inside pywebview's
  // embedded WebView is unreliable — notably on the Linux GTK/WebKit2 backend
  // it silently no-ops instead of launching a browser — so route through the
  // pywebview js_api bridge (_WindowApi.open_external in server.py, which
  // shells out via Python's webbrowser module) when running inside the
  // desktop app. Falls back to window.open() when running in a plain
  // browser tab (e.g. during development), where it works fine.
  window.VKA.openExternal = function (url) {
    if (window.pywebview?.api?.open_external) {
      window.pywebview.api.open_external(url);
    } else {
      window.open(url, '_blank', 'noopener');
    }
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
    _uploadInput.accept = '.s3db,.db,.sqlite,.adi,.adif,.log,.cbr,.txt';
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
      pct = Math.max(70, Math.min(150, Math.round(parseFloat(pct)*10)/10));
      document.documentElement.style.fontSize = pct+'%';
      if (label)  label.textContent = Math.round(pct)+'%';
      slider.value = pct;
      if (window.VKA?.setZoom) window.VKA.setZoom(pct);
      try { localStorage.setItem('vkca_zoom',pct); } catch {}
    }

    slider.addEventListener('input', ()=>applyZoom(slider.value));
    slider.addEventListener('dblclick', ()=>applyZoom(100));

    // Scroll wheel over the slider (or its label) nudges zoom in fine, 1%
    // steps — finer-grained than a mouse drag on the slider track can hit.
    function onWheel(e){
      e.preventDefault();
      const dir = e.deltaY < 0 ? 1 : -1;   // scroll up = zoom in
      applyZoom(parseFloat(slider.value) + dir);
    }
    slider.addEventListener('wheel', onWheel, {passive:false});
    if (label) label.addEventListener('wheel', onWheel, {passive:false});

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
      row.innerHTML = `<div style="color:var(--fg);font-weight:bold">${window.VKA.escapeHtml(ct.display_name||ct.contest_name||'')}</div>
        <div style="color:var(--muted);font-size:0.85em">${ct.qso_count||0} QSOs · ${(ct.start_date||'').substring(0,10)}
        ${!ct.qso_count ? '<span class="badge" style="color:#f0c040">Empty</span>' : ''}</div>`;
      row.addEventListener('mouseover', ()=>row.style.background='var(--bg3)');
      row.addEventListener('mouseout',  ()=>row.style.background='');
      row.addEventListener('click', async () => {
        menu.remove();
        try {
          await doLoad(_scannedPath, ct.contest_nr, ct.plugin);
          // Only assign after a successful load — doLoad() throws on
          // failure, and setting this beforehand left the titlebar
          // permanently labelled with the failed target's name while the
          // previous (still-loaded) contest's live data kept displaying
          // (see issue #63).
          _currentContestName = ct.display_name||'';
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

  const detectedWrap   = document.getElementById('detected-dbs-wrap');
  const detectedList   = document.getElementById('detected-dbs-list');
  const noDetectedHint = document.getElementById('no-detected-hint');

  // "Manage Folders" now opens the consolidated Settings dialog directly on
  // its Log Folders step (settings.js) rather than switching to an in-dialog
  // step here — kept as a button in this dialog too (not just the titlebar)
  // since if your log isn't listed, you want a quick way to add a folder
  // without abandoning the load flow.
  document.getElementById('btn-manage-folders')?.addEventListener('click', () => {
    window.VKA?.openSettings?.('logdirs');
  });

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
  function dirOf(p) {
    const idx = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'));
    return idx >= 0 ? p.slice(0, idx) : '';
  }

  async function scanKnownLocations() {
    if (!detectedWrap || !detectedList) return;
    try {
      const res  = await fetch('/api/scan_known_locations');
      const data = await res.json();
      // The default placeholder is a Windows-style N1MM path, which is
      // meaningless (and confusing) on Linux/Mac — clear it there.
      if (pathInput && data.os && data.os !== 'win32') pathInput.placeholder = '';
      const dbs  = data.databases || [];
      if (!dbs.length) {
        detectedWrap.classList.add('hidden');
        noDetectedHint?.classList.remove('hidden');
        return;
      }
      noDetectedHint?.classList.add('hidden');
      detectedList.innerHTML = '';
      dbs.forEach(db => {
        const row = document.createElement('div');
        row.className = 'contest-row';
        row.innerHTML = `<div class="contest-row-accent" style="background:var(--accent)"></div>
          <div class="contest-row-body">
            <div class="contest-row-name">${window.VKA.escapeHtml(db.name||'')}</div>
            <div class="contest-row-path" title="${window.VKA.escapeHtml(dirOf(db.path))}">${window.VKA.escapeHtml(dirOf(db.path))}</div>
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
    } catch { detectedWrap.classList.add('hidden'); noDetectedHint?.classList.remove('hidden'); }
  }
  // Exposed for settings.js — removing a log-search folder there should
  // refresh this dialog's detected-databases list too, since it's the same
  // underlying search that folder feeds into.
  window.VKA = window.VKA || {};
  window.VKA.scanKnownLocations = scanKnownLocations;

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
	  if (!alwaysShowPicker && contests.length===1) { await doLoad(data.path,contests[0].contest_nr,contests[0].plugin); _currentContestName=contests[0].display_name||''; _updateSwitchBtn(contests,contests[0]); hideDialog(); emit('vka:loaded',{}); doRefresh(); resetCountdown(); return; }
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
          <div class="contest-row-name">${window.VKA.escapeHtml(ct.display_name||'')}</div>
          <div class="contest-row-meta">
            <span style="color:${col};font-weight:bold">${ct.plugin}</span>
            <span>${ct.start_date}</span>
            <span>${ct.qso_count.toLocaleString()} QSOs</span>
            ${ct.qso_count===0 ? '<span class="badge" style="color:#f0c040">Empty</span>' : ''}
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
      await doLoad(_scannedPath||pathInput.value.trim(), _selectedContest.contest_nr, _selectedContest.plugin);
      // Only assign after a successful load — see issue #63.
      _currentContestName = _selectedContest.display_name || '';
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
    const sel          = document.getElementById('theme-select');
    const accentPicker = document.getElementById('accent-picker');
    const accentReset  = document.getElementById('accent-reset-btn');
    if (!sel) return;

    const ACCENT_KEY = 'vkca_custom_accent';
    // The full palette last applied by applyTheme(), before any custom-accent
    // override — onTheme() needs a complete palette every call (it has no
    // "keep the rest as-is" merge of its own), so a custom accent is applied
    // as this base palette with just .accent swapped out, never on its own.
    let _basePalette = null;

    // "System (OS default)" resolves to Dark or Light based on the OS preference,
    // live-updating whenever the user changes their system setting.
    const _osDark = window.matchMedia('(prefers-color-scheme: dark)');
    function resolveThemeName(name) {
      if (name === 'System (OS default)')
        return _osDark.matches ? 'Dark (Default)' : 'Light';
      return name;
    }

    function setAccentVar(hex) {
      document.documentElement.style.setProperty('--accent', hex);
      if (accentPicker) accentPicker.value = hex;
    }

    // Applies (and by default persists) a custom accent on top of whatever
    // theme is currently active. `skipPersist` is used when re-applying a
    // saved value on load or from a cross-window 'storage' event, where
    // writing it straight back to localStorage would be redundant.
    function applyCustomAccent(hex, skipPersist) {
      if (!_basePalette) return;
      setAccentVar(hex);
      if (window.VKA?.onTheme) window.VKA.onTheme({ ..._basePalette, accent: hex });
      if (!skipPersist) { try { localStorage.setItem(ACCENT_KEY, hex); } catch {} }
    }

    function clearCustomAccent(skipPersist) {
      if (!skipPersist) { try { localStorage.removeItem(ACCENT_KEY); } catch {} }
      if (!_basePalette) return;
      setAccentVar(_basePalette.accent);
      if (window.VKA?.onTheme) window.VKA.onTheme(_basePalette);
    }

    async function applyTheme(name) {
      const resolved = resolveThemeName(name);
      try {
        const res     = await fetch('/api/themes');
        const data    = await res.json();
        const palette = data.palette?.[resolved];
        if (!palette) return;
        _basePalette = palette;

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

        // Tells the engine to render native form controls (select dropdown
        // popups, scrollbars) in their dark variant instead of always
        // defaulting to light — page CSS can't restyle that OS/engine chrome
        // directly.
        root.style.setProperty('color-scheme', isLight ? 'light' : 'dark');

        // A saved custom accent survives theme switches — re-apply it on top
        // of the freshly-loaded palette rather than letting the theme's own
        // accent win.
        let customHex = null;
        try { customHex = localStorage.getItem(ACCENT_KEY); } catch {}
        if (customHex) {
          applyCustomAccent(customHex, true);
        } else {
          if (window.VKA?.onTheme) window.VKA.onTheme(palette);
          if (accentPicker) accentPicker.value = palette.accent;
        }

        try { localStorage.setItem('vkca_theme', name); } catch {}
      } catch(e) { console.warn('Theme error:', e); }
    }

    // Re-apply when the OS flips dark↔light while "System" is selected
    _osDark.addEventListener('change', () => {
      if (sel.value === 'System (OS default)') applyTheme('System (OS default)');
    });

    sel.addEventListener('change', () => applyTheme(sel.value));
    accentPicker?.addEventListener('input', () => applyCustomAccent(accentPicker.value));
    accentReset?.addEventListener('click', () => clearCustomAccent());

    // Cross-window sync: the 'storage' event fires in every other same-origin
    // window/tab (never the one that made the change) — this is what keeps
    // popped-out windows (HUD, popout tiles) in step when the theme is
    // changed from the main window, since they don't share the same document.
    window.addEventListener('storage', (e) => {
      if (e.key === 'vkca_theme' && e.newValue) {
        sel.value = e.newValue;
        applyTheme(e.newValue);
      } else if (e.key === ACCENT_KEY) {
        if (e.newValue) applyCustomAccent(e.newValue, true);
        else clearCustomAccent(true);
      }
    });

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

  // ── Corner hints — one-time, dismiss-only tips ───────────────────────────
  // Shared by the radio-readout setup hint and the Report Issue pointer
  // chained after it (see below). Same "explain it in words, gone for good
  // once acknowledged" pattern as the HUD field-picker hint in overview.js,
  // generalized so a future one-time tip doesn't have to grow its own
  // near-copy of the create/animate/dismiss boilerplate.

  // Reuses the Overview tab's own Sound Alerts toggle/key rather than adding
  // a second, independent mute control the user would have to discover —
  // muting one silences the other. Real recorded knock SFX (web/static/sfx/
  // knock.mp3 — "Knocking Sound Effect" by kokeshiofficial, via Pixabay)
  // rather than a synthesized tone: a corner hint is competing for
  // attention with whatever the user is actually looking at, not just
  // confirming an action they just took, so it needs to be heard, not just
  // technically audible.
  //
  // Played through Web Audio (BufferSource + Gain) rather than a plain
  // <audio> element: a plain element's .volume caps at 1.0 (no headroom to
  // go louder than the source recording) and has no clean way to raise
  // pitch independent of a separate time-stretch step. playbackRate on a
  // BufferSourceNode raises pitch and speed together — a knock sped up
  // reads as a sharper, higher-pitched knock, which is exactly the "knock"
  // sound this needs, not a concern to work around.
  const HINT_SOUND_KEY = 'vka_overview_sound';
  const KNOCK_SFX_URL       = '/static/sfx/knock.mp3';
  const KNOCK_PLAYBACK_RATE = 1.35;   // pitch/speed up the recording
  const KNOCK_GAIN          = 2.2;    // beyond a plain <audio> element's 1.0 volume ceiling
  let _hintAudioCtx = null;
  function getHintAudioCtx() {
    _hintAudioCtx = _hintAudioCtx || new (window.AudioContext || window.webkitAudioContext)();
    return _hintAudioCtx;
  }
  // Fetched/decoded once, eagerly, rather than lazily on the first chime —
  // decodeAudioData() is async, and starting it only when a hint's timer
  // fires would risk that hint's own chime missing its own sound.
  let _knockBufferPromise = null;
  function getKnockBuffer() {
    _knockBufferPromise = _knockBufferPromise || fetch(KNOCK_SFX_URL)
      .then(r => r.arrayBuffer())
      .then(buf => getHintAudioCtx().decodeAudioData(buf));
    return _knockBufferPromise;
  }
  getKnockBuffer().catch(() => {});
  // Browsers create a new AudioContext in a "suspended" state until a real
  // user gesture (click/key/touch) resumes it — silently, no error, so a
  // hint whose timer fires before the user has clicked anything at all
  // (very plausible for the Report Issue hint's fixed 30s-after-load timer,
  // especially when it's the *first* corner hint of the session because the
  // radio hint never appeared) would otherwise play into nothing. Resuming
  // eagerly on the first interaction anywhere on the page means any later
  // chimeHint() call already has a running context.
  ['pointerdown', 'keydown'].forEach(evt =>
    document.addEventListener(evt, () => getHintAudioCtx().resume().catch(() => {}), { once: true, passive: true }));

  function chimeHint() {
    const stored = localStorage.getItem(HINT_SOUND_KEY);
    if (stored === '0') return;
    getKnockBuffer().then(buffer => {
      const ctx = getHintAudioCtx();
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.playbackRate.value = KNOCK_PLAYBACK_RATE;
      const g = ctx.createGain();
      g.gain.value = KNOCK_GAIN;
      src.connect(g).connect(ctx.destination);
      src.start();
    }).catch(() => { /* fetch/decode/Web Audio unavailable — ignore */ });
  }

  // Returns a forceHide(markSeen) function so a caller can dismiss the hint
  // programmatically (e.g. the radio hint clearing itself once real
  // radio_info arrives) without going through the close button.
  //
  // autoHideMs, if given, auto-dismisses the hint after that long on
  // screen — treated the same as a real dismissal (markSeen: true), same
  // precedent as the HUD field-picker hint's own 8s auto-dismiss in
  // overview.js: a tip nobody acted on within a generous viewing window is
  // still "seen" for suppression purposes, not retried forever.
  function showCornerHint({ icon, title, bodyHtml, seenKey, onDismiss, autoHideMs }) {
    const hint = document.createElement('div');
    hint.className = 'corner-hint';
    hint.innerHTML = `<div class="ch-icon">${icon}</div>
      <div class="ch-body">
        <div class="ch-title">${title}</div>
        <div class="ch-text">${bodyHtml}</div>
      </div>
      <div class="ch-close" title="Dismiss">&#10005;</div>`;
    document.body.appendChild(hint);
    requestAnimationFrame(() => hint.classList.add('show'));
    chimeHint();
    let autoTimer = null;
    const dismiss = (markSeen) => {
      clearTimeout(autoTimer);
      hint.classList.remove('show');
      setTimeout(() => hint.remove(), 300);
      if (markSeen && seenKey) { try { localStorage.setItem(seenKey, '1'); } catch {} }
      onDismiss?.(markSeen);
    };
    hint.querySelector('.ch-close').addEventListener('click', () => dismiss(true));
    if (autoHideMs) autoTimer = setTimeout(() => dismiss(true), autoHideMs);
    return dismiss;
  }

  // Main window only — a HUD popout is too small a surface for a multi-line
  // tip, and one already-dismissed hint should cover the user, not one per
  // window.
  const IS_MAIN_WINDOW = location.pathname !== '/hud' && location.pathname !== '/operator_hud';

  // ── Report Issue pointer ─────────────────────────────────────────────────
  // Deliberately NOT persisted via localStorage (no seenKey) — unlike the
  // radio hint (a one-time "fix this setting" tip, right to suppress
  // forever once addressed), this is a recurring reminder that the feedback
  // feature exists, so it shows again every launch rather than only once
  // ever. _reportHintShown is in-memory only, just preventing the two
  // triggers below from double-showing it within the same page load:
  //   1. Chained right after the radio hint's own dismissal, reusing that
  //      "just read and acted on a corner hint" moment.
  //   2. A fixed 30s-after-load fallback, for the — very common — case
  //      where radio_info is already flowing and the radio hint never
  //      appears at all, so trigger 1 never happens.
  // Auto-hides after 60s on screen if not dismissed sooner (see autoHideMs).
  const REPORT_HINT_WAIT_MS      = 30000;
  const REPORT_HINT_AUTO_HIDE_MS = 60000;
  let _reportHintShown = false;
  function maybeShowReportHint() {
    if (!IS_MAIN_WINDOW || _reportHintShown) return;
    _reportHintShown = true;
    showCornerHint({
      icon: '&#9654;',
      title: 'Found a bug or have an idea?',
      bodyHtml: 'Click <b>&#128027; Report Issue</b> in the titlebar to open a pre-filled bug/feature form.' +
        ' <span style="color:var(--muted)">(Free GitHub account required to submit.)</span>',
      autoHideMs: REPORT_HINT_AUTO_HIDE_MS,
    });
    scheduleNextHelper();   // the rotating tips (below) start only after this hint's first appearance
  }
  if (IS_MAIN_WINDOW) {
    setTimeout(maybeShowReportHint, REPORT_HINT_WAIT_MS);
  }

  // ── Rotating feature-discovery tips ──────────────────────────────────────
  // Starts only once the Report Issue hint has actually been shown (see its
  // onDismiss-independent kickoff at the bottom of maybeShowReportHint,
  // below) — that hint always takes priority as the first thing a user
  // sees. After that, one tip every 30 minutes, in shuffled order with no
  // repeat until the whole list has been shown once, then a 5-hour cooldown
  // before reshuffling and starting a new cycle. State is persisted to
  // localStorage (not just an in-memory timer) so the schedule survives the
  // app being closed and reopened mid-contest — a relaunch 45 minutes after
  // the last tip shows the next one almost immediately rather than waiting
  // a fresh 30 minutes, and a relaunch during the 5h cooldown just keeps
  // waiting out whatever's left of it.
  const HELPER_TIPS = [
    { id: 'mini-hud', title: 'Try the Mini HUD',
      body: 'Click <b>&#128204; Mini HUD</b> in the toolbar for a tiny always-on-top window with score, rate, and time since last QSO — handy for keeping visible over your logging software.' },
    { id: 'operator-hud', title: 'Multi-op? Try the Operator HUD',
      body: '<b>&#128101; Operator HUD</b> shows per-operator QSOs, rate, and on-air % in its own always-on-top window.' },
    { id: 'replay', title: 'Scrub back through the contest',
      body: '<b>&#9194; Replay</b> lets you play back the whole contest&rsquo;s progression instead of only seeing the current state.' },
    { id: 'whatif', title: '&ldquo;What if I worked that mult?&rdquo;',
      body: '<b>&#128302; What if?</b> on the Missing Mults tab estimates the point/mult swing of working a specific missing multiplier, before you actually work it.' },
    { id: 'panels', title: 'Customize your Overview',
      body: '<b>&#9776; Panels</b> lets you show/hide individual Overview tiles; drag tiles to reorder them, and <b>&#8634; Reset layout</b> puts it all back to default.' },
    { id: 'accent', title: 'Pick your accent color',
      body: 'The color swatch next to the theme dropdown overrides any theme&rsquo;s accent color — your own color scheme.' },
    { id: 'zoom', title: 'Zoom by scrolling',
      body: 'Scroll your mouse wheel over the zoom slider for fine 1% steps; double-click the slider to reset to 100%.' },
    { id: 'export', title: 'Export anything as CSV or PNG',
      body: '<b>&#11015; CSV</b> and <b>&#128247; Snapshot</b> export whichever tab you&rsquo;re currently viewing, not just the Overview.' },
    { id: 'band-advisor', title: 'DX Cluster Band Advisor',
      body: 'The DX Cluster tab scores every band by recent needed-mult activity and tells you where to point the radio next.' },
    { id: 'qrz', title: 'QRZ lookups run automatically',
      body: 'Set your QRZ.com credentials in <b>&#9881; Settings</b> and names/grids/states fill in automatically as you log QSOs.' },
    { id: 'switch-contest', title: 'Switch contests without restarting',
      body: '<b>&#8644; Switch</b> (titlebar) loads a different contest from the same log database without relaunching.' },
    { id: 'yoy', title: 'Year-over-year comparison',
      body: 'The <b>Year on Year</b> tab compares this session&rsquo;s pace against your own past results in the same contest.' },
  ];
  const HELPER_INTERVAL_MS  = 30 * 60 * 1000;
  const HELPER_COOLDOWN_MS  = 5 * 60 * 60 * 1000;
  const HELPER_AUTO_HIDE_MS = 60000;
  const HELPER_QUEUE_KEY         = 'vkca_helper_queue';
  const HELPER_LAST_SHOWN_KEY    = 'vkca_helper_last_shown';
  const HELPER_CYCLE_DONE_AT_KEY = 'vkca_helper_cycle_done_at';

  function shuffledTipIds() {
    const ids = HELPER_TIPS.map(t => t.id);
    for (let i = ids.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [ids[i], ids[j]] = [ids[j], ids[i]];
    }
    return ids;
  }

  function getHelperQueue() {
    try {
      const raw = JSON.parse(localStorage.getItem(HELPER_QUEUE_KEY) || 'null');
      if (Array.isArray(raw)) return raw;
    } catch {}
    return null;
  }

  // Schedules (via setTimeout, computed from absolute stored timestamps —
  // not a relative "wait 30 minutes from now" — so state survives a
  // relaunch correctly) either the next tip in the current cycle, or the
  // reshuffle-and-resume once the cooldown after a completed cycle elapses.
  function scheduleNextHelper() {
    if (!IS_MAIN_WINDOW) return;
    let queue = getHelperQueue();
    // Empty ([]) and never-initialized (null) both mean "needs a fresh
    // shuffle" — a completed cycle stores [] (see showNextHelper's last
    // shift() leaving nothing), NOT null, so checking only for null here
    // would skip the cooldown gate below entirely once a cycle finishes.
    if (!queue || !queue.length) {
      const cycleDoneAt = parseInt(localStorage.getItem(HELPER_CYCLE_DONE_AT_KEY) || '0', 10);
      if (cycleDoneAt) {
        const readyAt = cycleDoneAt + HELPER_COOLDOWN_MS;
        const wait = readyAt - Date.now();
        if (wait > 0) { setTimeout(scheduleNextHelper, wait); return; }
      }
      queue = shuffledTipIds();
      try {
        localStorage.setItem(HELPER_QUEUE_KEY, JSON.stringify(queue));
        localStorage.removeItem(HELPER_CYCLE_DONE_AT_KEY);
      } catch {}
    }
    // No prior tip ever shown (lastShown 0) still waits a full interval
    // from now, same as any other gap — the Report Issue hint just showed
    // moments ago (this function is only ever called right after that),
    // and the first rotating tip shouldn't crowd right in behind it.
    const lastShown = parseInt(localStorage.getItem(HELPER_LAST_SHOWN_KEY) || '0', 10);
    const dueAt = (lastShown || Date.now()) + HELPER_INTERVAL_MS;
    setTimeout(showNextHelper, Math.max(0, dueAt - Date.now()));
  }

  function showNextHelper() {
    const queue = getHelperQueue();
    if (!queue || !queue.length) { scheduleNextHelper(); return; }
    const id = queue.shift();
    try {
      localStorage.setItem(HELPER_QUEUE_KEY, JSON.stringify(queue));
      localStorage.setItem(HELPER_LAST_SHOWN_KEY, String(Date.now()));
      if (!queue.length) localStorage.setItem(HELPER_CYCLE_DONE_AT_KEY, String(Date.now()));
    } catch {}
    const tip = HELPER_TIPS.find(t => t.id === id);
    if (tip) {
      showCornerHint({ icon: '&#9654;', title: tip.title, bodyHtml: tip.body, autoHideMs: HELPER_AUTO_HIDE_MS });
    }
    scheduleNextHelper();
  }

  // ── Radio-readout setup hint ──────────────────────────────────────────────
  // N1MM+'s RadioInfo UDP broadcast is opt-in (Config > Configure Ports >
  // Broadcast Data > "Radio" checkbox) — unlike most of this app's features,
  // there's no error or empty state that hints it's off, every radio readout
  // (titlebar chip, Mini HUD, Overview panel, Operator HUD, DX Cluster board)
  // just silently stays blank forever, which reads as broken rather than
  // unconfigured. N1MM+ broadcasts at least every 10s once enabled, so an
  // 8s wait can in principle fire while a correctly-configured N1MM+ just
  // hasn't sent its first packet yet — accepted tradeoff for a snappier
  // hint; it's harmless either way since it's dismiss-only and self-clears
  // (see onRadioSnap below) the moment real radio_info actually arrives.
  const RADIO_HINT_SEEN_KEY = 'vkca_radio_hint_seen';
  const RADIO_HINT_WAIT_MS  = 8000;
  if (IS_MAIN_WINDOW && !localStorage.getItem(RADIO_HINT_SEEN_KEY)) {
    let _radioSeen = false;
    let _hideHint = null;   // set once the hint element exists, so a radio
                             // showing up *after* it's already on screen can
                             // still clear it instead of leaving a stale tip
                             // up once the thing it's explaining is working.
    const onRadioSnap = e => {
      const ri = e.detail?.radio_info;
      if (ri?.own || Object.keys(ri?.all || {}).length) {
        _radioSeen = true;
        window.removeEventListener('vka:snapshot', onRadioSnap);
        _hideHint?.();
      }
    };
    window.addEventListener('vka:snapshot', onRadioSnap);
    setTimeout(() => {
      if (_radioSeen) return;
      _hideHint = showCornerHint({
        icon: '&#9654;',
        title: 'Want a live radio readout?',
        bodyHtml: 'No RadioInfo has arrived from N1MM+ yet. To show live frequency/band here, in N1MM+ go to' +
          ' <b>Config &rarr; Configure Ports &rarr; Broadcast Data</b> and check <b>"Radio"</b> (127.0.0.1:12060).',
        seenKey: RADIO_HINT_SEEN_KEY,
        // Only chain the Report Issue hint on a real user dismissal
        // (markSeen), not the auto-clear-because-radio-showed-up path.
        onDismiss: (markSeen) => { _hideHint = null; if (markSeen) maybeShowReportHint(); },
      });
    }, RADIO_HINT_WAIT_MS);
  }

})();
