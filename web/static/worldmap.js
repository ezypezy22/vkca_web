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

  let _map          = null;
  let _tileLayer    = null;
  let _markerLayer  = null;
  let _shortLayer   = null;
  let _longLayer    = null;
  let _homeMarker   = null;
  let _allData      = [];
  let _filterBand   = 'ALL';
  let _showShort    = true;
  let _showLong     = false;
  let _currentBasemap = 'Dark (CartoDB)';

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
  function initMap() {
    if (_map) return;
    const el = document.getElementById('world-map-container');
    if (!el) return;

    _map = L.map('world-map-container', {
      center: [-20, 150], zoom: 2,   // centered near Australia so VK arcs look natural
      preferCanvas: true,
      worldCopyJump: true,           // jump copies when panning across antimeridian
      // NO maxBounds — allow free panning so antimeridian lines render fully
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

    // Home marker
    _homeMarker = L.circleMarker(HOME, {
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
    try {
      const res  = await fetch('/api/map_data');
      _allData   = await res.json();
      render();
    } catch(e) { console.warn('Map load error:', e); }
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  function render() {
    _markerLayer.clearLayers();
    _shortLayer.clearLayers();
    _longLayer.clearLayers();

    const filtered = _allData.filter(d => {
      const band = (d.band||'?').trim().toUpperCase();
      d._band = band;
      return _filterBand === 'ALL' || band === _filterBand;
    });

    // Legend and stats
    const bandCounts = {};
    filtered.forEach(d => { bandCounts[d._band] = (bandCounts[d._band]||0)+d.count; });
    updateLegend(bandCounts);
    const statEl = document.getElementById('map-stats');
    if (statEl) statEl.textContent =
      `${filtered.length.toLocaleString()} callsigns · ${_allData.length.toLocaleString()} total`;

    const maxCount = Math.max(...filtered.map(d=>d.count), 1);

    filtered.forEach(d => {
      if (d.lat == null || d.lon == null) return;
      const col    = BAND_COLS[d._band] || '#8b949e';
      const r      = Math.max(4, Math.min(12, 4 + (d.count/maxCount)*8));
      const dist   = distKm(HOME[0], HOME[1], d.lat, d.lon);
      const distLP = Math.round(40075 - dist);

      // ── Short-path arc using Leaflet.Geodesic ──────────────────────────────
      // L.geodesic draws the shortest great-circle arc automatically, handling
      // antimeridian wrapping correctly (unlike L.polyline which draws straight)
      if (_showShort && typeof L.geodesic !== 'undefined') {
        const arc = L.geodesic(
          [[L.latLng(HOME[0], HOME[1]), L.latLng(d.lat, d.lon)]],
          {
            weight: 1.3,
            color: col,
            opacity: 0.60,
            steps: 100,      // more steps = shorter segments = better antimeridian handling
            wrap: false,     // false: don't split at antimeridian, draw continuous arc
          }
        );
        _shortLayer.addLayer(arc);
      } else if (_showShort) {
        // Fallback: manual SLERP with antimeridian splitting
        const pts = gcPoints(HOME[0], HOME[1], d.lat, d.lon, 80);
        const segments = splitAtAntimeridian(pts);
        segments.forEach(seg => {
          _shortLayer.addLayer(L.polyline(seg, {color:col, weight:1.2, opacity:0.55}));
        });
      }

      // ── Long-path arc (dashed) ─────────────────────────────────────────────
      // Long path = the great circle from A to B going the "wrong way around".
      // Correct method: the long path passes through BOTH antipodal points.
      // We use the antipodal of the TARGET station as an intermediate waypoint
      // so Leaflet.Geodesic routes home → antiTarget → target, which forces
      // it to go the long way. This always produces the correct long path.
      if (_showLong && typeof L.geodesic !== 'undefined') {
        const antiLat = -(d.lat);
        const antiLon = d.lon > 0 ? d.lon - 180 : d.lon + 180;
        const arc = L.geodesic(
          [[L.latLng(HOME[0], HOME[1]),
            L.latLng(antiLat, antiLon),
            L.latLng(d.lat, d.lon)]],
          {
            weight: 1.2,
            color: col,
            opacity: 0.35,
            dashArray: '5 7',
            steps: 120,
            wrap: false,     // continuous arc, no antimeridian splitting
          }
        );
        _longLayer.addLayer(arc);
      }

      // ── Station marker ────────────────────────────────────────────────────
      const marker = L.circleMarker([d.lat, d.lon], {
        radius: r,
        color: col,
        fillColor: col,
        fillOpacity: 0.85,
        weight: 1.5,
      }).bindTooltip(`
        <div style="font-family:Consolas,monospace;font-size:11px;line-height:1.7">
          <b style="color:${col}">${d.call}</b><br>
          ${d._band.toLowerCase()} · ${d.count} QSO${d.count>1?'s':''}
          ${d.mult ? `<br><span style="color:#f0c040">✦ Mult: ${d.mult}</span>` : ''}
          <br><span style="color:#8b949e">SP: ${dist.toLocaleString()} km</span>
          <span style="color:#8b949e"> · LP: ${distLP.toLocaleString()} km</span>
        </div>`, { direction:'top', offset:[0,-r], opacity:0.97 });
      _markerLayer.addLayer(marker);
    });

    // Bring markers to front
    _markerLayer.eachLayer(l => l.bringToFront?.());
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

  // Home coordinates manual entry
  function applyHomeInput() {
    const val = document.getElementById('map-home-input')?.value.trim();
    if (!val) return;
    const parts = val.split(',').map(Number);
    if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
      HOME = [parts[0], parts[1]];
      if (_homeMarker) _homeMarker.setLatLng(HOME);
      render();
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
    if (d?._home_lat != null && d?._home_lon != null) {
      HOME = [d._home_lat, d._home_lon];
      if (_homeMarker) _homeMarker.setLatLng(HOME);
    }
    if (_map && document.querySelector('.tab-btn[data-tab="map"]')?.classList.contains('active')) {
      load();
    }
  });

  // Tab switch
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab !== 'map') return;
    if (!_map) {
      setTimeout(() => { initMap(); load(); }, 80);
    } else {
      setTimeout(() => { _map.invalidateSize(true); render(); }, 100);
    }
  });

  window.addEventListener('resize', () => { if (_map) _map.invalidateSize(true); });

})();
