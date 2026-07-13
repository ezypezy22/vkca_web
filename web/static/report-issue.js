// report-issue.js — "Report Issue / Request Feature" dialog.
// Web equivalent of the desktop app's Help → Report Issue dialog: composes a
// structured GitHub issue (bug report or feature request), optionally with
// an AI-polish round-trip and a diagnostics block, then opens a pre-filled
// GitHub "New Issue" URL.
(function () {
  const GITHUB_REPO = 'ezypezy22/vkca_web';
  const VERSION      = '26.7.11';

  const overlay   = document.getElementById('report-issue-dialog');
  const btnOpen   = document.getElementById('btn-report-issue');
  if (!overlay || !btnOpen) return;

  const fieldsWrap  = document.getElementById('report-issue-fields');
  const titleInput  = document.getElementById('report-issue-title');
  const overrideBox = document.getElementById('report-issue-override');
  const diagCheck   = document.getElementById('report-issue-diag');
  const kindRadios  = () => Array.from(document.querySelectorAll('input[name="report-issue-kind"]'));

  function currentKind() {
    const checked = kindRadios().find(r => r.checked);
    return checked ? checked.value : 'bug';
  }

  // ── Type-specific field templates ─────────────────────────────────────────
  const BUG_FIELDS_HTML = `
    <div class="dialog-section-label">Report preparation</div>
    <label class="dialog-check"><input type="checkbox" id="ri-attached"> I have attached a support bundle or log file (attach manually after the issue opens)</label>
    <div class="dialog-section-label">What happened?</div>
    <textarea id="ri-what-happened" class="dialog-textarea" rows="3"></textarea>
    <div class="dialog-section-label">What did you expect?</div>
    <textarea id="ri-expected" class="dialog-textarea" rows="2"></textarea>
    <div class="dialog-section-label">Steps to reproduce</div>
    <textarea id="ri-steps" class="dialog-textarea" rows="3"></textarea>
  `;
  const FEATURE_FIELDS_HTML = `
    <div class="dialog-section-label">Request preparation</div>
    <label class="dialog-check"><input type="checkbox" id="ri-checked-existing"> I checked for existing issues covering the same feature</label>
    <div class="dialog-section-label">What would you like?</div>
    <textarea id="ri-what" class="dialog-textarea" rows="6"></textarea>
  `;

  function renderFields() {
    fieldsWrap.innerHTML = currentKind() === 'feature' ? FEATURE_FIELDS_HTML : BUG_FIELDS_HTML;
  }

  kindRadios().forEach(r => r.addEventListener('change', renderFields));

  // ── Body composition (mirrors the desktop app's _compose_*_body) ───────────
  function textVal(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
  }

  function composeFeatureBody() {
    const checkedExisting = document.getElementById('ri-checked-existing')?.checked;
    const what = textVal('ri-what');
    return [
      '### Request preparation',
      `- [${checkedExisting ? 'x' : ' '}] I checked for existing issues covering the same feature`,
      '',
      '### What would you like?',
      what || "_(describe the feature you'd like)_",
    ].join('\n');
  }

  function composeBugBody() {
    const attached = document.getElementById('ri-attached')?.checked;
    return [
      '### Report preparation',
      `- [${attached ? 'x' : ' '}] I have attached a support bundle or log file`,
      '',
      '### What happened?',
      textVal('ri-what-happened') || '_(describe what happened)_',
      '',
      '### What did you expect?',
      textVal('ri-expected') || '_(describe what you expected to happen)_',
      '',
      '### Steps to reproduce',
      textVal('ri-steps') || '_(n/a)_',
      '',
      '### VK Contest Analyzer version',
      VERSION,
    ].join('\n');
  }

  // "TITLE: ..." on the first line overrides the title field, same convention
  // as the desktop app's AI-polish round-trip.
  function extractAiTitleAndBody(raw) {
    const text = (raw || '').trim();
    const m = text.match(/^TITLE:\s*(.+?)\s*\n+([\s\S]*)$/i);
    if (m) return { title: m[1].trim(), body: m[2].trim() };
    return { title: null, body: text };
  }

  function composeReportBody() {
    const override = overrideBox.value.trim();
    if (override) return extractAiTitleAndBody(override).body;
    return currentKind() === 'feature' ? composeFeatureBody() : composeBugBody();
  }

  // ── Diagnostics block ───────────────────────────────────────────────────────
  async function buildDiagnosticBlock() {
    const lines = [`- App version: ${VERSION}`, `- Browser: ${navigator.userAgent}`];
    let theme = 'unknown';
    try { theme = localStorage.getItem('vkca_theme') || 'unknown'; } catch {}
    lines.push(`- Theme: ${theme}`);
    try {
      const res  = await fetch('/api/status');
      const data = await res.json();
      lines.push(data.loaded ? `- Active plugin: ${data.plugin || 'unknown'}` : '- No log loaded at time of report');
    } catch {
      lines.push('- Could not read app status');
    }
    return lines.join('\n');
  }

  // ── AI-polish prompt (copy to clipboard) ────────────────────────────────────
  async function copyAiPrompt() {
    const kind      = currentKind();
    const kindLabel = kind === 'feature' ? 'feature request' : 'bug report';
    const title     = titleInput.value.trim();

    let notes, templateHint;
    if (kind === 'feature') {
      notes = textVal('ri-what');
      templateHint = "Structure the body with a '### What would you like?' section.";
    } else {
      const parts = [];
      const whatHappened = textVal('ri-what-happened');
      const expected     = textVal('ri-expected');
      const steps        = textVal('ri-steps');
      if (whatHappened) parts.push(`What happened: ${whatHappened}`);
      if (expected)     parts.push(`What did you expect: ${expected}`);
      if (steps)        parts.push(`Steps to reproduce: ${steps}`);
      notes = parts.join('\n');
      templateHint = "Structure the body with these sections, in this order: " +
        "'### What happened?', '### What did you expect?', '### Steps to reproduce'.";
    }
    if (!notes) notes = "(no details yet — please describe what happened or what you'd like)";

    let prompt = `I'm using VK Contest Analyzer, a real-time companion app for ham radio ` +
      `contest logging (works alongside N1MM Logger+). I want to file a ${kindLabel} on its ` +
      `GitHub repo (https://github.com/${GITHUB_REPO}).\n\n` +
      `Please turn my rough notes below into a clear, well-written GitHub issue.\n` +
      `Reply with a short, specific title on the first line, prefixed exactly 'TITLE: ', ` +
      `then a blank line, then the issue body in Markdown. ${templateHint}\n` +
      `Do NOT add a 'Report/Request preparation' checklist or a diagnostics/system-info ` +
      `section — the app adds those automatically. Do not invent details I haven't given you.\n\n` +
      `--- MY ROUGH NOTES ---\n`;
    if (title) prompt += `Working title: ${title}\n\n`;
    prompt += notes + '\n--- END NOTES ---';

    try {
      await navigator.clipboard.writeText(prompt);
      window.VKA?.showToast?.('Prompt copied',
        "Paste it into Claude/ChatGPT, then paste the reply into the override box below.", '📋');
    } catch (e) {
      window.VKA?.showToast?.('Copy failed', e.message, '✗', true);
    }
  }

  // ── Submit: open a pre-filled GitHub issue ──────────────────────────────────
  const MAX_BODY = 3500;

  async function submitGithubIssue() {
    const override = overrideBox.value.trim();
    const aiTitle   = override ? extractAiTitleAndBody(override).title : null;
    const title     = titleInput.value.trim() || aiTitle || '';

    if (!title) {
      window.VKA?.showToast?.('Title needed',
        "Enter a title (or paste an AI reply starting with 'TITLE: ...') before opening the GitHub issue.",
        '✗', true);
      titleInput.focus();
      return;
    }

    let body = composeReportBody();
    if (diagCheck.checked) {
      body += '\n\n---\n\n**Diagnostics**\n\n' + await buildDiagnosticBlock();
    }
    if (body.length > MAX_BODY) {
      body = body.slice(0, MAX_BODY) +
        '\n\n…(truncated — please trim before submitting, or add extra detail after the issue is created)';
    }

    const label  = currentKind() === 'feature' ? 'enhancement' : 'bug';
    const params = new URLSearchParams({ title, body, labels: label });
    window.VKA.openExternal(`https://github.com/${GITHUB_REPO}/issues/new?${params.toString()}`);
  }

  // ── Open / close ─────────────────────────────────────────────────────────
  function openDialog() {
    kindRadios().forEach(r => { r.checked = r.value === 'bug'; });
    renderFields();
    titleInput.value = '';
    overrideBox.value = '';
    diagCheck.checked = true;
    overlay.classList.remove('hidden');
    setTimeout(() => titleInput?.focus(), 50);
  }
  function closeDialog() { overlay.classList.add('hidden'); }

  btnOpen.addEventListener('click', openDialog);
  document.getElementById('btn-report-cancel')?.addEventListener('click', closeDialog);
  document.getElementById('btn-report-submit')?.addEventListener('click', submitGithubIssue);
  document.getElementById('btn-report-copy-prompt')?.addEventListener('click', copyAiPrompt);
  document.getElementById('btn-report-open-claude')?.addEventListener('click',
    () => window.VKA.openExternal('https://claude.ai/new'));
  document.getElementById('btn-report-open-chatgpt')?.addEventListener('click',
    () => window.VKA.openExternal('https://chat.openai.com/'));
})();
