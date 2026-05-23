'use strict';

// ══════════════════════════════════════════════════════════════
// 1. Constants
// ══════════════════════════════════════════════════════════════
// 5 traffic levels: clear → slow → moderate → heavy → critical
const TRAFFIC_COLORS = ['#22C55E', '#EAB308', '#F97316', '#EF4444', '#7C3AED'];
const POI_COLORS = {
  restaurant: '#EA580C', gas_station: '#D97706', hospital: '#DC2626',
  hotel: '#7C3AED', school: '#2563EB', park: '#16A34A', mall: '#DB2777',
  bank: '#0891B2', police: '#1D4ED8', pharmacy: '#059669', coffee: '#92400E',
  parking: '#2563EB', repair: '#64748B', default: '#6366F1',
};
const POI_LABELS = {
  restaurant: '⁕', gas_station: '⛽', hospital: '✖', hotel: '⌂',
  school: '★', park: '♣', mall: '☷', bank: '$',
  police: '☆', pharmacy: '+', coffee: '☕',
  parking: 'P', repair: '⚒', default: '✸',
};

function poiSvgIcon(poiType) {
  const color = POI_COLORS[poiType] || POI_COLORS.default;
  const label = POI_LABELS[poiType] || POI_LABELS.default;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="40" viewBox="0 0 28 40">
    <path d="M14 0 C6.3 0 0 6.3 0 14 c0 10.5 14 26 14 26 s14-15.5 14-26 C28 6.3 21.7 0 14 0z"
          fill="${color}" stroke="#fff" stroke-width="1.5"/>
    <circle cx="14" cy="14" r="8" fill="#fff" opacity="0.9"/>
    <text x="14" y="18" text-anchor="middle" font-size="12" font-weight="bold"
          fill="${color}" font-family="Arial,sans-serif">${label}</text>
  </svg>`;
  return L.divIcon({
    html: svg,
    className: '',
    iconSize: [28, 40],
    iconAnchor: [14, 40],
    popupAnchor: [0, -36],
  });
}

// ══════════════════════════════════════════════════════════════
// 2. App State
// ══════════════════════════════════════════════════════════════
const S = {
  mapLoaded:   false,
  mapWidth:    2000,
  mapHeight:   1500,
  startVertex: null,
  endVertex:   null,
  cellPx:      75,
  showPois:    true,
  showTraffic: false,
  showCars:    false,
  simRunning:  false,
  genPolling:  null,
  simPolling:  null,
  nearbyMode:  false,
};

// AbortController for in-flight viewport requests (cancels stale ones)
let _vpAbort      = null;
// Separate timer for periodic traffic-color refresh during simulation
let _trafficTimer = null;
// Simulation speed levels (steps per 0.05s tick)
const SIM_SPEEDS = [1, 2, 5, 10, 20, 50];
let _simSpeedIdx = 2;  // default 5×

// Canvas rendering state (replaces Leaflet polyline/circleMarker layers)
let _edgeCanvas  = null;   // HTMLCanvasElement for edges
let _vtxCanvas   = null;   // HTMLCanvasElement for vertices
let _carCanvas   = null;   // HTMLCanvasElement for car dots
let _canvasEdges = [];     // last edge dataset
let _canvasVerts = [];     // last vertex dataset (all vertices, for BFS)
let _canvasCars  = [];     // last car positions [{x,y}, ...]
let _canvasRep   = { cellRep: {}, vidToCell: {}, cellParent: {}, cellRepVid: {} };
let _rafId       = null;   // requestAnimationFrame handle

// ══════════════════════════════════════════════════════════════
// 3. Coordinate helpers  (graph ↔ Leaflet CRS.Simple)
//    Graph: x→right y→down     Leaflet: lng=x lat=-y
// ══════════════════════════════════════════════════════════════
const ll  = (x, y) => [-y, x];            // graph → leaflet LatLng
const glx = (lat, lng) => ({ x: lng, y: -lat }); // leaflet → graph

// ══════════════════════════════════════════════════════════════
// 4. API helpers
// ══════════════════════════════════════════════════════════════
const post = (url, body) =>
  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

const get = (url, params = {}) =>
  fetch(url + '?' + new URLSearchParams(params));

// ══════════════════════════════════════════════════════════════
// 5. Canvas overlay (zero-flicker edge+vertex rendering)
// ══════════════════════════════════════════════════════════════
function initCanvasLayers() {
  const container = document.getElementById('map');

  const mkCanvas = (zIdx) => {
    const c = document.createElement('canvas');
    c.style.cssText =
      `position:absolute;top:0;left:0;pointer-events:none;
       width:100%;height:100%;z-index:${zIdx}`;
    container.appendChild(c);
    return c;
  };

  _edgeCanvas = mkCanvas(395);   // below Leaflet overlayPane (400)
  _vtxCanvas  = mkCanvas(396);
  _carCanvas  = mkCanvas(397);    // above vertices, below overlayPane

  // Keep canvas pixel dimensions in sync with container
  const ro = new ResizeObserver(() => {
    _edgeCanvas.width  = container.clientWidth;
    _edgeCanvas.height = container.clientHeight;
    _vtxCanvas.width   = container.clientWidth;
    _vtxCanvas.height  = container.clientHeight;
    _carCanvas.width   = container.clientWidth;
    _carCanvas.height  = container.clientHeight;
    scheduleCanvasDraw();
  });
  ro.observe(container);

  // Smooth tracking: redraw every frame while map is moving
  map.on('move zoom', scheduleCanvasDraw);
  map.on('moveend zoomend', scheduleCanvasDraw);
}

function scheduleCanvasDraw() {
  if (_rafId) cancelAnimationFrame(_rafId);
  _rafId = requestAnimationFrame(doCanvasDraw);
}

function doCanvasDraw() {
  _rafId = null;
  drawEdgeCanvas();
  drawVtxCanvas();
  drawCarCanvas();
}

// Trace path from vid back to its cell representative via BFS parent chain
function _pathToRep(vid) {
  const { cellParent, cellRep, vidToCell, vidLookup } = _canvasRep;

  if (!(vid in cellParent)) {
    // Not reached by BFS — fallback to straight line
    const cell = vidToCell[vid];
    const repV = cell ? cellRep[cell] : null;
    const vObj = vidLookup ? vidLookup[vid] : null;
    if (!vObj) return [];
    if (repV && (repV.x !== vObj.x || repV.y !== vObj.y)) {
      return [repV, vObj];
    }
    return [vObj];
  }
  const path = [];
  let cur = vid;
  for (let i = 0; i < 2000; i++) {
    const vObj = vidLookup ? vidLookup[cur] : null;
    if (vObj) path.push(vObj);
    const parent = cellParent[cur];
    if (parent === null || parent === undefined) break;
    cur = parent;
  }
  path.reverse();
  return path; // [rep, ..., vid]
}

function drawEdgeCanvas() {
  if (!_edgeCanvas || !map) return;
  const ctx = _edgeCanvas.getContext('2d');
  const W = _edgeCanvas.width, H = _edgeCanvas.height;
  ctx.clearRect(0, 0, W, H);

  const { vidToCell } = _canvasRep;
  const drawn = new Set();

  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';

  _canvasEdges.forEach(e => {
    const cu = vidToCell[e.u], cv = vidToCell[e.v];
    if (!cu || !cv || cu === cv) return;
    const pk = cu < cv ? cu + '|' + cv : cv + '|' + cu;
    if (drawn.has(pk)) return;
    drawn.add(pk);

    // Build polyline: rep_A → … → u → v → … → rep_B
    const segA = _pathToRep(e.u); // [rep_A, ..., u]
    const segB = _pathToRep(e.v); // [rep_B, ..., v]
    const full = segA.concat(segB.slice().reverse());
    if (full.length < 2) return;

    if (S.showTraffic) {
      ctx.strokeStyle = TRAFFIC_COLORS[e.level] || TRAFFIC_COLORS[0];
      ctx.lineWidth   = Math.max(2, 1.5 + (e.level || 0) * 0.8);
      ctx.globalAlpha = 0.92;
    } else {
      ctx.strokeStyle = '#A0AEBB';
      ctx.lineWidth   = 1.5;
      ctx.globalAlpha = 0.85;
    }
    ctx.beginPath();
    const p0 = map.latLngToContainerPoint(ll(full[0].x, full[0].y));
    ctx.moveTo(p0.x, p0.y);
    for (let i = 1; i < full.length; i++) {
      const pt = map.latLngToContainerPoint(ll(full[i].x, full[i].y));
      ctx.lineTo(pt.x, pt.y);
    }
    ctx.stroke();
  });
  ctx.globalAlpha = 1;
}

function drawVtxCanvas() {
  if (!_vtxCanvas || !map) return;
  const ctx    = _vtxCanvas.getContext('2d');
  const W = _vtxCanvas.width, H = _vtxCanvas.height;
  ctx.clearRect(0, 0, W, H);

  const zoom   = map.getZoom();
  const radius = Math.max(3.5, 3 + zoom * 0.7);
  ctx.fillStyle   = '#0F172A';
  ctx.globalAlpha = 0.9;

  Object.values(_canvasRep.cellRep).forEach(v => {
    if (v.is_poi) return;  // POIs handled by Leaflet markers
    const pt = map.latLngToContainerPoint(ll(v.x, v.y));
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, radius, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.globalAlpha = 1;
}

// ══════════════════════════════════════════════════════════════
// 6. Leaflet map & layer groups
// ══════════════════════════════════════════════════════════════
let map;
const L_ = {};   // layer refs

function initMap() {
  map = L.map('map', {
    crs: L.CRS.Simple,
    zoomControl: false,
    attributionControl: false,
    preferCanvas: true,
    minZoom: -5,
    maxBoundsViscosity: 0.3,
  });

  L.control.zoom({ position: 'topright' }).addTo(map);

  // Layer groups: edges+vertices now drawn on canvas; keep others
  const layerKeys = ['nearby', 'path', 'tPath', 'cars', 'pois', 'history', 'inject'];
  layerKeys.forEach(k => { L_[k] = L.layerGroup().addTo(map); });

  // Default view
  map.setView([0, 0], 0);

  // Events
  map.on('click', onMapClick);
  map.on('contextmenu', onMapRightClick);
  map.on('mousemove', onMapMouseMove);
  map.on('moveend zoomend', debounce(refreshViewport, 350));
  map.on('moveend zoomend', drawMinimap);

  // Initialise canvas layers AFTER map is created
  initCanvasLayers();
}

// ══════════════════════════════════════════════════════════════
// 6. Map load / generate
// ══════════════════════════════════════════════════════════════
async function doGenerate() {
  const n    = parseInt(document.getElementById('inp-n').value)    || 2000;
  const seed = parseInt(document.getElementById('inp-seed').value) || 2026;
  setStatus('⏳ 生成地图中…', 'busy');
  document.getElementById('btn-generate').disabled = true;
  showProgress(true);

  await post('/api/map/generate', { n, seed });

  // Poll status
  S.genPolling = setInterval(async () => {
    const r = await (await fetch('/api/map/generate/status')).json();
    if (r.status === 'done') {
      clearInterval(S.genPolling);
      showProgress(false);
      document.getElementById('btn-generate').disabled = false;
      applyStats(r.data);
      S.mapLoaded = true;
      setMapBounds(r.data.width, r.data.height);
      refreshViewport();
      setStatus('✅ 地图生成完毕', 'ok');
      loadMinimapData();
    } else if (r.status === 'error') {
      clearInterval(S.genPolling);
      showProgress(false);
      document.getElementById('btn-generate').disabled = false;
      setStatus('❌ 生成失败: ' + r.data, 'error');
    }
  }, 500);
}

async function doLoad() {
  const fp = prompt('输入地图文件路径 (map.json):', 'map.json');
  if (!fp) return;
  const r = await (await post('/api/map/load', { filepath: fp })).json();
  if (r.error) { setStatus('❌ ' + r.error, 'error'); return; }
  applyStats(r.stats);
  S.mapLoaded = true;
  setMapBounds(r.stats.width, r.stats.height);
  refreshViewport();
  setStatus('✅ 地图已加载', 'ok');
  loadMinimapData();
}

async function doSave() {
  const fp = prompt('保存到文件:', 'map.json');
  if (!fp) return;
  const r = await (await post('/api/map/save', { filepath: fp })).json();
  if (r.error) { setStatus('❌ ' + r.error, 'error'); return; }
  setStatus(`✅ 已保存: ${r.filepath}`, 'ok');
}

function setMapBounds(w, h) {
  S.mapWidth  = w;
  S.mapHeight = h;
  const bounds = [[-h, 0], [0, w]];
  map.fitBounds(bounds, { padding: [30, 30] });
  // Allow generous panning but no hard clamp so user can always see full map
  map.setMaxBounds([[-h * 3, -w * 2], [h * 2, w * 3]]);
}

function applyStats(s) {
  document.getElementById('stat-v').textContent    = s.vertices   ?? '—';
  document.getElementById('stat-e').textContent    = s.edges      ?? '—';
  document.getElementById('stat-poi').textContent  = s.poi_count  ?? '—';
  const conn = s.connected;
  const el   = document.getElementById('stat-conn');
  el.textContent = conn ? '✅ 完全连通' : '⚠ 未连通';
  el.className   = 'info-val ' + (conn ? 'green' : 'amber');
  // Enable traffic path button when start+end are set (sim not strictly required)
  document.getElementById('btn-tpath').disabled = !(S.startVertex && S.endVertex);
}

// ══════════════════════════════════════════════════════════════
// 7. Viewport refresh (F2) — server fetches all data, client does
//    grid-based representative point filtering (same as main_gui)
// ══════════════════════════════════════════════════════════════
async function refreshViewport() {
  if (!S.mapLoaded) return;

  // Cancel any in-flight request — stale responses must never overwrite fresh renders
  if (_vpAbort) { _vpAbort.abort(); }
  _vpAbort = new AbortController();
  const { signal } = _vpAbort;

  const b    = map.getBounds();
  const xMin = b.getWest(),   xMax = b.getEast();
  const yMin = -b.getNorth(), yMax = -b.getSouth();

  try {
    const resp = await fetch('/api/viewport?' + new URLSearchParams({
      x_min: xMin, y_min: yMin, x_max: xMax, y_max: yMax,
      representative: false,
      traffic: S.showTraffic,
    }), { signal });
    if (signal.aborted) return;
    const r = await resp.json();
    if (r.error || signal.aborted) return;

    _canvasVerts = r.vertices;  // store all vertices for BFS path tracing
    const repMap = buildRepMap(r.vertices, r.edges);
    renderEdgesRep(r.edges, repMap);
    renderVerticesRep(repMap);
    drawMinimap();
  } catch (e) {
    if (e.name !== 'AbortError') { /* network error — ignore */ }
  }
}

// Traffic auto-refresh: fires every 1.5 s during simulation to update edge colors
function startTrafficRefresh() {
  if (_trafficTimer) return;
  _trafficTimer = setInterval(() => {
    if (S.showTraffic && S.simRunning) refreshViewport();
  }, 1500);
}
function stopTrafficRefresh() {
  if (_trafficTimer) { clearInterval(_trafficTimer); _trafficTimer = null; }
}


// Build grid representative map in MAP-COORDINATE space.
// Using graph coords (not screen pixels) makes the grid stable during pan;
// cell size in map-units = cellPx screen-pixels / current zoom scale.
// Also builds BFS parent trees within each cell for polyline edge tracing.
function buildRepMap(vertices, edges) {
  const cellRep    = {};   // cellKey -> vertex object
  const vidToCell  = {};   // vertex.id -> cellKey
  const cellRepVid = {};   // cellKey -> vertex.id (representative vid)
  const cellParent = {};   // vertex.id -> parent vertex.id (BFS tree, null=root)
  const cellVerts  = {};   // cellKey -> [vid, ...]

  // Convert cellPx (screen pixels) → map-coordinate units at current zoom
  const originPt = map.containerPointToLatLng(L.point(0, 0));
  const cellPt   = map.containerPointToLatLng(L.point(S.cellPx, S.cellPx));
  const cellMapX = Math.abs(cellPt.lng - originPt.lng) || 1;
  const cellMapY = Math.abs(cellPt.lat - originPt.lat) || 1;

  vertices.forEach(v => {
    const cx  = Math.floor(v.x / cellMapX);
    const cy  = Math.floor(v.y / cellMapY);
    const key = cx + ',' + cy;
    vidToCell[v.id] = key;
    if (!(key in cellRepVid)) {
      // First vertex in cell becomes initial representative
      cellRepVid[key] = v.id;
      cellRep[key] = v;
    } else if (v.is_poi && !cellRep[key].is_poi) {
      // POI vertex takes priority over non-POI representative
      cellRepVid[key] = v.id;
      cellRep[key] = v;
    }
    if (!cellVerts[key]) cellVerts[key] = [];
    cellVerts[key].push(v.id);
  });

  // Build intra-cell adjacency from edges (only same-cell edges)
  const cellAdj = {};  // vid -> [neighbor_vid, ...]
  if (edges) {
    edges.forEach(e => {
      const cu = vidToCell[e.u], cv = vidToCell[e.v];
      if (cu && cv && cu === cv) {
        if (!cellAdj[e.u]) cellAdj[e.u] = [];
        if (!cellAdj[e.v]) cellAdj[e.v] = [];
        cellAdj[e.u].push(e.v);
        cellAdj[e.v].push(e.u);
      }
    });
  }

  // BFS within each cell from representative to build parent tree
  Object.keys(cellVerts).forEach(key => {
    const repVid = cellRepVid[key];
    cellParent[repVid] = null; // root
    const vids = cellVerts[key];
    if (vids.length <= 1) return;
    const visited = new Set([repVid]);
    const queue = [repVid];
    let qi = 0;
    while (qi < queue.length) {
      const cur = queue[qi++];
      const neighbors = cellAdj[cur] || [];
      for (const nb of neighbors) {
        if (!visited.has(nb)) {
          visited.add(nb);
          cellParent[nb] = cur;
          queue.push(nb);
        }
      }
    }
  });

  // Build vid -> vertex object lookup for path tracing
  const vidLookup = {};
  vertices.forEach(v => { vidLookup[v.id] = v; });

  return { cellRep, vidToCell, cellParent, cellRepVid, vidLookup };
}

// ══════════════════════════════════════════════════════════════
// 8. Render layers
// ══════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════
// 8. Render layers (canvas-based, no DOM per-edge overhead)
// ══════════════════════════════════════════════════════════════

function renderEdgesRep(edges, repMap) {
  _canvasEdges = edges;
  _canvasRep   = repMap;
  scheduleCanvasDraw();
}

function renderVerticesRep({ cellRep }) {
  // Vertices on canvas; POIs still use Leaflet markers for click/popup support
  _canvasRep = { ..._canvasRep, cellRep };  // update cellRep in place
  scheduleCanvasDraw();

  L_['pois'].clearLayers();
  Object.values(cellRep).forEach(v => {
    if (!v.is_poi || !S.showPois) return;
    const icon = poiSvgIcon(v.poi_type);
    const label = POI_LABELS[v.poi_type] || v.poi_type;
    L.marker(ll(v.x, v.y), { icon, zIndexOffset: 500 })
      .bindPopup(`<b>${label} ${v.poi_name || v.poi_type}</b><br/>
        <span style="color:#94A3B8;font-size:11px">(${v.x.toFixed(0)}, ${v.y.toFixed(0)})</span>`)
      .addTo(L_['pois']);
  });
}

function renderNearby(data) {
  L_['nearby'].clearLayers();
  // Edges
  data.edges.forEach(e => {
    L.polyline([ll(e.x1, e.y1), ll(e.x2, e.y2)], {
      color: '#F59E0B', weight: 2, opacity: 0.9,
    }).addTo(L_['nearby']);
  });
  // Vertices
  data.vertices.forEach(v => {
    L.circleMarker(ll(v.x, v.y), {
      radius: 4, fillColor: '#FCD34D', fillOpacity: 1,
      color: '#FDE68A', weight: 1,
    }).addTo(L_['nearby']);
  });
  // Center pulse
  L.circleMarker(ll(data.center.x, data.center.y), {
    radius: 18, fillColor: '#F59E0B', fillOpacity: 0.15,
    color: '#F59E0B', weight: 2,
  }).addTo(L_['nearby']);
}

function renderPath(coords, edgeLevels) {
  L_['path'].clearLayers();
  if (coords.length < 2) return;
  const latlngs = coords.map(p => ll(p.x, p.y));

  // Glow underlay
  L.polyline(latlngs, {
    color: '#3B82F6', weight: 10, opacity: 0.15, lineCap: 'round',
  }).addTo(L_['path']);

  // Main path (solid)
  L.polyline(latlngs, {
    color: '#3B82F6', weight: 4, opacity: 0.95, lineCap: 'round',
  }).addTo(L_['path']);
}

function renderTrafficPath(coords, edgeLevels) {
  L_['tPath'].clearLayers();
  if (coords.length < 2) return;

  // Draw segment by segment with traffic color
  for (let i = 0; i < coords.length - 1; i++) {
    const lv    = edgeLevels ? (edgeLevels[i] || 0) : 0;
    const color = TRAFFIC_COLORS[lv];
    // Glow
    L.polyline([ll(coords[i].x, coords[i].y), ll(coords[i+1].x, coords[i+1].y)], {
      color, weight: 9, opacity: 0.15, lineCap: 'round',
    }).addTo(L_['tPath']);
    // Line
    L.polyline([ll(coords[i].x, coords[i].y), ll(coords[i+1].x, coords[i+1].y)], {
      color, weight: 4, opacity: 0.95, lineCap: 'round',
    }).addTo(L_['tPath']);
  }
}

function renderCars(cars) {
  _canvasCars = cars || [];
  scheduleCanvasDraw();
}

function drawCarCanvas() {
  if (!_carCanvas || !map) return;
  const ctx = _carCanvas.getContext('2d');
  const W = _carCanvas.width, H = _carCanvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!S.showCars || _canvasCars.length === 0) return;

  // Density-based thinning: max ~600 dots visible at once
  const maxVisible = 600;
  let cars = _canvasCars;
  if (cars.length > maxVisible) {
    // Uniform sampling
    const ratio = maxVisible / cars.length;
    cars = cars.filter(() => Math.random() < ratio);
  }

  const zoom = map.getZoom();
  const r = Math.max(3, 2.5 + zoom * 0.4);
  ctx.fillStyle = '#FACC15';       // bright yellow
  ctx.strokeStyle = '#B45309';     // dark amber outline
  ctx.lineWidth = 1;
  ctx.globalAlpha = 0.95;

  cars.forEach(c => {
    const pt = map.latLngToContainerPoint(ll(c.x, c.y));
    // Only draw if in viewport
    if (pt.x < -10 || pt.x > W + 10 || pt.y < -10 || pt.y > H + 10) return;
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });
  ctx.globalAlpha = 1;
}

function renderHistory(data) {
  L_['history'].clearLayers();
  data.edges.forEach(e => {
    const color = TRAFFIC_COLORS[e.level || 0];
    L.polyline([ll(e.x1, e.y1), ll(e.x2, e.y2)], {
      color, weight: 3.5, opacity: 0.9,
    }).addTo(L_['history']);
  });
  // Center marker
  L.circleMarker(ll(data.center.x, data.center.y), {
    radius: 16, fillColor: '#3B82F6', fillOpacity: 0.12,
    color: '#3B82F6', weight: 2,
  }).addTo(L_['history']);
}

// ══════════════════════════════════════════════════════════════
// 9. Start/End markers
// ══════════════════════════════════════════════════════════════
let _startMarker = null, _endMarker = null;

function placeMarker(v, type) {
  const isStart = (type === 'start');
  if (isStart && _startMarker) { map.removeLayer(_startMarker); _startMarker = null; }
  if (!isStart && _endMarker)  { map.removeLayer(_endMarker);  _endMarker   = null; }

  const icon = L.divIcon({
    html: `<div class="marker-icon marker-${type}"><span>${isStart ? 'S' : 'E'}</span></div>`,
    className: '', iconSize: [28, 28], iconAnchor: [14, 28],
  });
  const m = L.marker(ll(v.x, v.y), { icon, zIndexOffset: 1000 }).addTo(map);
  if (isStart) _startMarker = m; else _endMarker = m;
  drawMinimap();
}

// ══════════════════════════════════════════════════════════════
// 10. Map click handlers
// ══════════════════════════════════════════════════════════════
async function onMapClick(e) {
  if (!S.mapLoaded) return;
  const { x, y } = glx(e.latlng.lat, e.latlng.lng);

  // Fetch nearest vertex
  let res;
  try {
    res = await (await get('/api/nearest', { x, y })).json();
  } catch { return; }
  if (res.error) return;
  const v = res;

  // F1 nearby mode: just set coords and run
  if (S.nearbyMode) {
    document.getElementById('nearby-x').value = v.x.toFixed(0);
    document.getElementById('nearby-y').value = v.y.toFixed(0);
    doNearby();
    return;
  }

  // Path mode
  if (!S.startVertex) {
    S.startVertex = v;
    placeMarker(v, 'start');
    document.getElementById('ep-start').textContent = `S — ID:${v.id}  (${v.x.toFixed(0)}, ${v.y.toFixed(0)})`;
    setStatus(`✅ 起点已设置 (ID:${v.id}) — 请点击终点`, 'ok');
  } else if (!S.endVertex) {
    S.endVertex = v;
    placeMarker(v, 'end');
    document.getElementById('ep-end').textContent = `E — ID:${v.id}  (${v.x.toFixed(0)}, ${v.y.toFixed(0)})`;
    setStatus('⏳ 规划路径中…', 'busy');
    await findPath();
  } else {
    // Reset to new start
    S.startVertex = v; S.endVertex = null;
    L_['path'].clearLayers(); L_['tPath'].clearLayers();
    document.getElementById('path-result').classList.add('hidden');
    placeMarker(v, 'start');
    document.getElementById('ep-start').textContent = `S — ID:${v.id}  (${v.x.toFixed(0)}, ${v.y.toFixed(0)})`;
    document.getElementById('ep-end').textContent   = 'E — 终点未设置';
    setStatus(`🔄 新起点 (ID:${v.id}) — 请点击终点`, 'ok');
  }
  updateTPathBtn();
}

function onMapRightClick() {
  clearPath();
}

function onMapMouseMove(e) {
  const { x, y } = glx(e.latlng.lat, e.latlng.lng);
  document.getElementById('coord-display').textContent =
    `(${x.toFixed(0)}, ${y.toFixed(0)})`;
}

// ══════════════════════════════════════════════════════════════
// 11. F3 Shortest path
// ══════════════════════════════════════════════════════════════
async function findPath() {
  if (!S.startVertex || !S.endVertex) return;
  const algo = document.getElementById('algo-sel').value;
  try {
    const r = await (await get('/api/path', {
      start: S.startVertex.id, end: S.endVertex.id, algo,
    })).json();
    if (r.error) { setStatus('❌ 路径错误: ' + r.error, 'error'); return; }
    renderPath(r.path);
    // Pan to fit
    if (r.path.length > 1) {
      const lls = r.path.map(p => ll(p.x, p.y));
      map.fitBounds(L.latLngBounds(lls), { padding: [60, 60], maxZoom: map.getZoom() });
    }
    // Show results
    document.getElementById('r-algo').textContent = r.algorithm.toUpperCase();
    document.getElementById('r-dist').textContent = r.distance.toFixed(1);
    document.getElementById('r-hops').textContent = r.hops;
    document.getElementById('r-vis').textContent  = r.nodes_visited;
    document.getElementById('r-ms').textContent   = r.elapsed_ms.toFixed(2) + ' ms';
    document.getElementById('path-result').classList.remove('hidden');
    setStatus(`✅ 路径规划完成 — 距离 ${r.distance.toFixed(1)}, ${r.hops} 跳`, 'ok');
  } catch (ex) {
    setStatus('❌ 路径规划失败: ' + ex.message, 'error');
  }
}

function clearPath() {
  S.startVertex = null; S.endVertex = null;
  if (_startMarker) { map.removeLayer(_startMarker); _startMarker = null; }
  if (_endMarker)   { map.removeLayer(_endMarker);   _endMarker   = null; }
  L_['path'].clearLayers(); L_['tPath'].clearLayers();
  document.getElementById('ep-start').textContent = 'S — 起点未设置';
  document.getElementById('ep-end').textContent   = 'E — 终点未设置';
  document.getElementById('path-result').classList.add('hidden');
  document.getElementById('tpath-result').classList.add('hidden');
  updateTPathBtn();
  setStatus('路径已清除', 'idle');
  drawMinimap();
}

// ══════════════════════════════════════════════════════════════
// 12. F1 Nearby subgraph
// ══════════════════════════════════════════════════════════════
async function doNearby() {
  if (!S.mapLoaded) { setStatus('请先加载地图', 'error'); return; }
  const x = parseFloat(document.getElementById('nearby-x').value) || 1000;
  const y = parseFloat(document.getElementById('nearby-y').value) || 750;
  const k = parseInt(document.getElementById('nearby-k').value)   || 100;
  setStatus('🔍 查询附近子图…', 'busy');
  try {
    const r = await (await get('/api/nearby', { x, y, k })).json();
    if (r.error) { setStatus('❌ ' + r.error, 'error'); return; }
    renderNearby(r);
    document.getElementById('nb-center').textContent = `(${x.toFixed(0)}, ${y.toFixed(0)})`;
    document.getElementById('nb-v').textContent      = r.vertices.length;
    document.getElementById('nb-e').textContent      = r.edges.length;
    document.getElementById('nearby-result').classList.remove('hidden');
    setStatus(`🔍 已显示 ${r.vertices.length} 个最近节点`, 'ok');
  } catch (ex) {
    setStatus('❌ 查询失败: ' + ex.message, 'error');
  }
}

function clearNearby() {
  L_['nearby'].clearLayers();
  document.getElementById('nearby-result').classList.add('hidden');
  setStatus('就绪', 'idle');
}

// ══════════════════════════════════════════════════════════════
// 13. F4 Traffic simulation
// ══════════════════════════════════════════════════════════════
async function doSimStart() {
  if (!S.mapLoaded) { setStatus('请先加载地图', 'error'); return; }
  const cars      = parseInt(document.getElementById('sim-cars').value)    || 0;
  const densLo    = parseFloat(document.getElementById('sim-dens-lo').value) || 0.2;
  const densHi    = parseFloat(document.getElementById('sim-dens-hi').value) || 0.5;
  document.getElementById('btn-sim-start').disabled = true;
  setStatus('🚗 正在启动模拟…', 'busy');
  try {
    const r = await (await post('/api/sim/start', {
      cars, density_low: densLo, density_high: densHi,
    })).json();
    if (r.error) {
      document.getElementById('btn-sim-start').disabled = false;
      setStatus('❌ ' + r.error, 'error');
      return;
    }
  } catch (ex) {
    document.getElementById('btn-sim-start').disabled = false;
    setStatus('❌ 启动失败: ' + ex.message, 'error');
    return;
  }
  S.simRunning = true;
  document.getElementById('btn-sim-stop').disabled  = false;
  document.getElementById('sim-stats').classList.remove('hidden');
  // Auto-enable traffic colors (same as main_gui: chk_traffic.setChecked(True))
  const chkTraffic = document.getElementById('chk-traffic');
  if (!chkTraffic.checked) {
    chkTraffic.checked = true;
    onTrafficToggle();
  }
  // Auto-enable car display
  const chkCars = document.getElementById('chk-cars');
  if (!chkCars.checked) {
    chkCars.checked = true;
    S.showCars = true;
  }
  // Switch to traffic tab so user sees sim stats
  switchTab('traffic');
  // Poll simulation state
  S.simPolling = setInterval(pollSimState, 400);
  setStatus('🚗 交通模拟运行中（车辆生成中…）', 'busy');
  updateTPathBtn();
  // Sync current speed to server and start traffic refresh if needed
  post('/api/sim/speed', { speed: SIM_SPEEDS[_simSpeedIdx] });
  if (S.showTraffic) startTrafficRefresh();
}

async function doSimStop() {
  // 1. Immediately update client state — don't wait for anything
  S.simRunning = false;
  if (S.simPolling) { clearInterval(S.simPolling); S.simPolling = null; }
  stopTrafficRefresh();
  document.getElementById('btn-sim-start').disabled = false;
  document.getElementById('btn-sim-stop').disabled  = true;
  _canvasCars = [];
  scheduleCanvasDraw();
  setStatus('⏹ 模拟已停止', 'ok');
  updateTPathBtn();
  // 2. Tell server to stop (fire-and-forget, returns instantly)
  post('/api/sim/stop', {}).catch(() => {});
  // 3. Refresh viewport for clean final state
  refreshViewport();
}

async function pollSimState() {
  if (!S.simRunning) return;
  try {
    const r = await (await fetch('/api/sim/state')).json();
    if (r.error || !S.simRunning) return;
    document.getElementById('sim-t').textContent      = r.time_step;
    document.getElementById('sim-active').textContent = r.active_cars;
    document.getElementById('sim-avg').textContent    = (r.average_ratio * 100).toFixed(1) + '%';
    document.getElementById('sim-max').textContent    = (r.max_ratio * 100).toFixed(1) + '%';
    if (r.cars && r.cars.length && S.simRunning) renderCars(r.cars);
    // Traffic colors are updated by the dedicated _trafficTimer, not here,
    // to avoid flooding the server with concurrent viewport requests.
  } catch { /* ignore */ }
}

async function doInject() {
  const x = parseFloat(document.getElementById('inj-x').value) || 1000;
  const y = parseFloat(document.getElementById('inj-y').value) || 750;
  const radius = parseFloat(document.getElementById('inj-r').value) || 100;
  const intensity = parseFloat(document.getElementById('inj-i').value) || 50;
  try {
    const r = await (await post('/api/traffic/inject', {
      x, y, radius, intensity,
    })).json();
    if (r.error) { setStatus('❌ ' + r.error, 'error'); return; }
    // 在注入中心绘制红色标记
    renderInjectMarker(x, y, radius, r.affected);
    setStatus(`💥 已注入事件，影响 ${r.affected} 条边`, 'ok');
  } catch (ex) {
    setStatus('❌ 注入失败: ' + ex.message, 'error');
  }
}

function renderInjectMarker(x, y, radius, affected) {
  // 保留之前的标记，叠加显示多次注入
  // 影响范围半透明红圈
  L.circle(ll(x, y), {
    radius: radius, fillColor: '#EF4444', fillOpacity: 0.08,
    color: '#EF4444', weight: 1.5, dashArray: '6,4',
  }).addTo(L_['inject']);
  // 红色实心圆点（中心）
  L.circleMarker(ll(x, y), {
    radius: 8, fillColor: '#EF4444', fillOpacity: 1,
    color: '#FFFFFF', weight: 2,
  }).addTo(L_['inject']);
  // 标注受影响边数
  const icon = L.divIcon({
    html: `<div style="
      color:#EF4444; font-size:11px; font-weight:700;
      text-shadow:0 0 3px #fff, 0 0 3px #fff;
      white-space:nowrap;
    ">💥 ${affected}条边</div>`,
    className: '',
    iconAnchor: [-12, 4],
  });
  L.marker(ll(x, y), { icon, interactive: false }).addTo(L_['inject']);
}

