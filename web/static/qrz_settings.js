// qrz_settings.js — "QRZ.com Lookup" settings dialog. Standalone-modal
// pattern mirrors report-issue.js: an IIFE guarded on both the overlay and
// the opening button existing, its own event wiring, window.VKA.showToast
// for feedback. Credentials are stored server-side (web/server.py's
// /api/qrz/credentials) — this file never persists anything itself.
(function () {
  const overlay = document.getElementById('qrz-settings-dialog');
  const btnOpen = document.getElementById('btn-qrz-settings');
  if (!overlay || !btnOpen) return;

  const statusLine   = document.getElementById('qrz-status-line');
  const userInput    = document.getElementById('qrz-username');
  const passInput    = document.getElementById('qrz-password');
  const credError    = document.getElementById('qrz-cred-error');
  const enrichStatus = document.getElementById('qrz-enrich-status');
  const ENRICH_DEFAULT_TEXT = enrichStatus ? enrichStatus.textContent : '';
  let pollHandle = null;

  async function refreshStatus() {
    try {
      const c = await fetch('/api/qrz/credentials').then(r => r.json());
      statusLine.textContent = c.configured
        ? `Configured — logged in as ${c.username}`
        : 'Not configured.';
      userInput.value = c.username || '';
    } catch (e) {
      statusLine.textContent = `Status unavailable: ${e.message}`;
    }
  }

  async function openDialog() {
    passInput.value = '';
    credError.classList.add('hidden');
    enrichStatus.textContent = ENRICH_DEFAULT_TEXT;
    await refreshStatus();
    overlay.classList.remove('hidden');
  }

  function closeDialog() {
    overlay.classList.add('hidden');
    if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
  }

  async function save() {
    const username = userInput.value.trim(), password = passInput.value;
    credError.classList.add('hidden');
    if (!username || !password) {
      credError.textContent = 'Enter both username and password.';
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

  async function pollEnrichStatus() {
    let s;
    try {
      s = await fetch('/api/qrz/status').then(r => r.json());
    } catch (e) {
      return; // transient — try again on the next tick
    }
    if (s.queue_depth === 0 && s.in_flight === 0) {
      enrichStatus.textContent = `Done — ${s.cache_size} calls cached.`;
      clearInterval(pollHandle);
      pollHandle = null;
    } else {
      enrichStatus.textContent = `Looking up… ${s.queue_depth} remaining in queue.`;
    }
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
    enrichStatus.textContent =
      `Queued ${data.queued} of ${data.total_calls} calls (${data.already_cached} already cached)…`;
    if (pollHandle) clearInterval(pollHandle);
    pollHandle = setInterval(pollEnrichStatus, 1000);
  }

  btnOpen.addEventListener('click', openDialog);
  document.getElementById('btn-qrz-close')?.addEventListener('click', closeDialog);
  document.getElementById('btn-qrz-save')?.addEventListener('click', save);
  document.getElementById('btn-qrz-remove')?.addEventListener('click', removeCreds);
  document.getElementById('btn-qrz-enrich-all')?.addEventListener('click', enrichAll);
})();
