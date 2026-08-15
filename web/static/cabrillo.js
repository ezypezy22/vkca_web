/**
 * cabrillo.js — Cabrillo contest-log export dialog (Worked tab).
 * Standalone-modal pattern mirrors report-issue.js/tips.js.
 *
 * Exports the FULL log (not the Worked tab's current filter), including
 * dupes — a Cabrillo submission is expected to contain every logged
 * contact, not just what the operator claims as valid; the contest
 * sponsor's own cross-checking against every entrant's log is what
 * actually determines final validity, not the submitter's own dupe flag.
 */
;(function () {
  'use strict';

  const overlay = document.getElementById('cabrillo-dialog');
  const btnOpen = document.getElementById('worked-export-cabrillo-btn');
  if (!overlay || !btnOpen) return;

  function val(id) { return (document.getElementById(id)?.value || '').trim(); }

  function cabrilloMode(mode) {
    const m = (mode || '').toUpperCase();
    if (m === 'CW') return 'CW';
    if (m.includes('RTTY')) return 'RY';
    if (m === 'FM') return 'FM';
    if (m === 'LSB' || m === 'USB' || m === 'SSB' || m === 'PH') return 'PH';
    return m ? 'DG' : 'PH';
  }

  function qsoDateParts(iso) {
    const s = String(iso || '');
    return { date: s.slice(0, 10), time: s.slice(11, 13) + s.slice(14, 16) };
  }

  // The raw value captured from the log's own frequency column — for
  // N1MM's .s3db that's already kHz (e.g. 7168.8 for 40m), but other
  // loggers/exports store MHz instead. A real HF/VHF frequency in kHz is
  // always a few thousand or more; the same frequency in MHz is always
  // under a few hundred — so a single threshold correctly disambiguates
  // both conventions without needing to know which one a given log uses.
  function freqToKhz(freq) {
    const f = parseFloat(freq);
    if (isNaN(f) || f <= 0) return null;
    return Math.round(f < 500 ? f * 1000 : f);
  }

  function guessModeCategory(qsos) {
    const buckets = new Set(qsos.map(q => cabrilloMode(q.mode)));
    if (buckets.size !== 1) return 'MIXED';
    const only = [...buckets][0];
    return only === 'CW' ? 'CW' : only === 'RY' ? 'RTTY' : only === 'PH' ? 'SSB' : 'DIGI';
  }

  async function buildCabrilloText() {
    const qsos = await window.VKA.fetchQsos();
    const myCall   = val('cab-callsign').toUpperCase();
    const sentExch = val('cab-sent-exch');

    const header = ['START-OF-LOG: 3.0'];
    const push = (tag, v) => { if (v) header.push(`${tag}: ${v}`); };
    push('CONTEST', val('cab-contest-id'));
    push('CALLSIGN', myCall);
    push('CATEGORY-OPERATOR', val('cab-cat-operator'));
    push('CATEGORY-ASSISTED', val('cab-cat-assisted'));
    push('CATEGORY-BAND', val('cab-cat-band'));
    push('CATEGORY-MODE', val('cab-cat-mode'));
    push('CATEGORY-POWER', val('cab-cat-power'));
    push('CATEGORY-STATION', val('cab-cat-station'));
    push('CLAIMED-SCORE', val('cab-claimed-score'));
    push('CLUB', val('cab-club'));
    push('NAME', val('cab-name'));
    push('ADDRESS', val('cab-address'));
    push('ADDRESS-CITY', val('cab-city'));
    push('ADDRESS-STATE-PROVINCE', val('cab-state'));
    push('ADDRESS-POSTALCODE', val('cab-postal'));
    push('ADDRESS-COUNTRY', val('cab-country'));
    push('EMAIL', val('cab-email'));
    push('OPERATORS', val('cab-operators'));
    val('cab-soapbox').split('\n').forEach(line => { if (line.trim()) push('SOAPBOX', line.trim()); });

    let missingFreq = 0;
    const qsoLines = qsos
      .filter(q => q.call && q.time)
      .sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0)
      .map(q => {
        const { date, time } = qsoDateParts(q.time);
        const khz = freqToKhz(q.freq);
        if (khz == null) missingFreq++;
        // Falls back to a bare band designator (e.g. "40") when no real
        // frequency was ever captured — syntactically acceptable to most
        // Cabrillo checkers, but flagged via cab-freq-warning below so the
        // operator knows to double check before submitting.
        const freqTok = khz != null ? khz : String(q.band || '').replace(/CM$/i, '').replace(/M$/i, '');
        const mode  = cabrilloMode(q.mode);
        const rstS  = q.rst_sent || '599';
        const rstR  = q.rst_rcvd || '599';
        const exchR = q.mult1 || '';
        return `QSO: ${freqTok} ${mode} ${date} ${time} ${myCall} ${rstS} ${sentExch} ${q.call} ${rstR} ${exchR}`;
      });

    const warnEl = document.getElementById('cab-freq-warning');
    if (warnEl) {
      warnEl.textContent = missingFreq
        ? `⚠ ${missingFreq} QSO(s) had no recorded frequency — the band name was used instead of a kHz value on those lines. Check whether your contest sponsor accepts that, or fill it in manually before submitting.`
        : '';
    }

    return header.join('\n') + '\n' + qsoLines.join('\n') + '\nEND-OF-LOG:\n';
  }

  async function openDialog() {
    const meta = await fetch('/api/plugin_meta').then(r => r.json()).catch(() => ({}));
    const snap = window.VKA?.lastSnap?.() || {};
    const qsos = await window.VKA.fetchQsos().catch(() => []);

    document.getElementById('cab-contest-id').value    = meta.cabrillo_contest_id || '';
    document.getElementById('cab-callsign').value      = meta.my_call || '';
    document.getElementById('cab-claimed-score').value = snap.score != null ? String(snap.score) : '';
    document.getElementById('cab-cat-mode').value       = guessModeCategory(qsos);
    document.getElementById('cab-operators').value      =
      [...new Set(qsos.map(q => (q.operator || '').trim()).filter(Boolean))].join(' ');
    document.getElementById('cab-freq-warning').textContent = '';

    overlay.classList.remove('hidden');
  }
  function closeDialog() { overlay.classList.add('hidden'); }

  async function doDownload() {
    const text = await buildCabrilloText();
    const call = val('cab-callsign').toUpperCase().replace(/[^A-Z0-9]/g, '') || 'log';
    const blob = new Blob([text], { type: 'text/plain' });
    await window.VKA.downloadBlob(blob, `${call}.log`, '✓ Cabrillo Saved', '📄');
  }

  btnOpen.addEventListener('click', () => openDialog().catch(e => console.warn('Cabrillo dialog open failed:', e)));
  document.getElementById('btn-cabrillo-cancel')?.addEventListener('click', closeDialog);
  document.getElementById('btn-cabrillo-download')?.addEventListener('click',
    () => doDownload().catch(e => console.warn('Cabrillo export failed:', e)));
})();
