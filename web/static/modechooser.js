/**
 * modechooser.js — startup chooser between Analyzer (today's full
 * monitoring/analysis dashboard) and Logger (a lean surface for actually
 * operating a contest: just the gauges/sparklines/minimal live-status
 * readout plus the Log Entry tab). Shown every launch, unlike the one-time
 * splash disclaimer (app.js) it sequences after.
 *
 * Drives the existing #load-dialog (app.js) from a second entry point
 * rather than duplicating its scan/load/new-log logic — see showDialog()/
 * showStep()/scanKnownLocations() exports added there, and the simulated
 * .click() calls on #btn-scan/#btn-new-log below, which reuse those
 * buttons' own existing listeners exactly as a real click would.
 */
;(function () {
  'use strict';
  if (location.pathname !== '/') return;   // main-window-only, like settings.js

  const LAST_MODE_KEY = 'vkca_last_mode';

  // ── Logger mode's tab-visibility ─────────────────────────────────────────
  const LOGGER_HIDDEN_TABS = ['overview','cluster','map','rate','missing','bands',
    'fatigue','yoy','pace','dupes','debug','worked','report'];

  function applyLoggerModeVisibility(on){
    LOGGER_HIDDEN_TABS.forEach(id => window.VKA.setTabVisible(id, !on));
    window.VKA.setTabVisible('logentry', true);   // always visible once Logger mode is on
    // Symmetric in both directions: Logger mode forces Log Entry active;
    // switching back to Analyzer restores Overview as the active tab,
    // rather than leaving whatever tab was active (possibly still hidden).
    const activeId = on ? 'logentry' : 'overview';
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.toggle('active', b.dataset.tab===activeId));
    document.querySelectorAll('.tab-panel').forEach(p=>p.classList.toggle('active', p.id==='tab-'+activeId));
    const bar=document.getElementById('logger-status-bar');
    if (bar) bar.style.display = on ? 'flex' : 'none';
    window.VKA.setLoggerMode?.(on);
  }

  // Switch-back-to-Analyzer button (see #logger-status-bar in index.html) —
  // a log is already loaded, so this is just a mode/visibility toggle, not
  // a new dialog or reload.
  document.getElementById('btn-switch-to-analyzer')?.addEventListener('click', ()=>{
    window.VKA.appMode='analyzer';
    try { localStorage.setItem(LAST_MODE_KEY,'analyzer'); } catch {}
    applyLoggerModeVisibility(false);
  });

  // ── Logger mode's "resume a previous standalone log" list ────────────────
  async function renderResumeList(){
    const list=document.getElementById('resume-list');
    const hint=document.getElementById('no-resume-hint');
    if (!list) return;
    list.innerHTML='';
    try{
      const res=await fetch('/api/scan_known_locations?check_standalone=1');
      const data=await res.json();
      const dbs=(data.databases||[]).filter(db=>db.is_standalone);
      if (!dbs.length){ hint?.classList.remove('hidden'); return; }
      hint?.classList.add('hidden');
      dbs.forEach(db=>{
        const row=document.createElement('div');
        row.className='contest-row';
        row.innerHTML=`<div class="contest-row-accent" style="background:var(--accent)"></div>
          <div class="contest-row-body">
            <div class="contest-row-name">${window.VKA.escapeHtml(db.name||'')}</div>
            <div class="contest-row-path" title="${window.VKA.escapeHtml(window.VKA.dirOf(db.path))}">${window.VKA.escapeHtml(window.VKA.dirOf(db.path))}</div>
            <div class="contest-row-meta">
              <span>${window.VKA.fmtAgo(db.mtime)}</span>
              <span>${window.VKA.fmtBytes(db.size)}</span>
            </div>
          </div>
          <div class="contest-row-arrow">›</div>`;
        row.addEventListener('click', ()=>{
          const pathInput=document.getElementById('load-path-input');
          if (pathInput) pathInput.value=db.path;
          window.VKA.showStep('path');
          // Reuses the exact existing scan-then-auto-load pipeline (a real
          // click on the same button a manual "Scan for Contests" press
          // would use) rather than a second copy of that logic — every
          // standalone log create_new_log() writes always has exactly one
          // ContestInstance row, so doScan()'s own "auto-load if exactly
          // one contest found" already handles the resume case as-is.
          document.getElementById('btn-scan')?.click();
        });
        list.appendChild(row);
      });
    }catch(e){ console.warn('modechooser: renderResumeList failed:',e); hint?.classList.remove('hidden'); }
  }

  function showResumeDialog(){
    document.getElementById('load-dialog')?.classList.remove('hidden');
    window.VKA.showStep('resume');
    renderResumeList();
  }
  document.getElementById('btn-resume-new-log')?.addEventListener('click', ()=>{
    // Reuses "+ New Log"'s own existing button/listener (contest-type
    // lazy-load, default path suggestion, etc.) rather than a second copy.
    document.getElementById('btn-new-log')?.click();
  });

  // ── The chooser overlay itself — same technique as the splash overlay
  // (app.js): a plain div built via innerHTML + document.body.appendChild(),
  // position:fixed;inset:0 at a high z-index (see style.css), no click-
  // outside dismissal and no Cancel — mandatory, one deliberate action to
  // proceed, matching the splash's own precedent. ─────────────────────────
  function showModeChooser(){
    const suggested = (() => { try { return localStorage.getItem(LAST_MODE_KEY); } catch { return null; } })();
    const el=document.createElement('div');
    el.id='mode-chooser-overlay';
    el.innerHTML=`
      <div id="mode-chooser-box">
        <div id="mode-chooser-title">VK CONTEST ANALYZER</div>
        <div id="mode-chooser-sub">What are you here to do?</div>
        <div id="mode-chooser-cards">
          <button class="mode-card${suggested==='analyzer'?' mode-card--suggested':''}" data-mode="analyzer" type="button">
            <span class="mode-card-icon">🔍</span>
            <span class="mode-card-title">Analyzer</span>
            <span class="mode-card-desc">Monitor and analyze a contest log — the full dashboard.</span>
          </button>
          <button class="mode-card${suggested==='logger'?' mode-card--suggested':''}" data-mode="logger" type="button">
            <span class="mode-card-icon">📝</span>
            <span class="mode-card-title">Logger</span>
            <span class="mode-card-desc">Just the essentials for operating a contest — score, rate, time, and logging.</span>
          </button>
        </div>
      </div>`;
    document.body.appendChild(el);

    // Focus trap — same pattern as the splash overlay (app.js), keeps
    // Tab/Shift+Tab cycling within the chooser rather than walking into the
    // app chrome behind it.
    el.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const focusables = el.querySelectorAll('button, input');
      if (!focusables.length) return;
      const first = focusables[0], last = focusables[focusables.length-1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });

    function dismiss(){ el.style.opacity='0'; setTimeout(()=>el.remove(), 400); }

    el.querySelector('.mode-card[data-mode="analyzer"]').addEventListener('click', ()=>{
      dismiss();
      window.VKA.appMode='analyzer';
      try { localStorage.setItem(LAST_MODE_KEY,'analyzer'); } catch {}
      window.VKA.showDialog();
    });
    el.querySelector('.mode-card[data-mode="logger"]').addEventListener('click', ()=>{
      dismiss();
      window.VKA.appMode='logger';
      try { localStorage.setItem(LAST_MODE_KEY,'logger'); } catch {}
      applyLoggerModeVisibility(true);
      showResumeDialog();
    });

    el.querySelector('.mode-card--suggested')?.focus();
    if (!el.querySelector('.mode-card--suggested')) el.querySelector('.mode-card').focus();
  }

  // ── Sequencing with the one-time splash overlay (app.js) ─────────────────
  // The "already accepted" fast path returns synchronously inside app.js's
  // own IIFE, well before this script even starts loading — a
  // vka:splash-dismissed listener registered only after that point would
  // never see it fire. So that path is handled here directly via the same
  // localStorage check, not an event. The "first ever run" path IS handled
  // via the event, since its actual dismissal requires real user
  // interaction (clicking through the two-screen splash) that can't
  // possibly happen before this listener is registered.
  let splashAccepted=false;
  try { splashAccepted = localStorage.getItem('vkca_splash_accepted') === '1'; } catch {}
  if (splashAccepted) showModeChooser();
  else window.addEventListener('vka:splash-dismissed', showModeChooser, {once:true});
})();