function clearInject() {
  L_['inject'].clearLayers();
}

// ══════════════════════════════════════════════════════════════
// 14. F5 Traffic-aware path
// ══════════════════════════════════════════════════════════════
async function doTrafficPath() {
  if (!S.startVertex || !S.endVertex) {
    setStatus('请先设置起点和终点', 'error'); return;
  }
  const c   = parseFloat(document.getElementById('f5-c').value)   || 1.5;
  const thr = parseFloat(document.getElementById('f5-thr').value) || 0.8;
  setStatus('🚀 规划交通感知路径…', 'busy');
  try {
    const r = await (await get('/api/traffic_path', {
      start: S.startVertex.id, end: S.endVertex.id,
      c, threshold: thr,
    })).json();
    if (r.error) { setStatus('❌ ' + r.error, 'error'); return; }
    renderTrafficPath(r.path, r.edge_levels);
    document.getElementById('tp-dist').textContent  = r.distance.toFixed(1);
    document.getElementById('tp-sdist').textContent = r.static_distance.toFixed(1);
    document.getElementById('tp-saved').textContent = r.saved.toFixed(1);
    document.getElementById('tp-cong').textContent  = r.congestion_count;
    document.getElementById('tp-ms').textContent    = r.elapsed_ms.toFixed(2) + ' ms';
    document.getElementById('tpath-result').classList.remove('hidden');
    setStatus(`🚀 交通路径规划完成 — 距离 ${r.distance.toFixed(1)}`, 'ok');
  } catch (ex) {
    setStatus('❌ 规划失败: ' + ex.message, 'error');
  }
}

