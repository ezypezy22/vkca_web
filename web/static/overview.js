/**
 * overview.js v7 — CORRECT gauge geometry verified by coordinate math:
 *
 * canvas y-DOWN: 0°=3-o'clock, 90°=6-o'clock, 270°=12-o'clock
 * Desired: C-shape opening at bottom, arc goes over the top
 *   Start = 30° (5-o'clock, lower-right)  cos=+0.87, sin=+0.50 ✓ lower-right
 *   End   = 150° (7-o'clock, lower-left)  cos=-0.87, sin=+0.50 ✓ lower-left
 *   Direction: CCW (anticlockwise=true) from 30° to 150° = 240° over the top ✓
 *
 * Fill: CCW from 30°, so fillEnd = 30° - frac*240°
 *   frac=0:   fillEnd=30°   (no fill, starts at lower-right)
 *   frac=0.5: fillEnd=-90°=270° (top of arc, half full) ✓
 *   frac=1:   fillEnd=-210°=150° (lower-left, full) ✓
 */
;(function () {
  'use strict';

  const escapeHtml = window.VKA.escapeHtml;

  // ── Theme-aware colour state (updated by applyTheme) ─────────────────────
  let T = {
    accent:'#00d4aa', accent2:'#ff6b35', accent3:'#f0c040',
    green:'#2ed573',  red:'#ff4757',     muted:'#8b949e',
    bg:'#0d1117',     bg2:'#161b22',     bg3:'#21262d',    fg:'#e6edf3',
  };
  // Independent copy (not a shared reference) — onTheme() below mutates this
  // per-tab for colorblind-safe palettes, and that mutation must not leak
  // into every other tab's band colors via the shared window.VKA.BAND_COLS object.
  let BAND_COLS = { ...window.VKA.BAND_COLS };
  let STATE_COLS = {
    NSW:'#00d4aa',QLD:'#f0c040',VIC:'#64b5f6',SA:'#ff6b35',
    WA:'#e040fb', TAS:'#2ed573',NT:'#ff5252',ACT:'#ffab40',
  };

  function onTheme(palette) {
    if (!palette) return;
    T = { ...T,
      accent:palette.accent, accent2:palette.accent2, accent3:palette.accent3,
      green:palette.green, red:palette.red, muted:palette.muted,
      bg:palette.bg, bg2:palette.bg2, bg3:palette.bg3, fg:palette.fg,
    };
    if (palette.band_colours) {
      Object.keys(palette.band_colours).forEach(k => {
        BAND_COLS[k.toUpperCase()] = palette.band_colours[k];
      });
    }
    if (palette.state_colours) {
      Object.keys(palette.state_colours).forEach(k => {
        STATE_COLS[k.toUpperCase()] = palette.state_colours[k];
      });
    }
    Chart.defaults.color = T.muted;
    // Rebuild charts that exist
    if (regionChart) { regionChart.destroy(); regionChart = null; }
    // bandDonutChart's per-tick update (updateBandDonut()) intentionally
    // skips a full rebuild when the set of worked bands hasn't changed,
    // to stop it re-animating on every snapshot poll — but that fast path
    // only refreshes slice values/colours, not the chart's borderColor or
    // legend text colour baked in at creation time. Without forcing a
    // rebuild here, a theme switch leaves the donut's slice borders and
    // legend stuck on the *previous* theme's colours (e.g. near-black
    // dividers surviving into Light theme) even though every other panel
    // switches instantly.
    if (bandDonutChart) { bandDonutChart.destroy(); bandDonutChart = null; _bandDonutShape=''; }
    applyGlowMapTheme();
    if (_snap) render(_snap);
    redrawAll();
  }

  window.VKA = window.VKA || {};
  window.VKA.onTheme = onTheme;

  Chart.defaults.color       = T.muted;
  Chart.defaults.font.family = 'Consolas, monospace';

  // ══ GAUGE GEOMETRY (VERIFIED) ════════════════════════════════════════════════
  // Convert Python matplotlib (CCW, y-UP) angles to canvas (CW, y-DOWN):
  //   ts=210° CCW y-up  →  canvas -210° = 150° CW y-down
  //   te=-30° CCW y-up  →  canvas  +30° = 30°  CW y-down
  // Track: CW (anticlockwise=false) from 150° to 30° = 240° over the top ✓
  // Fill:  CW from 150°, adding angle: fillEnd = 150° + frac*240°
  //   frac=0:   150° (lower-left,  7-o'clock) — tip starts LEFT  ✓
  //   frac=0.5: 270° (top,         12-o'clock) — halfway          ✓
  //   frac=1:    30° (lower-right,  5-o'clock) — tip ends RIGHT   ✓
  const DEG     = Math.PI / 180;
  const G_START = 150 * DEG;   // 7-o'clock (lower-left)  — fill start, "0" label
  const G_END   = 30  * DEG;   // 5-o'clock (lower-right) — fill end,   "max" label
  const G_SWEEP = 240 * DEG;   // CW sweep over the top

  function polarXY(cx, cy, r, a) {
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  }

  function fmtVal(v, fmt) {
    if (!fmt || fmt === '{v}')  return Math.round(v||0).toLocaleString('en-AU');
    if (fmt.includes(':,'))      return Math.round(v||0).toLocaleString('en-AU');
    const m = fmt.match(/\{v:\.(\d+)f\}/);
    if (m) return (v||0).toFixed(parseInt(m[1]));
    return String(Math.round(v||0));
  }

  function fmtMax(n) {
    n = Math.round(n||0);
    if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
    if (n >= 1e3) return (n/1e3).toFixed(0)+'k';
    return n.toLocaleString();
  }

  function drawGauge(canvas, frac, colour, valStr, label, maxStr, fs) {
    const dpr = window.devicePixelRatio || 1;
    const w   = canvas.clientWidth;
    const h   = canvas.clientHeight;
    if (!w || !h) return;
    canvas.width  = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const cx  = w / 2;
    const cy  = h * 0.50;
    const ro  = Math.min(w, h) * 0.46;
    const ri  = ro * 0.70;
    const mid = (ro + ri) / 2;
    const lw  = ro - ri;

    // ── Track: CW (anticlockwise=false) from G_START(150°) to G_END(30°) = 240° over top
    ctx.beginPath();
    ctx.arc(cx, cy, mid, G_START, G_END, false);
    ctx.strokeStyle = T.bg3;
    ctx.lineWidth   = lw;
    ctx.lineCap     = 'butt';
    ctx.stroke();

    // ── Fill: CW from 150°, add frac*240° (tip moves left→right) — glowing
    if (frac > 0.001) {
      const fillEnd = G_START + Math.min(frac, 1) * G_SWEEP;
      ctx.save();
      // Clip the glow to the ring itself (r >= ri) so its blur can't bleed
      // inward onto the value text — barely visible on dark backgrounds but
      // shows as fuzzy digit edges against a light card background.
      ctx.beginPath();
      ctx.rect(0, 0, w, h);
      ctx.arc(cx, cy, ri, 0, Math.PI * 2, true);
      ctx.clip('evenodd');
      ctx.shadowColor = colour;
      ctx.shadowBlur  = Math.max(5, lw * 0.4);
      ctx.beginPath();
      ctx.arc(cx, cy, mid, G_START, fillEnd, false);
      ctx.strokeStyle = colour;
      ctx.lineWidth   = lw;
      ctx.lineCap     = 'round';
      ctx.stroke();

      // White tip dot (glowing)
      const [tx, ty] = polarXY(cx, cy, mid, fillEnd);
      ctx.beginPath();
      ctx.arc(tx, ty, Math.max(3.5, lw*0.30), 0, Math.PI*2);
      ctx.fillStyle = '#ffffff';
      ctx.shadowBlur = Math.max(5, lw * 0.4);
      ctx.fill();
      ctx.restore();
    }

    // ── Tick marks at 0/25/50/75/100% (CCW = subtract)
    [0, 0.25, 0.5, 0.75, 1.0].forEach(tf => {
      const ta = G_START + tf * G_SWEEP;
      const [x1,y1] = polarXY(cx, cy, ri*0.88, ta);
      const [x2,y2] = polarXY(cx, cy, ri*1.00, ta);
      ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2);
      ctx.strokeStyle=T.muted; ctx.lineWidth=1.5; ctx.lineCap='butt'; ctx.stroke();
    });

    // ── Value + label
    // Font sizes scale off the gauge's own rendered radius (ri) so text stays
    // legible whether there are 3 wide gauges or 8 narrow ones on the row —
    // a fixed pixel size (the old `fs * const` approach) looked fine at one
    // tile width and tiny at another. `fs`/15 (from the zoom slider, default
    // ~1.07) still scales everything up/down around that responsive baseline.
    //
    // These are real DOM elements, not ctx.fillText. WebKitGTK's Cairo/Pango
    // text path defaults to LCD/subpixel antialiasing, which visibly fringes
    // (red/green channel split) on saturated coloured text — confirmed via
    // an isolated pywebview repro to be unrelated to canvas/compositing and
    // present even on plain DOM text, just far less noticeable at the sizes
    // used elsewhere in the UI. The `-webkit-font-smoothing:antialiased` on
    // <body> (style.css) is the actual fix (forces grayscale AA); these are
    // still DOM elements rather than ctx.fillText mainly so that CSS rule is
    // guaranteed to apply — it's a text-layout property, not guaranteed to
    // reach into a canvas's internal text rasterizer.
    const snap = v => Math.round(v * dpr) / dpr;
    const zoomMult = fs / 15;
    const sf    = valStr.length > 7 ? (7/valStr.length) : valStr.length > 5 ? 0.88 : 1.0;
    const valFs = Math.max(12, ri * 0.30 * sf * zoomMult);
    const labelFs = Math.max(8, ri * 0.17 * zoomMult);
    const idx = canvas.id.replace('gauge-','');
    const valEl = document.getElementById(`gauge-val-${idx}`);
    const lblEl = document.getElementById(`gauge-lbl-${idx}`);
    if (valEl) {
      valEl.textContent = valStr;
      valEl.style.color = colour;
      valEl.style.fontSize = `${valFs}px`;
      valEl.style.top  = `${cy - ri*0.05 - valFs*0.55}px`;
    }
    if (lblEl) {
      lblEl.style.fontSize = `${labelFs}px`;
      lblEl.style.top  = `${cy + ri*0.33 - labelFs*0.55}px`;
    }

    // ── 0 at G_START (150°=lower-left), max at G_END (30°=lower-right)
    const endFs = Math.round(Math.max(7, ri * 0.15 * zoomMult));
    const [x0,y0] = polarXY(cx, cy, ro*1.10, G_START);
    const [xm,ym] = polarXY(cx, cy, ro*1.10, G_END);
    ctx.fillStyle=T.muted; ctx.font=`${endFs}px Consolas, monospace`; ctx.textAlign='center';
    ctx.fillText('0', snap(x0), snap(y0));
    ctx.fillText(maxStr, snap(xm), snap(ym));
  }

  // ══ PLUGIN-DRIVEN GAUGES ═══════════════════════════════════════════════════
  let _gaugeDefs=[], _gaugeState={}, _snap=null, _fs=15, _metaLoaded=false, _usesCqZoneScoring=false, _whatifBands=[], _hasFixedMultList=true;

  const _tip = document.createElement('div');
  _tip.style.cssText=`position:fixed;display:none;pointer-events:none;z-index:9999;
    background:var(--bg2);border:1px solid var(--accent);border-radius:6px;padding:10px 14px;
    font-family:Consolas,monospace;font-size:11px;color:var(--fg);max-width:300px;
    line-height:1.7;white-space:pre-wrap;box-shadow:0 8px 24px rgba(0,0,0,.35);`;
  document.body.appendChild(_tip);
  function showTip(t,x,y){_tip.textContent=t;_tip.style.display='block';
    const tw=_tip.offsetWidth,th=_tip.offsetHeight,vw=window.innerWidth,vh=window.innerHeight;
    _tip.style.left=Math.min(x+14,vw-tw-10)+'px'; _tip.style.top=Math.max(10,Math.min(y-th/2,vh-th-10))+'px';}
  function hideTip(){_tip.style.display='none';}

  async function loadPluginMeta() {
    try {
      const res=await fetch('/api/plugin_meta'); const meta=await res.json();
      if (!meta.loaded) return;
      _metaLoaded=true; _gaugeDefs=meta.gauge_defs||[]; _usesCqZoneScoring=!!meta.uses_cq_zone_scoring;
      _whatifBands = meta.bands || [];
      // has_missing_tab doubles as "this contest has a fixed, enumerable mult
      // list" (see the whatifSupported comment below) — for open-ended mult
      // contests (WPX prefixes, WAE countries, etc.) there's no fixed universe
      // to measure "missing" against, so mult-efficiency-style stats using
      // worked/(worked+missing) are meaningless here (missing is always 0).
      _hasFixedMultList = meta.has_missing_tab !== false;
      setTabVisible('missing', meta.has_missing_tab!==false);
      // Standalone logging mode only (see index.html's tab-btn comment) —
      // hidden for every ordinary opened-from-N1MM log, the common case.
      setTabVisible('logentry', !!meta.is_standalone_log);
      // "What if?" simulates working a MISSING mult, so it's only meaningful
      // for contests with a fixed, enumerable mult list (has_missing_tab) —
      // for open-ended ones (e.g. WPX prefixes) there's nothing to list, so
      // the mult dropdown would come back empty while the band dropdown
      // still looked populated, a dead-end control. Hide it entirely.
      const whatifSupported = meta.has_missing_tab!==false;
      if (whatifToggleBtn) whatifToggleBtn.style.display = whatifSupported ? '' : 'none';
      // Every (re)load of plugin meta means a contest was just loaded/switched
      // — the bar's mult/band options and last result belong to whatever was
      // loaded before, so always reset and close it rather than leaving stale
      // choices (e.g. another contest's shire codes) sitting in the dropdowns.
      resetWhatif();
      closeWhatif();
      const br=document.getElementById('bars-row');
      if (br) br.style.display=meta.has_state_bars?'':'none';
      buildGaugeRow(_gaugeDefs);
      if (_snap) updateGauges(_snap);
    } catch(e){ console.warn('plugin_meta:',e); }
  }

  function setTabVisible(id,v){const b=document.querySelector(`.tab-btn[data-tab="${id}"]`);if(b)b.style.display=v?'':'none';}

  function buildGaugeRow(defs) {
    const row=document.getElementById('gauge-row'); if(!row) return;
    row.innerHTML='';
    row.style.gridTemplateColumns=`repeat(${defs.length},1fr)`;
    _gaugeState={};
    defs.forEach((g,i)=>{
      const card=document.createElement('div'); card.className='gauge-card';
      card.dataset.tileKey=(g.label||('gauge'+i)).toLowerCase().replace(/[^a-z0-9]+/g,'-');
      const canvas=document.createElement('canvas'); canvas.id=`gauge-${i}`;
      card.appendChild(canvas);
      // Value/label are real DOM text, not canvas fillText — WebKitGTK's
      // Cairo/Pango text rasterizer applies LCD/subpixel antialiasing to
      // canvas text that assumes an opaque known background, and on the
      // canvas's transparent backing store that decomposes into visible
      // red/green channel fringing on saturated colours (invisible on the
      // muted-gray label, which is why only the value looked "off"). DOM
      // text goes through the normal compositor path and renders clean,
      // matching every other coloured number elsewhere in the UI.
      const valEl=document.createElement('div'); valEl.className='gauge-value'; valEl.id=`gauge-val-${i}`;
      const lblEl=document.createElement('div'); lblEl.className='gauge-label'; lblEl.id=`gauge-lbl-${i}`;
      lblEl.textContent=g.label||'';
      card.appendChild(valEl); card.appendChild(lblEl);
      row.appendChild(card);
      _gaugeState[i]={cur:0,curVal:0,raf:null};
      if (g.tooltip){
        card.addEventListener('mousemove',e=>showTip(g.tooltip,e.clientX,e.clientY));
        card.addEventListener('mouseleave',hideTip);
        card.style.cursor='help';
      }
    });
    Array.from(row.children).forEach(addPopoutButton);
    markDraggable(row);
    applyTileOrder(row,'vkca_layout_gauge');
    setupReorder(row,'vkca_layout_gauge');
    applyPopoutFilter();
    setTimeout(redrawAll,50);
  }

  function updateGauges(snap) {
    if (!snap) return; _snap=snap;
    if (!_metaLoaded){loadPluginMeta();return;}
    _gaugeDefs.forEach((g,i)=>{
      const val=snap[g.value_key]??0, maxVal=Number(g.max_val)||1;
      animGauge(i,g,val,maxVal,Math.max(0,Math.min(1,val/maxVal)));
    });
  }

  function animGauge(idx,gDef,val,maxVal,target){
    const st=_gaugeState[idx]; if(!st) return;
    const t0=performance.now(),s0=st.cur,sVal0=st.curVal??0;
    if(st.raf) cancelAnimationFrame(st.raf);
    function step(now){
      const t=Math.min((now-t0)/700,1);
      const eased=1-Math.pow(1-t,3);
      st.cur=s0+(target-s0)*eased;
      // Tweens the raw value in lockstep with the arc rather than reusing
      // the arc's own (clamped-to-1) fraction — a gauge whose value has
      // overshot its nominal max (frac pinned at 1) would otherwise have
      // its number stuck at maxVal instead of counting up past it.
      st.curVal=sVal0+(val-sVal0)*eased;
      redrawGauge(idx,gDef,st.cur,st.curVal,maxVal);
      if(t<1) st.raf=requestAnimationFrame(step);
      else{st.cur=target;st.curVal=val;st.raf=null;}
    }
    st.raf=requestAnimationFrame(step);
  }

  function redrawGauge(idx,gDef,frac,val,maxVal){
    const canvas=document.getElementById(`gauge-${idx}`); if(!canvas) return;
    drawGauge(canvas,frac,gDef.colour||T.accent,fmtVal(val,gDef.fmt),gDef.label,fmtMax(maxVal),_fs);
  }

  function redrawAll(){
    if(!_snap||!_metaLoaded) return;
    _gaugeDefs.forEach((g,i)=>{
      const val=_snap[g.value_key]??0,maxVal=Number(g.max_val)||1;
      redrawGauge(i,g,_gaugeState[i]?.cur??0,val,maxVal);
    });
  }

  window.VKA.setZoom=pct=>{_fs=15*(pct/100);redrawAll();};
  window.addEventListener('resize',redrawAll);

  // ══ SPARKLINES ═════════════════════════════════════════════════════════════
  // UTC start hour of the current contest — used by the x-axis tick callback
  // to show real UTC hours (e.g. "00z", "06z") rather than bucket indices.
  let _sparkStartUTC = 0;
  let _sparks={};

  function makeSparkline(id,colour){
    const canvas=document.getElementById(id); if(!canvas) return null;
    canvas.style.filter=`drop-shadow(0 0 4px ${colour}80)`;
    const ctx=canvas.getContext('2d');
    const grad=ctx.createLinearGradient(0,0,0,100);
    grad.addColorStop(0,   colour+'59');
    grad.addColorStop(0.65,colour+'14');
    grad.addColorStop(1,   colour+'00');
    return new Chart(ctx,{type:'line',
      data:{labels:[],datasets:[{data:[],borderColor:colour,borderWidth:2.5,
        backgroundColor:grad,fill:true,tension:0,cubicInterpolationMode:'monotone',
        borderCapStyle:'round',borderJoinStyle:'round',
        pointRadius:0,pointHoverRadius:5,pointHoverBackgroundColor:colour,
        pointHoverBorderColor:'#fff',pointHoverBorderWidth:2}]},
      options:{responsive:true,maintainAspectRatio:false,animation:{duration:400},
        interaction:{mode:'index',intersect:false},
        layout:{padding:{bottom:2}},
        plugins:{legend:{display:false},
          tooltip:{mode:'index',intersect:false,backgroundColor:T.bg3,
            borderColor:colour,borderWidth:1,titleColor:colour,bodyColor:T.fg,
            displayColors:false,padding:8,
            callbacks:{title:items=>{
              // Show actual UTC hour in tooltip title
              const h=(_sparkStartUTC+items[0].dataIndex)%24;
              return String(h).padStart(2,'0')+':00 UTC';
            }}}},
        scales:{
          x:{
            display:true,
            grid:{display:false},
            border:{display:false},
            ticks:{
              color:T.muted+'aa',
              font:{size:8,family:'Consolas,monospace'},
              maxTicksLimit:5,
              maxRotation:0,
              autoSkip:true,
              // Convert bucket index → "HHz" UTC label
              callback:(val,i)=>{
                const h=(_sparkStartUTC+i)%24;
                return String(h).padStart(2,'0')+'z';
              },
            },
          },
          y:{display:false,beginAtZero:true},
        }},
    });
  }

  function initSparklines(){
    _sparks={
      qsos: makeSparkline('spark-qsos',T.accent),
      score:makeSparkline('spark-score',T.accent3),
      mults:makeSparkline('spark-mults',T.accent2),
    };
  }
  initSparklines();

  function updateSparklines(snap){
    const sl=snap?.sparklines; if(!sl) return;

    // Extract contest start UTC hour for the x-axis labels.
    // start_dt comes back as an ISO string like "2024-07-20T00:00:00" (naive UTC).
    const startDt=snap?.session_status?.start_dt;
    if(startDt) {
      // Parse the hour directly from the ISO string — avoids local-timezone
      // ambiguity that new Date() would introduce on the user's machine.
      const hStr=String(startDt).substring(11,13);
      const parsed=parseInt(hStr,10);
      if(!isNaN(parsed)) _sparkStartUTC=parsed;
    }

    function apply(chart,data,heroId){
      if(!chart||!data?.length) return;
      chart.data.labels=data.map((_,i)=>i);
      chart.data.datasets[0].data=data;
      const peak=Math.max(...data,0),pi=data.lastIndexOf(peak);
      chart.data.datasets[0].pointRadius=data.map((_,i)=>i===pi?4:0);
      chart.data.datasets[0].pointBackgroundColor=
        data.map((_,i)=>i===pi?chart.data.datasets[0].borderColor:'transparent');
      chart.data.datasets[0].pointBorderColor=
        data.map((_,i)=>i===pi?'#fff':'transparent');
      chart.data.datasets[0].pointBorderWidth=
        data.map((_,i)=>i===pi?2:0);
      chart.update();
      const last=[...data].reverse().find(v=>v>0)||0;
      animateNumber(heroId,last);
    }
    apply(_sparks.qsos, sl.qsos,'sp-qsos-val');
    apply(_sparks.score,sl.running_score,'sp-score-val');
    apply(_sparks.mults,sl.new_mults,'sp-mults-val');
  }

  // ══ CONTEST TIME PANEL ═════════════════════════════════════════════════════
  function updateContestTime(snap){
    const el=document.getElementById('panel-contest-time'); if(!el) return;
    const ss=snap?.session_status||{}, sc=snap?.score||0;
    const state=ss.state||'';
    const col=state==='live'?T.accent:state==='over'?T.muted:T.accent3;
    const uses_blocks=snap?._uses_block_structure??false;
    const title=uses_blocks?'[ B ] BLOCK STATUS':'[ T ] CONTEST TIME';

    let body='';
    if (state==='over') {
      body=`<div class="ct-label" style="color:${T.accent3}">FINAL SCORE</div>
        <div class="ct-score" style="color:${T.accent3}">${(sc||0).toLocaleString('en-AU')}</div>
        <div class="ct-sub">${snap?.valid||0} Q × ${snap?.band_mults||snap?.worked||0} mults</div>
        <div class="ct-info" style="color:${T.muted}">Best rate: ${snap?.personal_bests?.best_hour_rate||0} Q/hr @ ${String(snap?.personal_bests?.best_hour_time||'').substring(11,16)||'—'} UTC</div>
        <div class="ct-info" style="color:${T.red}">Dupes: ${(snap?.total||0)-(snap?.valid||0)}</div>
        <div class="ct-info" style="color:${T.muted}">${ss.end_dt?String(ss.end_dt).substring(0,16)+' UTC':''}</div>`;
    } else if (state==='live') {
      const rem=Math.round(ss.total_remaining_mins??ss.remaining_mins??0);
      const pct=((ss.total_pct_elapsed??ss.pct_elapsed)||0).toFixed(0);
      const valid=snap?.valid||0;
      // Same "extrapolate current pace over remaining time" formula the
      // Pace tab's own projected-score KPI uses (see pace.js's
      // updateKPIs) — reusing it here rather than a different method (e.g.
      // straight-line from % elapsed) so the two tabs never show two
      // different "projected final score" numbers for the same contest.
      let projLine='';
      if (rem>0 && valid>0){
        const curRate=snap?.personal_bests?.current_hour_rate||0;
        const projQsos=valid+curRate*(rem/60);
        const projScore=Math.round((sc/valid)*projQsos);
        projLine=`<div class="ct-info" style="color:${T.muted}">Projected final: ~${projScore.toLocaleString('en-AU')} pts at current pace</div>`;
      }
      body=`<div class="ct-label">${ss.session_label||''}</div>
        <div class="ct-prog-wrap"><div class="ct-prog-bar" style="width:${pct}%;background:${col}55;border-right:2px solid ${col}"></div></div>
        <div class="ct-sub" style="color:${col}">${rem}m remaining · ${pct}%</div>
        <div class="ct-score" style="color:${T.accent}">${(sc||0).toLocaleString('en-AU')}</div>
        <div class="ct-sub">${valid} Q × ${snap?.band_mults||snap?.worked||0} mults</div>
        ${projLine}`;
    } else if (state==='pre') {
      // Log is loaded and may already have test/early QSOs, but the
      // contest's scheduled start (per the plugin's start_hour) hasn't
      // arrived yet — show a countdown instead of implying nothing's loaded.
      const mins=Math.round(ss.mins_to_start??0);
      const h=Math.floor(mins/60), m=mins%60;
      body=`<div class="ct-label" style="color:${T.accent3}">${ss.session_label||'Pre-Contest'}</div>
        <div class="ct-sub" style="color:${T.accent3}">Starts in ${h}h ${String(m).padStart(2,'0')}m</div>
        <div class="ct-info" style="color:${T.muted}">${ss.start_dt?String(ss.start_dt).substring(0,16)+' UTC':''}</div>
        ${snap?.total ? `<div class="ct-info" style="color:${T.muted}">${snap.total} test QSO${snap.total===1?'':'s'} logged so far</div>` : ''}`;
    } else {
      body=`<div class="ct-sub" style="color:${T.muted}">No contest loaded</div>`;
    }

    el.innerHTML=`<div class="ip-hdr"><span style="color:${col}">[ T ]</span>
      <span class="ip-title" style="color:${col}">${title.replace(/\[.\] /,'')}</span></div>${body}`;
  }

  // ══ REGION BARS ════════════════════════════════════════════════════════════
  let regionChart=null;
  function updateRegionBars(snap){
    const heat=snap?.region_heat; if(!heat?.length) return;
    const br=document.getElementById('bars-row'); if(br?.style.display==='none') return;
    const labels=heat.map(r=>r.state||r.region||'?');
    const worked=heat.map(r=>r.worked||0);
    const total=heat.map(r=>r.total||0);
    const missing=heat.map(r=>Math.max(0,(r.total||0)-(r.worked||0)));
    const colours=labels.map(s=>STATE_COLS[s]||T.muted);
    const canvas=document.getElementById('chart-region-bars'); if(!canvas) return;
    if(regionChart){
      regionChart.data.labels=labels;
      regionChart.data.datasets[0].data=worked;
      regionChart.data.datasets[1].data=missing;
      regionChart.data.datasets[0].backgroundColor=colours.map(c=>c+'e6');
      regionChart.data.datasets[1].backgroundColor=colours.map(c=>c+'28');
      regionChart.update(); return;
    }
    regionChart=new Chart(canvas.getContext('2d'),{type:'bar',
      data:{labels,datasets:[
        {label:'Worked',data:worked,backgroundColor:colours.map(c=>c+'e6'),borderRadius:3,stack:'s'},
        {label:'Missing',data:missing,backgroundColor:colours.map(c=>c+'28'),
         borderColor:colours.map(c=>c+'60'),borderWidth:1,borderRadius:3,stack:'s'},
      ]},
      options:{responsive:true,maintainAspectRatio:false,animation:{duration:600},
        plugins:{legend:{display:false},tooltip:{backgroundColor:T.bg3,borderColor:T.bg3,
          borderWidth:1,titleColor:T.accent,bodyColor:T.fg,
          callbacks:{label(item){const i=item.dataIndex,w=worked[i],t=total[i];
            return item.datasetIndex===0?` ${w}/${t} worked (${t?((w/t)*100).toFixed(0):0}%)`
              :` ${missing[i]} still needed`;}}}},
        scales:{
          x:{stacked:true,ticks:{color:colours,font:{size:11,weight:'bold'}},grid:{display:false}},
          y:{stacked:true,ticks:{color:T.muted,font:{size:9}},grid:{color:T.bg3+'80'}},
        }},
    });
  }

  // ══ INFO PANELS ════════════════════════════════════════════════════════════
  function ip(id){return document.getElementById(id);}
  function hdr(icon,col,title,extra=''){
    // extra: raw HTML appended after the title span, inside the same flex
    // row (see .ip-hdr) — used by the Radio panel's live-signal pulse icon;
    // every other caller leaves it at its default and is unaffected.
    return `<div class="ip-hdr"><span style="color:${col}">${icon}</span><span class="ip-title" style="color:${col}">${title}</span>${extra}</div>`;
  }

  function updateBandEfficiency(snap){
    const be=snap?.band_efficiency; if(!be?.length) return;
    const el=ip('panel-band-eff'); if(!el) return;
    const maxEff=Math.max(...be.map(r=>r.efficiency||0),0.001);
    el.innerHTML=hdr('[ ~ ]',T.accent,'BAND EFFICIENCY')+`
      <table class="ip-tbl">
        <tr><th>Band</th><th>Mults/QSO</th><th class="tr">QSOs</th></tr>
        ${be.map(r=>{const b=(r.band||'?').toUpperCase(),col=BAND_COLS[b]||T.muted;
          const bw=Math.round(((r.efficiency||0)/maxEff)*60);
          return `<tr><td style="color:${col};font-weight:bold">${b.toLowerCase()}</td>
            <td><div class="ibar"><div style="width:${bw}px;height:3px;background:${col};border-radius:2px"></div>
            <span style="color:${col}">${(r.efficiency||0).toFixed(3)}</span></div></td>
            <td class="tr" style="color:${T.muted}">${r.qsos||0}</td></tr>`;
        }).join('')}
      </table>`;
  }

  function updatePersonalBests(snap){
    const pb=snap?.personal_bests; const el=ip('panel-personal-bests'); if(!el) return;
    const cur=pb?.current_hour_rate||0,prev=pb?.prev_hour_rate||0,best=pb?.best_hour_rate||0;
    const bt=String(pb?.best_hour_time||'').substring(11,16);
    const tr=cur-prev, tc=tr>0?T.green:tr<0?T.red:T.muted;
    el.innerHTML=hdr('[ * ]',T.accent2,'PERSONAL BESTS')+`
      <table class="ip-tbl">
        <tr><td>Current hr rate</td><td style="color:${T.accent};font-weight:bold">${cur} Q/hr</td></tr>
        <tr><td>Prev hr rate</td><td style="color:${T.muted}">${prev} Q/hr</td></tr>
        <tr><td>Rate trend</td><td style="color:${tc}">${tr>0?'+':''}${tr} Q/hr</td></tr>
        <tr><td>Best hour</td><td style="color:${T.accent3};font-weight:bold">${best} Q/hr</td></tr>
        <tr><td></td><td style="color:${T.muted};font-size:0.85em">${bt?'at '+bt+' UTC':''}</td></tr>
        <tr><td colspan="2"><div class="ip-div"></div></td></tr>
        <tr><td>Mult 1</td><td style="color:${T.accent}">${snap?.worked||0}</td></tr>
        <tr><td>Mult 2 (zones)</td><td style="color:${(snap?.zone_cnt||0)?T.accent:T.muted}">${snap?.zone_cnt||0}</td></tr>
        <tr><td>Total mults</td><td style="color:${T.accent3};font-weight:bold">${snap?.band_mults||snap?.worked||0}</td></tr>
      </table>`;
  }

  function updateQsoValue(snap){
    const qv=snap?.qso_value; const el=ip('panel-qso-value'); if(!el||!qv) return;
    const bands=qv.band_order||Object.keys(qv.bands||{});
    const sc=qv.scenarios||['no_mult'], labs=qv.scenario_labels||{no_mult:'+Q'};
    el.innerHTML=hdr('[ $ ]',T.accent3,'QSO VALUE')+`
      <table class="ip-tbl">
        <tr><th>Band</th><th>Avg</th>${sc.map(s=>`<th>${labs[s]||s}</th>`).join('')}</tr>
        ${bands.map(b=>{const d=qv.bands[b]||{},col=BAND_COLS[b.toUpperCase()]||T.muted;
          return `<tr><td style="color:${col};font-weight:bold">${b.toLowerCase()}</td>
            <td style="color:${T.muted}">${(d.avg_pts||0).toFixed(1)}</td>
            ${sc.map(s=>`<td style="color:${col}">${Math.round(d[s]||0).toLocaleString()}</td>`).join('')}
          </tr>`;}).join('')}
        <tr><td colspan="${2+sc.length}"><div class="ip-div"></div>
          <span style="color:${T.muted};font-size:0.85em">
            now: ${Math.round(qv.total_pts||0).toLocaleString()} pts × ${qv.total_mults||0} mults
          </span></td></tr>
      </table>`;
  }

  // QRZ.com lookup enrichment (see settings.js/server.py) tags each QSO
  // with qrz_status ("none"|"pending"|"found"|"not_found") — last_worked
  // entries are the same dicts as ContestLog.qsos (not copies), so these
  // fields are already present with no extra fetch needed. Returns null
  // (no tooltip at all) when QRZ lookup was never attempted for this call.
  function qrzTipText(q){
    if (q.qrz_status==='pending')   return `${q.call}\nQRZ.com: looking up…`;
    if (q.qrz_status==='not_found') return `${q.call}\nNot found on QRZ.com`;
    if (q.qrz_status!=='found')     return null;
    const lines=[q.call];
    if (q.qrz_name)  lines.push(`Name:  ${q.qrz_name}`);
    if (q.qrz_grid)  lines.push(`Grid:  ${q.qrz_grid}`);
    if (q.qrz_state) lines.push(`State: ${q.qrz_state}`);
    if (lines.length===1) lines.push('No QRZ.com details on file');
    return lines.join('\n');
  }

  function updateLastWorked(snap){
    const lw=snap?.last_worked; const el=ip('panel-last-worked'); if(!el||!lw?.length) return;
    const rows=lw.slice(0,5);
    el.innerHTML=hdr('[ » ]',T.green,'LAST WORKED')+`
      <table class="ip-tbl">
        <tr><th>Call</th><th>Band/Mode</th><th>Mult</th></tr>
        ${rows.map(q=>{const band=(q.band||'').toUpperCase(),col=BAND_COLS[band]||T.muted;
          return `<tr class="lw-row">
            <td><div style="color:${T.accent};font-weight:bold">${escapeHtml(q.call||'—')}</div>
                <div style="color:${T.muted};font-size:0.85em">${String(q.time||'').substring(11,16)}</div></td>
            <td style="color:${col}">${band.toLowerCase()} ${q.mode||'—'}</td>
            <td style="color:${T.muted}">${escapeHtml(q.mult1||q.prefix||'—')}</td></tr>`;
        }).join('')}
      </table>`;

    // Hover a row for QRZ.com Name/Grid/State, when available — same
    // showTip/hideTip popup the gauge cards above use.
    el.querySelectorAll('tr.lw-row').forEach((tr,i)=>{
      const tip=qrzTipText(rows[i]);
      if (!tip) return;
      tr.style.cursor='help';
      tr.addEventListener('mousemove',e=>showTip(tip,e.clientX,e.clientY));
      tr.addEventListener('mouseleave',hideTip);
    });
  }

  function updateOperatorTimes(snap){
    const ops=snap?.operator_times; const el=ip('panel-op-times'); if(!el||!ops?.length) return;
    const fmH=m=>{const h=Math.floor(m/60),mm=Math.round(m%60);return h?`${h}h ${mm}m`:`${mm}m`;};
    const pal=[T.accent,T.accent3,T.accent2,'#a78bfa'];
    el.innerHTML=hdr('[ O ]',T.accent,'OPERATOR TIMES')+`
      <table class="ip-tbl">
        <tr><th>Operator</th><th>On Air</th><th>Off</th></tr>
        ${ops.slice(0,4).map((op,i)=>`
          <tr><td style="color:${pal[i%4]};font-weight:bold">${escapeHtml(op.operator||'—')}</td>
              <td style="color:${T.green}">${fmH(op.on_minutes||0)}</td>
              <td style="color:${T.muted}">${fmH(op.off_minutes||0)}</td></tr>
          <tr><td colspan="3" style="color:${T.muted};font-size:0.85em;padding-bottom:3px">
            ${(op.qsos||0).toLocaleString()} QSOs · ${fmH(op.span_minutes||0)} span</td></tr>`
        ).join('')}
      </table>`;
  }

  // Per-operator on-air efficiency + rate — same formulas as fatigue.js's
  // renderOpCards(), condensed into the Overview's info-panel table style so
  // it's visible at a glance without switching to the Fatigue tab.
  function updateFatigueTile(snap){
    const ops=snap?.operator_times; const el=ip('panel-fatigue'); if(!el||!ops?.length) return;
    const pal=[T.accent,T.accent3,T.accent2,'#a78bfa'];
    el.innerHTML=hdr('[ Z ]',T.accent2,'FATIGUE')+`
      <table class="ip-tbl">
        <tr><th>Operator</th><th>On-Air %</th><th>Q/hr</th></tr>
        ${ops.slice(0,4).map((op,i)=>{
          const onPct = op.span_minutes>0 ? Math.round(op.on_minutes/op.span_minutes*100) : 0;
          const rate  = op.on_minutes>0 ? ((op.qsos||0)/(op.on_minutes/60)).toFixed(1) : '—';
          const pctCol = onPct>=70?T.green:onPct>=40?T.accent3:T.red;
          const flag = onPct<40 ? ' 😴' : onPct>=85 ? ' 🔥' : '';
          return `<tr><td style="color:${pal[i%4]};font-weight:bold">${escapeHtml(op.operator||'—')}</td>
              <td style="color:${pctCol}">${onPct}%${flag}</td>
              <td style="color:${T.muted}">${rate}</td></tr>`;
        }).join('')}
      </table>`;
  }

  // ── Live Ranking (Contest Online ScoreBoard) — polled independently on its
  // own timer below, NOT from render()/vka:snapshot, since it's a slow
  // external network call unrelated to local log state.
  function updateLiveRank(data){
    const el=ip('panel-live-rank'); if(!el) return;
    if(!data || !data.available){
      const msg = data?.reason==='no_callsign'
        ? 'No callsign found in this log.'
        : data?.reason==='different_contest'
        ? `Not posting to this contest on COSB yet${data.other_contest ? ` (found: ${escapeHtml(data.other_contest)})` : ''}.`
        : 'Not currently posting to Contest Online ScoreBoard.';
      el.innerHTML=hdr('[ # ]',T.red,'LIVE RANKING')+
        `<div style="color:${T.muted};font-size:0.85em;padding:8px 0">${msg}</div>`;
      addPopoutButton(el);
      return;
    }
    el.innerHTML=hdr('[ # ]',T.red,'LIVE RANKING')+`
      <table class="ip-tbl">
        <tr><td>Rank</td><td style="color:${T.accent};font-weight:bold">#${data.rank} of ${data.total_in_category}</td></tr>
        <tr><td>Category</td><td style="color:${T.muted}">${escapeHtml(data.category||'—')}</td></tr>
        <tr><td>Score</td><td style="color:${T.accent3}">${(data.score||0).toLocaleString()}</td></tr>
        <tr><td>QSOs</td><td style="color:${T.muted}">${(data.qsos||0).toLocaleString()}</td></tr>
        <tr><td colspan="2" style="color:${T.muted};font-size:0.77em;padding-top:4px">
          ${escapeHtml(data.contest_name||'')}${data.profile_url?` — <a href="${data.profile_url}" target="_blank" style="color:${T.accent}">View on COSB &rarr;</a>`:''}
        </td></tr>
      </table>`;
    addPopoutButton(el);
  }

  // ── Radio panel — driven by the same snapshot as every other Overview
  // panel (radio_info rides along on snapshot.radio_info, no extra fetch),
  // unlike Live Ranking above which is a slow external network call.
  function updateRadioPanel(snap){
    const el=ip('panel-radio'); if(!el) return;
    const r=window.VKA.formatRadio(snap?.radio_info?.own);
    if (!r){
      // bind_error means the listener never even started this session (most
      // likely another process already had the UDP port) — a completely
      // different problem from "N1MM+ just hasn't broadcast yet", and one no
      // amount of checking N1MM+'s own settings will fix. Say so plainly
      // instead of pointing at the generic broadcast-config hint, which
      // sends the operator troubleshooting the wrong end.
      const bindErr=snap?.radio_info?.bind_error;
      const msg=bindErr
        ? `⚠ ${escapeHtml(bindErr)}`
        : `No radio connected — enable N1MM+'s RadioInfo broadcast (Config &gt; Config Ports &gt; Broadcast Data &gt; Radio) to show this.`;
      el.innerHTML=hdr('[ &asymp; ]',bindErr?T.red:T.accent3,'RADIO')+
        `<div style="color:${bindErr?T.red:T.muted};font-size:0.85em;padding:8px 0">${msg}</div>`;
      addPopoutButton(el);
      return;
    }
    // Animated broadcast-wave rings — three arcs pulsing outward from the
    // center in sequence, only shown once radio_info is actually flowing
    // (there's nothing live to represent in the "no radio" branch above).
    // CSS-only (see .radio-pulse in style.css) rather than a raster image:
    // scales cleanly, recolors with the theme's accent3 automatically, and
    // ships no binary asset.
    const pulse = `<span class="radio-pulse" title="Receiving live RadioInfo from N1MM+">
        <span class="rp-ring"></span><span class="rp-ring"></span><span class="rp-ring"></span>
      </span>`;
    el.innerHTML=hdr('[ &asymp; ]',T.accent3,'RADIO',pulse)+`
      <table class="ip-tbl">
        <tr><td>Freq</td><td style="color:${T.accent3};font-weight:bold;font-size:1.15em">${r.freqStr} MHz</td></tr>
        <tr><td>Band</td><td><span class="band-chip" style="background:${r.bandColor}30;color:${r.bandColor}">${r.band}</span></td></tr>
        <tr><td>Mode</td><td style="color:${T.muted}">${r.modeStr||'—'}</td></tr>
        <tr><td>Radio</td><td style="color:${T.muted}">${r.radioNr}</td></tr>
      </table>`;
    addPopoutButton(el);
  }

  // ── Top DXCC — resolved from each QSO's callsign server-side (see
  // /api/top_countries), independent of what the loaded contest's own
  // mult1 means, so it reads the same way for any contest type. Polled on
  // a timer rather than every snapshot tick — it's a full-log scan on the
  // server, and a country leaderboard doesn't need sub-10-second freshness.
  let _topDxccTimer=null;
  async function fetchTopDxcc(){
    try {
      const res=await fetch('/api/top_countries');
      renderTopDxcc(await res.json());
    } catch(e) { /* leave the panel showing its last known state */ }
  }
  function startTopDxccPolling(){
    fetchTopDxcc();
    if(_topDxccTimer) clearInterval(_topDxccTimer);
    _topDxccTimer=setInterval(fetchTopDxcc,15000);
  }
  function renderTopDxcc(rows){
    const el=ip('panel-top-dxcc'); if(!el) return;
    if(!rows||!rows.length){
      el.innerHTML=hdr('[ &#127760; ]',T.green,'TOP DXCC')+
        `<div style="color:${T.muted};font-size:0.85em;padding:8px 0">No countries resolved yet.</div>`;
      addPopoutButton(el); return;
    }
    const maxQ=rows[0].qsos||1;
    const rowsHtml=rows.slice(0,10).map(r=>`
      <tr>
        <td>${escapeHtml(r.country)}</td>
        <td style="width:60%">
          <div class="ibar"><div style="flex:1;height:6px;background:${T.bg3};border-radius:3px;overflow:hidden">
            <div style="width:${Math.round(r.qsos/maxQ*100)}%;height:100%;background:${T.green}"></div>
          </div></div>
        </td>
        <td class="tr" style="color:${T.green};font-weight:bold">${r.qsos}</td>
      </tr>`).join('');
    el.innerHTML=hdr('[ &#127760; ]',T.green,'TOP DXCC')+
      `<table class="ip-tbl">${rowsHtml}</table>`;
    addPopoutButton(el);
  }

  // ── QSOs by band — donut (Overview) ────────────────────────────────────
  // Destroying and rebuilding on every tick (this panel updates on every
  // snapshot poll, every few seconds) turned out to be the wrong default:
  // it re-triggers the entry animation and visibly flickers/redraws the
  // whole donut on every poll, even when the underlying counts hadn't
  // changed at all. Rebuild is only actually needed the first time (fresh
  // canvas) and when the *set* of worked bands changes (a new band's
  // slice/legend entry appears, or the sort-by-qsos order shifts) — that's
  // the actual shape of the original bug this guarded against (Chart.js's
  // legend laid out against a stale canvas size after this panel's grid
  // row settled to its final height post-load). Same band set as last
  // tick just gets its values updated in place with animation off.
  let bandDonutChart=null, _bandDonutShape='';
  function updateBandDonut(snap){
    const canvas=document.getElementById('chart-band-donut'); if(!canvas) return;
    const be=(snap?.band_efficiency||[]).filter(r=>r.qsos>0).sort((a,b)=>b.qsos-a.qsos);
    const totalEl=document.getElementById('donut-center-total');
    const total=be.reduce((a,r)=>a+(r.qsos||0),0);
    if(totalEl) totalEl.innerHTML=`<div class="dc-total">${total.toLocaleString()}</div><div class="dc-label">QSOs</div>`;
    if(!be.length){
      // Switching to an empty/fresh log: clear out whatever the previous
      // log's chart was showing rather than leaving its stale slices and
      // legend on screen (vka:loaded doesn't touch this chart itself).
      if(bandDonutChart){ bandDonutChart.destroy(); bandDonutChart=null; }
      _bandDonutShape='';
      return;
    }
    const labels=be.map(r=>r.band.toLowerCase());
    const data=be.map(r=>r.qsos);
    const colours=be.map(r=>BAND_COLS[(r.band||'').toUpperCase()]||T.muted);
    // Order-independent (sorted alphabetically), not the qsos-count display
    // order those labels are already in — a pure rank swap between two
    // already-worked bands (20m overtakes 40m this tick) must not by
    // itself force a rebuild, only the actual *set* of worked bands
    // changing should.
    const shape=labels.slice().sort().join(',');
    if(bandDonutChart && shape===_bandDonutShape){
      bandDonutChart.data.labels=labels;
      bandDonutChart.data.datasets[0].data=data;
      bandDonutChart.data.datasets[0].backgroundColor=colours;
      bandDonutChart.update('none');
      return;
    }
    _bandDonutShape=shape;
    if(bandDonutChart){ bandDonutChart.destroy(); bandDonutChart=null; }
    bandDonutChart=new Chart(canvas.getContext('2d'),{
      type:'doughnut',
      data:{labels,datasets:[{data,backgroundColor:colours,borderColor:T.bg2,borderWidth:2}]},
      options:{
        responsive:true,maintainAspectRatio:false,cutout:'58%',
        animation:{duration:500,easing:'easeOutQuart'},
        plugins:{
          // fg (bright), not muted (dim grey) — this legend lives in a
          // narrow 24%-width column, where a low-contrast colour at small
          // size reads as illegible/"black" against the dark panel
          // background rather than as a deliberate muted style. color is
          // set both on labels (the option Chart.js reads) and per-item
          // as fontColor (the legacy field its draw() checks first, ahead
          // of the option) — belt and suspenders against any legend
          // rendering path that prefers the per-item field.
          legend:{display:true,position:'bottom',
            labels:{color:T.fg,font:{size:12,weight:'bold'},boxWidth:11,padding:7,
              generateLabels:chart=>chart.data.labels.map((l,i)=>({
                text:`${l} ${chart.data.datasets[0].data[i]}`,
                fillStyle:chart.data.datasets[0].backgroundColor[i],
                strokeStyle:chart.data.datasets[0].backgroundColor[i],
                fontColor:T.fg,
                index:i,
              }))}},
          tooltip:{backgroundColor:T.bg3,bodyColor:T.fg,borderWidth:1,
            callbacks:{label:c=>{
              const v=c.raw,pct=total>0?(v/total*100).toFixed(1):'0';
              return ` ${v} QSOs (${pct}%)`;
            }}},
        },
      },
    });
  }

  // ── QSOs by DXCC — hero glow map (Overview) ─────────────────────────────
  // Reverted back to this from a from-scratch canvas dot-matrix renderer
  // (real coastline data, hand-rolled heatmap) that spent many rounds
  // chasing an exact match to a mockup image — worth recording why: every
  // fix was verified working by direct pixel sampling on this end, yet
  // each still came back "still blurry" against a screenshot that likely
  // wasn't a faithful capture of what was actually on screen (the app's
  // own Snapshot button goes through html2canvas, which doesn't reproduce
  // <canvas> content reliably) — an unfalsifiable loop neither side could
  // actually close. A real, proven, boring Leaflet map with glowing
  // markers is worse at pretending to be that mockup image but isn't
  // fighting an un-debuggable capture pipeline to get there.
  const GLOW_LOAD_THROTTLE_MS=15000;
  let _glowMap=null, _glowMarkerLayer=null, _glowLastLoadAt=0;

  // fitBounds() was tried here (fitting a real lat/lon box against both the
  // panel's width AND height) and made things actively worse against the
  // old abstract dark tile source: it zoomed out enough to fit height,
  // leaving the world narrower than the panel with dead margins each side
  // that clashed visually against the old tiles' background colour.
  //
  // Rounding to a whole zoom level (ceil fills the width but over-crops
  // latitude; floor shows more latitude but leaves dead space on the
  // sides) was the tradeoff before this — neither is actually necessary.
  // zoomSnap:0 on the map (see initGlowMap) lets Leaflet hold any
  // fractional zoom, so the world width can be set to exactly match the
  // container: zero dead space AND no extra cropping. Leaflet still loads
  // whichever integer-zoom tiles are nearest and scales them a hair via
  // CSS to hit the exact size — imperceptible, and still real imagery.
  //
  // Centered on longitude 0, not some "interesting" offset: once the
  // world's pixel width matches the container's almost exactly, the
  // visible span is nearly the full 360°, so any non-zero center leaves
  // no slack to absorb the antimeridian wraparound — with noWrap:true
  // (no duplicate world copies) that wrapped sliver just renders as a
  // dead gap on one edge. Lon 0 makes the visible span exactly one world
  // copy with no wraparound needed, and happens to split the seam through
  // the empty Pacific — the conventional world-map centering for exactly
  // this reason.
  function fitGlowMapBounds(){
    if(!_glowMap) return;
    const el=document.getElementById('glow-map-container'); if(!el) return;
    _glowMap.invalidateSize();
    const w=el.clientWidth||900;
    // The +0.004 is deliberate, not a stray magic number: an exact fit
    // (world pixel width == container width, centered at lon 0 so the
    // viewport's left edge should land exactly on the world's own left
    // edge) leaves zero floating-point margin — a sub-pixel rounding
    // error in Leaflet's own pixel-bounds math can tip that edge just
    // negative, requesting an out-of-range tile column (x:-1), observed
    // reliably after a tile layer swap (applyGlowMapTheme()). Zooming in
    // a hair beyond exact-fit makes the world very slightly *larger* than
    // the container instead of exactly equal, so that edge sits safely
    // inside world bounds instead of balanced on the boundary — a few px
    // of imperceptible overfit versus a visible missing edge tile.
    const fitZoom=Math.max(0,Math.min(8,Math.log2(w/256)+0.004));
    _glowMap.setView([10,0],fitZoom,{animate:false});
  }

  // NASA GIBS VIIRS "Earth at Night" city-lights composite for dark themes
  // — the real imagery the original mockup is a crop of, not a hand-
  // rolled recreation of it. Note the {z}/{y}/{x} order (GIBS WMTS REST
  // path segments are TileMatrix/TileRow/TileCol, i.e. z/y/x, not the
  // usual slippy-map z/x/y). Light theme swaps to CartoDB's Positron —
  // the same soft light-gray basemap style the rest of Light theme's
  // panels use, since a vivid night-lights image (or a daytime true-
  // colour satellite image, the closest "real imagery" equivalent) reads
  // as visually loud/high-contrast against Light theme's soft, pastel UI.
  const GLOW_TILE_DARK ='https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_CityLights_2012/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg';
  const GLOW_TILE_LIGHT='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
  let _glowTileLayer=null;

  // Perceptual luminance of the panel background, not a hardcoded theme
  // name check — robust to any future theme addition without needing to
  // list it here. Only "Light" is currently bright; Dark/High Contrast/
  // both colorblind-safe variants are all near-black backgrounds.
  function isLightTheme(){
    const hex=(T.bg2||'#161b22').replace('#','');
    const r=parseInt(hex.substr(0,2),16), g=parseInt(hex.substr(2,2),16), b=parseInt(hex.substr(4,2),16);
    return (0.299*r+0.587*g+0.114*b)/255 > 0.6;
  }
  function applyGlowMapTheme(){
    if(!_glowMap) return;
    const light=isLightTheme();
    if(_glowTileLayer){ _glowMap.removeLayer(_glowTileLayer); _glowTileLayer=null; }
    _glowTileLayer=light
      ? L.tileLayer(GLOW_TILE_LIGHT,{subdomains:'abcd',maxZoom:19,minZoom:0,noWrap:true,attribution:'CARTO'})
      : L.tileLayer(GLOW_TILE_DARK,{maxZoom:8,minZoom:0,noWrap:true,attribution:'NASA GIBS'});
    _glowTileLayer.addTo(_glowMap);
    // Re-fit (not just re-add) after a layer swap on an already-live map
    // at a fractional zoom (zoomSnap:0) — observed requesting an out-of-
    // range tile column (x:-1) for the new layer without this, a stale-
    // internal-state symptom of the same kind fitGlowMapBounds() already
    // guards against on resize/tab-visibility changes elsewhere; an
    // explicit setView() forces Leaflet to fully recompute the tile grid
    // against the new layer instead of reusing whatever it last computed.
    fitGlowMapBounds();
  }

  function initGlowMap(){
    if(_glowMap || typeof L==='undefined') return;
    const el=document.getElementById('glow-map-container'); if(!el) return;
    _glowMap=L.map('glow-map-container',{
      center:[10,0],zoom:2,zoomSnap:0,
      zoomControl:false,attributionControl:false,dragging:false,
      touchZoom:false,scrollWheelZoom:false,doubleClickZoom:false,
      boxZoom:false,keyboard:false,worldCopyJump:false,
    });
    applyGlowMapTheme();
    _glowMarkerLayer=L.layerGroup().addTo(_glowMap);
    fitGlowMapBounds();
    // A plain window 'resize' listener only catches the browser window
    // itself changing size — it misses every other reason this panel's
    // actual pixel width can change after the initial fit: the zoom
    // slider's root font-size restore-on-launch (persisted, so it can run
    // after this first fit), a tile getting dragged to reorder the row,
    // even DPI changes. All of those left the map's Leaflet-computed size
    // stale against the container's real size, which reads as the map
    // being oddly zoomed or cut off along one edge. A ResizeObserver on
    // the container itself catches its size changing for any reason.
    if(typeof ResizeObserver!=='undefined'){
      new ResizeObserver(()=>fitGlowMapBounds()).observe(el);
    } else {
      window.addEventListener('resize',fitGlowMapBounds);
    }
  }
  function glowSpotIcon(col){
    return L.divIcon({className:'map-spot-icon',
      html:`<span class="map-spot-dot" style="--col:${col}"></span>`,
      iconSize:[16,16],iconAnchor:[8,8]});
  }
  async function updateGlowMap(){
    if(!_glowMap) return;
    if(Date.now()-_glowLastLoadAt<GLOW_LOAD_THROTTLE_MS) return;
    _glowLastLoadAt=Date.now();
    try{
      const res=await fetch('/api/map_data');
      const data=await res.json();
      _glowMarkerLayer.clearLayers();
      data.forEach(d=>{
        if(d.lat==null||d.lon==null) return;
        const col=BAND_COLS[(d.band||'').toUpperCase()]||T.muted;
        const band=(d.band||'?').toLowerCase();
        // Tooltip flips to below the marker instead of always above it
        // when the marker sits near the top of the panel — .glow-map-panel
        // needs overflow:hidden to keep the map's own tiles contained
        // (see fitGlowMapBounds()'s comment), which was silently clipping
        // an always-above tooltip for any marker near that edge (northern
        // Europe/Canada/Russia are exactly where markers cluster).
        const py=_glowMap.latLngToContainerPoint([d.lat,d.lon]).y;
        const flip=py<80;
        // Same tooltip markup as the World Map tab's own live-spot markers
        // (worldmap.js addLiveSpot()) — a plain string, not that one's lazy
        // function form, since this layer is fully torn down and rebuilt
        // on every poll rather than mutating existing markers.
        L.marker([d.lat,d.lon],{icon:glowSpotIcon(col)})
          .bindTooltip(`
            <div style="font-family:Consolas,monospace;font-size:11px;line-height:1.6">
              <b style="color:${col}">${escapeHtml(d.call)}</b>
              ${d.country?` · ${escapeHtml(d.country)}`:''}<br>
              ${band} · ${d.count} QSO${d.count===1?'':'s'}
              ${d.mult?`<br>mult: ${escapeHtml(d.mult)}`:''}
            </div>`, {direction:flip?'bottom':'top',offset:flip?[0,8]:[0,-8]})
          .addTo(_glowMarkerLayer);
      });
      updateGlowLegend(data);
    } catch(e){ /* leave whatever's already plotted */ }
  }
  // Same idiom as the World Map tab's own updateLegend() (worldmap.js) —
  // dot colour meant "which band" was only explained by a separate panel
  // (the QSOs-by-band donut, elsewhere on the page); a legend directly on
  // this map makes it self-explanatory without having to hover every dot
  // or cross-reference another panel.
  function updateGlowLegend(data){
    const el=document.getElementById('glow-map-legend'); if(!el) return;
    const counts={};
    data.forEach(d=>{
      const band=(d.band||'?').toUpperCase();
      counts[band]=(counts[band]||0)+(d.count||0);
    });
    el.innerHTML=Object.entries(counts)
      .sort((a,b)=>b[1]-a[1]).slice(0,8)
      .map(([band,n])=>{
        const col=BAND_COLS[band]||T.muted;
        return `<span class="map-legend-item">
          <span class="map-legend-dot" style="background:${col}"></span>
          <span style="color:${col}">${band.toLowerCase()}</span>
          <span class="map-legend-count">${n}</span>
        </span>`;
      }).join('');
  }

  async function fetchLiveRank(){
    try {
      const res = await fetch('/api/live_rank');
      updateLiveRank(await res.json());
    } catch(e) { /* leave the panel showing its last known state */ }
  }

  let _liveRankTimer=null;
  function startLiveRankPolling(){
    fetchLiveRank();
    if(_liveRankTimer) clearInterval(_liveRankTimer);
    _liveRankTimer=setInterval(fetchLiveRank,120000);   // matches server cache TTL
  }

  // ══ SESSION BAR ════════════════════════════════════════════════════════════
  function updateSessionStatus(snap){
    const ss=snap?.session_status,pb=snap?.personal_bests;
    const bar=document.getElementById('session-bar'); if(!bar) return;
    if(!ss?.state){bar.style.display='none';document.body.classList.remove('has-session-bar');return;}
    bar.style.display='flex'; document.body.classList.add('has-session-bar');
    const col=ss.state==='live'?T.accent:ss.state==='over'?T.muted:T.accent3;
    const rem=Math.round(ss.total_remaining_mins??ss.remaining_mins??0);
    const pct=((ss.total_pct_elapsed??ss.pct_elapsed)||0).toFixed(0);
    bar.innerHTML=`
      <span style="color:${col};font-size:0.7em">●</span>
      <span class="sess-label">${ss.session_label||''}</span>
      <span class="sess-sep">|</span>
      <span class="sess-stat">${rem}m remaining</span>
      <div class="sess-prog-wrap">
        <div class="sess-prog-bar" style="width:${pct}%;background:${col}55;border-right:2px solid ${col}"></div>
      </div>
      <span class="sess-pct" style="color:${col}">${pct}%</span>
      <span class="sess-sep">|</span>
      <span class="sess-stat">Rate: <b style="color:${T.accent}">${pb?.current_hour_rate||0}/hr</b></span>
      <span class="sess-sep">|</span>
      <span class="sess-stat">Best hr: <b style="color:${T.accent3}">${pb?.best_hour_rate||0}</b></span>
      <span class="sess-sep">|</span>
      <span class="sess-stat">Best session: <b style="color:${T.accent2}">${pb?.best_session_qsos||0} QSOs</b></span>`;
  }


  // ══ QSO VALUE INSIGHT BAR ══════════════════════════════════════════════════
  function updateInsightBar(snap) {
    const el = document.getElementById('insight-text'); if (!el) return;
    const qv = snap?.qso_value;
    const pb = snap?.personal_bests || {};
    const ss = snap?.session_status || {};
    const cur = pb.current_hour_rate || 0;
    const rem = Math.round(ss.total_remaining_mins ?? ss.remaining_mins ?? 0);

    if (!qv || !qv.bands) {
      el.innerHTML = 'Load a contest log to see real-time QSO value insights.';
      return;
    }

    // Find best band by current scenario
    const bands = qv.band_order || Object.keys(qv.bands);
    const sc    = (qv.scenarios || ['no_mult'])[0];  // first scenario = no new mult
    let bestBand = null, bestVal = 0;
    bands.forEach(b => {
      const v = qv.bands[b]?.[sc] || 0;
      if (v > bestVal) { bestVal = v; bestBand = b; }
    });

    // Find best band for new mult
    const scMult = qv.scenarios?.includes('one_mult') ? 'one_mult' : sc;
    let bestMultBand = null, bestMultVal = 0;
    bands.forEach(b => {
      const v = qv.bands[b]?.[scMult] || 0;
      if (v > bestMultVal) { bestMultVal = v; bestMultBand = b; }
    });

    const parts = [];

    if (bestBand) {
      parts.push(`Next fill QSO worth most on <b style="color:var(--accent)">${bestBand.toLowerCase()}</b> (+${Math.round(bestVal).toLocaleString()} pts)`);
    }
    if (bestMultBand && scMult !== sc) {
      parts.push(`New mult most valuable on <b style="color:var(--accent3)">${bestMultBand.toLowerCase()}</b> (+${Math.round(bestMultVal).toLocaleString()} pts)`);
    }
    if (cur > 0 && rem > 0) {
      parts.push(`At ${cur} Q/hr with ${rem}m remaining → ~<b style="color:var(--green)">${Math.round(cur * rem / 60)}</b> more QSOs possible`);
    }

    el.innerHTML = parts.length ? parts.join(' &nbsp;|&nbsp; ') : 'No QSO value data available.';
  }


  // ══ EXTRA ANALYTICS ROW ════════════════════════════════════════════════════
  function updateExtraAnalytics(snap) {
    const pb   = snap?.personal_bests || {};
    const cur  = pb.current_hour_rate  || 0;
    const prev = pb.prev_hour_rate     || 0;
    const total= snap?.total || 0;
    const valid= snap?.valid || 0;
    const score= snap?.score || 0;

    function setEA(id, val, sub, col) {
      const el = document.getElementById(id); if (!el) return;
      el.textContent = val;
      if (col) el.style.color = col;
    }

    // Rate trend
    const trend = cur - prev;
    const trendStr = trend > 0 ? `+${trend} ▲` : trend < 0 ? `${trend} ▼` : `0 →`;
    const trendCol = trend > 0 ? T.green : trend < 0 ? T.red : T.muted;
    setEA('eat-trend', trendStr, '', trendCol);
    setEA('eat-sub', `cur: ${cur} | prev: ${prev}`, '', '');

    // Mult efficiency — meaningless for open-ended mult lists (WPX prefixes,
    // WAE countries, etc.): "missing" is always 0 with nothing to compare
    // against, which would otherwise show a false 100%.
    const worked  = snap?.worked  || 0;
    const missing = snap?.missing || 0;
    const possible = worked + missing;
    const multPct = (_hasFixedMultList && possible > 0) ? ((worked/possible)*100).toFixed(1)+'%' : '—';
    const multCol = (_hasFixedMultList && possible > 0) ? (worked/possible > 0.7 ? T.green : worked/possible > 0.4 ? T.accent3 : T.red) : T.muted;
    setEA('eat-mult-pct', multPct, '', multCol);

    // Dupe rate
    const dupes    = total - valid;
    const dupeRate = total > 0 ? ((dupes/total)*100).toFixed(1)+'%' : '—';
    const dupeCol  = total > 0 ? (dupes/total > 0.1 ? T.red : dupes/total > 0.05 ? T.accent3 : T.green) : T.muted;
    setEA('eat-dupe-rate', dupeRate, '', dupeCol);

    // Avg pts/QSO
    const avgPts = valid > 0 ? (score/valid).toFixed(2) : '—';
    setEA('eat-pts-qso', avgPts, '', T.accent);

    // Best band by efficiency
    const be = snap?.band_efficiency || [];
    const best = be.reduce((a,b) => (b.efficiency||0) > (a.efficiency||0) ? b : a, {});
    const bestBand = best.band ? best.band.toLowerCase() : '—';
    const bestCol  = BAND_COLS[((best.band||'').toUpperCase())] || T.accent;
    setEA('eat-best-band', bestBand, '', bestCol);
  }

  // ══ TIME SINCE LAST QSO (live ticker, independent of snapshot cadence) ════
  let _lastQsoTime=null;   // Date, parsed from the most recent snapshot

  function trackLastQso(snap){
    const t=snap?.last_worked?.[0]?.time;
    _lastQsoTime = t ? new Date(t+'Z') : null;   // server times are naive UTC
  }

  function fmtElapsed(totalSec){
    totalSec=Math.max(0,Math.floor(totalSec));
    const h=Math.floor(totalSec/3600), m=Math.floor((totalSec%3600)/60), s=totalSec%60;
    if (h>0) return `${h}h ${String(m).padStart(2,'0')}m`;
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }

  // Same breakdown as fmtElapsed, but keeps the seconds digit even past the
  // 1-hour mark — used for the HUD countdown so it visibly ticks every
  // second instead of appearing to sit still for up to 59s at a time.
  function fmtCountdown(totalSec){
    totalSec=Math.max(0,Math.floor(totalSec));
    const h=Math.floor(totalSec/3600), m=Math.floor((totalSec%3600)/60), s=totalSec%60;
    if (h>0) return `${h}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`;
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }

  function tickSinceLastQso(){
    const valEl=document.getElementById('eat-since-last');
    const subEl=document.getElementById('eat-since-sub');
    const hudEl=document.getElementById('hud-since');
    if (!_lastQsoTime){
      if (valEl) { valEl.textContent='—'; valEl.style.color=T.muted; }
      if (subEl) subEl.textContent='—';
      if (hudEl) hudEl.textContent='—';
      return;
    }
    const sec=(Date.now()-_lastQsoTime.getTime())/1000;
    const str=fmtElapsed(sec);
    const col = sec<120?T.green : sec<300?T.accent3 : T.red;
    if (valEl) { valEl.textContent=str; valEl.style.color=col; }
    if (subEl) subEl.textContent = sec<120?'on pace':sec<300?'getting quiet':'go find a QSO';
    if (hudEl) { hudEl.textContent=str; hudEl.style.color=col; }
  }
  setInterval(tickSinceLastQso,1000);

  // ══ CONTEST-OVER PANEL ══════════════════════════════════════════════════════
  function updateContestOverPanel(snap) {
    const panel = document.getElementById('contest-over-panel'); if (!panel) return;
    const ss    = snap?.session_status || {};

    if (ss.state !== 'over') {
      panel.style.display = 'none';
      return;
    }

    panel.style.display = 'flex';

    const score   = snap?.score   || 0;
    const valid   = snap?.valid   || 0;
    const total   = snap?.total   || 0;
    const worked  = snap?.worked  || 0;
    const band_m  = snap?.band_mults || worked;
    const dupes   = total - valid;
    const pb      = snap?.personal_bests || {};

    const titleEl = document.getElementById('cop-title');
    const statsEl = document.getElementById('cop-stats');
    const metaEl  = document.getElementById('cop-meta');

    // Translate block labels:
    //   WPX uses label_prefix="B", num_sessions=4 → "B1".."B4" = 12-hr operating blocks
    //   "B4 (ended)" means the 4th 12-hour block has ended (i.e. the full 48-hr contest)
    const rawLabel = ss.session_label || 'CONTEST COMPLETE';
    const blockMatch = rawLabel.match(/^([A-Z])(\d+)(.*)/);
    let displayLabel;
    if (blockMatch) {
      const prefixMap = { B:'Block', S:'Session', R:'Round', P:'Period' };
      const word = prefixMap[blockMatch[1]] || `Period`;
      displayLabel = `${word} ${blockMatch[2]}${blockMatch[3]}`;
    } else {
      displayLabel = rawLabel;
    }
    if (titleEl) titleEl.textContent = `🏆 ${displayLabel} — FINAL SCORE: ${score.toLocaleString('en-AU')}`;
    if (statsEl) statsEl.innerHTML =
      `<span style="color:${T.accent}">${valid.toLocaleString()}</span> valid QSOs &nbsp;×&nbsp; ` +
      `<span style="color:${T.accent3}">${band_m}</span> mults &nbsp;=&nbsp; ` +
      `<span style="color:${T.accent3};font-weight:bold">${score.toLocaleString('en-AU')} pts</span>` +
      `&nbsp;&nbsp;|&nbsp;&nbsp;` +
      `Best rate: <span style="color:${T.green}">${pb.best_hour_rate || 0} Q/hr</span>` +
      (pb.best_hour_time ? ` at <span style="color:${T.muted}">${String(pb.best_hour_time).substring(11,16)} UTC</span>` : '') +
      `&nbsp;&nbsp;|&nbsp;&nbsp;Dupes: <span style="color:${dupes>0?T.red:T.green}">${dupes}</span>`;
    if (metaEl) metaEl.innerHTML =
      `${ss.end_dt ? String(ss.end_dt).substring(0,16)+' UTC' : ''}`;
  }

  // ══ TILE REORDERING (drag-and-drop, persisted per-section) ═════════════════
  function tileKey(el){ return el.dataset.tileKey || el.id || ''; }

  function saveTileOrder(container,storageKey){
    const order=Array.from(container.children).map(tileKey).filter(Boolean);
    try{ localStorage.setItem(storageKey,JSON.stringify(order)); }catch{}
  }

  function applyTileOrder(container,storageKey){
    let saved;
    try{ saved=JSON.parse(localStorage.getItem(storageKey)||'null'); }catch{ saved=null; }
    if(!saved||!saved.length) return;
    const byKey=new Map(Array.from(container.children).map(c=>[tileKey(c),c]));
    saved.forEach(k=>{ const el=byKey.get(k); if(el){ container.appendChild(el); byKey.delete(k); } });
    byKey.forEach(el=>container.appendChild(el));
  }

  function markDraggable(container){
    Array.from(container.children).forEach(c=>{
      c.setAttribute('draggable','true');
      c.classList.add('reorderable-tile');
    });
  }

  function setupReorder(container,storageKey){
    if(!container||container._reorderBound) return;
    container._reorderBound=true;
    container.classList.add('reorderable-row');
    let dragEl=null;
    container.addEventListener('dragstart',e=>{
      const tile=e.target.closest('.reorderable-tile');
      if(!tile||tile.parentElement!==container) return;
      dragEl=tile; tile.classList.add('dragging');
      e.dataTransfer.effectAllowed='move';
      try{ e.dataTransfer.setData('text/plain',''); }catch{}
    });
    container.addEventListener('dragover',e=>{
      if(!dragEl) return;
      e.preventDefault();
      const tile=e.target.closest('.reorderable-tile');
      if(!tile||tile===dragEl||tile.parentElement!==container) return;
      const rect=tile.getBoundingClientRect();
      const before=(e.clientX-rect.left)<rect.width/2;
      container.insertBefore(dragEl,before?tile:tile.nextSibling);
    });
    container.addEventListener('dragend',()=>{
      if(dragEl){ dragEl.classList.remove('dragging'); dragEl=null; saveTileOrder(container,storageKey); }
    });
  }

  // ══ POP-OUT TILES (own OS window, live-updating) ═══════════════════════════
  // Path-based (/popout/<key>), not query-string — see index.html bootstrap
  // script for why.
  const POPOUT_KEY=location.pathname.startsWith('/popout/')
    ? decodeURIComponent(location.pathname.slice('/popout/'.length))
    : null;

  function addPopoutButton(el){
    if (POPOUT_KEY || el.querySelector('.popout-btn')) return;
    const btn=document.createElement('button');
    btn.className='popout-btn';
    btn.type='button';
    btn.title='Pop out to its own window';
    btn.textContent='⤢';
    btn.setAttribute('draggable','false');
    btn.addEventListener('mousedown',e=>e.stopPropagation());
    btn.addEventListener('click',async e=>{
      e.stopPropagation();
      const key=tileKey(el); if(!key) return;
      const label=el.querySelector('.ip-title,.spark-title,.ea-label')?.textContent?.trim()||key;
      const openInBrowserTab=()=>window.open(
        `/popout/${encodeURIComponent(key)}`,
        'vkca_popout_'+key, 'width=480,height=380,resizable=yes');
      try {
        const res=await fetch('/api/popout',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({key,title:label,width:480,height:380})});
        if (!res.ok) { openInBrowserTab(); return; }
        const data=await res.json();
        if (!data.ok) openInBrowserTab();
      } catch { openInBrowserTab(); }
    });
    el.appendChild(btn);
  }

  function applyPopoutFilter(){
    if (!POPOUT_KEY) return;
    const all=document.querySelectorAll('.gauge-card,.spark-card,.info-panel,.ea-card');
    let target=null;
    all.forEach(el=>{ if(tileKey(el)===POPOUT_KEY) target=el; });
    if (!target) return;
    const row=target.parentElement;
    row.classList.add('popout-host-row');
    target.classList.add('popout-host-tile');
    const label=target.querySelector('.ip-title,.spark-title,.ea-label')?.textContent?.trim();
    if (label) document.title=label+' — VK Contest Analyzer';
    setTimeout(()=>{
      redrawAll();
      Object.values(_sparks).forEach(c=>c?.resize());
    },60);
  }

  // ══ HIDE/SHOW INDIVIDUAL PANELS ═════════════════════════════════════════════
  // Brings back the old desktop app's per-panel collapse toggle (lost in the
  // web rewrite — only the pop-out half survived). Scoped to the three
  // static, tile-based rows (spark/info/ea cards) plus the standalone Region
  // Completion panel; gauges are excluded since gauge-row is rebuilt fresh
  // per plugin/snapshot with positional ids, not stable per-gauge keys.
  const HIDDEN_TILES_KEY='vkca_hidden_tiles';

  function loadHiddenTiles(){
    try{ return new Set(JSON.parse(localStorage.getItem(HIDDEN_TILES_KEY)||'[]')); }
    catch{ return new Set(); }
  }
  let _hiddenTiles=loadHiddenTiles();
  function saveHiddenTiles(){
    try{ localStorage.setItem(HIDDEN_TILES_KEY,JSON.stringify(Array.from(_hiddenTiles))); }catch{}
  }

  function applyHiddenTiles(){
    document.querySelectorAll('.spark-card,.info-panel,.ea-card').forEach(el=>{
      el.classList.toggle('tile-hidden',_hiddenTiles.has(tileKey(el)));
    });
    const bars=document.getElementById('bars-row');
    if (bars) bars.classList.toggle('tile-hidden',_hiddenTiles.has('bars-row'));
  }

  function setTileHidden(key,hidden){
    if (hidden) _hiddenTiles.add(key); else _hiddenTiles.delete(key);
    saveHiddenTiles();
    applyHiddenTiles();
    buildPanelsMenu();   // keep the open menu's checkboxes in sync
  }

  function addHideButton(el){
    if (POPOUT_KEY || el.querySelector('.hide-btn')) return;
    const btn=document.createElement('button');
    btn.className='hide-btn';
    btn.type='button';
    btn.title='Hide this panel (bring back via ☰ Panels)';
    btn.textContent='✕';
    btn.setAttribute('draggable','false');
    btn.addEventListener('mousedown',e=>e.stopPropagation());
    btn.addEventListener('click',e=>{
      e.stopPropagation();
      const key=tileKey(el); if(!key) return;
      setTileHidden(key,true);
    });
    el.appendChild(btn);
  }

  function panelLabel(el){
    const raw=el.querySelector('.ip-title,.spark-title,.ea-label')?.textContent?.trim()||tileKey(el);
    // Strips a leading "[ T ]"/"[»]"-style icon prefix some panel titles
    // carry (e.g. the Contest Time panel) — the menu just wants plain text.
    return raw.replace(/^\[[^\]]*\]\s*/,'');
  }

  const PANEL_MENU_GROUPS=[
    {label:'Sparklines',  sel:'.spark-row > *'},
    {label:'Info Panels', sel:'.info-panels-row > *'},
    {label:'Analytics',   sel:'.extra-analytics-row > *'},
  ];

  function buildPanelsMenu(){
    const menu=document.getElementById('panels-menu'); if(!menu) return;
    menu.innerHTML='';
    const addRow=(key,label)=>{
      const row=document.createElement('label');
      row.className='panels-menu-row';
      const cb=document.createElement('input');
      cb.type='checkbox'; cb.checked=!_hiddenTiles.has(key);
      cb.addEventListener('change',()=>setTileHidden(key,!cb.checked));
      row.appendChild(cb);
      row.appendChild(document.createTextNode(label));
      menu.appendChild(row);
    };
    PANEL_MENU_GROUPS.forEach(({label,sel})=>{
      const items=Array.from(document.querySelectorAll(sel));
      if (!items.length) return;
      const h=document.createElement('div');
      h.className='panels-menu-group'; h.textContent=label;
      menu.appendChild(h);
      items.forEach(el=>{ const key=tileKey(el); if(key) addRow(key,panelLabel(el)); });
    });
    // Region Completion — standalone panel, only offered when the current
    // plugin's own has_state_bars gate (set elsewhere) has actually shown it.
    const bars=document.getElementById('bars-row');
    if (bars && bars.style.display!=='none'){
      const h=document.createElement('div');
      h.className='panels-menu-group'; h.textContent='Other';
      menu.appendChild(h);
      addRow('bars-row','Region Completion');
    }
  }

  document.getElementById('btn-panels-toggle')?.addEventListener('click',e=>{
    e.stopPropagation();
    const menu=document.getElementById('panels-menu'); if(!menu) return;
    const opening=!menu.classList.contains('open');
    menu.classList.toggle('open',opening);
    if (opening) buildPanelsMenu();
  });
  document.addEventListener('click',e=>{
    const menu=document.getElementById('panels-menu');
    if (!menu||!menu.classList.contains('open')) return;
    if (!menu.contains(e.target) && e.target.id!=='btn-panels-toggle') menu.classList.remove('open');
  });

  const REORDER_SECTIONS=[
    {sel:'.spark-row',          key:'vkca_layout_spark'},
    {sel:'.info-panels-row',    key:'vkca_layout_info'},
    {sel:'.extra-analytics-row',key:'vkca_layout_ea'},
  ];
  const GAUGE_LAYOUT_KEY='vkca_layout_gauge';

  function initReorder(){
    REORDER_SECTIONS.forEach(({sel,key})=>{
      const el=document.querySelector(sel); if(!el) return;
      Array.from(el.children).forEach(addPopoutButton);
      Array.from(el.children).forEach(addHideButton);
      markDraggable(el);
      applyTileOrder(el,key);
      setupReorder(el,key);
    });
    applyPopoutFilter();
    applyHiddenTiles();
  }
  initReorder();

  document.getElementById('btn-reset-layout')?.addEventListener('click',()=>{
    REORDER_SECTIONS.forEach(({key})=>{ try{ localStorage.removeItem(key); }catch{} });
    try{ localStorage.removeItem(GAUGE_LAYOUT_KEY); }catch{}
    try{ localStorage.removeItem(HIDDEN_TILES_KEY); }catch{}
    location.reload();
  });

  // ══ MINI HUD (own popped-out window, /hud) ══════════════════════════════════
  // Path-based, not query-string — see index.html bootstrap script for why.
  const HUD_MODE=location.pathname==='/hud';

  // ══ OPERATOR HUD (own popped-out window, /operator_hud) ═════════════════════
  const OPERATOR_HUD_MODE=location.pathname==='/operator_hud';

  // ══ SPECTATOR (read-only LAN viewer, /spectator) ═════════════════════════════
  const SPECTATOR_MODE=location.pathname==='/spectator';

  // Same 8-colour identity palette as fatigue.js's OP_PALETTE — an operator
  // reads as the same colour on the Fatigue tab and this HUD.
  const OPERATOR_HUD_PALETTE=['#00d4aa','#f0c040','#ff6b35','#a78bfa',
                              '#60a5fa','#34d399','#f87171','#fbbf24'];

  function fmtOpHudTime(m){
    const h=Math.floor(m/60), mm=Math.round(m%60);
    return h ? `${h}h ${mm}m` : `${mm}m`;
  }

  // Cards rebuild wholesale every snapshot (see updateOperatorHud below), so
  // without this an entrance animation would replay on every op's card on
  // every poll, not just when an operator genuinely first appears — tracks
  // which operator names have already been seen so only a real newcomer
  // (someone starting their first session) gets the entrance animation.
  let _seenOperators=new Set();

  // Cards are rebuilt wholesale every snapshot (innerHTML='' + forEach +
  // createElement) rather than incrementally diffed — same idiom fatigue.js's
  // renderOpCards() and pace.js's roster tables already use for "N dynamic
  // items"; a handful of operator cards makes a full rebuild cheap and this
  // codebase has no precedent for anything fancier.
  function updateOperatorHud(snap,containerId){
    const wrap=document.getElementById(containerId||'operator-hud-cards'); if (!wrap) return;
    const ops=snap?.operator_times||[];
    wrap.innerHTML='';
    if (!ops.length){
      wrap.innerHTML=`<div style="color:var(--muted);font-family:var(--font-mono);font-size:0.85em;padding:8px">
        No operator data yet.</div>`;
      return;
    }
    // Match each operator's own card to a live radio by callsign — N1MM+'s
    // RadioInfo OpCall field vs. the DXLOG Operator column, both already
    // upper-cased server-side. Exact match only (no portable-suffix
    // normalisation): a near-miss just means no badge on that card, which
    // is a safe degradation, not a crash. Blank/placeholder operator names
    // ("—", used when the DXLOG Operator column is empty) never match.
    const radios=Object.values(snap?.radio_info?.all||{});
    const radioForOp=(operator)=>{
      const call=(operator||'').trim().toUpperCase();
      if (!call || call==='—') return null;
      return radios.find(r=>r.op_call===call) || null;
    };
    ops.forEach((op,i)=>{
      const col=OPERATOR_HUD_PALETTE[i%OPERATOR_HUD_PALETTE.length];
      const onPct=op.span_minutes>0 ? Math.round(op.on_minutes/op.span_minutes*100) : 0;
      const div=document.createElement('div');
      div.className='fatigue-card';
      const opKey=(op.operator||'').trim().toUpperCase();
      if (opKey && opKey!=='—' && !_seenOperators.has(opKey)){
        div.classList.add('op-card-enter');
        _seenOperators.add(opKey);
      }
      div.style.borderTopColor=col;
      div.style.boxShadow=`0 0 20px -8px ${col}, 0 2px 8px -2px rgba(0,0,0,.5)`;
      const r=window.VKA.formatRadio(radioForOp(op.operator));
      const radioBadge=r ? `<span class="badge op-freq-badge${r.stale?' op-freq-badge--stale':''}">
          <span class="band-chip" style="background:${r.bandColor}30;color:${r.bandColor}">${r.band}</span>
          ${r.freqStr} MHz${r.modeStr?' '+escapeHtml(r.modeStr):''}</span>` : '';
      // op.operator is free-text from the DXLOG Operator column — same
      // log-derived-text category as callsigns/comments elsewhere, escaped
      // before going into innerHTML (matches fatigue.js's renderOpCards()).
      div.innerHTML=`
        <div class="fatigue-op" style="color:${col}">${escapeHtml(op.operator||'—')}${radioBadge}</div>
        <div class="fatigue-stat-row">
          <div class="fatigue-stat">
            <div class="fatigue-stat-val">${(op.qsos||0).toLocaleString()}</div>
            <div class="fatigue-stat-label">QSOs</div>
          </div>
          <div class="fatigue-stat">
            <div class="fatigue-stat-val" style="color:${T.accent3}">${op.current_hour_rate||0}</div>
            <div class="fatigue-stat-label">Q/hr now</div>
          </div>
          <div class="fatigue-stat">
            <div class="fatigue-stat-val" style="color:${T.green}">${fmtOpHudTime(op.on_minutes||0)}</div>
            <div class="fatigue-stat-label">On Air</div>
          </div>
        </div>
        <div class="fatigue-prog-wrap">
          <div class="fatigue-prog-bar" style="width:${onPct}%;background:${col}"></div>
        </div>
        <div class="fatigue-prog-label">${onPct}% on-air efficiency</div>
        <canvas class="operator-hud-spark"></canvas>`;
      wrap.appendChild(div);
      drawSparkline(div.querySelector('canvas'), op.hourly||[], col);
    });
  }

  // REMAIN ticks down live between snapshots (same "absolute target + local
  // 1s interval" approach as tickSinceLastQso above) rather than only jumping
  // in whole-minute steps whenever a snapshot happens to push in.
  let _hudState=null;    // session_status.state from the most recent snapshot
  let _hudTarget=null;   // Date — contest start (state 'pre') or end (state 'live')

  // Same on-air efficiency formula as the Fatigue tile/tab: most-active
  // operator's on-air minutes as a % of their first-to-last-QSO span.
  // Shared by updateHud() (the big number) and trackHudSparklines() (the
  // trend line) so the two can't silently drift out of sync.
  function computeHudEff(snap){
    const top=(snap?.operator_times||[])[0];
    return top?.span_minutes>0 ? Math.round(top.on_minutes/top.span_minutes*100) : null;
  }

  function updateHud(snap){
    const pb=snap?.personal_bests||{};
    const ss=snap?.session_status||{};
    const scoreEl  =document.getElementById('hud-score');
    const multsEl  =document.getElementById('hud-mults');
    const rateEl   =document.getElementById('hud-rate');
    const effEl    =document.getElementById('hud-eff');
    const sessionEl=document.getElementById('hud-session');
    if (scoreEl) scoreEl.textContent=(snap?.score||0).toLocaleString('en-AU');
    if (multsEl) multsEl.textContent=(snap?.band_mults||snap?.worked||0).toLocaleString('en-AU');
    if (rateEl)  rateEl.textContent=(pb.current_hour_rate||0)+'/hr';
    if (sessionEl) sessionEl.textContent=ss.session_label||'—';
    if (effEl){
      const eff=computeHudEff(snap);
      effEl.textContent = eff==null ? '—' : eff+'%';
      effEl.style.color = eff==null ? T.muted : (eff>=70?T.green:eff>=40?T.accent3:T.red);
    }
    updateHudRadio(snap);
    _hudState=ss.state||null;
    const targetDt = ss.state==='pre' ? ss.start_dt : ss.state==='live' ? ss.end_dt : null;
    _hudTarget = targetDt ? new Date(targetDt+'Z') : null;   // naive UTC, like _lastQsoTime above
    tickHudRemain();
  }

  // Compact 2-line RADIO tile — band+freq on the .hud-val line (same big
  // style as every other field), mode/radio# smaller underneath, rather
  // than three separate tiles: one logical reading, and the HUD bar is
  // already sized for up to 7 fields (see style.css's own comment on
  // .hud-item) so a single combined tile keeps this the 8th without
  // pushing the window wider.
  function updateHudRadio(snap){
    const valEl=document.getElementById('hud-radio');
    const subEl=document.getElementById('hud-radio-sub');
    if (!valEl) return;
    const r=window.VKA.formatRadio(snap?.radio_info?.own);
    if (!r){ valEl.textContent='—'; valEl.style.color=T.muted; if(subEl) subEl.textContent=''; return; }
    valEl.innerHTML=`<span class="band-chip" style="background:${r.bandColor}30;color:${r.bandColor}">${r.band}</span> ${r.freqStr} MHz`;
    valEl.style.color=T.accent;
    if (subEl) subEl.textContent = r.modeStr ? `${r.modeStr} · RADIO ${r.radioNr}` : `RADIO ${r.radioNr}`;
  }

  // ══ SPECTATOR: read-only scoreboard for a LAN viewer at /spectator ══════════
  // Reuses the same snapshot fields updateHud()/updateHudRadio() already
  // render — no new calculation logic, just a simpler 4-tile display with no
  // sparklines/countdown/field-picker (this is a plain browser tab on
  // someone else's device, not a pywebview popout window).

  // Tweens a tile's number with the same ease-out cubic the Overview gauges
  // use (see animGauge). The very first call for a given id just snaps to
  // the value with no animation — counting up from 0 on page load (a
  // contest already hours in) would just be a slow, meaningless wait.
  // Shared by the Spectator tiles (animateSpectatorNumber below) and the
  // Overview spark-hero numbers (see updateSparklines' apply()); opts.onRise
  // lets a caller add its own "value just went up" cue — the spectator
  // tiles flash their own card, Overview's already gets that from
  // checkCelebrations' gauge-row pulse, so it opts out.
  const _numAnimState={};
  function animateNumber(id,target,opts){
    const el=document.getElementById(id); if(!el) return;
    const fmt=(opts&&opts.fmt)||(n=>Math.round(n).toLocaleString('en-AU'));
    const suffix=(opts&&opts.suffix)||'';
    let st=_numAnimState[id];
    if (!st){
      st=_numAnimState[id]={cur:target,raf:null};
      el.textContent=fmt(target)+suffix;
      return;
    }
    if (target>st.cur && opts&&opts.onRise) opts.onRise(el);
    if (st.raf) cancelAnimationFrame(st.raf);
    const from=st.cur,t0=performance.now();
    function step(now){
      const t=Math.min((now-t0)/700,1);
      const val=from+(target-from)*(1-Math.pow(1-t,3));
      el.textContent=fmt(val)+suffix;
      st.cur=val;
      if(t<1) st.raf=requestAnimationFrame(step);
      else{st.cur=target;st.raf=null;el.textContent=fmt(target)+suffix;}
    }
    st.raf=requestAnimationFrame(step);
  }
  function animateSpectatorNumber(id,target,opts){
    animateNumber(id,target,Object.assign({},opts,
      {onRise:el=>flashEl(el.closest('.spectator-item'),'flash-new-qso',900)}));
  }

  function updateSpectator(snap){
    const pb=snap?.personal_bests||{};
    const nameEl =document.getElementById('spectator-contest');
    animateSpectatorNumber('spectator-score',snap?.score||0);
    animateSpectatorNumber('spectator-mults',snap?.band_mults||snap?.worked||0);
    animateSpectatorNumber('spectator-rate',pb.current_hour_rate||0,{suffix:'/hr'});
    if (nameEl && snap?._plugin_name) nameEl.textContent=snap._plugin_name;
    const valEl=document.getElementById('spectator-radio');
    const subEl=document.getElementById('spectator-radio-sub');
    if (valEl){
      const r=window.VKA.formatRadio(snap?.radio_info?.own);
      if (!r){ valEl.textContent='—'; if(subEl) subEl.textContent=''; }
      else {
        valEl.innerHTML=`<span class="band-chip" style="background:${r.bandColor}30;color:${r.bandColor}">${r.band}</span> ${r.freqStr} MHz`;
        if (subEl) subEl.textContent = r.modeStr || '';
      }
    }
    // Full per-operator table — same cards/data as the Operator HUD
    // (see updateOperatorHud above), just pointed at this page's own
    // container instead of the popout window's.
    updateOperatorHud(snap,'spectator-operator-cards');
  }

  // ── HUD mini sparklines ────────────────────────────────────────────────
  // Score/Mults/Rate/Eff each get a tiny trend line — Remain/Session/Last
  // QSO are excluded since they're either a countdown (trivially always
  // falling) or not a numeric trend at all. The server has no historical
  // series for current_hour_rate or on-air efficiency (only Overview's
  // hour-bucketed sparklines, which don't cover those two), so this keeps
  // its own small rolling client-side history instead of reusing snap data.
  const HUD_SPARK_MAX=40;
  const HUD_SPARK_KEYS=['score','mults','rate','eff'];
  let _hudHistory={};
  function resetHudSparklines(){
    _hudHistory={score:[],mults:[],rate:[],eff:[]};
  }
  resetHudSparklines();

  // One identity colour per stat, matching Overview's own sparkline
  // palette exactly (makeSparkline() above: qsos=accent, score=accent3,
  // mults=accent2) so a user who already knows that colour language reads
  // the HUD's trends the same way. Eff has no Overview sparkline
  // equivalent to match, so it gets green — distinct from the other three
  // and consistent with eff's own "healthy" value-colour convention.
  const HUD_SPARK_COLOURS={score:()=>T.accent3,mults:()=>T.accent2,rate:()=>T.accent,eff:()=>T.green};

  // Same visual language as Overview's makeSparkline(): a soft drop-shadow
  // glow on the canvas element itself, a gradient fill fading out under a
  // smoothed line, and a highlighted endpoint. Hand-rolled rather than a
  // Chart.js instance per stat — four Chart.js instances in a window this
  // size is unnecessary overhead for what's a ~50×14px line, and this also
  // needs to resize on the fly when the HUD switches orientation (see
  // HUD_ORIENTATIONS below), which is simpler to do by hand than by
  // re-instantiating four chart objects on every layout change.
  // Canvas-keyed animation state for the newest-point draw-in (see
  // drawSparkline below) — a WeakMap so a canvas that's torn down (e.g. an
  // operator card rebuilt wholesale next snapshot) doesn't leak state.
  const _sparkAnimState=new WeakMap();

  // Redraws the newest point's height smoothly from its previous value
  // instead of snapping straight to it — same ease-out cubic/duration
  // family as the gauge and Spectator-tile number tweens (animGauge,
  // animateSpectatorNumber) for a consistent feel across the app. Only the
  // last point's *value* is interpolated (its x-position is always the
  // rightmost pixel regardless), which reads as the newest tick "settling
  // into place" rather than a full re-layout of the whole trend line.
  function drawSparkline(canvas,values,colour){
    if (!canvas) return;
    const idx=values.map((v,i)=>({v,i})).filter(p=>p.v!=null);
    if (idx.length<2){ _renderSparklineFrame(canvas,values,colour); return; }
    const lastPoint=idx[idx.length-1];
    let st=_sparkAnimState.get(canvas);
    if (!st){
      // First time this canvas has ever been drawn — snap straight to the
      // real data with no animation, same rationale as the number tweens:
      // counting/growing in from nothing on first load is just a slow,
      // meaningless wait, not a meaningful "value changed" cue.
      st={lastVal:lastPoint.v,raf:null};
      _sparkAnimState.set(canvas,st);
      _renderSparklineFrame(canvas,values,colour);
      return;
    }
    if (st.raf) cancelAnimationFrame(st.raf);
    const fromVal=st.lastVal,targetVal=lastPoint.v,t0=performance.now();
    function step(now){
      const t=Math.min((now-t0)/350,1);
      const animVal=fromVal+(targetVal-fromVal)*(1-Math.pow(1-t,3));
      const animValues=values.slice();
      animValues[lastPoint.i]=animVal;
      _renderSparklineFrame(canvas,animValues,colour);
      if (t<1) st.raf=requestAnimationFrame(step);
      else{st.raf=null;st.lastVal=targetVal;_renderSparklineFrame(canvas,values,colour);}
    }
    st.raf=requestAnimationFrame(step);
  }

  function _renderSparklineFrame(canvas,values,colour){
    // Canvas size is CSS-driven (.hud-spark / html.hud-vertical .hud-spark)
    // so it can change shape when the orientation toggle flips — read the
    // rendered box size fresh each draw rather than trusting the width/
    // height HTML attributes, which only reflect the very first layout.
    const dpr=window.devicePixelRatio||1;
    const cssW=canvas.clientWidth||56, cssH=canvas.clientHeight||14;
    canvas.width=cssW*dpr; canvas.height=cssH*dpr;
    const ctx=canvas.getContext('2d'); if (!ctx) return;
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,cssW,cssH);
    canvas.style.filter=`drop-shadow(0 0 3px ${colour}80)`;

    const idx=values.map((v,i)=>({v,i})).filter(p=>p.v!=null);
    if (idx.length<2) return;
    const vals=idx.map(p=>p.v);
    const min=Math.min(...vals),max=Math.max(...vals);
    const range=(max-min)||1;
    const coords=idx.map(({v,i})=>[
      (i/(values.length-1))*(cssW-2)+1,
      cssH-1-((v-min)/range)*(cssH-3)-1,
    ]);

    const tracePath=()=>{
      ctx.beginPath();
      ctx.moveTo(coords[0][0],coords[0][1]);
      for (let i=1;i<coords.length-1;i++){
        const [x0,y0]=coords[i],[x1,y1]=coords[i+1];
        ctx.quadraticCurveTo(x0,y0,(x0+x1)/2,(y0+y1)/2);
      }
      const last=coords[coords.length-1];
      ctx.lineTo(last[0],last[1]);
    };

    // Gradient fill under the curve — same stop pattern as Overview's
    // makeSparkline() (colour+alpha at top fading to transparent).
    tracePath();
    const last=coords[coords.length-1];
    ctx.lineTo(last[0],cssH);
    ctx.lineTo(coords[0][0],cssH);
    ctx.closePath();
    const grad=ctx.createLinearGradient(0,0,0,cssH);
    grad.addColorStop(0,   colour+'59');
    grad.addColorStop(0.65,colour+'14');
    grad.addColorStop(1,   colour+'00');
    ctx.fillStyle=grad; ctx.fill();

    // Stroke the line itself on top (the fill above closed the path down
    // to the bottom edge, so it's redrawn here rather than reused).
    tracePath();
    ctx.strokeStyle=colour; ctx.lineWidth=1.4;
    ctx.lineCap='round'; ctx.lineJoin='round'; ctx.stroke();

    // Endpoint dot — same "only the meaningful point gets emphasis"
    // convention as Overview's peak-hour marker on the Mults/Hour chart.
    ctx.beginPath();
    ctx.arc(last[0],last[1],1.6,0,Math.PI*2);
    ctx.fillStyle=colour; ctx.fill();
  }

  function trackHudSparklines(snap){
    if (!snap) return;
    const pb=snap.personal_bests||{};
    const vals={
      score: snap.score||0,
      mults: snap.band_mults||snap.worked||0,
      rate:  pb.current_hour_rate||0,
      eff:   computeHudEff(snap),
    };
    HUD_SPARK_KEYS.forEach(key=>{
      const hist=_hudHistory[key];
      hist.push(vals[key]);
      if (hist.length>HUD_SPARK_MAX) hist.shift();
      drawSparkline(document.getElementById('hud-spark-'+key),hist,HUD_SPARK_COLOURS[key]());
    });
  }

  function tickHudRemain(){
    const remEl=document.getElementById('hud-remain'); if(!remEl) return;
    if (_hudState==='over'){ remEl.textContent='0:00'; remEl.style.color=T.muted; return; }
    if (!_hudState || !_hudTarget){ remEl.textContent='—'; remEl.style.color=T.muted; return; }
    const secs=(_hudTarget.getTime()-Date.now())/1000;
    remEl.textContent=fmtCountdown(secs);
    remEl.style.color = secs<600?T.red:secs<1800?T.accent3:T.accent;
  }
  setInterval(tickHudRemain,1000);

  // ── HUD orientation toggle (horizontal ⇄ vertical) ────────────────────────
  // The window's *initial* size still comes from create_window() in
  // server.py, which has no way to know this client-side preference before
  // the window exists — so a HUD reopened in vertical mode briefly shows
  // at the horizontal window size until this script runs and calls
  // api.resize(). Not perfectly seamless, but a one-frame pop beats
  // threading the preference through settings.json just to avoid it.
  if (HUD_MODE) {
    const HUD_ORIENTATION_KEY='vkca_hud_orientation';
    const HUD_ORIENTATIONS={
      horizontal:{width:780,height:210,next:'vertical',  icon:'⇕',title:'Switch to vertical layout'},
      vertical:  {width:190,height:560,next:'horizontal',icon:'⇔',title:'Switch to horizontal layout'},
    };
    let _hudOrientation='horizontal';
    try{ _hudOrientation=localStorage.getItem(HUD_ORIENTATION_KEY)||'horizontal'; }catch{}

    function applyHudOrientation(mode){
      document.documentElement.classList.toggle('hud-vertical',mode==='vertical');
      const btn=document.getElementById('hud-orientation');
      const cfg=HUD_ORIENTATIONS[mode];
      if (btn && cfg){ btn.textContent=cfg.icon; btn.title=cfg.title; }
      // Sparkline canvases are sized by CSS, which just changed — redraw
      // against the new box size rather than leaving them stretched/tiny
      // until the next snapshot happens to tick in.
      HUD_SPARK_KEYS.forEach(key=>{
        drawSparkline(document.getElementById('hud-spark-'+key),_hudHistory[key],HUD_SPARK_COLOURS[key]());
      });
    }
    applyHudOrientation(_hudOrientation);

    function wireHudOrientationToggle(api){
      document.getElementById('hud-orientation')?.addEventListener('click', async e=>{
        e.stopPropagation();
        const next=HUD_ORIENTATIONS[_hudOrientation].next;
        const cfg=HUD_ORIENTATIONS[next];
        _hudOrientation=next;
        try{ localStorage.setItem(HUD_ORIENTATION_KEY,next); }catch{}
        applyHudOrientation(next);
        if (api && api.resize) { try{ await api.resize(cfg.width,cfg.height); }catch{} }
      });
    }
    if (window.pywebview) wireHudOrientationToggle(window.pywebview.api);
    else window.addEventListener('pywebviewready', ()=>wireHudOrientationToggle(window.pywebview.api));

    // The window's *actual current* size is just whatever it was last
    // left at (create_window()'s own default, or a previous session's
    // toggle) — not necessarily whatever this session's persisted
    // preference says it should be. Resize to match on every open,
    // regardless of which orientation that turns out to be, once the API
    // is ready — otherwise a stale mismatch (e.g. content re-flowed to
    // horizontal CSS but the window itself still narrow from a previous
    // vertical session) leaves the layout looking broken until the next
    // manual toggle.
    const doInitialResize=api=>{
      if (!api || !api.resize) return;
      const cfg=HUD_ORIENTATIONS[_hudOrientation];
      api.resize(cfg.width,cfg.height).catch?.(()=>{});
    };
    if (window.pywebview) doInitialResize(window.pywebview.api);
    else window.addEventListener('pywebviewready', ()=>doInitialResize(window.pywebview.api));
  }

  // ── HUD field picker: ⚙ button (discoverable) + right-click (fast path) ──
  // Same localStorage-backed show/hide pattern as the Overview "☰ Panels"
  // menu (see .tile-hidden), scoped to this tiny window's own field set
  // rather than shared with the main window's tile visibility.
  if (HUD_MODE) {
    const HUD_FIELDS_KEY='vkca_hud_fields';
    const HUD_FIELD_LABELS={score:'Score',mults:'Mults',rate:'Rate',eff:'On-air %',
                             remain:'Remaining',session:'Session',since:'Last QSO',
                             radio:'Radio Freq/Band'};
    const HUD_FIELD_DESC={
      score:  'Total contest score',
      mults:  'Multiplier count driving your score',
      rate:   'QSOs worked in the current hour',
      eff:    "Top operator's on-air time as % of their session span",
      remain: 'Time left in the current session',
      session:'Current session or block label',
      since:  'Time since your last logged QSO',
      radio:  "Live band/frequency/mode from N1MM+'s RadioInfo broadcast",
    };
    let _hudHidden;
    try{ _hudHidden=new Set(JSON.parse(localStorage.getItem(HUD_FIELDS_KEY)||'[]')); }
    catch{ _hudHidden=new Set(); }
    const saveHudHidden=()=>{ try{ localStorage.setItem(HUD_FIELDS_KEY,JSON.stringify(Array.from(_hudHidden))); }catch{} };

    function applyHudFieldVisibility(){
      document.querySelectorAll('#hud-bar .hud-item[data-hud-key]').forEach(el=>{
        el.classList.toggle('tile-hidden',_hudHidden.has(el.dataset.hudKey));
      });
    }
    applyHudFieldVisibility();

    const hudMenu = document.getElementById('hud-menu');

    function openHudMenu(x,y){
      if (!hudMenu) return;
      hudMenu.innerHTML='';
      document.querySelectorAll('#hud-bar .hud-item[data-hud-key]').forEach(el=>{
        const key=el.dataset.hudKey;
        const row=document.createElement('label');
        row.className='panels-menu-row panels-menu-row--desc';
        const cb=document.createElement('input');
        cb.type='checkbox'; cb.checked=!_hudHidden.has(key);
        cb.addEventListener('change',()=>{
          if (cb.checked) _hudHidden.delete(key); else _hudHidden.add(key);
          saveHudHidden(); applyHudFieldVisibility();
        });
        const text=document.createElement('div');
        text.className='pmr-text';
        const title=document.createElement('div');
        title.className='pmr-title';
        title.textContent=HUD_FIELD_LABELS[key]||key;
        text.appendChild(title);
        if (HUD_FIELD_DESC[key]){
          const desc=document.createElement('div');
          desc.className='pmr-desc';
          desc.textContent=HUD_FIELD_DESC[key];
          text.appendChild(desc);
        }
        row.appendChild(cb);
        row.appendChild(text);
        hudMenu.appendChild(row);
      });
      // The CSS max-height/min-width are generous static values for the
      // HUD's default horizontal size, but both the vertical orientation
      // (as narrow as 150px) and manual resizing can make the window
      // smaller than that in either dimension — recompute against the
      // *actual* current window size so the menu always fits inside it
      // (scrolling internally via its own overflow-y:auto) instead of
      // getting clipped by the window's own edge, which no amount of CSS
      // overflow can undo.
      const availW=Math.max(120,window.innerWidth-8);
      const availH=Math.max(60,window.innerHeight-8);
      hudMenu.style.maxWidth=availW+'px';
      hudMenu.style.maxHeight=availH+'px';
      const left=Math.max(4,Math.min(x,window.innerWidth-availW-4));
      const top =Math.max(4,Math.min(y,window.innerHeight-availH));
      hudMenu.style.left=left+'px';
      hudMenu.style.top =top+'px';
      hudMenu.classList.add('open');
    }

    document.getElementById('hud-settings')?.addEventListener('click', e=>{
      e.stopPropagation();
      const r=e.currentTarget.getBoundingClientRect();
      openHudMenu(r.left,r.bottom+4);
    });
    document.getElementById('hud-bar')?.addEventListener('contextmenu', e=>{
      e.preventDefault();
      openHudMenu(e.clientX,e.clientY);
    });
    document.addEventListener('click', e=>{
      if (!hudMenu||!hudMenu.classList.contains('open')) return;
      if (!hudMenu.contains(e.target) && e.target.id!=='hud-settings') hudMenu.classList.remove('open');
    });

    // One-time callout: a static ⚙ icon in the corner turned out to not be
    // enough on its own for people to discover that the field set is
    // customisable at all. Points directly at the button, explains what it
    // does in words, and is gone for good (this window/profile) once
    // dismissed — by clicking it, clicking the button itself, or after 8s.
    const HUD_HINT_SEEN_KEY='vkca_hud_hint_seen';
    if (!localStorage.getItem(HUD_HINT_SEEN_KEY)) {
      const hint=document.createElement('div');
      hint.id='hud-hint';
      hint.textContent='⚙ Click to add/remove stats';
      document.getElementById('hud-bar')?.appendChild(hint);
      const dismissHint=()=>{
        hint.remove();
        try{ localStorage.setItem(HUD_HINT_SEEN_KEY,'1'); }catch{}
      };
      hint.addEventListener('click', e=>{ e.stopPropagation(); dismissHint(); });
      document.getElementById('hud-settings')?.addEventListener('click', dismissHint, {once:true});
      setTimeout(dismissHint, 8000);
    }
  }

  document.getElementById('btn-hud')?.addEventListener('click', async ()=>{
    try {
      const res=await fetch('/api/hud',{method:'POST'});
      const data=await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error||'failed');
    } catch {
      window.open('/hud','vkca_hud','width=760,height=130,resizable=yes');
    }
  });

  document.getElementById('btn-operator-hud')?.addEventListener('click', async ()=>{
    try {
      const res=await fetch('/api/operator_hud',{method:'POST'});
      const data=await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error||'failed');
    } catch {
      window.open('/operator_hud','vkca_operator_hud','width=900,height=280,resizable=yes');
    }
  });

  // ══ REPLAY SCRUBBER (+ autoplay) ════════════════════════════════════════════
  let _replaying=false, _lastReplaySnap=null, _scrubStartMs=null, _scrubEndMs=null;
  let _playTimer=null, _playing=false;

  const replayBar       = document.getElementById('replay-bar');
  const replaySlider    = document.getElementById('replay-slider');
  const replayTimeEl    = document.getElementById('replay-time');
  const replaySpeedSel  = document.getElementById('replay-speed');
  const replayToggleBtn = document.getElementById('btn-replay-toggle');
  const replayPlayBtn   = document.getElementById('btn-replay-play');
  const replayLiveBtn   = document.getElementById('btn-replay-live');

  function fmtScrubTime(ms){
    return new Date(ms).toISOString().slice(0,16).replace('T',' ')+' UTC';
  }

  async function openReplay(){
    if (!replayBar||!replaySlider) return;
    try {
      const res=await fetch('/api/scrub_range');
      const data=await res.json();
      if (!data.start||!data.end) return;
      _scrubStartMs=new Date(data.start+'Z').getTime();
      _scrubEndMs  =new Date(data.end+'Z').getTime();
      replaySlider.value=0;
      replayTimeEl.textContent=fmtScrubTime(_scrubStartMs);
      replayBar.style.display='flex';
    } catch(e){ console.warn('scrub_range failed:',e); }
  }

  function stopPlayback(){
    if (_playTimer) { clearInterval(_playTimer); _playTimer=null; }
    _playing=false;
    if (replayPlayBtn) replayPlayBtn.textContent='▶';
  }

  function closeReplay(){
    stopPlayback();
    _replaying=false; _lastReplaySnap=null;
    if (replayBar) replayBar.style.display='none';
    const snap=window.VKA.lastSnap(); if (snap) render(snap);
  }

  // Fetches the snapshot at `frac` (0..1 across the contest's QSO range) and
  // renders it. Shared by manual slider release and the autoplay timer.
  let _scrubInFlight=false;
  async function scrubToFrac(frac){
    if (_scrubStartMs==null || _scrubInFlight) return;
    _scrubInFlight=true;
    frac=Math.max(0,Math.min(1,frac));
    if (replaySlider) replaySlider.value=Math.round(frac*1000);
    const ms=_scrubStartMs+(_scrubEndMs-_scrubStartMs)*frac;
    if (replayTimeEl) replayTimeEl.textContent=fmtScrubTime(ms);
    const iso=new Date(ms).toISOString().slice(0,19);   // naive — matches server format
    try {
      const res=await fetch('/api/scrub?t='+encodeURIComponent(iso));
      const data=await res.json();
      if (data.error) return;
      _replaying=true; _lastReplaySnap=data;
      render(data);
    } catch(e){ console.warn('scrub failed:',e); }
    finally { _scrubInFlight=false; }
  }

  const REPLAY_TICK_MS=250;   // short tick → smooth motion at every speed, incl. real-time "Live"

  function startPlayback(){
    if (_scrubStartMs==null || _playing) return;
    // Replay opens parked at the live/end position — pressing Play from there
    // would immediately satisfy the "reached the end" check on the very first
    // tick and stop again with no visible motion. Restart from the beginning
    // instead, so Play always does something.
    if (Number(replaySlider?.value||0)>=999) scrubToFrac(0);
    _playing=true;
    if (replayPlayBtn) replayPlayBtn.textContent='⏸';
    _playTimer=setInterval(async ()=>{
      // replay-speed value = contest-seconds advanced per real second (1 = Live/real-time pace)
      const speedX   =Number(replaySpeedSel?.value||60);
      const stepFrac =(speedX*REPLAY_TICK_MS)/(_scrubEndMs-_scrubStartMs);
      const frac     =Number(replaySlider?.value||0)/1000 + stepFrac;
      await scrubToFrac(frac);
      if (frac>=1) stopPlayback();
    }, REPLAY_TICK_MS);
  }

  replayToggleBtn?.addEventListener('click',()=>{
    const open=replayBar && replayBar.style.display!=='none';
    if (open) closeReplay(); else openReplay();
  });
  replayLiveBtn?.addEventListener('click', closeReplay);
  replayPlayBtn?.addEventListener('click', ()=>{ _playing?stopPlayback():startPlayback(); });

  replaySlider?.addEventListener('input',()=>{
    if (_scrubStartMs==null) return;
    if (_playing) stopPlayback();
    const ms=_scrubStartMs+(_scrubEndMs-_scrubStartMs)*(replaySlider.value/1000);
    replayTimeEl.textContent=fmtScrubTime(ms);
  });

  replaySlider?.addEventListener('change',()=>{
    if (_scrubStartMs==null) return;
    scrubToFrac(Number(replaySlider.value)/1000);
  });

  // ── "What if?" — simulate working a missing multiplier ──────────────────
  const whatifBar      = document.getElementById('whatif-bar');
  const whatifToggleBtn= document.getElementById('btn-whatif-toggle');
  const whatifMultSel  = document.getElementById('whatif-mult-select');
  const whatifBandSel  = document.getElementById('whatif-band-select');
  const whatifZoneInp  = document.getElementById('whatif-zone-input');
  const whatifSimBtn   = document.getElementById('btn-whatif-simulate');
  const whatifResultEl = document.getElementById('whatif-result');

  async function openWhatif(){
    if (!whatifBar) return;
    whatifBar.style.display='flex';
    whatifZoneInp.style.display = _usesCqZoneScoring ? '' : 'none';
    whatifResultEl.textContent = '';
    try {
      const res = await fetch('/api/missing');
      const rows = await res.json();
      whatifMultSel.innerHTML = '<option value="">— missing mult —</option>' +
        rows.map(r=>`<option value="${r.mult}">${r.mult} (${r.region})</option>`).join('');
    } catch(e){ console.warn('missing mults load failed:',e); }
    // Band choices come from the plugin's band_list() (see /api/plugin_meta),
    // so a contest that excludes e.g. WARC bands doesn't offer a band its
    // own rules don't allow.
    whatifBandSel.innerHTML = '<option value="">— band —</option>' +
      _whatifBands.map(b=>`<option value="${b}">${b.toLowerCase()}</option>`).join('');
  }
  function closeWhatif(){ if (whatifBar) whatifBar.style.display='none'; }
  function resetWhatif(){
    if (whatifMultSel)  whatifMultSel.innerHTML  = '<option value="">— missing mult —</option>';
    if (whatifBandSel)  whatifBandSel.innerHTML  = '<option value="">— band —</option>';
    if (whatifZoneInp)  whatifZoneInp.value      = '';
    if (whatifResultEl) whatifResultEl.textContent = '';
  }

  whatifToggleBtn?.addEventListener('click',()=>{
    const open = whatifBar && whatifBar.style.display!=='none';
    if (open) closeWhatif(); else openWhatif();
  });

  whatifSimBtn?.addEventListener('click', async ()=>{
    const mult = whatifMultSel?.value, band = whatifBandSel?.value;
    if (!mult || !band) { whatifResultEl.textContent='Pick a mult and band first.'; return; }
    whatifSimBtn.disabled = true;
    try {
      const body = { mult, band };
      if (_usesCqZoneScoring && whatifZoneInp?.value) body.zone = whatifZoneInp.value;
      const res  = await fetch('/api/replay_whatif', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.error) { whatifResultEl.textContent = data.error; whatifResultEl.style.color = T.red; return; }
      whatifResultEl.style.color = T.green;
      let txt = `+${Math.round(data.pts_delta).toLocaleString()} pts` +
                (data.is_new_mult ? ', +1 mult' : ' (already worked)');
      if (data.caveat) txt += `  —  ${data.caveat}`;
      whatifResultEl.textContent = txt;
    } catch(e){ whatifResultEl.textContent='Simulation failed.'; console.warn('what-if simulate failed:',e); }
    finally { whatifSimBtn.disabled = false; }
  });

  // ══ COSMETIC LIVE FEEDBACK ══════════════════════════════════════════════════
  // Personal-best flash / new-QSO pulse / score-milestone burst. Only ever
  // called from the live vka:snapshot path (not render()'s replay/tab-switch
  // callers) — replay scrubbing jumps around in time, which would otherwise
  // "celebrate" past milestones out of context or fire on a scrub going
  // backward.
  let _celebPrevTotal=null, _celebPrevBestRate=null;
  const _celebMilestones=new Set();
  const SCORE_MILESTONES=[100,250,500,1000,2500,5000,10000,25000,50000,
                           100000,250000,500000,1000000,2500000,5000000,10000000];

  function resetCelebrations(){
    _celebPrevTotal=null; _celebPrevBestRate=null; _celebMilestones.clear();
  }

  function flashEl(el,cls,ms){
    if (!el) return;
    el.classList.remove(cls); void el.offsetWidth;   // restart if already mid-flash
    el.classList.add(cls);
    setTimeout(()=>el.classList.remove(cls),ms);
  }

  function showMilestoneBurst(milestone,host){
    if (!host) return;
    host.querySelectorAll('.milestone-burst').forEach(b=>b.remove());
    const burst=document.createElement('div');
    burst.className='milestone-burst';
    burst.textContent=`🎉 ${milestone.toLocaleString()} PTS`;
    host.appendChild(burst);
    setTimeout(()=>burst.remove(),2300);
  }

  // ── Desktop notifications ─────────────────────────────────────────────
  // Complements the in-app celebration effects above for when neither the
  // Overview tab nor the HUD is actually on screen — minimized, or another
  // window has focus (the whole reason the Mini HUD exists in the first
  // place; this closes the one remaining gap where even that isn't open).
  // Scoped to the two "worth interrupting for" moments — a broken best-rate
  // record and a score milestone — not every new QSO, which fires far too
  // often to surface as a system toast. Uses fixed strings/numbers only
  // (title, a plain "N Q/hr" or "N points" body) — no log-derived free text
  // (callsigns, comments) ever reaches this, so there's no injection
  // surface here the way there was with unescaped innerHTML elsewhere.
  //
  // Posts to /api/notify (a native Win32 balloon, see server.py) rather
  // than calling the browser's own Notification API directly — confirmed
  // via direct testing that WebView2 auto-denies Notification.
  // requestPermission() in this frameless embedded window with no prompt
  // ever shown, since there's no browser chrome to render one against.
  function notifyOS(title,body){
    if (!document.hidden) return;   // this window is on screen — the in-app effect already covers it
    fetch('/api/notify',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title,message:body})}).catch(()=>{});
  }

  // ── Sound alerts ─────────────────────────────────────────────────────────
  // Same Web Audio oscillator-beep technique as cluster.js's alertOnSpot() —
  // unlike notifyOS() above, sound isn't gated on document.hidden: it's
  // audible without looking either way, and doubles as a game-achievement-
  // style flourish on top of the in-app burst when the tab IS visible.
  const SOUND_KEY = 'vka_overview_sound';
  const soundToggleBtn = document.getElementById('btn-sound-toggle');
  let _soundEnabled = true;
  {
    const stored = localStorage.getItem(SOUND_KEY);
    _soundEnabled = stored === null ? true : stored === '1';
  }
  function updateSoundToggleBtn(){
    if (!soundToggleBtn) return;
    soundToggleBtn.textContent = _soundEnabled ? '🔊 Sound Alerts' : '🔇 Sound Alerts';
    soundToggleBtn.classList.toggle('btn--muted-off', !_soundEnabled);
  }
  updateSoundToggleBtn();
  soundToggleBtn?.addEventListener('click', () => {
    _soundEnabled = !_soundEnabled;
    localStorage.setItem(SOUND_KEY, _soundEnabled ? '1' : '0');
    updateSoundToggleBtn();
  });

  let _audioCtx = null;
  function beep(freq,startAt,durSec,gain){
    try {
      _audioCtx = _audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const t0   = _audioCtx.currentTime + startAt;
      const osc  = _audioCtx.createOscillator();
      const g    = _audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      g.gain.setValueAtTime(gain, t0);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + durSec);
      osc.connect(g).connect(_audioCtx.destination);
      osc.start(t0);
      osc.stop(t0 + durSec);
    } catch (e) { /* Web Audio unavailable — ignore */ }
  }
  function playBestRateSound(){
    if (!_soundEnabled) return;
    beep(880, 0, 1.5, 0.08);
  }

  // One chime note: a fundamental plus a quiet octave-up partial (a cheap
  // approximation of a bell's overtone) — two stacked sines read as a
  // "ding" rather than a flat oscillator beep.
  function chimeNote(freq,startAt,durSec,gain){
    try {
      _audioCtx = _audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const ctx = _audioCtx;
      const t0  = ctx.currentTime + startAt;
      [[1,1],[2,0.25]].forEach(([mult,partialGain])=>{
        const osc = ctx.createOscillator();
        const g   = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq * mult;
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.exponentialRampToValueAtTime(gain * partialGain, t0 + 0.008);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + durSec);
        osc.connect(g).connect(ctx.destination);
        osc.start(t0);
        osc.stop(t0 + durSec);
      });
    } catch (e) { /* Web Audio unavailable — ignore */ }
  }

  function playMilestoneSound(){
    if (!_soundEnabled) return;
    // Bright ascending major arpeggio — C6, E6, G6, C7, E7, G7 — the classic
    // "achievement unlocked" cascade, extended into a second lap up the
    // chord an octave higher. Notes overlap into each other (staggered
    // starts, long decay) for a sustained sparkling ring-out rather than a
    // quick handful of beeps — the last note is held longest.
    const notes = [1047, 1319, 1568, 2093, 2637, 3136];
    notes.forEach((freq,i)=>{
      const isLast = i === notes.length - 1;
      chimeNote(freq, i*0.12, isLast ? 1.6 : 0.9, 0.07);
    });
  }

  function checkCelebrations(snap){
    if (!snap) return;
    const total=snap.valid??snap.total??0;
    const bestRate=snap.personal_bests?.best_hour_rate??0;
    const score=snap.score??0;

    if (_celebPrevTotal===null){
      // First snapshot since load — seed the baseline so pre-existing
      // progress (e.g. re-opening a log mid-contest) doesn't immediately
      // "celebrate" as if it just happened.
      _celebPrevTotal=total; _celebPrevBestRate=bestRate;
      for (const m of SCORE_MILESTONES) if (score>=m) _celebMilestones.add(m);
      return;
    }

    // The HUD has no "gauges"/"personal bests panel" of its own — the whole
    // bar stands in for the pulse, and the Rate item (the closest analogue
    // to a rate record) stands in for the flash.
    const pulseTarget = HUD_MODE ? document.getElementById('hud-bar')
                                  : document.getElementById('gauge-row');
    const bestTarget   = HUD_MODE ? document.getElementById('hud-rate')?.closest('.hud-item')
                                  : document.getElementById('panel-personal-bests');
    const burstHost    = pulseTarget;

    if (total>_celebPrevTotal) flashEl(pulseTarget,'flash-new-qso',900);
    // >0 guard: going from "no rate recorded yet" (0) to a first real rate
    // isn't a broken record, just the first data point.
    if (bestRate>_celebPrevBestRate && _celebPrevBestRate>0){
      flashEl(bestTarget,'flash-best',1400);
      notifyOS('🔥 New best rate', `${bestRate} Q/hr`);
      playBestRateSound();
    }
    for (const m of SCORE_MILESTONES){
      if (score>=m && !_celebMilestones.has(m)){
        _celebMilestones.add(m);
        showMilestoneBurst(m,burstHost);
        notifyOS('🎉 Milestone reached', `${m.toLocaleString()} points`);
        playMilestoneSound();
      }
    }
    _celebPrevTotal=total; _celebPrevBestRate=bestRate;
  }

  // ── Contest end-time alerts ─────────────────────────────────────────────
  // Nothing else proactively tells the operator time's running out — the
  // countdown on the Contest Time panel is passive, easy to miss heads-down
  // mid-run. Unlike the milestone/best-rate celebrations above, these fire
  // even on the very first snapshot after load: opening the app with 8
  // minutes left, "10 minutes remaining" is useful information, not a false
  // celebration of progress that didn't just happen — so this is a
  // separate function, not folded into checkCelebrations()'s baseline-seed
  // branch (which explicitly suppresses first-snapshot effects).
  const END_TIME_THRESHOLDS = [10, 5, 1];   // minutes remaining
  const _endTimeAlertsFired = new Set();

  function resetEndTimeAlerts(){
    _endTimeAlertsFired.clear();
  }

  function playEndTimeAlertSound(){
    if (!_soundEnabled) return;
    // Two short neutral pings — deliberately not the celebratory chime;
    // this is a warning, not a reward.
    beep(660, 0,    0.18, 0.07);
    beep(660, 0.22, 0.18, 0.07);
  }

  function checkEndTimeAlert(snap){
    const ss = snap?.session_status;
    if (!ss || ss.state !== 'live') return;
    const remMins = ss.total_remaining_mins ?? ss.remaining_mins;
    if (remMins == null || remMins <= 0) return;

    for (const t of END_TIME_THRESHOLDS){
      if (remMins<=t && !_endTimeAlertsFired.has(t)){
        _endTimeAlertsFired.add(t);
        const target = HUD_MODE ? document.getElementById('hud-bar')
                                 : document.getElementById('panel-contest-time');
        flashEl(target,'flash-endtime',1400);
        notifyOS('⏰ Contest ending soon', `${t} minute${t===1?'':'s'} remaining`);
        playEndTimeAlertSound();
      }
    }
  }

  // ── Live dead-air detection ────────────────────────────────────────────
  // Distinct from two existing checks: the Fatigue tab's dead-zone analysis
  // is a whole-contest, 24-hour-of-day retrospective average (not live, and
  // not usable per-band in real time); the Pace tab's rate alarm is live but
  // whole-station only and only trips after a FULL clock-hour comes up empty.
  // Neither can tell you "you've been parked on 40m for 15 minutes with
  // nothing" while other bands might be open. Tracks time since the last QSO
  // logged WHILE ON THIS BAND (not time since first tuning to it — a QSO 2
  // minutes in shouldn't reset a clock that then runs to the threshold
  // anyway). A QSO-count increase while the band hasn't changed is treated
  // as a QSO on that band — a reasonable simplification for the common
  // single-radio case; for SO2R this can occasionally miss (a QSO worked on
  // radio 2 while radio 1 — "own" — sits idle on a dead band) since only one
  // "own" radio is tracked, a documented narrow gap same as other known,
  // rare-case simplifications already in this codebase.
  const DEAD_AIR_THRESHOLD_MINS = 15;
  let _deadAirBand=null, _deadAirClockStart=null, _deadAirBaseline=null, _deadAirFired=false;

  function resetDeadAirTracking(){
    _deadAirBand=null; _deadAirClockStart=null; _deadAirBaseline=null; _deadAirFired=false;
  }

  function playDeadAirSound(){
    if (!_soundEnabled) return;
    // Two short low pings — distinct from both the celebratory chime and
    // the end-time warning's higher-pitched pings.
    beep(440, 0,   0.25, 0.06);
    beep(370, 0.3, 0.35, 0.06);
  }

  function checkDeadAir(snap){
    const band  = snap?.radio_info?.own?.band;
    const valid = snap?.valid || 0;
    if (!band){ resetDeadAirTracking(); return; }
    if (band !== _deadAirBand || valid > (_deadAirBaseline ?? valid)){
      // Band changed, or a QSO just landed on this band — (re)start the clock.
      _deadAirBand=band; _deadAirClockStart=Date.now();
      _deadAirBaseline=valid; _deadAirFired=false;
      return;
    }
    if (_deadAirFired) return;
    if ((Date.now()-_deadAirClockStart)/60000 >= DEAD_AIR_THRESHOLD_MINS){
      _deadAirFired = true;
      const target = HUD_MODE ? document.getElementById('hud-radio')
                               : document.getElementById('panel-radio');
      flashEl(target,'flash-endtime',1400);   // reuse the existing red "needs attention" flash
      notifyOS('📻 Dead air', `No QSOs on ${band} in ${DEAD_AIR_THRESHOLD_MINS} min — try another band?`);
      playDeadAirSound();
    }
  }

  // ── Continuous-operator fatigue alert ────────────────────────────────
  // Distinct from the Fatigue tab's own cross-session dead-zone/nap
  // analysis (retrospective, and easy to forget to go check mid-run) —
  // this watches whoever N1MM+ currently reports as the active operator
  // (radio_info.own.op_call) and flags a long unbroken stretch while it's
  // actually happening. Known narrow gap, same spirit as checkDeadAir's
  // documented SO2R limitation above: the clock only resets when N1MM's
  // active-operator field itself changes (or the broadcast goes stale
  // entirely) — stepping away from the radio without changing that field
  // in N1MM won't reset it, so a very long single-operator stretch that's
  // actually had real breaks can still fire. Worth the false positive; the
  // alternative (never checking) misses every genuine case too.
  const OP_FATIGUE_THRESHOLD_MINS = 90;
  let _opFatigueCall=null, _opFatigueClockStart=null, _opFatigueFired=false;

  function resetOperatorFatigueTracking(){
    _opFatigueCall=null; _opFatigueClockStart=null; _opFatigueFired=false;
  }

  function playOperatorFatigueSound(){
    if (!_soundEnabled) return;
    // Three low, unhurried descending tones — deliberately calmer than the
    // dead-air/end-time alert pings; this is a wellbeing nudge, not an
    // emergency.
    beep(392,0,0.3,0.05); beep(349,0.35,0.3,0.05); beep(294,0.7,0.45,0.05);
  }

  function checkOperatorFatigue(snap){
    const call = snap?.radio_info?.own?.op_call;
    if (!call){ resetOperatorFatigueTracking(); return; }
    if (call !== _opFatigueCall){
      // Operator changed (or first sighting this session) — (re)start the clock.
      _opFatigueCall=call; _opFatigueClockStart=Date.now(); _opFatigueFired=false;
      return;
    }
    if (_opFatigueFired) return;
    if ((Date.now()-_opFatigueClockStart)/60000 >= OP_FATIGUE_THRESHOLD_MINS){
      _opFatigueFired = true;
      const target = HUD_MODE ? document.getElementById('hud-bar')
                               : document.getElementById('panel-fatigue');
      flashEl(target,'flash-endtime',1400);
      notifyOS('😴 Time for a break?', `${call} has been at the radio for ${OP_FATIGUE_THRESHOLD_MINS}+ min straight`);
      playOperatorFatigueSound();
    }
  }

  // ══ MAIN ═══════════════════════════════════════════════════════════════════
  function render(snap){
    updateGauges(snap); updateSparklines(snap); updateRegionBars(snap);
    updateSessionStatus(snap); updateContestTime(snap);
    updateBandEfficiency(snap); updatePersonalBests(snap);
    updateQsoValue(snap); updateLastWorked(snap); updateOperatorTimes(snap);
    updateFatigueTile(snap);
    updateRadioPanel(snap);
    updateInsightBar(snap);
    updateExtraAnalytics(snap);
    updateContestOverPanel(snap);
    updateBandDonut(snap);
    initGlowMap(); updateGlowMap();
    // Each panel above replaces its own innerHTML on every refresh, which
    // wipes out the pop-out button appended as a child — re-add it (addPopoutButton
    // no-ops if one's already present).
    document.querySelectorAll('.info-panel').forEach(addPopoutButton);
  }

  let _firstSnap=true;
  window.addEventListener('vka:snapshot',e=>{
    trackLastQso(e.detail);
    if (SPECTATOR_MODE) { updateSpectator(e.detail); return; }
    if (OPERATOR_HUD_MODE) { updateOperatorHud(e.detail); return; }
    if (HUD_MODE) { updateHud(e.detail); trackHudSparklines(e.detail); checkCelebrations(e.detail); checkEndTimeAlert(e.detail); checkDeadAir(e.detail); checkOperatorFatigue(e.detail); return; }
    if (_replaying) return;
    if(_firstSnap){_firstSnap=false;loadPluginMeta().then(()=>render(e.detail));}
    else render(e.detail);
    checkCelebrations(e.detail);
    checkEndTimeAlert(e.detail);
    checkDeadAir(e.detail);
    checkOperatorFatigue(e.detail);
  });
  window.addEventListener('vka:tabchange',e=>{
    if(e.detail.tab!=='overview') return;
    // The glow map's container was display:none while this tab was
    // inactive — Leaflet cached whatever size it had (possibly 0×0) and
    // needs telling to re-measure and re-fit now that it's visible again.
    if (_glowMap) setTimeout(fitGlowMapBounds,50);
    if (_replaying && _lastReplaySnap) { render(_lastReplaySnap); return; }
    const snap=window.VKA.lastSnap(); if(snap) render(snap);
  });
  window.addEventListener('vka:loaded',()=>{
    _metaLoaded=false;_firstSnap=true;resetCelebrations();resetEndTimeAlerts();resetHudSparklines();resetDeadAirTracking();resetOperatorFatigueTracking();
    _seenOperators.clear();
    for (const k in _numAnimState) delete _numAnimState[k];
    _glowLastLoadAt=0;   // force the next updateGlowMap() past the throttle for the new log
    // panel-live-rank/panel-top-dxcc don't exist in either HUD window's DOM
    // — polling there just fires unnecessary requests every load (see issue #72).
    if (!HUD_MODE && !OPERATOR_HUD_MODE && !SPECTATOR_MODE) { startLiveRankPolling(); startTopDxccPolling(); }
  });

  if (!HUD_MODE && !OPERATOR_HUD_MODE) startLiveRankPolling();
  if (!HUD_MODE && !OPERATOR_HUD_MODE && !SPECTATOR_MODE) startTopDxccPolling();

})();
