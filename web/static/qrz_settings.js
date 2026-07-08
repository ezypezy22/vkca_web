// qrz_settings.js — "QRZ.com Lookup" settings dialog + titlebar progress
// badge. Standalone-modal pattern mirrors report-issue.js: an IIFE guarded
// on both the overlay and the opening button existing, its own event
// wiring, window.VKA.showToast for feedback. Credentials are stored
// server-side (web/server.py's /api/qrz/credentials) — this file never
// persists anything itself.
(function () {
  const overlay = document.getElementById('qrz-settings-dialog');
  const btnOpen = document.getElementById('btn-qrz-settings');
  if (!overlay || !btnOpen) return;

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
  // the QRZ Lookup button, gone the instant everything's synced. in_flight
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

  async function openDialog() {
    passInput.value = '';
    credError.classList.add('hidden');
    await refreshStatus();
    pollTick(); // refresh the progress bar/text immediately rather than waiting for the next tick
    overlay.classList.remove('hidden');
  }

  function closeDialog() {
    overlay.classList.add('hidden');
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

  btnOpen.addEventListener('click', openDialog);
  document.getElementById('btn-qrz-close')?.addEventListener('click', closeDialog);
  document.getElementById('btn-qrz-save')?.addEventListener('click', save);
  document.getElementById('btn-qrz-remove')?.addEventListener('click', removeCreds);
  document.getElementById('btn-qrz-enrich-all')?.addEventListener('click', enrichAll);
})();