function updateTPathBtn() {
  document.getElementById('btn-tpath').disabled =
    !(S.startVertex && S.endVertex);
}

// ══════════════════════════════════════════════════════════════
// 15. Historical traffic query
// ══════════════════════════════════════════════════════════════
async function doHistory() {
  if (!S.mapLoaded) { setStatus('请先加载地图', 'error'); return; }
  const x = parseFloat(document.getElementById('hist-x').value) || 1000;
  const y = parseFloat(document.getElementById('hist-y').value) || 750;
  const t = parseInt(document.getElementById('hist-t').value)   || 0;
  const r = parseFloat(document.getElementById('hist-r').value) || 300;
  try {
    const res = await (await get('/api/traffic/history', { x, y, t, r })).json();
    if (res.error) { setStatus('❌ ' + res.error, 'error'); return; }
    renderHistory(res);
    document.getElementById('hist-edges').textContent = res.edges.length;
    const hc = document.getElementById('hist-center');
    const ht = document.getElementById('hist-time-res');
    if (hc) hc.textContent = `(${x.toFixed(0)}, ${y.toFixed(0)})`;
    if (ht) ht.textContent = t;
    document.getElementById('hist-result').classList.remove('hidden');
    setStatus(`🕒 已查询 T=${t} 时的交通状态，${res.edges.length} 条边`, 'ok');
  } catch (ex) {
    setStatus('❌ 查询失败', 'error');
  }
}

