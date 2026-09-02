// settings.js — Consolidated Settings dialog: QRZ.com lookup credentials +
// log-search-folder management, both previously their own separate
// standalone dialogs (qrz_settings.js, and a step inside the "Open Contest
// Log" dialog in app.js). Neither backing API changed — /api/qrz/credentials
// and /api/settings/log_dirs are untouched; this is purely a UI relocation.
// Standalone-modal pattern mirrors report-issue.js: an IIFE guarded on both
// the overlay and the opening button existing, its own event wiring,
// window.VKA.showToast for feedback.
(function () {
  // The SPA serves the identical index.html for every route (main window,
  // Mini HUD at /hud, Operator HUD at /operator_hud — see web/server.py),
  // so #settings-dialog/#btn-settings exist in the DOM everywhere and the
  // guard below alone would pass in all three windows. Without this, the
  // always-on setInterval(pollTick, 2000) further down runs redundantly in
  // all three, and each window could independently fire its own "QRZ
  // Enrich All Complete" toast on the same batch (see issue #60). Settings
  // is a main-window-only concept, so gate on pathname like app.js/
  // overview.js already do for their own HUD-specific branching.
  if (location.pathname !== '/') return;

  const overlay = document.getElementById('settings-dialog');
  const btnOpen = document.getElementById('btn-settings');
  if (!overlay || !btnOpen) return;

  // ── Step switching ─────────────────────────────────────────────────────
  // Same plain .hidden-toggling idiom as the load-dialog's own showStep()
  // (app.js) — not the main window's vka:tabchange, which is a global event
  // ~14 other modules already listen for by name; reusing it inside a modal
  // would fire spurious handlers elsewhere in the app.
  const stepQrz     = document.getElementById('settings-step-qrz');
  const stepLogDirs = document.getElementById('settings-step-logdirs');
  const stepRadio   = document.getElementById('settings-step-radio');
  const stepRigctl  = document.getElementById('settings-step-rigctl');
  const tabQrz      = document.getElementById('settings-tab-qrz');
  const tabLogDirs  = document.getElementById('settings-tab-logdirs');
  const tabRadio    = document.getElementById('settings-tab-radio');
  const tabRigctl   = document.getElementById('settings-tab-rigctl');
  const footerQrz   = document.getElementById('settings-footer-qrz');

  function showSettingsStep(step) {
    stepQrz?.classList.toggle('hidden', step !== 'qrz');
    stepLogDirs?.classList.toggle('hidden', step !== 'logdirs');
    stepRadio?.classList.toggle('hidden', step !== 'radio');
    stepRigctl?.classList.toggle('hidden', step !== 'rigctl');
    tabQrz?.classList.toggle('active', step === 'qrz');
    tabLogDirs?.classList.toggle('active', step === 'logdirs');
    tabRadio?.classList.toggle('active', step === 'radio');
    tabRigctl?.classList.toggle('active', step === 'rigctl');
    footerQrz?.classList.toggle('hidden', step !== 'qrz');
    if (step === 'qrz') { refreshStatus(); pollTick(); }
    else if (step === 'logdirs') { loadLogDirs(); }
    else if (step === 'radio') { loadRadioPort(); }
    else if (step === 'rigctl') { loadRigctl(); }
  }

  function openSettings(step) {
    overlay.classList.remove('hidden');
    showSettingsStep(step || 'qrz');
  }
  function closeSettings() {
    overlay.classList.add('hidden');
  }

  tabQrz?.addEventListener('click', () => showSettingsStep('qrz'));
  tabLogDirs?.addEventListener('click', () => showSettingsStep('logdirs'));
  tabRadio?.addEventListener('click', () => showSettingsStep('radio'));
  tabRigctl?.addEventListener('click', () => showSettingsStep('rigctl'));
  btnOpen.addEventListener('click', () => openSettings('qrz'));
  document.getElementById('btn-settings-close')?.addEventListener('click', closeSettings);

  window.VKA = window.VKA || {};
  window.VKA.openSettings = openSettings;

  // ── QRZ.com lookup (ported unchanged from qrz_settings.js) ─────────────
  const statusLine    = document.getElementById('qrz-status-line');
  const userInput     = document.getElementById('qrz-username');
  const passInput     = document.getElementById('qrz-password');
  const credError     = document.getElementById('qrz-cred-error');
  const enrichStatus  = document.getElementById('qrz-enrich-status');
  const progressWrap  = document.getElementById('qrz-progress-wrap');
  const progressBar   = document.getElementById('qrz-progress-bar');
  const badge         = document.getElementById('qrz-progress-badge');
  const ENRICH_DEFAULT_TEXT = enrichStatus ? enrichStatus.textContent : '';

  let batchActive = false;  // true while an Enrich All batch we know about is still running — fires the completion toast exactly once, on the active→done transition

  function formatEta(seconds) {
    if (seconds <= 0) return '';
    if (seconds < 60) return `~${seconds}s left`;
    const mins = Math.round(seconds / 60);
    return `~${mins} min left`;
  }

  // Titlebar badge: "N left" for ANY outstanding QRZ lookup — live
  // per-QSO enrichment as well as an Enrich All batch — visible next to
  // the Settings button, gone the instant everything's synced. in_flight
  // (not queue_depth) is the right count here: it's incremented when a
  // call is enqueued and only cleared once the worker finishes it, so it
  // already covers the one lookup actively in progress that queue_depth
  // alone would miss (see _qrz_enqueue/_qrz_worker_loop in server.py).
  function renderBadge(s) {
    if (!badge) return;
    const pending = s.in_flight || 0;
    if (pending > 0) {
      badge.textContent = `⏳ ${pending} left`;
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
  }

  // Dialog-specific: the Enrich All progress bar/text and completion toast.
  // Scoped to batch_total/batch_remaining (only set by Enrich All), unlike
  // the badge above which reacts to any outstanding lookup.
  function renderStatus(s) {
    const total     = s.batch_total || 0;
    const remaining = s.batch_remaining || 0;
    const running   = total > 0 && (s.queue_depth > 0 || s.in_flight > 0);

    if (!total) {
      progressWrap.classList.add('hidden');
      enrichStatus.textContent = ENRICH_DEFAULT_TEXT;
    } else if (running) {
      const done    = Math.max(0, total - remaining);
      const percent = Math.round((done / total) * 100);
      progressWrap.classList.remove('hidden');
      progressBar.style.width = `${percent}%`;
      const eta = formatEta(remaining);
      enrichStatus.textContent = `Looking up… ${done} / ${total} (${percent}%)${eta ? ' · ' + eta : ''}`;
    } else {
      progressWrap.classList.remove('hidden');
      progressBar.style.width = '100%';
      enrichStatus.textContent = `Done — ${total} looked up, ${s.cache_size} calls cached.`;
    }

    if (running) {
      batchActive = true;
    } else if (batchActive) {
      // Transitioned from running to finished — notify even if the dialog
      // is closed right now; showToast renders as a page-level overlay.
      batchActive = false;
      window.VKA?.showToast?.('QRZ Enrich All Complete', `${total} calls looked up.`, '✓');
    }
  }

  async function pollTick() {
    let s;
    try {
      s = await fetch('/api/qrz/status').then(r => r.json());
    } catch (e) {
      return; // transient — try again on the next tick
    }
    renderBadge(s);
    renderStatus(s);
  }

  // Always-on, for the page's lifetime — not gated by the dialog being open
  // or a batch being active, since the titlebar badge above needs to react
  // to live per-QSO enrichment too, which can start at any time as new
  // QSOs come in. A same-origin JSON fetch every 2s is negligible next to
  // the app's existing ~5s WebSocket poll cadence.
  setInterval(pollTick, 2000);
  pollTick();

  async function refreshStatus() {
    try {
      const c = await fetch('/api/qrz/credentials').then(r => r.json());
      statusLine.textContent = c.configured
        ? `Configured — logged in as ${c.username}`
        : 'Not configured.';
      userInput.value = c.username || '';
      // The real password is never sent back by the server (see
      // /api/qrz/credentials GET in server.py) — this placeholder is only a
      // visual cue that one is already saved, not the password itself.
      // passInput.value stays empty; typing here always sets a NEW password.
      passInput.placeholder = c.configured ? '•••••••••••• (saved — leave blank to keep)' : '';
    } catch (e) {
      statusLine.textContent = `Status unavailable: ${e.message}`;
    }
  }

  async function save() {
    const username = userInput.value.trim(), password = passInput.value;
    credError.classList.add('hidden');
    // password may be blank here on purpose — the server reuses the saved
    // password when one already exists (see api_qrz_credentials_post in
    // server.py), matching the "leave blank to keep" placeholder above. It
    // only rejects a blank password when there's nothing saved to fall
    // back to, which the response's error message will say.
    if (!username) {
      credError.textContent = 'Enter a username.';
      credError.classList.remove('hidden');
      return;
    }
    let data;
    try {
      const res = await fetch('/api/qrz/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      data = await res.json();
    } catch (e) {
      credError.textContent = `Request failed: ${e.message}`;
      credError.classList.remove('hidden');
      return;
    }
    if (data.error) {
      credError.textContent = data.error;
      credError.classList.remove('hidden');
      return;
    }
    window.VKA?.showToast?.('QRZ Configured', `Logged in as ${data.username}`, '✓');
    await refreshStatus();
  }

  async function removeCreds() {
    await fetch('/api/qrz/credentials', { method: 'DELETE' });
    await refreshStatus();
  }

  async function enrichAll() {
    let data;
    try {
      const res = await fetch('/api/qrz/enrich_all', { method: 'POST' });
      data = await res.json();
    } catch (e) {
      enrichStatus.textContent = `Request failed: ${e.message}`;
      return;
    }
    if (data.error) {
      enrichStatus.textContent = data.error;
      return;
    }
    if (data.queued === 0) {
      progressWrap.classList.add('hidden');
      enrichStatus.textContent = `Nothing to do — all ${data.total_calls} calls already cached.`;
      return;
    }
    progressWrap.classList.remove('hidden');
    progressBar.style.width = '0%';
    enrichStatus.textContent =
      `Queued ${data.queued} of ${data.total_calls} calls (${data.already_cached} already cached)…`;
    batchActive = true;
    // No need to (re)start polling — pollTick() already runs continuously.
  }

  document.getElementById('btn-qrz-save')?.addEventListener('click', save);
  document.getElementById('btn-qrz-remove')?.addEventListener('click', removeCreds);
  document.getElementById('btn-qrz-enrich-all')?.addEventListener('click', enrichAll);

  // ── Log search folders (ported unchanged from app.js) ──────────────────
  const logDirsList     = document.getElementById('log-dirs-list');
  const defaultLogDirEl = document.getElementById('default-log-dir');
  const not1mmDirRow    = document.getElementById('not1mm-log-dir-row');
  const not1mmDirEl     = document.getElementById('not1mm-log-dir');
  const addFolderInput  = document.getElementById('add-folder-input');
  const btnBrowseFolder = document.getElementById('btn-browse-folder');
  const btnAddFolder    = document.getElementById('btn-add-folder');
  const folderError     = document.getElementById('folder-error');

  function showFolderError(msg) { folderError.textContent = msg; folderError.classList.remove('hidden'); }

  async function loadLogDirs() {
    if (!logDirsList) return;
    try {
      const res  = await fetch('/api/settings/log_dirs');
      const data = await res.json();
      if (defaultLogDirEl) defaultLogDirEl.textContent = data.default_dir || '';
      if (not1mmDirRow) not1mmDirRow.classList.toggle('hidden', !data.not1mm_default_dir);
      if (not1mmDirEl) not1mmDirEl.textContent = data.not1mm_default_dir || '';
      const dirs = data.dirs || [];
      logDirsList.innerHTML = '';
      if (!dirs.length) {
        logDirsList.innerHTML = `<div class="dialog-hint" style="margin:6px 2px">No custom folders added yet.</div>`;
        return;
      }
      dirs.forEach(d => {
        const row = document.createElement('div');
        row.className = 'log-dir-row' + (d.exists ? '' : ' log-dir-missing');
        row.innerHTML = `<span class="log-dir-path" title="${d.path}">${d.path}${d.exists ? '' : ' (not found)'}</span>
          <button class="log-dir-remove" title="Remove">✕</button>`;
        row.querySelector('.log-dir-remove').addEventListener('click', async () => {
          await fetch('/api/settings/log_dirs', {
            method: 'DELETE', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({path: d.path})
          });
          loadLogDirs();
          window.VKA?.scanKnownLocations?.();
        });
        logDirsList.appendChild(row);
      });
    } catch (e) { console.warn('loadLogDirs failed:', e); }
  }

  btnAddFolder?.addEventListener('click', async () => {
    const path = addFolderInput.value.trim();
    folderError.classList.add('hidden');
    if (!path) { showFolderError('Enter or browse to a folder path.'); return; }
    try {
      const res  = await fetch('/api/settings/log_dirs', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({path})
      });
      const data = await res.json();
      if (!res.ok || data.error) { showFolderError(data.error || 'Failed to add folder.'); return; }
      addFolderInput.value = '';
      loadLogDirs();
    } catch (e) { showFolderError(`Add failed: ${e.message}`); }
  });

  btnBrowseFolder?.addEventListener('click', async () => {
    btnBrowseFolder.disabled=true; btnBrowseFolder.textContent='…';
    try {
      const res = await fetch('/api/browse_folder');
      const data = await res.json();
      if (res.status === 503) { showFolderError('No native browser available — enter the folder path manually.'); return; }
      if (data.error) { showFolderError(data.error); return; }
      if (data.path)  { addFolderInput.value = data.path; folderError.classList.add('hidden'); }
    } catch(e) { showFolderError(`Browse failed: ${e.message}`); }
    finally { btnBrowseFolder.disabled=false; btnBrowseFolder.textContent='📁'; }
  });

  // ── Radio Setup (N1MM+ RadioInfo UDP listener port) ─────────────────────
  const radioPortInput  = document.getElementById('radio-port-input');
  const radioPortError  = document.getElementById('radio-port-error');
  const radioPortStatus = document.getElementById('radio-port-status');
  const btnRadioSave    = document.getElementById('btn-radio-port-save');

  function setRadioPortStatus(port, bindError) {
    if (!radioPortStatus) return;
    radioPortStatus.textContent = bindError
      ? `⚠ ${bindError}`
      : `✓ Listening on port ${port}.`;
    radioPortStatus.style.color = bindError ? 'var(--red)' : 'var(--green)';
  }

  async function loadRadioPort() {
    if (!radioPortInput) return;
    try {
      const res  = await fetch('/api/settings/radio_port');
      const data = await res.json();
      radioPortInput.value = data.port;
      setRadioPortStatus(data.port, data.bind_error);
    } catch (e) { console.warn('loadRadioPort failed:', e); }
  }

  btnRadioSave?.addEventListener('click', async () => {
    radioPortError.classList.add('hidden');
    const port = parseInt(radioPortInput.value, 10);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      radioPortError.textContent = 'Enter a port number between 1 and 65535.';
      radioPortError.classList.remove('hidden');
      return;
    }
    btnRadioSave.disabled = true;
    try {
      const res  = await fetch('/api/settings/radio_port', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({port}),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        radioPortError.textContent = data.error || 'Failed to save port.';
        radioPortError.classList.remove('hidden');
        return;
      }
      setRadioPortStatus(data.port, data.bind_error);
      if (!data.bind_error) {
        window.VKA?.showToast?.('Radio port updated',
          `Now listening on ${data.port} — remember to also update N1MM+'s own Broadcast Data → Radio port to match.`, '📡');
      }
    } catch (e) {
      radioPortError.textContent = `Save failed: ${e.message}`;
      radioPortError.classList.remove('hidden');
    } finally {
      btnRadioSave.disabled = false;
    }
  });

  // ── Rig Control (Hamlib rigctld — standalone Logger mode only) ─────────
  const RIGCTL_MACRO_KEYS = ['1', '2', '3', '5', '7', '8', '9'];
  const RIGCTL_BAND_KEYS  = ['160M', '80M', '40M', '20M', '15M', '10M'];
  const rigctlEnabled = document.getElementById('rigctl-enabled');
  const rigctlHost    = document.getElementById('rigctl-host');
  const rigctlPort    = document.getElementById('rigctl-port');
  const rigctlError   = document.getElementById('rigctl-error');
  const rigctlStatus  = document.getElementById('rigctl-status');
  const btnRigctlSave = document.getElementById('btn-rigctl-save');

  function setRigctlStatus(data) {
    if (!rigctlStatus) return;
    if (!data.enabled) {
      rigctlStatus.textContent = 'Rig Control is disabled.';
      rigctlStatus.style.color = 'var(--muted)';
    } else if (data.status) {
      rigctlStatus.textContent = `⚠ ${data.status}`;
      rigctlStatus.style.color = 'var(--red)';
    } else if (data.connected) {
      rigctlStatus.textContent = `✓ Connected to rigctld at ${data.host}:${data.port}.`;
      rigctlStatus.style.color = 'var(--green)';
    } else {
      rigctlStatus.textContent = 'Not connected — will connect once a standalone log is loaded.';
      rigctlStatus.style.color = 'var(--muted)';
    }
  }

  async function loadRigctl() {
    if (!rigctlEnabled) return;
    try {
      const res  = await fetch('/api/settings/rigctld');
      const data = await res.json();
      rigctlEnabled.checked = !!data.enabled;
      rigctlHost.value = data.host;
      rigctlPort.value = data.port;
      RIGCTL_MACRO_KEYS.forEach(k => {
        const el = document.getElementById(`rigctl-macro-${k}`);
        if (el) el.value = (data.macros || {})[k] || '';
      });
      RIGCTL_BAND_KEYS.forEach(b => {
        const el = document.getElementById(`rigctl-band-${b}`);
        const hz = (data.band_defaults || {})[b];
        if (el) el.value = hz ? (hz / 1000) : '';
      });
      setRigctlStatus(data);
    } catch (e) { console.warn('loadRigctl failed:', e); }
  }

  btnRigctlSave?.addEventListener('click', async () => {
    rigctlError.classList.add('hidden');
    const port = parseInt(rigctlPort.value, 10);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      rigctlError.textContent = 'Enter a port number between 1 and 65535.';
      rigctlError.classList.remove('hidden');
      return;
    }
    const macros = {};
    RIGCTL_MACRO_KEYS.forEach(k => {
      const el = document.getElementById(`rigctl-macro-${k}`);
      if (el) macros[k] = el.value;
    });
    const bandDefaults = {};
    RIGCTL_BAND_KEYS.forEach(b => {
      const el = document.getElementById(`rigctl-band-${b}`);
      if (el && el.value.trim()) bandDefaults[b] = el.value.trim();
    });
    btnRigctlSave.disabled = true;
    try {
      const res  = await fetch('/api/settings/rigctld', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          enabled: rigctlEnabled.checked,
          host: rigctlHost.value.trim() || '127.0.0.1',
          port, macros, band_defaults: bandDefaults,
        }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        rigctlError.textContent = data.error || 'Failed to save.';
        rigctlError.classList.remove('hidden');
        return;
      }
      setRigctlStatus({enabled: rigctlEnabled.checked, host: rigctlHost.value.trim(), port,
        status: data.status, connected: data.connected});
    } catch (e) {
      rigctlError.textContent = `Save failed: ${e.message}`;
      rigctlError.classList.remove('hidden');
    } finally {
      btnRigctlSave.disabled = false;
    }
  });
})();
