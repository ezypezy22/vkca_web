// tips.js — "Tips" dialog next to the Postcontest Report header: lists every
// entry from app.js's HELPER_TIPS (the same tips that rotate as corner-hint
// popups) in one scrollable list, so a user can browse them all on demand
// instead of waiting for the 30-minute rotation. Standalone-modal pattern
// mirrors report-issue.js/settings.js.
(function () {
  const overlay = document.getElementById('tips-dialog');
  const btnOpen = document.getElementById('btn-tips');
  if (!overlay || !btnOpen) return;

  const list = document.getElementById('tip-list');

  function renderTips() {
    const tips = window.VKA?.helperTips || [];
    list.innerHTML = tips.map(t => `
      <div class="tip-row">
        <div class="tip-row-icon">&#128161;</div>
        <div class="tip-row-body">
          <div class="tip-row-title">${t.title}</div>
          <div class="tip-row-text">${t.body}</div>
        </div>
      </div>`).join('');
  }

  function openDialog() {
    renderTips();
    overlay.classList.remove('hidden');
  }
  function closeDialog() { overlay.classList.add('hidden'); }

  btnOpen.addEventListener('click', openDialog);
  document.getElementById('btn-tips-close')?.addEventListener('click', closeDialog);
})();