function clearHistory() {
  L_['history'].clearLayers();
  document.getElementById('hist-result').classList.add('hidden');
}

// ══════════════════════════════════════════════════════════════
// 16. Display option toggles
// ══════════════════════════════════════════════════════════════
function onTrafficToggle() {
  S.showTraffic = document.getElementById('chk-traffic').checked;
  // Instant canvas redraw with current data — no network request needed
  scheduleCanvasDraw();
  refreshViewport();  // also fetch updated traffic levels from server
  if (S.showTraffic && S.simRunning) startTrafficRefresh();
  else stopTrafficRefresh();
}

function onCarsToggle() {
  S.showCars = document.getElementById('chk-cars').checked;
  scheduleCanvasDraw();  // car canvas reads S.showCars
}

// Simulation speed control
async function changeSimSpeed(delta) {
  _simSpeedIdx = Math.max(0, Math.min(SIM_SPEEDS.length - 1, _simSpeedIdx + delta));
  const speed = SIM_SPEEDS[_simSpeedIdx];
  document.getElementById('sim-speed-val').textContent = speed + '×';
  if (S.simRunning) {
    await post('/api/sim/speed', { speed });
  }
}

function changeCellPx(delta) {
  S.cellPx = Math.max(20, Math.min(250, S.cellPx + delta));
  document.getElementById('cell-px-val').textContent = S.cellPx;
  refreshViewport();
}

