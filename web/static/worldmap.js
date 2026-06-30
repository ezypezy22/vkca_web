/**
 * worldmap.js v3 — Leaflet with Leaflet.Geodesic for correct great-circle arcs
 * Uses L.Geodesic for proper curved arc rendering (handles antimeridian correctly)
 * Multiple ESRI basemap options
 */
;(function () {
  'use strict';

  const BAND_COLS = {
    '160M':'#e040fb','80M':'#ff6b35','60M':'#f0c040','40M':'#2ed573',
    '30M':'#00bcd4','20M':'#00d4aa','17M':'#64b5f6','15M':'#ff5252',
    '12M':'#ffab40','10M':'#69f0ae','6M':'#ea80fc','2M':'#80d8ff','?':'#8b949e',
  };

  // High-quality basemap tile URLs
  const BASEMAPS = {
    // ── Dark themes ──────────────────────────────────────────────────────────
    'Dark (CartoDB)': {
      url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      attribution: '© OpenStreetMap © CARTO',
      subdomains: 'abcd', maxZoom: 19,
    },
    'Voyager (CartoDB)': {
      url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
      attribution: '© OpenStreetMap © CARTO',
      subdomains: 'abcd', maxZoom: 19,
    },
    // ── ESRI ─────────────────────────────────────────────────────────────────
    'ESRI Satellite': {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      attribution: 'Tiles © Esri — Esri, DigitalGlobe, GeoEye, i-cubed, USDA FSA, USGS, AEX, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and GIS User Community',
      maxZoom: 20,
    },
    'ESRI Satellite + Labels': {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      attribution: 'Tiles © Esri',
      overlay: 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
      maxZoom: 20,
    },
    'ESRI Topo': {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
      attribution: 'Tiles © Esri — Esri, DeLorme, NAVTEQ, TomTom, Intermap, iPC, USGS, FAO, NPS, NRCAN, GeoBase, Kadaster NL, Ordnance Survey, Esri Japan, METI, Esri China, and the GIS User Community',
      maxZoom: 20,
    },
    'ESRI Ocean': {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}',
      attribution: 'Tiles © Esri — Source: GEBCO, NOAA, CHS, OSU, UNH, CSUMB, National Geographic, DeLorme, NAVTEQ, and Esri',
      maxZoom: 13,
    },
    'ESRI Dark Gray': {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
      attribution: 'Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community',
      maxZoom: 16,
    },
    'ESRI NatGeo': {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer/tile/{z}/{y}/{x}',
      attribution: 'Tiles © Esri — National Geographic, Esri, DeLorme, NAVTEQ, UNEP-WCMC, USGS, NASA, ESA, METI, NRCAN, GEBCO, NOAA, iPC',
      maxZoom: 16,
    },
    'ESRI Streets': {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
      attribution: 'Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community',
      maxZoom: 20,
    },
    'ESRI Terrain': {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}',
      attribution: 'Tiles © Esri — Source: USGS, Esri, TANA, DeLorme, and NPS',
      maxZoom: 13,
    },
    'ESRI Physical': {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Physical_Map/MapServer/tile/{z}/{y}/{x}',
      attribution: 'Tiles © Esri — Source: US National Park Service',
      maxZoom: 8,
    },
    // ── OpenStreetMap ─────────────────────────────────────────────────────────
    'OSM Standard': {
      url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      attribution: '© OpenStreetMap contributors',
      maxZoom: 19,
    },
    // ── Stadia ────────────────────────────────────────────────────────────────
    'Stadia Alidade Dark': {
      url: 'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png',
      attribution: '© Stadia Maps © OpenMapTiles © OpenStreetMap contributors',
      maxZoom: 20,
    },
    'Stadia Alidade Satellite': {
      url: 'https://tiles.stadiamaps.com/tiles/alidade_satellite/{z}/{x}/{y}{r}.png',
      attribution: '© Stadia Maps © CNES/Airbus DS © Microsoft',
      maxZoom: 20,
    },
    'Stadia OSM Bright': {
      url: 'https://tiles.stadiamaps.com/tiles/osm_bright/{z}/{x}/{y}{r}.png',
      attribution: '© Stadia Maps © OpenMapTiles © OpenStreetMap contributors',
      maxZoom: 20,
    },
  };
  
  // Label overlays (rendered on top of base tile layer)
  const OVERLAYS = {
    'ESRI Satellite + Labels': 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
  };

  // Every station is plotted at its REAL lat/lon against a stock (unmodified)
  // tile layer. Two earlier designs were tried and rejected here:
  //  1) Shift the whole world so HOME sits at the visual center — tile
  //     imagery can only shift by whole tile widths while markers shifted by
  //     the exact amount, so coastal stations rendered offshore.
  //  2) Snap the marker shift to match the tile rounding at each zoom — this
  //     fixed the coastal misalignment, but HOME's own dot then visibly
  //     moved between zoom levels as the rounding snapped to a different
  //     tile boundary, which is worse.
  // Real coordinates have neither problem and need no rounding/snapping.
  let _map          = null;
  let _tileLayer    = null;
  let _markerLayer  = null;
  let _shortLayer   = null;
  let _longLayer    = null;
  let _homeMarker   = null;
  let _allData      = [];
  let _lastLoadAt   = 0;
  const LOAD_THROTTLE_MS = 8000;   // map data/geometry don't need to rebuild every snapshot tick
  let _filterBand   = 'ALL';
  let _showShort    = true;
  let _showLong     = false;
  let _currentBasemap = 'Dark (CartoDB)';
  let _renderer     = null;
  let _isDragging   = false;
  let _pendingRender = false;
  let _layerCache   = null;

  let HOME = [-33.9, 151.2];   // default VK2 Sydney

  // ── Haversine distance ──────────────────────────────────────────────────────
  function distKm(lat1, lon1, lat2, lon2) {
    const R=6371;
    const dLat=(lat2-lat1)*Math.PI/180, dLon=(lon2-lon1)*Math.PI/180;
    const a=Math.sin(dLat/2)**2+Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)**2;
    return Math.round(R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a)));
  }


  // ── Fallback great-circle helpers (used if Leaflet.Geodesic fails to load) ──
  function gcPoints(lat1, lon1, lat2, lon2, steps) {
    const D2R = Math.PI/180, R2D = 180/Math.PI;
    const φ1=lat1*D2R, λ1=lon1*D2R, φ2=lat2*D2R, λ2=lon2*D2R;
    const d=2*Math.asin(Math.sqrt(
      Math.sin((φ2-φ1)/2)**2+Math.cos(φ1)*Math.cos(φ2)*Math.sin((λ2-λ1)/2)**2));
    if (d<0.0001) return [[lat1,lon1],[lat2,lon2]];
    const pts=[];
    for (let i=0;i<=steps;i++) {
      const f=i/steps;
      const A=Math.sin((1-f)*d)/Math.sin(d), B=Math.sin(f*d)/Math.sin(d);
      const x=A*Math.cos(φ1)*Math.cos(λ1)+B*Math.cos(φ2)*Math.cos(λ2);
      const y=A*Math.cos(φ1)*Math.sin(λ1)+B*Math.cos(φ2)*Math.sin(λ2);
      const z=A*Math.sin(φ1)+B*Math.sin(φ2);
      pts.push([Math.atan2(z,Math.sqrt(x*x+y*y))*R2D, Math.atan2(y,x)*R2D]);
    }
    return pts;
  }

  function splitAtAntimeridian(pts) {
    // Split a polyline into segments that don't cross ±180°
    const segs=[[]], threshold=180;
    for (let i=1;i<pts.length;i++) {
      const prev=pts[i-1], cur=pts[i];
      const dLon=cur[1]-prev[1];
      if (Math.abs(dLon)>threshold) {
        // Crossed antimeridian — start new segment
        segs.push([cur]);
      } else {
        segs[segs.length-1].push(cur);
      }
    }
    if (segs[0].length===0) segs[0].push(pts[0]);
    return segs.filter(s=>s.length>1);
  }

  // ── Map init ────────────────────────────────────────────────────────────────
  // At low zoom a single world copy (256*2^zoom px) is narrower than most
  // browser windows, so pick the smallest zoom whose world width covers the
  // container, and raise the current zoom to at least that on load/resize.
  // Also cap how far out the user can zoom manually (+/-/scroll) to at most
  // ~2 world copies visible — without this, worldCopyJump lets you zoom out
  // indefinitely and see the whole wrapped map repeated many times over.
  function _fitZoomToWidth() {
    if (!_map) return;
    const el = document.getElementById('world-map-container');
    const w  = el && el.clientWidth;
    if (!w) return;
    const zFit = Math.max(2, Math.ceil(Math.log2(w / 256)));
    _map.setMinZoom(Math.max(1, zFit - 1));
    if (_map.getZoom() < zFit) _map.setZoom(zFit);
  }

  function initMap() {
    if (_map) return;
    const el = document.getElementById('world-map-container');
    if (!el) return;

    // padding:0.5 extends the canvas 50% beyond the viewport in every direction
    // (total canvas = 2× viewport). Without a larger padding, Leaflet clips the
    // canvas to viewport+10% and great-circle arcs starting from home (off-screen
    // after panning) get hard-clipped mid-arc.
    _renderer = L.canvas({ padding: 0.5 });

    _map = L.map('world-map-container', {
      center: [HOME[0], HOME[1]],
      zoom: 2,
      renderer: _renderer,
      // A VK (Australia) station's DX contacts routinely span the
      // antimeridian (e.g. into North America). noWrap previously cut that
      // content off hard at +/-180; wrapping lets the map continue
      // seamlessly across the date line in either direction. worldCopyJump
      // keeps panning from drifting many world-widths away.
      worldCopyJump: true,
    });
    _fitZoomToWidth();

    // Hide the vector overlay during drag so only tiles move (CSS transform,
    // GPU-composited, 60 fps). Any render() triggered mid-drag (from snapshot
    // events or async load() completion) is queued and fires on dragend instead.
    _map.on('dragstart', () => {
      _isDragging = true;
      if (_renderer._container) _renderer._container.style.display = 'none';
    });
    _map.on('dragend', () => {
      _isDragging = false;
      if (_renderer._container) _renderer._container.style.display = '';
      if (_pendingRender) { _pendingRender = false; render(); }
    });

    const bm = BASEMAPS['Dark (CartoDB)'];
    _tileLayer = L.tileLayer(bm.url, {
      attribution: bm.attribution,
      subdomains: bm.subdomains || 'abc',
      maxZoom: 16,
    }).addTo(_map);

    _shortLayer  = L.layerGroup().addTo(_map);
    _longLayer   = L.layerGroup();
    _markerLayer = L.layerGroup().addTo(_map);

    // Home marker at its real position
    _homeMarker = L.circleMarker([HOME[0], HOME[1]], {
      radius: 10, color: '#00d4aa', fillColor: '#00d4aa',
      fillOpacity: 1, weight: 3,
    }).addTo(_map).bindTooltip('Home Station', {permanent:false,direction:'top'});
  }

  // ── Basemap switcher ────────────────────────────────────────────────────────
  let _labelLayer = null;

  function switchBasemap(name) {
    if (!_map || !BASEMAPS[name]) return;
    // Remove existing tile layers
    if (_tileLayer)  { _map.removeLayer(_tileLayer);  _tileLayer  = null; }
    if (_labelLayer) { _map.removeLayer(_labelLayer); _labelLayer = null; }

    const bm = BASEMAPS[name];
    _tileLayer = L.tileLayer(bm.url, {
      attribution: bm.attribution,
      subdomains:  bm.subdomains || 'abc',
      maxZoom:     bm.maxZoom    || 18,
    }).addTo(_map);

    // Label overlay for satellite+labels variant
    const overlayUrl = bm.overlay || OVERLAYS[name];
    if (overlayUrl) {
      _labelLayer = L.tileLayer(overlayUrl, {
        opacity: 0.85, maxZoom: 20,
      }).addTo(_map);
    }

    // Bring data layers above tiles
    if (_shortLayer)  _shortLayer.bringToFront?.();
    if (_longLayer)   _longLayer.bringToFront?.();
    if (_markerLayer) _markerLayer.bringToFront?.();

    _currentBasemap = name;

    // Adjust arc opacity: lighter on bright basemaps
    const isDark = name.toLowerCase().includes('dark') ||
                   name.toLowerCase().includes('satellite') ||
                   name.toLowerCase().includes('ocean');
    const opacity = isDark ? 0.55 : 0.70;
    // Re-render with updated opacity preference
    render();
  }

  // ── Load data ───────────────────────────────────────────────────────────────
  async function load() {
    if (!_map) return;
    _lastLoadAt = Date.now();
    try {
      const res  = await fetch('/api/map_data');
      _allData   = await res.json();
      render();
    } catch(e) { console.warn('Map load error:', e); }
  }

  // ── Layer cache ─────────────────────────────────────────────────────────────
  // L.geodesic / L.polyline / L.circleMarker creation for 800+ stations is the
  // dominant cost in render(). Cache the built objects keyed on (data reference,
  // HOME, showShort, showLong) so that band-filter changes, tab switches, and
  // post-drag redraws only call addLayer() on pre-built objects — no recomputation.
  const LON_SHIFTS = [-360, 360];

  function crossesAntimeridian(lon1, lon2, marginDeg) {
    const d = ((lon2 - lon1 + 540) % 360) - 180;
    const unwrapped = lon1 + d;
    return unwrapped > 180 - marginDeg || unwrapped < -180 + marginDeg;
  }

  function shiftLngTree(node, dLon) {
    if (Array.isArray(node)) return node.map(n => shiftLngTree(n, dLon));
    return L.latLng(node.lat, node.lng + dLon);
  }

  function _cacheValid() {
    return _layerCache
      && _layerCache.dataRef  === _allData
      && _layerCache.home[0]  === HOME[0]
      && _layerCache.home[1]  === HOME[1]
      && _layerCache.showShort === _showShort
      && _layerCache.showLong  === _showLong;
  }

  // Leaflet's canvas renderer does one beginPath()/stroke() PER PATH OBJECT on
  // every redraw — the per-object overhead (not the point count) dominates for
  // many short arcs. L.Geodesic and L.Polyline both accept an array of *lines*
  // (LatLngExpression[][]), so all of one band's arcs are merged into a single
  // multi-line Path object: one stroke() call per band (~13) instead of one per
  // station (~800+). With wrap:true the library may split an individual line at
  // the antimeridian into extra sub-arrays — getLatLngs() reflects that, and we
  // shift *all* returned sub-arrays without needing to map them back to a
  // specific station, since every station in the "wrap" group already gets a
  // shifted duplicate regardless of which sub-array its points ended up in.
  function _buildCache() {
    const maxCount = Math.max(..._allData.map(d => d.count), 1);
    const valid = _allData.filter(d => d.lat != null && d.lon != null);

    const byBand = new Map();
    valid.forEach(d => {
      const band = (d.band || '?').trim().toUpperCase();
      d._band = band;
      if (!byBand.has(band)) byBand.set(band, []);
      byBand.get(band).push(d);
    });

    const bandData = {};

    byBand.forEach((stations, band) => {
      const col = BAND_COLS[band] || '#8b949e';
      const wrapStations  = stations.filter(d => crossesAntimeridian(HOME[1], d.lon, 8));
      const plainStations = stations.filter(d => !crossesAntimeridian(HOME[1], d.lon, 8));

      // ── Short-path arcs: merged into up to 3 Path objects per band ──────────
      const shortLayers = [];
      if (_showShort && typeof L.geodesic !== 'undefined') {
        const sStyle = { weight: 1.3, color: col, opacity: 0.60 };
        if (plainStations.length) {
          const lines = plainStations.map(d => [L.latLng(HOME[0], HOME[1]), L.latLng(d.lat, d.lon)]);
          shortLayers.push(L.geodesic(lines, { ...sStyle, steps: 36, wrap: true }));
        }
        if (wrapStations.length) {
          const lines = wrapStations.map(d => [L.latLng(HOME[0], HOME[1]), L.latLng(d.lat, d.lon)]);
          const wrapArc = L.geodesic(lines, { ...sStyle, steps: 36, wrap: true });
          shortLayers.push(wrapArc);
          const subLines = wrapArc.getLatLngs() || [];
          const shifted = [];
          subLines.forEach(line => { shifted.push(shiftLngTree(line, -360)); shifted.push(shiftLngTree(line, 360)); });
          if (shifted.length) shortLayers.push(L.polyline(shifted, sStyle));
        }
      } else if (_showShort) {
        const allSegs = [];
        stations.forEach(d => {
          const pts = gcPoints(HOME[0], HOME[1], d.lat, d.lon, 40);
          splitAtAntimeridian(pts).forEach(seg => allSegs.push(seg));
        });
        if (allSegs.length) shortLayers.push(L.polyline(allSegs, { color: col, weight: 1.2, opacity: 0.55 }));
      }

      // ── Long-path arcs: merged into up to 2 Path objects per band ───────────
      const longLayers = [];
      if (_showLong && typeof L.geodesic !== 'undefined') {
        const lStyle = { weight: 1.2, color: col, opacity: 0.35, dashArray: '5 7' };
        const lines = stations.map(d => {
          const antiLat = -d.lat;
          const antiLon = d.lon > 0 ? d.lon - 180 : d.lon + 180;
          return [L.latLng(HOME[0], HOME[1]), L.latLng(antiLat, antiLon), L.latLng(d.lat, d.lon)];
        });
        const longArc = L.geodesic(lines, { ...lStyle, steps: 46, wrap: true });
        longLayers.push(longArc);
        const subLines = longArc.getLatLngs() || [];
        const shifted = [];
        subLines.forEach(line => { shifted.push(shiftLngTree(line, -360)); shifted.push(shiftLngTree(line, 360)); });
        if (shifted.length) longLayers.push(L.polyline(shifted, lStyle));
      }

      // ── Markers stay one-per-station (each needs its own hover tooltip) ────
      // Tooltip content is a function so the HTML string is only built lazily
      // on first hover, not for all 800+ stations up front.
      const markers = [];
      stations.forEach(d => {
        const r      = Math.max(4, Math.min(12, 4 + (d.count / maxCount) * 8));
        const dist   = distKm(HOME[0], HOME[1], d.lat, d.lon);
        const distLP = Math.round(40075 - dist);
        const shifts = crossesAntimeridian(HOME[1], d.lon, 8) ? [0, -360, 360] : [0];
        shifts.forEach(shift => {
          markers.push(L.circleMarker([d.lat, d.lon + shift], {
            radius: r, color: col, fillColor: col, fillOpacity: 0.85, weight: 1.5,
          }).bindTooltip(() => `
            <div style="font-family:Consolas,monospace;font-size:11px;line-height:1.7">
              <b style="color:${col}">${d.call}</b><br>
              ${band.toLowerCase()} · ${d.count} QSO${d.count > 1 ? 's' : ''}
              ${d.mult ? `<br><span style="color:#f0c040">✦ Mult: ${d.mult}</span>` : ''}
              <br><span style="color:#8b949e">SP: ${dist.toLocaleString()} km</span>
              <span style="color:#8b949e"> · LP: ${distLP.toLocaleString()} km</span>
            </div>`, { direction: 'top', offset: [0, -r], opacity: 0.97 }));
        });
      });

      bandData[band] = {
        shortLayers, longLayers, markers,
        stationCount: stations.length,
        qsoCount: stations.reduce((a, d) => a + d.count, 0),
      };
    });

    _layerCache = {
      dataRef: _allData, home: [...HOME],
      showShort: _showShort, showLong: _showLong,
      bandData,
    };
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  function render() {
    if (_isDragging) { _pendingRender = true; return; }
    if (!_cacheValid()) _buildCache();

    _markerLayer.clearLayers();
    _shortLayer.clearLayers();
    _longLayer.clearLayers();

    const bandCounts = {};
    let visStations = 0;
    Object.entries(_layerCache.bandData).forEach(([band, bd]) => {
      if (_filterBand !== 'ALL' && band !== _filterBand) return;
      bandCounts[band] = bd.qsoCount;
      visStations += bd.stationCount;
      // Arcs added first so markers paint on top (canvas insertion order)
      if (_showShort) bd.shortLayers.forEach(l => _shortLayer.addLayer(l));
      if (_showLong)  bd.longLayers.forEach(l => _longLayer.addLayer(l));
      bd.markers.forEach(m => _markerLayer.addLayer(m));
    });

    updateLegend(bandCounts);
    const statEl = document.getElementById('map-stats');
    if (statEl) statEl.textContent =
      `${visStations.toLocaleString()} callsigns · ${_allData.length.toLocaleString()} total`;
  }

  function updateLegend(counts) {
    const el = document.getElementById('map-legend'); if (!el) return;
    el.innerHTML = Object.entries(counts)
      .sort((a,b)=>b[1]-a[1]).slice(0,8)
      .map(([band,n]) => {
        const col = BAND_COLS[band]||'#8b949e';
        return `<span class="map-legend-item">
          <span class="map-legend-dot" style="background:${col}"></span>
          <span style="color:${col}">${band.toLowerCase()}</span>
          <span class="map-legend-count">${n}</span>
        </span>`;
      }).join('');
  }

  // ── Controls ────────────────────────────────────────────────────────────────
  document.querySelectorAll('.map-band-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.map-band-btn').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      _filterBand = btn.dataset.band;
      render();
    });
  });

  document.getElementById('map-toggle-short')?.addEventListener('change', e => {
    _showShort = e.target.checked;
    if (_map) {
      if (_showShort) _map.addLayer(_shortLayer);
      else _map.removeLayer(_shortLayer);
    }
    render();
  });

  document.getElementById('map-toggle-long')?.addEventListener('change', e => {
    _showLong = e.target.checked;
    if (_map) {
      if (_showLong) _map.addLayer(_longLayer);
      else _map.removeLayer(_longLayer);
    }
    render();
  });

  // Basemap switcher
  document.getElementById('map-basemap-select')?.addEventListener('change', e => {
    switchBasemap(e.target.value);
  });

  // HOME changed: recenter on its real position and redraw everything.
  function _setHome(lat, lon) {
    HOME = [lat, lon];
    if (!_map) return;   // map tab not opened yet — nothing to redraw
    // Skip panTo during drag — it fires moveend which triggers a canvas redraw
    // mid-drag. The map will not jump to home position until the next render.
    if (!_isDragging) _map.panTo([HOME[0], HOME[1]], { animate: false });
    if (_homeMarker) _homeMarker.setLatLng([HOME[0], HOME[1]]);
    render();
  }

  // Home coordinates manual entry
  function applyHomeInput() {
    const val = document.getElementById('map-home-input')?.value.trim();
    if (!val) return;
    const parts = val.split(',').map(Number);
    if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
      _setHome(parts[0], parts[1]);
      try { localStorage.setItem('vkca_map_home', val); } catch {}
    }
  }
  document.getElementById('map-home-btn')?.addEventListener('click', applyHomeInput);
  document.getElementById('map-home-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') applyHomeInput();
  });
  // Restore saved home
  try {
    const saved = localStorage.getItem('vkca_map_home');
    if (saved) {
      const el = document.getElementById('map-home-input');
      if (el) el.value = saved;
      const parts = saved.split(',').map(Number);
      if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
        HOME = [parts[0], parts[1]];
      }
    }
  } catch {}

  // Update home position from snapshot plugin data
  window.addEventListener('vka:snapshot', e => {
    const d = e.detail;
    if (d?._home_lat != null && d?._home_lon != null
        && (d._home_lat !== HOME[0] || d._home_lon !== HOME[1])) {
      _setHome(d._home_lat, d._home_lon);
    }
    if (_map && document.querySelector('.tab-btn[data-tab="map"]')?.classList.contains('active')
        && Date.now() - _lastLoadAt >= LOAD_THROTTLE_MS) {
      load();
    }
  });

  // Tab switch
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab !== 'map') return;
    if (!_map) {
      setTimeout(() => { initMap(); load(); }, 80);
    } else {
      setTimeout(() => { _map.invalidateSize(true); _fitZoomToWidth(); render(); }, 100);
    }
  });

  window.addEventListener('resize', () => {
    if (!_map) return;
    _map.invalidateSize(true);
    _fitZoomToWidth();
  });

})();
