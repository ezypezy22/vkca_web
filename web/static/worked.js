/**
 * worked.js — Full QSO log (all worked, not just last 5)
 * Paginated with filter for performance on large logs.
 * Adds the old desktop app's "Block" / live-ticking countdown column, plus
 * multi-select delete.
 *
 * The countdown means one of two different things depending on the
 * contest, and shows accordingly:
 *   - Most contests: a fixed operating-block schedule (session_config()) —
 *     "Next Block In", same countdown for every QSO in the same block.
 *   - Contests with a rolling per-contact re-work rule instead (e.g. WIA
 *     Remembrance Day's "not less than 3 hours between contacts on the
 *     same band/mode" — see ContestPlugin.rework_window_hours) — "Time
 *     Left to Work", each row counting down independently from ITS OWN
 *     QSO time, not a shared block boundary. Showing the block-schedule
 *     countdown for a contest that has no actual blocks (as this used to,
 *     unconditionally) read as flatly wrong: every row showed the same
 *     countdown regardless of when that specific contact happened.
 */
;(function () {
  'use strict';
  const BAND_COLS = window.VKA.BAND_COLS;

  let _allQsos  = [];
  let _filtered = [];
  let _selected = new Set();
  let _tickHandle = null;
  const PAGE_SIZE = 100;
  let _page = 0;
  let _sortCol = null, _sortDir = 1;   // 1 = ascending, -1 = descending

  // Session/block config, pulled from the latest snapshot.
  let _contestStart = null;   // Date
  let _durationMins = null;
  let _labelPrefix  = 'B';
  // Rework-window config, pulled from /api/plugin_meta (see
  // ContestPlugin.rework_window_hours) — null means this contest uses the
  // block schedule above instead.
  let _reworkWindowHours = null;

  const tbody       = document.getElementById('worked-tbody');
  const countEl     = document.getElementById('worked-count');
  const filterEl    = document.getElementById('worked-filter');
  const prevBtn     = document.getElementById('worked-prev');
  const nextBtn     = document.getElementById('worked-next');
  const pageEl       = document.getElementById('worked-page');
  const deleteBtn     = document.getElementById('worked-delete-btn');
  const selectAllChk  = document.getElementById('worked-select-all');
  const exportCsvBtn  = document.getElementById('worked-export-csv-btn');
  const exportAdifBtn = document.getElementById('worked-export-adif-btn');
  const thBlock       = document.getElementById('worked-th-block');
  const thCountdown   = document.getElementById('worked-th-countdown');
  const countdownHint = document.getElementById('worked-countdown-hint');

  function fmt(isoStr) {
    if (!isoStr) return '—';
    return String(isoStr).replace('T',' ').substring(0,19)+' UTC';
  }

  function fmtRemaining(ms) {
    if (ms <= 0) return 'Workable';
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    return `${h}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`;
  }

  function readSessionConfig() {
    const snap = window.VKA?.lastSnap?.();
    const ss   = snap?.session_status || {};
    _contestStart = ss.start_dt ? new Date(ss.start_dt+'Z') : null;   // server times are naive UTC
    _durationMins = ss.duration_mins || null;
    _labelPrefix  = ss.label_prefix || 'B';
  }

  async function readPluginMeta() {
    try {
      const res  = await fetch('/api/plugin_meta');
      const meta = await res.json();
      _reworkWindowHours = meta.loaded ? (meta.rework_window_hours || null) : null;
    } catch { _reworkWindowHours = null; }
    if (thBlock)     thBlock.style.display = _reworkWindowHours ? 'none' : '';
    if (thCountdown) thCountdown.textContent = _reworkWindowHours ? 'Time Left to Work' : 'Next Block In';
    if (countdownHint) countdownHint.textContent = _reworkWindowHours
      ? `— Time Left to Work = when this station's own ${_reworkWindowHours}h rework window ends`
      : '— Next Block In = when this operating block ends';
  }

  // Per-QSO "next workable" info — either this row's own rework-window
  // deadline (its own QSO time + rework_window_hours, independent of
  // every other row) or the shared block boundary it falls in, whichever
  // this contest uses (see the file header comment for why these differ).
  function countdownInfo(qsoTimeIso) {
    if (!qsoTimeIso) return null;
    const t = new Date(qsoTimeIso+'Z');   // server times are naive UTC
    if (_reworkWindowHours) {
      return { label: null, end: new Date(t.getTime() + _reworkWindowHours * 3600000) };
    }
    if (!_contestStart || !_durationMins) return null;
    const elapsedMins = (t - _contestStart) / 60000;
    if (elapsedMins < 0) return null;
    const bn = Math.floor(elapsedMins / _durationMins);
    const end = new Date(_contestStart.getTime() + (bn + 1) * _durationMins * 60000);
    return { label: `${_labelPrefix}${bn + 1}`, end };
  }

  // Mode bucket for grouping rework-window contacts — mirrors
  // plugins/vk_rd.py's _vkrd_dupe_mode_key() ("CW and RTTY count as one
  // mode; SSB and FM count as one mode"). Only meaningful in rework-
  // window mode; block-mode contests don't group rows at all.
  function reworkModeKey(mode) {
    const m = (mode || '').toUpperCase();
    return (m === 'CW' || m.includes('RTTY') || m.includes('FSK')) ? 'CW_DIGITAL' : 'PHONE';
  }

  // Stamps every loaded QSO with its countdown target as a plain number
  // (q._countdownAt, ms epoch) so the click-to-sort column (applySort())
  // can compare it like any other field — sorting by "time left" is the
  // same ordering as sorting by this absolute deadline, since "now" is a
  // constant offset shared by every row at sort time.
  //
  // In rework-window mode specifically, only the most recent *valid*
  // (non-dupe) contact per (call, band, mode-group) gets a real countdown.
  // Two things get filtered out of contention here, not just one:
  //   - An older contact superseded by a later one already had its own
  //     rework window exercised, so showing "Workable" on it reads as if
  //     that opportunity is still outstanding when it's actually done.
  //   - A too-early rework attempt (q.dupe) is itself invalid — it never
  //     legitimately reset anything, so it can't be treated as "the
  //     current state" either (matches plugins/vk_rd.py recalc_pts()'s
  //     own prev_valid_time, which skips dupe rows for the same reason).
  // Both cases render as "—" instead.
  function annotateCountdowns() {
    let latest = null;
    if (_reworkWindowHours) {
      latest = new Map();   // group key -> most recent non-dupe QSO in it
      _allQsos.forEach(q => {
        if (!q.time || q.dupe) return;
        const key = `${(q.call||'').toUpperCase()}|${(q.band||'').toUpperCase()}|${reworkModeKey(q.mode)}`;
        const cur = latest.get(key);
        if (!cur || new Date(q.time+'Z') > new Date(cur.time+'Z')) latest.set(key, q);
      });
      latest = new Set(latest.values());
    }
    _allQsos.forEach(q => {
      const ci = countdownInfo(q.time);
      const show = ci && (!latest || latest.has(q));
      q._countdownAt    = show ? ci.end.getTime() : null;
      q._countdownLabel = ci ? ci.label : null;
    });
  }

  // Bumped on every load() call so an older, slower-to-resolve fetch can't
  // clobber the table with stale rows after a newer one already rendered
  // (e.g. a rapid snapshot-tick + tab-switch) — mirrors report.js's own
  // _loadGeneration pattern (see issue #64).
  let _loadGeneration = 0;

  // Fetched at most once per loaded contest (reset on vka:loaded below) —
  // load() itself runs on every snapshot poll, and rework_window_hours
  // can't change without a contest switch, so re-fetching it every few
  // seconds would just be wasted requests.
  let _metaLoaded = false;
  window.addEventListener('vka:loaded', () => { _metaLoaded = false; _page = 0; });

  async function load() {
    const gen = ++_loadGeneration;
    readSessionConfig();
    if (!_metaLoaded) { _metaLoaded = true; await readPluginMeta(); }
    try {
      const data = await window.VKA.fetchQsos();
      if (gen !== _loadGeneration) return;
      _allQsos  = data;
      annotateCountdowns();
      applyFilter();
    } catch(e) {
      if (gen !== _loadGeneration) return;
      if (tbody) tbody.innerHTML = `<tr><td colspan="13" style="color:var(--red);padding:12px">Failed: ${e.message}</td></tr>`;
    }
  }

  function applyFilter() {
    const q = (filterEl?.value || '').toLowerCase().trim();
    _filtered = q
      ? _allQsos.filter(r =>
          (r.call||'').toLowerCase().includes(q) ||
          (r.band||'').toLowerCase().includes(q) ||
          (r.mode||'').toLowerCase().includes(q) ||
          (r.mult1||'').toLowerCase().includes(q))
      : _allQsos;
    applySort();
    render();
  }

  // Click-to-sort column headers — numeric columns (pts, the countdown's
  // underlying ms-epoch deadline) compare as numbers, everything else
  // (including time, an ISO string, which sorts correctly as text)
  // compares case-insensitively as text.
  function applySort() {
    if (!_sortCol) return;
    const col = _sortCol, dir = _sortDir, numeric = col === 'pts' || col === '_countdownAt';
    _filtered = [..._filtered].sort((a, b) => {
      let av = a[col], bv = b[col];
      if (numeric) { av = av || 0; bv = bv || 0; return (av - bv) * dir; }
      av = String(av || '').toLowerCase(); bv = String(bv || '').toLowerCase();
      return av.localeCompare(bv) * dir;
    });
  }

  function updateSortHeaders() {
    document.querySelectorAll('.sortable-th').forEach(th => {
      th.classList.toggle('sort-asc',  th.dataset.sort === _sortCol && _sortDir === 1);
      th.classList.toggle('sort-desc', th.dataset.sort === _sortCol && _sortDir === -1);
    });
  }

  document.querySelectorAll('#tab-worked .sortable-th').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (_sortCol === col) _sortDir = -_sortDir; else { _sortCol = col; _sortDir = 1; }
      updateSortHeaders();
      applySort();
      _page = 0;
      render();
    });
  });

  function updateDeleteBtn() {
    if (deleteBtn) deleteBtn.disabled = _selected.size === 0;
  }

  function renderQrzCell(val, status) {
    if (status === 'pending')   return `<span style="color:var(--muted);font-style:italic" title="Looking up on QRZ.com…">…</span>`;
    if (status === 'not_found') return `<span style="color:var(--muted)" title="Not found on QRZ.com">✗</span>`;
    if (status === 'found')     return val ? window.VKA.escapeHtml(val) : `<span style="color:var(--muted)" title="No data on QRZ.com">—</span>`;
    return `<span style="color:var(--muted)">—</span>`;   // "none" — QRZ lookup not configured/never attempted
  }

  function render() {
    if (!tbody) return;
    const total = _filtered.length;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    _page = Math.max(0, Math.min(_page, pages - 1));
    const start = _page * PAGE_SIZE;
    const slice = _filtered.slice(start, start + PAGE_SIZE);

    if (countEl)  countEl.textContent  = total.toLocaleString();
    if (pageEl)   pageEl.textContent   = `${_page + 1} / ${pages}`;
    if (prevBtn)  prevBtn.disabled     = _page === 0;
    if (nextBtn)  nextBtn.disabled     = _page >= pages - 1;
    if (selectAllChk) selectAllChk.checked = false;

    // Matches thBlock's own display:none toggle in readPluginMeta() — kept
    // as a hidden <td> rather than omitted entirely, so every row still
    // has the same cell count/positions as the header regardless of mode.
    const blockTdStyle = _reworkWindowHours ? 'display:none' : 'color:var(--accent3)';

    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    slice.forEach(q => {
      const band = (q.band||'').toUpperCase();
      const col  = BAND_COLS[band] || 'var(--muted)';
      const isDupe = q.dupe ? '✗' : '';
      const endIso = q._countdownAt ? new Date(q._countdownAt).toISOString() : '';
      const tr   = document.createElement('tr');
      if (q.dupe) tr.style.opacity = '0.4';
      tr.innerHTML = `
        <td><input type="checkbox" class="worked-row-chk" data-qid="${q.qso_id||''}" ${_selected.has(q.qso_id) ? 'checked' : ''}></td>
        <td style="color:var(--accent);font-weight:bold">${window.VKA.escapeHtml(q.call||'—')}</td>
        <td style="color:${col}">${band.toLowerCase()}</td>
        <td>${q.mode||'—'}</td>
        <td style="color:${col}">${window.VKA.escapeHtml(q.mult1||'—')}</td>
        <td>${q.pts||0}</td>
        <td>${renderQrzCell(q.qrz_name,  q.qrz_status)}</td>
        <td>${renderQrzCell(q.qrz_grid,  q.qrz_status)}</td>
        <td>${renderQrzCell(q.qrz_state, q.qrz_status)}</td>
        <td style="color:var(--muted);font-size:0.85em">${fmt(q.time)}</td>
        <td style="${blockTdStyle}">${q._countdownLabel || '—'}</td>
        <td class="worked-countdown" data-block-end="${endIso}" style="font-size:0.85em">${q._countdownAt ? fmtRemaining(q._countdownAt - Date.now()) : '—'}</td>
        <td style="color:var(--red);font-size:0.85em">${isDupe}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  function tickCountdowns() {
    if (!tbody) return;
    const now = new Date();
    tbody.querySelectorAll('.worked-countdown').forEach(td => {
      const iso = td.dataset.blockEnd;
      if (!iso) return;
      td.textContent = fmtRemaining(new Date(iso) - now);
    });
  }

  async function deleteSelected() {
    if (!_selected.size) return;
    const calls = _allQsos.filter(q => _selected.has(q.qso_id)).map(q => q.call).join(', ');
    const msg = _selected.size === 1
      ? `Permanently delete this QSO (${calls}) from the database?`
      : `Permanently delete ${_selected.size} QSOs (${calls}) from the database?`;
    if (!window.confirm(msg)) return;
    try {
      const res  = await fetch('/api/qsos/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ qso_ids: [..._selected] }),
      });
      const data = await res.json();
      if (data.errors && data.errors.length) console.warn('Delete errors:', data.errors);
      _selected.clear();
      updateDeleteBtn();
      // Must happen before load() below, not just the vka:qsos_changed
      // dispatch after it — otherwise load() can still serve the
      // just-deleted rows back out of the shared cache's short TTL.
      window.VKA.invalidateQsosCache();
      await load();
      window.dispatchEvent(new CustomEvent('vka:qsos_changed'));
    } catch (e) { console.warn('Delete failed:', e); }
  }

  // ── Export (filtered + sorted view, not the whole log — the titlebar's
  // own CSV menu already covers a full unfiltered export via
  // /api/export/csv/qsos; this one respects whatever the operator has
  // actually filtered/sorted down to here, plus the QRZ enrichment columns
  // that endpoint doesn't have) ─────────────────────────────────────────
  function qsoDateParts(iso) {
    const s = String(iso || '');
    return { date: s.slice(0,4)+s.slice(5,7)+s.slice(8,10), time: s.slice(11,13)+s.slice(14,16)+s.slice(17,19) };
  }

  function csvCell(v) {
    v = String(v ?? '');
    return /[",\n]/.test(v) ? '"' + v.replace(/"/g,'""') + '"' : v;
  }

  async function exportCsv() {
    const cols = ['call','band','mode','mult1','pts','qrz_name','qrz_grid','qrz_state','time','dupe'];
    const lines = [cols.join(',')];
    _filtered.forEach(q => lines.push(cols.map(c => csvCell(c === 'dupe' ? (q.dupe ? '1' : '0') : q[c])).join(',')));
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    await window.VKA.downloadBlob(blob, `vkcontest_worked_${new Date().toISOString().slice(0,10)}.csv`, '✓ CSV Saved', '📄');
  }

  async function exportAdif() {
    const lines = ['Generated by VK Contest Analyzer', '<ADIF_VER:5>3.1.4', '<PROGRAMID:16>VKContestAnalyzer', '<EOH>', ''];
    _filtered.forEach(q => {
      if (q.dupe) return;   // dupes aren't real contacts — don't pollute an ADIF import with them
      const { date, time } = qsoDateParts(q.time);
      const call = String(q.call || '').trim();
      if (!call || !date) return;
      const band = String(q.band || '').toLowerCase();
      const mode = String(q.mode || '').toUpperCase();
      const rec = [
        `<CALL:${call.length}>${call}`,
        `<QSO_DATE:${date.length}>${date}`,
        `<TIME_ON:${time.length}>${time}`,
      ];
      if (band) rec.push(`<BAND:${band.length}>${band}`);
      if (mode) rec.push(`<MODE:${mode.length}>${mode}`);
      rec.push('<EOR>');
      lines.push(rec.join(' '));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    await window.VKA.downloadBlob(blob, `vkcontest_worked_${new Date().toISOString().slice(0,10)}.adi`, '✓ ADIF Saved', '📄');
  }

  exportCsvBtn?.addEventListener('click', () => exportCsv().catch(e => console.warn('CSV export failed:', e)));
  exportAdifBtn?.addEventListener('click', () => exportAdif().catch(e => console.warn('ADIF export failed:', e)));

  filterEl?.addEventListener('input', () => { _page = 0; applyFilter(); });
  prevBtn?.addEventListener('click', () => { _page--; render(); });
  nextBtn?.addEventListener('click', () => { _page++; render(); });
  deleteBtn?.addEventListener('click', deleteSelected);

  tbody?.addEventListener('change', e => {
    if (!e.target.classList.contains('worked-row-chk')) return;
    const qid = e.target.dataset.qid;
    if (e.target.checked) _selected.add(qid); else _selected.delete(qid);
    updateDeleteBtn();
  });

  selectAllChk?.addEventListener('change', () => {
    const checked = selectAllChk.checked;
    tbody?.querySelectorAll('.worked-row-chk').forEach(chk => {
      chk.checked = checked;
      if (checked) _selected.add(chk.dataset.qid); else _selected.delete(chk.dataset.qid);
    });
    updateDeleteBtn();
  });

  window.addEventListener('vka:snapshot', load);
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab === 'worked') load(); });

  if (!_tickHandle) _tickHandle = setInterval(tickCountdowns, 1000);
})();