// ══════════════════════════════════════════════════════════════
// 17. Tab switching
// ══════════════════════════════════════════════════════════════
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === name);
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'tab-' + name);
  });
}

// ══════════════════════════════════════════════════════════════
// 18. Status bar
// ══════════════════════════════════════════════════════════════
function setStatus(msg, type = 'idle') {
  document.getElementById('status-text').textContent = msg;
  const dot = document.getElementById('status-dot');
  dot.className = 'status-dot ' + type;
}

function showProgress(show) {
  document.getElementById('gen-progress').classList.toggle('hidden', !show);
}

// ══════════════════════════════════════════════════════════════
// MINIMAP
// ══════════════════════════════════════════════════════════════
let _minimapData = null;   // { vertices, edges } — downsampled full graph
let _minimapCtx  = null;
const MMAP_W = 190, MMAP_H = 142;  // canvas pixel dimensions

function initMinimap() {
  const canvas = document.getElementById('minimap');
  if (!canvas) return;
  _minimapCtx = canvas.getContext('2d');
  canvas.addEventListener('click', onMinimapClick);
  drawMinimap();
}

async function loadMinimapData() {
  try {
    const r = await (await fetch('/api/minimap')).json();
    if (r.error || !r.vertices) return;
    _minimapData = r;
    drawMinimap();
  } catch (e) { /* ignore */ }
}

function drawMinimap() {
  if (!_minimapCtx) return;
  const ctx = _minimapCtx;

  // Scale helpers: graph coords → minimap canvas pixels
  const mx = (x) => (x / S.mapWidth)  * MMAP_W;
  const my = (y) => (y / S.mapHeight) * MMAP_H;

  // Background (same as map)
  ctx.fillStyle = '#E4E8EE';
  ctx.fillRect(0, 0, MMAP_W, MMAP_H);

  if (_minimapData && _minimapData.vertices.length > 0) {
    // Edges
    ctx.strokeStyle = '#B4BEC9';
    ctx.lineWidth   = 0.7;
    ctx.globalAlpha = 0.6;
    _minimapData.edges.forEach(e => {
      ctx.beginPath();
      ctx.moveTo(mx(e.x1), my(e.y1));
      ctx.lineTo(mx(e.x2), my(e.y2));
      ctx.stroke();
    });

    // Vertices (tiny dots)
    ctx.globalAlpha = 0.85;
    ctx.fillStyle   = '#7A8FA0';
    _minimapData.vertices.forEach(v => {
      ctx.beginPath();
      ctx.arc(mx(v.x), my(v.y), 1.2, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  ctx.globalAlpha = 1;

  // Viewport rectangle
  if (S.mapLoaded && map) {
    const b   = map.getBounds();
    const rx1 = Math.max(0,      mx( b.getWest()));
    const ry1 = Math.max(0,      my(-b.getNorth()));
    const rx2 = Math.min(MMAP_W, mx( b.getEast()));
    const ry2 = Math.min(MMAP_H, my(-b.getSouth()));
    ctx.fillStyle   = 'rgba(37, 99, 235, 0.10)';
    ctx.fillRect(rx1, ry1, rx2 - rx1, ry2 - ry1);
    ctx.strokeStyle = '#2563EB';
    ctx.lineWidth   = 1.5;
    ctx.strokeRect(rx1, ry1, rx2 - rx1, ry2 - ry1);
  }

  // Start marker (blue S)
  if (S.startVertex) {
    const sx = mx(S.startVertex.x), sy = my(S.startVertex.y);
    ctx.fillStyle = '#2563EB';
    ctx.beginPath(); ctx.arc(sx, sy, 4.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 6px Inter,sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('S', sx, sy);
  }

  // End marker (red E)
  if (S.endVertex) {
    const ex = mx(S.endVertex.x), ey = my(S.endVertex.y);
    ctx.fillStyle = '#DC2626';
    ctx.beginPath(); ctx.arc(ex, ey, 4.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 6px Inter,sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('E', ex, ey);
  }
}

function onMinimapClick(e) {
  if (!S.mapLoaded) return;
  const canvas = document.getElementById('minimap');
  const rect   = canvas.getBoundingClientRect();
  const gx = (e.clientX - rect.left) / rect.width  * S.mapWidth;
  const gy = (e.clientY - rect.top)  / rect.height * S.mapHeight;
  map.setView(ll(gx, gy), map.getZoom());
}

// ══════════════════════════════════════════════════════════════
// 19. Utility
// ══════════════════════════════════════════════════════════════
function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ══════════════════════════════════════════════════════════════
// 20. Entry point
// ══════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  initMinimap();
  setStatus('就绪 — 请生成或加载地图', 'idle');

  // Keyboard shortcuts (matches main_gui keybindings)
  document.addEventListener('keydown', (e) => {
    // F — fit map to bounds
    if (e.key === 'f' || e.key === 'F') {
      if (!S.mapLoaded || !map) return;
      const bounds = [[-S.mapHeight, 0], [0, S.mapWidth]];
      map.fitBounds(bounds, { padding: [30, 30] });
    }
    // Escape — clear path
    if (e.key === 'Escape') {
      clearPath();
    }
  });
});
