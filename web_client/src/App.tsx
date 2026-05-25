import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import L, { Map as LeafletMap } from 'leaflet';
import { api } from './api';
import type { AlgorithmCompareDTO, AnalyticsDTO, CarDTO, DemoDTO, EdgeDTO, ExportSnapshotDTO, HoveredEdgeDTO, MinimapDTO, NearbyDTO, PathDTO, POI, RouteExplainDTO, SimulationState, Stats, TrafficHistoryDTO, VertexDTO, ViewportDTO } from './types';

const trafficColors = ['#22c55e', '#eab308', '#f97316', '#ef4444'];
const poiLabels: Record<string, string> = {
  gas_station: '⛽',
  restaurant: '🍴',
  parking: 'P',
  repair: '🔧',
  hospital: 'H',
};
const poiNames: Record<string, string> = {
  all: 'All',
  gas_station: 'Gas Station',
  restaurant: 'Restaurant',
  parking: 'Parking',
  repair: 'Repair',
  hospital: 'Hospital',
};

const ll = (x: number, y: number): L.LatLngExpression => [-y, x];
const glx = (lat: number, lng: number) => ({ x: lng, y: -lat });
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));
const fmt = (n?: number, digits = 1) => Number.isFinite(n) ? Number(n).toFixed(digits) : '—';
const MAP_SIZE_MIN = 100;
const MAP_SIZE_MAX = 30000;
const MAP_SIZE_PRESETS = [5000, 10000, 20000, 30000];
const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));
const normalizeMapSize = (n: number) => Math.round(clamp(Number.isFinite(n) ? n : 30000, MAP_SIZE_MIN, MAP_SIZE_MAX));

type StepState = 'idle' | 'active' | 'done';
type SelectionMode = 'none' | 'start' | 'end';

interface LayerSettings {
  traffic: boolean;
  heat: boolean;
  cars: boolean;
  poi: boolean;
  trace: boolean;
}

interface DemoStep {
  label: string;
  state: StepState;
}

const makeDemoSteps = (n: number): DemoStep[] => [
  { label: `Generate ${n} vertices`, state: 'idle' },
  { label: 'Start rush-hour traffic', state: 'idle' },
  { label: 'Choose cross-city route', state: 'idle' },
  { label: 'Inject incident congestion', state: 'idle' },
  { label: 'Compare static vs detour', state: 'idle' },
];

const poiScenarios = [
  { label: 'Emergency Care', category: 'hospital' },
  { label: 'Nearest Gas', category: 'gas_station' },
  { label: 'Parking', category: 'parking' },
  { label: 'Roadside Repair', category: 'repair' },
  { label: 'Restaurant Route', category: 'restaurant' },
];

function pointToSegmentDistance(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax;
  const dy = by - ay;
  if (dx === 0 && dy === 0) return Math.hypot(px - ax, py - ay);
  const t = clamp(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy), 0, 1);
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function overviewMetrics(width: number, height: number, stats: Stats) {
  const padding = 8;
  const innerW = Math.max(1, width - padding * 2);
  const innerH = Math.max(1, height - padding * 2);
  const scale = Math.min(innerW / stats.width, innerH / stats.height);
  const mapW = stats.width * scale;
  const mapH = stats.height * scale;
  const offsetX = (width - mapW) / 2;
  const offsetY = (height - mapH) / 2;
  return {
    scale,
    offsetX,
    offsetY,
    toScreen: (x: number, y: number) => ({ x: offsetX + x * scale, y: offsetY + y * scale }),
    toWorld: (x: number, y: number) => ({ x: (x - offsetX) / scale, y: (y - offsetY) / scale }),
  };
}

function zoomDetail(zoom: number) {
  return clamp((zoom + 1.6) / 4.2, 0, 1);
}

export default function App() {
  const mapRef = useRef<LeafletMap | null>(null);
  const edgeCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const heatCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const vertexCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const carCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const traceCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const overviewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const statusTimerRef = useRef<number | null>(null);
  const lastMouseStatusRef = useRef(0);
  const highlightTimerRef = useRef<number | null>(null);
  const lastRouteExplainRequestRef = useRef<string | null>(null);
  const incidentModeRef = useRef(false);
  const selectionModeRef = useRef<SelectionMode>('none');
  const incidentRadiusRef = useRef(150);
  const incidentIntensityRef = useRef(120);
  const viewportRef = useRef<ViewportDTO>({ vertices: [], edges: [] });
  const injectManualIncidentRef = useRef<((x: number, y: number) => Promise<void>) | null>(null);

  const [status, setStatus] = useState({ text: 'Ready - generate a map or run the demo', kind: 'idle' });
  const [mapSize, setMapSize] = useState(30000);
  const [stats, setStats] = useState<Stats | null>(null);
  const [viewport, setViewport] = useState<ViewportDTO>({ vertices: [], edges: [] });
  const [minimapData, setMinimapData] = useState<MinimapDTO | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsDTO | null>(null);
  const [simState, setSimState] = useState<SimulationState | null>(null);
  const [cars, setCars] = useState<CarDTO[]>([]);
  const [layers, setLayers] = useState<LayerSettings>({ traffic: true, heat: true, cars: true, poi: true, trace: true });
  const [start, setStart] = useState<VertexDTO | null>(null);
  const [end, setEnd] = useState<VertexDTO | null>(null);
  const [staticPath, setStaticPath] = useState<PathDTO | null>(null);
  const [trafficPath, setTrafficPath] = useState<PathDTO | null>(null);
  const [algorithmCompare, setAlgorithmCompare] = useState<AlgorithmCompareDTO | null>(null);
  const [routeExplain, setRouteExplain] = useState<RouteExplainDTO | null>(null);
  const [routeExplainPending, setRouteExplainPending] = useState(false);
  const [routeExplainError, setRouteExplainError] = useState<string | null>(null);
  const [activeTrace, setActiveTrace] = useState<PathDTO | null>(null);
  const [traceIndex, setTraceIndex] = useState(0);
  const [tracePlaying, setTracePlaying] = useState(false);
  const [traceSpeed, setTraceSpeed] = useState(4);
  const [traceStepOverride, setTraceStepOverride] = useState<number | null>(null);
  const [algorithm, setAlgorithm] = useState<'astar' | 'dijkstra'>('astar');
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('none');
  const [simRunning, setSimRunning] = useState(false);
  const [poiCategory, setPoiCategory] = useState('gas_station');
  const [pois, setPois] = useState<POI[]>([]);
  const [poiScenario, setPoiScenario] = useState<string | null>(null);
  const [incident, setIncident] = useState<DemoDTO['incident'] | null>(null);
  const [incidentMode, setIncidentMode] = useState(false);
  const [incidentRadius, setIncidentRadius] = useState(150);
  const [incidentIntensity, setIncidentIntensity] = useState(120);
  const [highlightedEdge, setHighlightedEdge] = useState<EdgeDTO | null>(null);
  const [highlightVisible, setHighlightVisible] = useState(true);
  const [hoveredEdge, setHoveredEdge] = useState<HoveredEdgeDTO | null>(null);
  const [showCongestedPanel, setShowCongestedPanel] = useState(false);
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoStepIndex, setDemoStepIndex] = useState<number | null>(null);
  const [demoSteps, setDemoSteps] = useState<DemoStep[]>(() => makeDemoSteps(30000));
  const [nearbyX, setNearbyX] = useState(1000);
  const [nearbyY, setNearbyY] = useState(750);
  const [nearbyK, setNearbyK] = useState(100);
  const [nearbyResult, setNearbyResult] = useState<NearbyDTO | null>(null);
  const [trafficQueryX, setTrafficQueryX] = useState(1000);
  const [trafficQueryY, setTrafficQueryY] = useState(750);
  const [trafficQueryTime, setTrafficQueryTime] = useState(0);
  const [trafficQueryRadius, setTrafficQueryRadius] = useState(300);
  const [trafficQueryResult, setTrafficQueryResult] = useState<TrafficHistoryDTO | null>(null);

  const mapLoaded = Boolean(stats);
  const selectedMapSize = normalizeMapSize(mapSize);

  const setBusy = (text: string) => setStatus({ text, kind: 'busy' });
  const setOk = (text: string) => setStatus({ text, kind: 'ok' });
  const setError = (text: string) => setStatus({ text, kind: 'error' });

  const setDemoTimeline = useCallback((activeIndex: number | null, doneUntil = -1, size = selectedMapSize) => {
    setDemoStepIndex(activeIndex);
    setDemoSteps(makeDemoSteps(size).map((step, idx) => ({
      ...step,
      state: activeIndex === idx ? 'active' : idx <= doneUntil ? 'done' : 'idle',
    })));
  }, [selectedMapSize]);

  const startTracePlayback = useCallback((path: PathDTO, targetMs?: number) => {
    const maxLen = Math.max(path.visited.length, path.relaxed_edges.length);
    const targetStep = targetMs && maxLen > 0
      ? Math.max(1, Math.ceil(maxLen / Math.max(1, targetMs / 70)))
      : null;
    setActiveTrace(path);
    setTraceIndex(0);
    setTraceStepOverride(targetStep);
    setTracePlaying(true);
  }, []);

  const fitMap = useCallback((nextStats: Stats) => {
    const map = mapRef.current;
    if (!map) return;
    const bounds = L.latLngBounds([[-nextStats.height, 0], [0, nextStats.width]]);
    map.fitBounds(bounds, { padding: [32, 32] });
    map.setMaxBounds([[-nextStats.height * 2.5, -nextStats.width], [nextStats.height, nextStats.width * 2]]);
  }, []);

  const fitRoute = useCallback((points: Array<{ x: number; y: number }>) => {
    const map = mapRef.current;
    if (!map || points.length === 0) return;
    const bounds = L.latLngBounds(points.map((pt) => ll(pt.x, pt.y)));
    map.fitBounds(bounds, { padding: [72, 72] });
  }, []);

  const loadMinimap = useCallback(async () => {
    const data = await api.minimap();
    setMinimapData(data);
    return data;
  }, []);

  const flashCongestedEdge = useCallback((edge: EdgeDTO) => {
    if (highlightTimerRef.current !== null) {
      window.clearInterval(highlightTimerRef.current);
      highlightTimerRef.current = null;
    }
    setHighlightedEdge(edge);
    setHighlightVisible(true);
    mapRef.current?.panTo(ll((edge.x1 + edge.x2) / 2, (edge.y1 + edge.y2) / 2));
    setOk(`Centered congested road ${edge.u} - ${edge.v}`);
    let ticks = 0;
    highlightTimerRef.current = window.setInterval(() => {
      ticks += 1;
      setHighlightVisible((visible) => !visible);
      if (ticks >= 8) {
        if (highlightTimerRef.current !== null) {
          window.clearInterval(highlightTimerRef.current);
          highlightTimerRef.current = null;
        }
        setHighlightVisible(true);
        setHighlightedEdge(null);
      }
    }, 220);
  }, []);

  const resizeCanvases = useCallback(() => {
    const frame = document.getElementById('map-frame');
    if (!frame) return;
    const rect = frame.getBoundingClientRect();
    [heatCanvasRef, edgeCanvasRef, vertexCanvasRef, carCanvasRef, traceCanvasRef].forEach((ref) => {
      const canvas = ref.current;
      if (!canvas) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    });
  }, []);

  const mapPoint = useCallback((x: number, y: number) => {
    const map = mapRef.current;
    if (!map) return null;
    return map.latLngToContainerPoint(ll(x, y));
  }, []);

  const findHoveredEdge = useCallback((point: L.Point): HoveredEdgeDTO | null => {
    const map = mapRef.current;
    const currentViewport = viewportRef.current;
    if (!map || currentViewport.representative || currentViewport.edges.length > 9000 || zoomDetail(map.getZoom()) < 0.52) {
      return null;
    }
    let bestEdge: EdgeDTO | null = null;
    let bestDistance = Infinity;
    for (const edge of currentViewport.edges) {
      const a = mapPoint(edge.x1, edge.y1);
      const b = mapPoint(edge.x2, edge.y2);
      if (!a || !b) continue;
      const distance = pointToSegmentDistance(point.x, point.y, a.x, a.y, b.x, b.y);
      if (distance <= 8 && distance < bestDistance) {
        bestEdge = edge;
        bestDistance = distance;
      }
    }
    if (!bestEdge) return null;
    const edge = bestEdge;
    const rect = document.getElementById('map-frame')?.getBoundingClientRect();
    const maxX = Math.max(12, (rect?.width || window.innerWidth) - 250);
    const maxY = Math.max(12, (rect?.height || window.innerHeight) - 132);
    return {
      ...edge,
      screenX: clamp(point.x + 14, 12, maxX),
      screenY: clamp(point.y + 14, 12, maxY),
    };
  }, [mapPoint]);

  const drawRoads = useCallback(() => {
    const canvas = edgeCanvasRef.current;
    const map = mapRef.current;
    if (!canvas || !map) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.lineCap = 'round';
    const detail = zoomDetail(map.getZoom());
    viewport.edges.forEach((edge) => {
      if (detail < 0.18 && edge.level < 2 && edge.capacity < 110) return;
      const a = mapPoint(edge.x1, edge.y1);
      const b = mapPoint(edge.x2, edge.y2);
      if (!a || !b) return;
      const width = clamp(1 + Math.log1p(edge.capacity) / 2.4, 1.4, 5.6) * (0.42 + detail * 0.48);
      ctx.strokeStyle = layers.traffic && detail > 0.08
        ? trafficColors[edge.level]
        : edge.capacity > 120 ? '#7f8ea3' : '#b8c4d3';
      ctx.globalAlpha = layers.traffic ? 0.22 + detail * 0.42 : 0.42;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    });
    ctx.globalAlpha = 1;
  }, [layers.traffic, mapPoint, viewport.edges]);

  const drawHeat = useCallback(() => {
    const canvas = heatCanvasRef.current;
    const map = mapRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    if (!layers.heat) return;
    const detail = zoomDetail(map?.getZoom() ?? 0);
    viewport.edges.forEach((edge) => {
      if (detail < 0.25 && edge.level < 3 && edge.ratio < 1.1) return;
      if (edge.ratio < 0.35 && edge.level < 1) return;
      const a = mapPoint(edge.x1, edge.y1);
      const b = mapPoint(edge.x2, edge.y2);
      if (!a || !b) return;
      const ratio = clamp(edge.ratio, 0, 2.5);
      ctx.strokeStyle = trafficColors[edge.level];
      ctx.globalAlpha = (0.035 + Math.min(0.15, ratio * 0.065)) * (0.35 + detail * 0.65);
      ctx.lineWidth = (7 + ratio * 4.5) * (0.55 + detail * 0.55);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    });
    ctx.globalAlpha = 1;
  }, [layers.heat, mapPoint, viewport.edges]);

  const drawVerticesAndCity = useCallback(() => {
    const canvas = vertexCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);

    const poiColors: Record<string, string> = {
      gas_station: '#f59e0b',
      restaurant: '#ef4444',
      parking: '#2563eb',
      repair: '#64748b',
      hospital: '#dc2626',
    };

    if (layers.poi) {
      const districtGroups = new Map<string, VertexDTO[]>();
      viewport.vertices.forEach((v) => {
        if (v.is_poi && v.poi_type) {
          districtGroups.set(v.poi_type, [...(districtGroups.get(v.poi_type) || []), v]);
        }
      });
      districtGroups.forEach((list, type) => {
        list.slice(0, 20).forEach((v) => {
          const p = mapPoint(v.x, v.y);
          if (!p) return;
          const gradient = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 72);
          gradient.addColorStop(0, `${poiColors[type] || '#6366f1'}22`);
          gradient.addColorStop(1, `${poiColors[type] || '#6366f1'}00`);
          ctx.fillStyle = gradient;
          ctx.beginPath();
          ctx.arc(p.x, p.y, 72, 0, Math.PI * 2);
          ctx.fill();
        });
      });
    }

    const maxDots = 1600;
    const stride = Math.max(1, Math.ceil(viewport.vertices.length / maxDots));
    viewport.vertices.forEach((v, idx) => {
      if (idx % stride !== 0 && !v.is_poi) return;
      const p = mapPoint(v.x, v.y);
      if (!p) return;
      if (v.is_poi && layers.poi) {
        ctx.fillStyle = poiColors[v.poi_type || ''] || '#6366f1';
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = '#ffffff';
        ctx.font = '700 10px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(poiLabels[v.poi_type || ''] || '•', p.x, p.y);
      } else {
        ctx.fillStyle = '#73839a';
        ctx.globalAlpha = 0.55;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 2.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    });
  }, [layers.poi, mapPoint, viewport.vertices]);

  const drawCars = useCallback(() => {
    const canvas = carCanvasRef.current;
    const map = mapRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    if (!layers.cars) return;
    const detail = zoomDetail(map?.getZoom() ?? 0);
    if (detail < 0.28) return;
    const maxVisibleCars = detail > 0.76 ? 420 : 240;
    const stride = Math.max(1, Math.ceil(cars.length / maxVisibleCars));
    cars.forEach((car, idx) => {
      if (idx % stride !== 0) return;
      const p = mapPoint(car.x, car.y);
      if (!p) return;
      ctx.fillStyle = '#fde047';
      ctx.strokeStyle = '#92400e';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
  }, [cars, layers.cars, mapPoint]);

  const drawPathLine = useCallback((ctx: CanvasRenderingContext2D, path: PathDTO | null, color: string, dashed = false) => {
    if (!path || path.path.length < 2) return;
    const detail = zoomDetail(mapRef.current?.getZoom() ?? 0);
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = color;
    ctx.lineWidth = 4.2 + detail * 3.2;
    ctx.globalAlpha = 0.07 + detail * 0.08;
    ctx.setLineDash([]);
    ctx.beginPath();
    path.path.forEach((pt, idx) => {
      const p = mapPoint(pt.x, pt.y);
      if (!p) return;
      if (idx === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.stroke();
    ctx.globalAlpha = 0.58 + detail * 0.28;
    ctx.lineWidth = 1.8 + detail * 1.8;
    ctx.strokeStyle = color;
    if (dashed) ctx.setLineDash([12, 8]);
    ctx.beginPath();
    path.path.forEach((pt, idx) => {
      const p = mapPoint(pt.x, pt.y);
      if (!p) return;
      if (idx === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.stroke();
    ctx.restore();
  }, [mapPoint]);

  const drawTraceAndPaths = useCallback(() => {
    const canvas = traceCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);

    if (layers.trace && activeTrace) {
      const edgeLimit = Math.min(traceIndex, activeTrace.relaxed_edges.length);
      ctx.save();
      ctx.strokeStyle = '#8b5cf6';
      ctx.globalAlpha = 0.13;
      ctx.lineWidth = 2;
      for (let i = 0; i < edgeLimit; i++) {
        const edge = activeTrace.relaxed_edges[i];
        if (edge.x1 === undefined || edge.x2 === undefined) continue;
        const a = mapPoint(edge.x1, edge.y1!);
        const b = mapPoint(edge.x2, edge.y2!);
        if (!a || !b) continue;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
      const vLimit = Math.min(traceIndex, activeTrace.visited.length);
      ctx.fillStyle = '#7c3aed';
      ctx.globalAlpha = 0.24;
      for (let i = 0; i < vLimit; i++) {
        const v = activeTrace.visited[i];
        if (v.x === undefined || v.y === undefined) continue;
        const p = mapPoint(v.x, v.y);
        if (!p) continue;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3.2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    if (nearbyResult) {
      ctx.save();
      ctx.lineCap = 'round';
      ctx.strokeStyle = '#f59e0b';
      ctx.globalAlpha = 0.54;
      ctx.lineWidth = 2.4;
      nearbyResult.edges.forEach((edge) => {
        const a = mapPoint(edge.x1, edge.y1);
        const b = mapPoint(edge.x2, edge.y2);
        if (!a || !b) return;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      });
      ctx.fillStyle = '#f59e0b';
      ctx.globalAlpha = 0.74;
      nearbyResult.vertices.forEach((v) => {
        const p = mapPoint(v.x, v.y);
        if (!p) return;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.restore();
    }

    if (trafficQueryResult) {
      ctx.save();
      ctx.lineCap = 'round';
      trafficQueryResult.edges.forEach((edge) => {
        const a = mapPoint(edge.x1, edge.y1);
        const b = mapPoint(edge.x2, edge.y2);
        if (!a || !b) return;
        ctx.strokeStyle = trafficColors[edge.level] || '#64748b';
        ctx.globalAlpha = 0.76;
        ctx.lineWidth = 3.4;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      });
      ctx.restore();
    }

    drawPathLine(ctx, staticPath, '#2563eb');
    if (trafficPath?.edge_levels && trafficPath.path.length > 1) {
      const detail = zoomDetail(mapRef.current?.getZoom() ?? 0);
      if (detail < 0.32) {
        drawPathLine(ctx, trafficPath, '#7c3aed', true);
      } else {
        trafficPath.path.slice(0, -1).forEach((pt, i) => {
          const next = trafficPath.path[i + 1];
          const a = mapPoint(pt.x, pt.y);
          const b = mapPoint(next.x, next.y);
          if (!a || !b) return;
          const level = trafficPath.edge_levels?.[i] || 0;
          const color = trafficColors[level];
          ctx.strokeStyle = color;
          ctx.globalAlpha = (0.06 + level * 0.018) + detail * 0.06;
          ctx.lineWidth = 3.8 + detail * 3.4;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
          ctx.globalAlpha = 0.36 + detail * 0.34;
          ctx.lineWidth = 1.7 + detail * 1.7;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        });
        ctx.globalAlpha = 1;
      }
    } else {
      drawPathLine(ctx, trafficPath, '#7c3aed', true);
    }

    if (hoveredEdge) {
      const a = mapPoint(hoveredEdge.x1, hoveredEdge.y1);
      const b = mapPoint(hoveredEdge.x2, hoveredEdge.y2);
      if (a && b) {
        ctx.save();
        ctx.lineCap = 'round';
        ctx.strokeStyle = '#0f172a';
        ctx.globalAlpha = 0.2;
        ctx.lineWidth = 9;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.strokeStyle = trafficColors[hoveredEdge.level];
        ctx.globalAlpha = 0.82;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.restore();
      }
    }

    if (highlightedEdge && highlightVisible) {
      const a = mapPoint(highlightedEdge.x1, highlightedEdge.y1);
      const b = mapPoint(highlightedEdge.x2, highlightedEdge.y2);
      if (a && b) {
        ctx.save();
        ctx.lineCap = 'round';
        ctx.strokeStyle = '#fef08a';
        ctx.globalAlpha = 0.78;
        ctx.lineWidth = 16;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.strokeStyle = '#dc2626';
        ctx.globalAlpha = 1;
        ctx.lineWidth = 5;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.restore();
      }
    }

    const markerAt = (x: number, y: number, label: string, color: string) => {
      const p = mapPoint(x, y);
      if (!p) return;
      ctx.fillStyle = color;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 12, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#ffffff';
      ctx.font = '800 12px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, p.x, p.y);
    };
    const marker = (v: VertexDTO | null, label: string, color: string) => {
      if (!v) return;
      markerAt(v.x, v.y, label, color);
    };
    if (nearbyResult) markerAt(nearbyResult.center.x, nearbyResult.center.y, 'Q', '#f59e0b');
    if (trafficQueryResult) markerAt(trafficQueryResult.center.x, trafficQueryResult.center.y, 'T', '#14b8a6');
    marker(start, 'S', '#2563eb');
    marker(end, 'E', '#dc2626');

    if (incident) {
      const p = mapPoint(incident.x, incident.y);
      if (p) {
        ctx.strokeStyle = '#ef4444';
        ctx.fillStyle = '#ef444422';
        ctx.lineWidth = 2;
        ctx.setLineDash([8, 6]);
        ctx.beginPath();
        ctx.arc(p.x, p.y, Math.max(24, incident.radius / 5), 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#ef4444';
        ctx.font = '800 18px Inter, sans-serif';
        ctx.fillText('!', p.x - 4, p.y + 6);
      }
    }
  }, [activeTrace, drawPathLine, end, highlightedEdge, highlightVisible, hoveredEdge, incident, layers.trace, mapPoint, nearbyResult, start, staticPath, traceIndex, trafficPath, trafficQueryResult]);

  const drawOverview = useCallback(() => {
    const canvas = overviewCanvasRef.current;
    if (!canvas || !stats) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width));
    const height = Math.max(1, Math.floor(rect.height));
    const targetW = Math.max(1, Math.floor(width * ratio));
    const targetH = Math.max(1, Math.floor(height * ratio));
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(0, 0, width, height);
    const metrics = overviewMetrics(width, height, stats);

    ctx.save();
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.78;
    minimapData?.edges.forEach((edge) => {
      const a = metrics.toScreen(edge.x1, edge.y1);
      const b = metrics.toScreen(edge.x2, edge.y2);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    });
    ctx.restore();

    const drawOverviewPath = (path: PathDTO | null, color: string, dashed = false) => {
      if (!path || path.path.length < 2) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.2;
      ctx.globalAlpha = 0.92;
      if (dashed) ctx.setLineDash([5, 4]);
      ctx.beginPath();
      path.path.forEach((pt, idx) => {
        const p = metrics.toScreen(pt.x, pt.y);
        if (idx === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.stroke();
      ctx.restore();
    };
    drawOverviewPath(staticPath, '#2563eb');
    drawOverviewPath(trafficPath, '#7c3aed', true);

    if (incident) {
      const p = metrics.toScreen(incident.x, incident.y);
      ctx.save();
      ctx.fillStyle = '#ef444433';
      ctx.strokeStyle = '#ef4444';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(4, incident.radius * metrics.scale), 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }

    const map = mapRef.current;
    if (map) {
      const b = map.getBounds();
      const west = clamp(b.getWest(), 0, stats.width);
      const east = clamp(b.getEast(), 0, stats.width);
      const north = clamp(-b.getNorth(), 0, stats.height);
      const south = clamp(-b.getSouth(), 0, stats.height);
      const a = metrics.toScreen(west, north);
      const c = metrics.toScreen(east, south);
      ctx.save();
      ctx.strokeStyle = '#0f172a';
      ctx.fillStyle = '#2563eb16';
      ctx.lineWidth = 1.5;
      ctx.fillRect(a.x, a.y, c.x - a.x, c.y - a.y);
      ctx.strokeRect(a.x, a.y, c.x - a.x, c.y - a.y);
      ctx.restore();
    }
  }, [incident, minimapData, staticPath, stats, trafficPath]);

  const drawAll = useCallback(() => {
    resizeCanvases();
    drawHeat();
    drawRoads();
    drawVerticesAndCity();
    drawCars();
    drawTraceAndPaths();
    drawOverview();
  }, [drawCars, drawHeat, drawOverview, drawRoads, drawTraceAndPaths, drawVerticesAndCity, resizeCanvases]);

  const refreshViewport = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !stats) return;
    const b = map.getBounds();
    const detail = zoomDetail(map.getZoom());
    const largeMap = stats.vertices >= 18000;
    const representative = largeMap && detail < 0.72;
    const maxEdges = representative
      ? (detail < 0.30 ? 4200 : 8500)
      : (largeMap ? 16000 : 22000);
    const maxVertices = representative
      ? (detail < 0.30 ? 2400 : 4200)
      : (largeMap ? 9000 : 14000);
    const data = await api.viewport({
      x_min: b.getWest(),
      y_min: -b.getNorth(),
      x_max: b.getEast(),
      y_max: -b.getSouth(),
      traffic: true,
      representative,
      lod: largeMap ? 'auto' : 'detail',
      max_edges: maxEdges,
      max_vertices: maxVertices,
      grid_cols: detail < 0.30 ? 64 : 90,
      grid_rows: detail < 0.30 ? 48 : 68,
    });
    setViewport(data);
  }, [stats]);

  useEffect(() => {
    if (mapRef.current) return;
    const map = L.map('map', {
      crs: L.CRS.Simple,
      zoomControl: false,
      attributionControl: false,
      preferCanvas: true,
      minZoom: -5,
      maxZoom: 5,
    });
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    map.setView([0, 0], 0);
    map.on('mousemove', (e) => {
      const { x, y } = glx(e.latlng.lat, e.latlng.lng);
      const now = performance.now();
      if (now - lastMouseStatusRef.current > 120) {
        lastMouseStatusRef.current = now;
        setStatus((prev) => ({ ...prev, text: `${prev.text.split(' | ')[0]} | Coord (${fmt(x, 0)}, ${fmt(y, 0)})` }));
      }
      const point = map.latLngToContainerPoint(e.latlng);
      const nextHover = findHoveredEdge(point);
      setHoveredEdge((prev) => {
        if (!nextHover && !prev) return prev;
        if (prev && nextHover && prev.u === nextHover.u && prev.v === nextHover.v
          && Math.abs(prev.screenX - nextHover.screenX) < 4 && Math.abs(prev.screenY - nextHover.screenY) < 4) {
          return prev;
        }
        return nextHover;
      });
    });
    map.on('mouseout', () => setHoveredEdge(null));
    map.on('contextmenu', () => clearRoutes());
    map.on('click', async (e) => {
      const { x, y } = glx(e.latlng.lat, e.latlng.lng);
      try {
        if (incidentModeRef.current) {
          await injectManualIncidentRef.current?.(x, y);
          return;
        }
        const mode = selectionModeRef.current;
        if (mode === 'none') {
          setOk(`Coord (${fmt(x, 0)}, ${fmt(y, 0)}); click "Set Start" or "Set End" first`);
          return;
        }
        const v = await api.nearest(x, y);
        resetRouteResults();
        if (mode === 'start') {
          setStart(v);
          setOk(`Start set to ID:${v.id}`);
        } else {
          setEnd(v);
          setOk(`End set to ID:${v.id}`);
        }
        setSelectionMode('none');
      } catch (error) {
        setError((error as Error).message);
      }
    });
    map.on('moveend zoomend', () => {
      void refreshViewportRef.current?.();
      requestAnimationFrame(drawAllRef.current);
    });
    mapRef.current = map;
    resizeCanvases();
  }, [resizeCanvases]);

  const startRef = useRef<VertexDTO | null>(null);
  const endRef = useRef<VertexDTO | null>(null);
  const refreshViewportRef = useRef<(() => Promise<void>) | null>(null);
  const drawAllRef = useRef<() => void>(() => {});
  useEffect(() => { startRef.current = start; }, [start]);
  useEffect(() => { endRef.current = end; }, [end]);
  useEffect(() => { viewportRef.current = viewport; }, [viewport]);
  useEffect(() => { incidentModeRef.current = incidentMode; }, [incidentMode]);
  useEffect(() => { selectionModeRef.current = selectionMode; }, [selectionMode]);
  useEffect(() => { incidentRadiusRef.current = incidentRadius; }, [incidentRadius]);
  useEffect(() => { incidentIntensityRef.current = incidentIntensity; }, [incidentIntensity]);
  useEffect(() => { injectManualIncidentRef.current = injectManualIncident; });
  useEffect(() => { refreshViewportRef.current = refreshViewport; }, [refreshViewport]);
  useEffect(() => { drawAllRef.current = drawAll; }, [drawAll]);

  useEffect(() => { drawAll(); }, [drawAll, viewport, cars, staticPath, trafficPath, activeTrace, traceIndex, layers, start, end, incident, hoveredEdge, nearbyResult, trafficQueryResult]);
  useEffect(() => { drawOverview(); }, [drawOverview]);
  useEffect(() => { if (stats) void refreshViewport(); }, [layers.traffic, stats, refreshViewport]);
  useEffect(() => {
    if (!demoRunning) setDemoSteps(makeDemoSteps(selectedMapSize));
  }, [selectedMapSize]);
  useEffect(() => () => {
    if (highlightTimerRef.current !== null) window.clearInterval(highlightTimerRef.current);
  }, []);

  useEffect(() => {
    if (!tracePlaying || !activeTrace) return;
    const maxLen = Math.max(activeTrace.visited.length, activeTrace.relaxed_edges.length);
    const step = traceStepOverride ?? traceSpeed;
    const id = window.setInterval(() => {
      setTraceIndex((idx) => {
        const next = idx + step;
        if (next >= maxLen) {
          window.clearInterval(id);
          setTracePlaying(false);
          return maxLen;
        }
        return next;
      });
    }, 70);
    return () => window.clearInterval(id);
  }, [activeTrace, tracePlaying, traceSpeed, traceStepOverride]);

  useEffect(() => {
    if (!simRunning) return;
    const intervalMs = (stats?.vertices || 0) >= 18000 ? 1600 : 850;
    const id = window.setInterval(async () => {
      try {
        const state = await api.simState();
        setSimState(state);
        setCars(state.cars || []);
        setAnalytics(await api.analytics());
        await refreshViewport();
      } catch {
        // keep the UI resilient during server restarts
      }
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [refreshViewport, simRunning, stats?.vertices]);

  const generateMap = async () => {
    const n = selectedMapSize;
    setBusy(`Generating a ${n}-vertex map...`);
    setMinimapData(null);
    setHighlightedEdge(null);
    setHoveredEdge(null);
    setAlgorithmCompare(null);
    setRouteExplain(null);
    setRouteExplainPending(false);
    setRouteExplainError(null);
    lastRouteExplainRequestRef.current = null;
    setNearbyResult(null);
    setTrafficQueryResult(null);
    setPois([]);
    await api.generateMap(n, 2026);
    for (;;) {
      const res = await api.generationStatus();
      if (res.status === 'done' && typeof res.data === 'object' && res.data) {
        setStats(res.data);
        fitMap(res.data);
        setOk(res.data.cache_hit
          ? `${res.data.vertices}-vertex map loaded from cache. Ready to demo.`
          : `${res.data.vertices}-vertex map generated and cached.`);
        await new Promise((r) => setTimeout(r, 100));
        await refreshViewportRef.current?.();
        await loadMinimap();
        setAnalytics(await api.analytics());
        break;
      }
      if (res.status === 'error') {
        setError(String(res.data || 'Generation failed'));
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
  };

  const startSimulation = async () => {
    if (!stats) return setError('Generate a map first');
    await api.simStart(1800);
    await api.simSpeed(5);
    setSimRunning(true);
    setOk('Rush-hour traffic simulation is running');
  };

  const stopSimulation = async () => {
    await api.simStop();
    setSimRunning(false);
    setCars([]);
    setOk('Simulation stopped');
  };

  function resetRouteResults() {
    setStaticPath(null);
    setTrafficPath(null);
    setAlgorithmCompare(null);
    setRouteExplain(null);
    setRouteExplainPending(false);
    setRouteExplainError(null);
    lastRouteExplainRequestRef.current = null;
    setActiveTrace(null);
    setTraceIndex(0);
    setTracePlaying(false);
    setTraceStepOverride(null);
  }

  function applyRouteExplain(data: RouteExplainDTO, play: 'static' | 'traffic' | 'none' = 'traffic') {
    const staticRoute = {
      ...data.static_path,
      edge_levels: data.static_edge_levels,
      congestion_count: data.static_congested_edges,
    };
    const traffic = {
      ...data.traffic_path,
      edge_levels: data.traffic_edge_levels,
      congestion_count: data.traffic_congested_edges,
    };
    setRouteExplainPending(false);
    setRouteExplainError(null);
    setRouteExplain(data);
    setStaticPath(staticRoute);
    setTrafficPath(traffic);
    if (play !== 'none') {
      startTracePlayback(play === 'static' ? staticRoute : traffic, play === 'traffic' ? 3500 : undefined);
    }
  }

  async function refreshRouteExplainFor(
    s: VertexDTO | null = startRef.current,
    e: VertexDTO | null = endRef.current,
    play: 'static' | 'traffic' | 'none' = 'traffic',
  ) {
    if (!s || !e) return null;
    setRouteExplainPending(true);
    setRouteExplainError(null);
    try {
      const data = await api.routeExplain(s.id, e.id, algorithm, true);
      applyRouteExplain(data, play);
      return data;
    } finally {
      setRouteExplainPending(false);
    }
  }

  async function runAlgorithmCompare() {
    if (!start || !end) return setError('Select a start and end first');
    setBusy('Comparing A* and Dijkstra...');
    try {
      const data = await api.compareAlgorithms(start.id, end.id, true);
      setAlgorithmCompare(data);
      startTracePlayback(data.astar);
      setOk(`A* visited ${fmt(data.visit_reduction_percent, 1)}% fewer vertices; time delta ${fmt(data.time_delta_ms, 2)}ms`);
    } catch (error) {
      setError((error as Error).message);
    }
  }

  function playCompareTrace(kind: 'astar' | 'dijkstra') {
    const trace = algorithmCompare?.[kind];
    if (!trace) return;
    startTracePlayback(trace);
    setOk(`Playing the ${kind === 'astar' ? 'A*' : 'Dijkstra'} search trace`);
  }

  async function injectManualIncident(x: number, y: number) {
    if (!stats) return setError('Generate a map first');
    setBusy(`Injecting incident at (${fmt(x, 0)}, ${fmt(y, 0)})...`);
    try {
      const result = await api.injectTraffic(
        x, y,
        incidentRadiusRef.current,
        incidentIntensityRef.current,
      );
      setIncident({
        x: result.x,
        y: result.y,
        radius: result.radius,
        intensity: incidentIntensityRef.current,
        affected_edges: result.affected,
      });
      setSimRunning(true);
      setAnalytics(await api.analytics());
      await refreshViewportRef.current?.();
      await refreshRouteExplainFor(startRef.current, endRef.current, 'traffic');
      setOk(`Incident injected, affecting ${result.affected} roads`);
    } catch (error) {
      setError((error as Error).message);
    }
  }

  const runPath = async () => {
    if (!start || !end) return setError('Click "Set Start" and "Set End", then choose points on the map');
    setBusy('Computing the static shortest path and route explanation...');
    try {
      const data = await refreshRouteExplainFor(start, end, 'static');
      if (data) setOk(`${data.static_path.algorithm} route complete: static route crosses ${data.static_congested_edges} congested/severe segments`);
    } catch (error) {
      setError((error as Error).message);
    }
  };

  const runTrafficPath = async () => {
    if (!start || !end) return setError('Select a start and end first');
    setBusy('Computing the traffic-aware route and explanation...');
    try {
      const data = await refreshRouteExplainFor(start, end, 'traffic');
      if (data) setOk(`Traffic-aware route avoids ${data.avoided_congested_edges} congested segments; time delta ${fmt(data.metrics.time_delta)}`);
    } catch (error) {
      setError((error as Error).message);
    }
  };

  function clearRoutes() {
    setStart(null);
    setEnd(null);
    resetRouteResults();
    setIncident(null);
    setPoiScenario(null);
    setSelectionMode('none');
  }

  const runDemo = async () => {
    const n = selectedMapSize;
    setDemoRunning(true);
    setDemoTimeline(0, -1, n);
    setBusy(`Preparing the ${n}-vertex demo map...`);
    setMinimapData(null);
    setTrafficPath(null);
    setStaticPath(null);
    setIncident(null);
    setHighlightedEdge(null);
    setRouteExplainPending(false);
    setRouteExplainError(null);
    setNearbyResult(null);
    setTrafficQueryResult(null);
    try {
      const demo = await api.demo(n);
      if (demo.error) {
        setError(demo.error);
        return;
      }

      setDemoTimeline(1, 0, n);
      setBusy('Starting rush-hour traffic...');
      setStats(demo.stats);
      fitMap(demo.stats);
      setSimRunning(true);
      setAnalytics(await api.analytics());
      await loadMinimap();
      await refreshViewportRef.current?.();
      await sleep(550);

      setDemoTimeline(2, 1, n);
      setBusy('Choosing cross-city endpoints...');
      setStart(demo.start);
      setEnd(demo.end);
      fitRoute([demo.start, demo.end]);
      await sleep(650);

      setDemoTimeline(3, 2, n);
      setBusy('Injecting incident congestion and refreshing traffic...');
      setIncident(demo.incident);
      await refreshViewportRef.current?.();
      await sleep(650);

      setDemoTimeline(4, 3, n);
      setBusy('Playing the static-route search trace...');
      setStaticPath(demo.static_path);
      setTrafficPath(null);
      startTracePlayback(demo.static_path);
      fitRoute(demo.static_path.path);
      await sleep(1300);

      setBusy('Switching to the traffic-aware detour...');
      setTrafficPath(demo.traffic_path);
      startTracePlayback(demo.traffic_path, 3500);
      if (demo.route_explain) {
        applyRouteExplain(demo.route_explain, 'none');
      } else {
        try {
          const explanation = await api.routeExplain(demo.start.id, demo.end.id, 'astar', true);
          applyRouteExplain(explanation, 'none');
        } catch {
          setRouteExplainPending(false);
          setRouteExplain(null);
          setRouteExplainError('Route explanation failed. Click a route button to retry.');
        }
      }
      await sleep(700);

      setDemoTimeline(null, 4, n);
      setOk(`Demo ready: incident affects ${demo.incident.affected_edges} roads`);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setDemoRunning(false);
    }
  };

  const searchPois = async (category = poiCategory, limit = 12) => {
    if (!stats) return setError('Generate a map first');
    const center = start || currentMapCenter(stats);
    const data = await api.poiSearch(center.x, center.y, category, limit, 700);
    setPois(data.pois);
    setOk(`Found ${data.pois.length} ${poiNames[category] || 'POIs'}`);
    if (data.pois[0]) {
      mapRef.current?.panTo(ll(data.pois[0].x, data.pois[0].y));
    }
  };

  const routeToPoi = async (poi: POI) => {
    if (!stats) return;
    setBusy(`Planning a route to ${poi.name}...`);
    let s = start;
    if (!s) {
      const center = currentMapCenter(stats);
      s = await api.nearest(center.x, center.y);
      setStart(s);
    }
    const e = await api.nearest(poi.x, poi.y);
    setEnd(e);
    const path = await api.path(s.id, e.id, algorithm, true);
    setStaticPath(path);
    startTracePlayback(path);
    fitRoute(path.path);
    try {
      await refreshRouteExplainFor(s, e, 'static');
    } catch {
      setRouteExplain(null);
    }
    setOk(`Route to ${poi.name} planned: distance ${fmt(path.distance)}, ${path.hops} hops`);
  };

  const runPoiScenario = async (scenario: { label: string; category: string }) => {
    if (!stats) return setError('Generate a map first');
    setPoiScenario(scenario.label);
    setPoiCategory(scenario.category);
    const center = start || currentMapCenter(stats);
    setBusy(`Running scenario: ${scenario.label}`);
    try {
      const data = await api.poiSearch(center.x, center.y, scenario.category, 6, 1800);
      setPois(data.pois);
      if (!data.pois[0]) {
        setError(`No nearby ${poiNames[scenario.category] || 'target'} found`);
        return;
      }
      await routeToPoi(data.pois[0]);
      setOk(`${scenario.label}: selected nearest ${data.pois[0].name}`);
    } catch (error) {
      setError((error as Error).message);
    }
  };

  async function queryNearbyVertices() {
    if (!stats) return setError('Generate a map first');
    const x = Number(nearbyX);
    const y = Number(nearbyY);
    const k = Math.round(clamp(Number(nearbyK) || 100, 1, 500));
    setBusy(`Querying ${k} nearest vertices around (${fmt(x, 0)}, ${fmt(y, 0)})...`);
    try {
      const data = await api.nearby(x, y, k);
      setNearbyK(k);
      setNearbyResult(data);
      mapRef.current?.panTo(ll(data.center.x, data.center.y));
      setOk(`F1 query complete: ${data.vertices.length} nearest vertices, ${data.edges.length} associated roads`);
    } catch (error) {
      setError((error as Error).message);
    }
  }

  async function queryTrafficByTime() {
    if (!stats) return setError('Generate a map first');
    const x = Number(trafficQueryX);
    const y = Number(trafficQueryY);
    const t = Math.max(0, Math.round(Number(trafficQueryTime) || 0));
    const r = Math.max(10, Number(trafficQueryRadius) || 300);
    setBusy(`Querying nearby traffic at t=${t}...`);
    try {
      const data = await api.trafficHistory(x, y, t, r);
      setTrafficQueryTime(t);
      setTrafficQueryRadius(r);
      setTrafficQueryResult(data);
      mapRef.current?.panTo(ll(data.center.x, data.center.y));
      setOk(data.edges.length
        ? `Traffic query complete: ${data.edges.length} nearby roads`
        : 'No nearby traffic record for this time. Start the simulation first.');
    } catch (error) {
      setError((error as Error).message);
    }
  }

  function downloadTextFile(filename: string, content: string, type: string) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function buildMarkdownReport(snapshot: ExportSnapshotDTO) {
    const compare = snapshot.algorithm_compare;
    const explain = snapshot.route_explain;
    const lines = [
      '# Navigation Demo Report',
      '',
      `- Exported at: ${snapshot.exported_at}`,
      `- Map scale: ${snapshot.stats ? `${snapshot.stats.vertices} vertices / ${snapshot.stats.edges} roads / ${snapshot.stats.poi_count} POIs` : 'Not generated'}`,
      `- Start: ${snapshot.start ? `ID ${snapshot.start.id} (${fmt(snapshot.start.x, 0)}, ${fmt(snapshot.start.y, 0)})` : 'Not selected'}`,
      `- End: ${snapshot.end ? `ID ${snapshot.end.id} (${fmt(snapshot.end.x, 0)}, ${fmt(snapshot.end.y, 0)})` : 'Not selected'}`,
      `- Incident: ${snapshot.incident ? `(${fmt(snapshot.incident.x, 0)}, ${fmt(snapshot.incident.y, 0)}), radius ${snapshot.incident.radius}, intensity ${snapshot.incident.intensity}, affected ${snapshot.incident.affected_edges} roads` : 'None'}`,
      '',
      '## Algorithm Race',
      compare
        ? `- A*: ${fmt(compare.astar.elapsed_ms, 2)}ms, visited ${compare.astar.nodes_visited} vertices, ${compare.astar.hops} hops, distance ${fmt(compare.astar.distance)}`
        : '- Not run',
      compare
        ? `- Dijkstra: ${fmt(compare.dijkstra.elapsed_ms, 2)}ms, visited ${compare.dijkstra.nodes_visited} vertices, ${compare.dijkstra.hops} hops, distance ${fmt(compare.dijkstra.distance)}`
        : '',
      compare ? `- A* visit reduction: ${fmt(compare.visit_reduction_percent, 1)}%, time delta: ${fmt(compare.time_delta_ms, 2)}ms` : '',
      '',
      '## Route Explanation',
      explain ? `- ${explain.summary}` : '- No route explanation generated',
      explain ? `- Static congested segments: ${explain.static_congested_edges}, traffic-route congested segments: ${explain.traffic_congested_edges}, avoided congested roads: ${explain.avoided_congested_edges}` : '',
      explain ? `- Static estimated travel time: ${fmt(explain.metrics.static_traffic_time)}, traffic-route estimated travel time: ${fmt(explain.metrics.traffic_traffic_time)}` : '',
      '',
      '## Traffic Status',
      snapshot.analytics ? `- Active cars: ${snapshot.analytics.active_cars}` : '- No traffic analytics',
      snapshot.analytics ? `- Average congestion: ${fmt(snapshot.analytics.average_ratio * 100, 1)}%, max congestion: ${fmt(snapshot.analytics.max_ratio * 100, 1)}%` : '',
      '',
      '## POI',
      snapshot.pois.length
        ? snapshot.pois.slice(0, 8).map((poi, idx) => `- #${idx + 1} ${poi.name} (${poi.poi_type}), distance ${fmt(poi.distance, 0)}, ID ${poi.id}`).join('\n')
        : '- No POI search',
      '',
    ];
    return lines.join('\n');
  }

  function exportDemoResult() {
    const snapshot: ExportSnapshotDTO = {
      exported_at: new Date().toISOString(),
      stats,
      start,
      end,
      incident,
      algorithm_compare: algorithmCompare,
      route_explain: routeExplain,
      analytics,
      pois,
    };
    downloadTextFile(
      'navigation_demo_snapshot.json',
      JSON.stringify(snapshot, null, 2),
      'application/json;charset=utf-8',
    );
    downloadTextFile(
      'navigation_demo_report.md',
      buildMarkdownReport(snapshot),
      'text/markdown;charset=utf-8',
    );
    setOk('Exported Markdown report and JSON snapshot');
  }

  function currentMapCenter(fallback: Stats) {
    const c = mapRef.current?.getCenter();
    return c ? glx(c.lat, c.lng) : { x: fallback.width / 2, y: fallback.height / 2 };
  }

  useEffect(() => {
    if (!start || !end || routeExplain || routeExplainPending) return;
    if (!staticPath && !trafficPath) return;
    const key = `${start.id}-${end.id}-${algorithm}-${staticPath?.distance ?? 'none'}-${trafficPath?.distance ?? 'none'}`;
    if (lastRouteExplainRequestRef.current === key) return;
    lastRouteExplainRequestRef.current = key;
    void refreshRouteExplainFor(start, end, 'none').catch(() => {
      setRouteExplainPending(false);
        setRouteExplainError('Route explanation failed. Click "Static Route" or "Traffic-Aware Route" to retry.');
    });
  }, [algorithm, end, routeExplain, routeExplainPending, start, staticPath, trafficPath]);

  const handleOverviewClick = (event: ReactMouseEvent<HTMLCanvasElement>) => {
    if (!stats) return;
    const canvas = overviewCanvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const metrics = overviewMetrics(rect.width, rect.height, stats);
    const world = metrics.toWorld(event.clientX - rect.left, event.clientY - rect.top);
    const x = clamp(world.x, 0, stats.width);
    const y = clamp(world.y, 0, stats.height);
    mapRef.current?.panTo(ll(x, y));
  };

  const congestedCount = useMemo(() => {
    if (!analytics) return 0;
    return Number(analytics.level_counts['2'] || 0) + Number(analytics.level_counts['3'] || 0);
  }, [analytics]);

  const trafficQueryLevelCounts = useMemo(() => {
    const counts: Record<string, number> = { '0': 0, '1': 0, '2': 0, '3': 0 };
    trafficQueryResult?.edges.forEach((edge) => {
      counts[String(edge.level)] = (counts[String(edge.level)] || 0) + 1;
    });
    return counts;
  }, [trafficQueryResult]);

  const routeCongestionCounts = useMemo(() => {
    const staticCongested = routeExplain?.static_congested_edges
      ?? staticPath?.congestion_count
      ?? staticPath?.edge_levels?.filter((level) => level >= 2).length
      ?? 0;
    const trafficCongested = routeExplain?.traffic_congested_edges
      ?? trafficPath?.congestion_count
      ?? trafficPath?.edge_levels?.filter((level) => level >= 2).length
      ?? 0;
    const avoided = routeExplain?.avoided_congested_edges
      ?? Math.max(0, staticCongested - trafficCongested);
    return { staticCongested, trafficCongested, avoided };
  }, [routeExplain, staticPath, trafficPath]);

  const trafficPathBadge = staticPath && trafficPath
    ? routeExplain ? `Avoided ${routeCongestionCounts.avoided}` : routeExplainPending ? 'Analyzing' : 'Pending'
    : `Congested ${trafficPath?.congestion_count ?? 0}`;

  const routeDecisionText = useMemo(() => {
    if (routeExplainPending) {
      return {
        text: 'Generating route decision explanation...',
        meta: 'Comparing static and traffic-aware routes with congestion benefits',
      };
    }
    if (routeExplainError) {
      return {
        text: routeExplainError,
        meta: 'Current routes remain visible; click a route button to retry the explanation',
      };
    }
    if (routeExplain) {
      const timeDelta = Number(routeExplain.metrics.time_delta || 0);
      const timeWord = timeDelta >= 0 ? 'saves' : 'adds';
      return {
        text: `The static route crosses ${routeExplain.static_congested_edges} congested/severe segments. The traffic-aware route avoids ${routeExplain.avoided_congested_edges} of them and ${timeWord} ${fmt(Math.abs(timeDelta))} travel time.`,
        meta: `Avoided ${routeExplain.avoided_congested_edges} segments · Time delta ${fmt(timeDelta)}`,
      };
    }
    if (staticPath && trafficPath) {
      return {
        text: 'Generating route decision explanation...',
        meta: 'Reading live congestion state and estimating detour benefits',
      };
    }
    return null;
  }, [routeCongestionCounts, routeExplain, routeExplainError, routeExplainPending, staticPath, trafficPath]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <header className="brand">
          <div className="brand-mark">NAV</div>
          <div>
            <h1>Navigation System Pro</h1>
            <p>Data Structures · Web Showcase</p>
          </div>
        </header>

        <section className="panel primary-panel">
          <div className="panel-title">Guided Demo</div>
          <button className="command primary" onClick={runDemo} disabled={demoRunning}>
            {demoRunning && demoStepIndex !== null ? `Demo ${demoStepIndex + 1}/5` : 'Run Guided Demo'}
          </button>
          <div className="timeline">
            {demoSteps.map((step) => <div key={step.label} className={`timeline-row ${step.state}`}><span />{step.label}</div>)}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">Map & Routing</div>
          <label className="field">Vertices
            <input
              type="number"
              min={MAP_SIZE_MIN}
              max={MAP_SIZE_MAX}
              step={100}
              value={mapSize}
              onChange={(e) => setMapSize(Number(e.target.value))}
              onBlur={() => setMapSize(selectedMapSize)}
              disabled={demoRunning}
            />
          </label>
          <div className="size-presets">
            {MAP_SIZE_PRESETS.map((preset) => (
              <button
                key={preset}
                className={`chip ${selectedMapSize === preset ? 'active' : ''}`}
                onClick={() => setMapSize(preset)}
                disabled={demoRunning}
              >
                {preset}
              </button>
            ))}
          </div>
          <div className="grid2">
            <button className="command" onClick={generateMap} disabled={demoRunning}>Generate {selectedMapSize}</button>
            <button className="command" onClick={simRunning ? stopSimulation : startSimulation}>{simRunning ? 'Stop Sim' : 'Start Traffic'}</button>
          </div>
          <div className="grid2">
            <button className={`command ${selectionMode === 'start' ? 'active' : ''}`} onClick={() => setSelectionMode(selectionMode === 'start' ? 'none' : 'start')}>
              {selectionMode === 'start' ? 'Pick Start' : 'Set Start'}
            </button>
            <button className={`command ${selectionMode === 'end' ? 'active' : ''}`} onClick={() => setSelectionMode(selectionMode === 'end' ? 'none' : 'end')}>
              {selectionMode === 'end' ? 'Pick End' : 'Set End'}
            </button>
          </div>
          <label className="field">Algorithm
            <select value={algorithm} onChange={(e) => setAlgorithm(e.target.value as 'astar' | 'dijkstra')}>
              <option value="astar">A* Search</option>
              <option value="dijkstra">Dijkstra</option>
            </select>
          </label>
          <div className="grid2">
            <button className="command" onClick={runPath}>Static Route</button>
            <button className="command purple" onClick={runTrafficPath}>Traffic-Aware</button>
          </div>
          <button className="command ghost" onClick={clearRoutes}>Clear Route</button>
        </section>

        <section className="panel route-summary">
          <div className="panel-title">Route Info</div>
          <div className="route-line">
            <b>S</b>
            <span>{start ? `ID ${start.id} (${fmt(start.x, 0)}, ${fmt(start.y, 0)})` : 'Click "Set Start", then pick on the map'}</span>
          </div>
          <div className="route-line">
            <b>E</b>
            <span>{end ? `ID ${end.id} (${fmt(end.x, 0)}, ${fmt(end.y, 0)})` : 'Click "Set End", then pick on the map'}</span>
          </div>
          {staticPath && <div className="path-row blue">Static Route {fmt(staticPath.distance)} · {staticPath.hops} hops · {fmt(staticPath.elapsed_ms, 2)}ms</div>}
          {trafficPath && <div className="path-row purple">Traffic-Aware {fmt(trafficPath.distance)} · {trafficPathBadge}</div>}
          {routeDecisionText ? (
            <div className="explain-row">
              {routeDecisionText.text}
              <span>{routeDecisionText.meta}</span>
            </div>
          ) : (
            <div className="empty-note">Route explanation appears here after routing</div>
          )}
        </section>

        <section className="panel">
          <div className="panel-title">Coordinate Query</div>
          <div className="grid2">
            <label className="mini-field">X Coord
              <input type="number" value={nearbyX} onChange={(e) => setNearbyX(Number(e.target.value))} />
            </label>
            <label className="mini-field">Y Coord
              <input type="number" value={nearbyY} onChange={(e) => setNearbyY(Number(e.target.value))} />
            </label>
          </div>
          <label className="field">Nearest
            <input type="number" min={1} max={500} value={nearbyK} onChange={(e) => setNearbyK(Number(e.target.value))} />
          </label>
          <div className="grid2">
            <button className="command" onClick={queryNearbyVertices}>Query {Math.round(clamp(Number(nearbyK) || 100, 1, 500))}</button>
            <button className="command" onClick={() => setNearbyResult(null)}>Clear Query</button>
          </div>
          {nearbyResult && (
            <>
              <Metric label="Nearest Vertices" value={nearbyResult.vertices.length} />
              <Metric label="Associated Roads" value={nearbyResult.edges.length} />
              <Metric label="Center" value={`${fmt(nearbyResult.center.x, 0)}, ${fmt(nearbyResult.center.y, 0)}`} />
            </>
          )}
        </section>

        <section className="panel">
          <div className="panel-title">Traffic by Time</div>
          <div className="grid2">
            <label className="mini-field">X Coord
              <input type="number" value={trafficQueryX} onChange={(e) => setTrafficQueryX(Number(e.target.value))} />
            </label>
            <label className="mini-field">Y Coord
              <input type="number" value={trafficQueryY} onChange={(e) => setTrafficQueryY(Number(e.target.value))} />
            </label>
          </div>
          <div className="grid2">
            <label className="mini-field">Time Step
              <input type="number" min={0} value={trafficQueryTime} onChange={(e) => setTrafficQueryTime(Number(e.target.value))} />
            </label>
            <label className="mini-field">Radius
              <input type="number" min={10} step={10} value={trafficQueryRadius} onChange={(e) => setTrafficQueryRadius(Number(e.target.value))} />
            </label>
          </div>
          <div className="grid2">
            <button className="command" onClick={() => setTrafficQueryTime(simState?.time_step ?? trafficQueryTime)}>Use Current</button>
            <button className="command" onClick={queryTrafficByTime}>Query Traffic</button>
          </div>
          <button className="command" onClick={() => setTrafficQueryResult(null)}>Clear Traffic Query</button>
          {trafficQueryResult && (
            <>
              <Metric label="Nearby Roads" value={trafficQueryResult.edges.length} />
              <Metric label="Query Time" value={trafficQueryResult.time} />
              <div className="query-levels">
                {[0, 1, 2, 3].map((level) => (
                  <span key={level}><i style={{ background: trafficColors[level] }} />{['Free', 'Slow', 'Cong.', 'Sev.'][level]} {trafficQueryLevelCounts[String(level)] || 0}</span>
                ))}
              </div>
            </>
          )}
        </section>

        <section className="panel">
          <div className="panel-title">Search Animation</div>
          <div className="trace-controls">
            <button className="chip" onClick={() => setTracePlaying((p) => !p)}>{tracePlaying ? 'Pause' : 'Play'}</button>
            {[1, 4, 10].map((s) => <button key={s} className={`chip ${traceSpeed === s && traceStepOverride === null ? 'active' : ''}`} onClick={() => { setTraceStepOverride(null); setTraceSpeed(s); }}>{s}x</button>)}
            <button className="chip" onClick={() => { setTraceStepOverride(null); setTraceIndex(0); setTracePlaying(Boolean(activeTrace)); }}>Replay</button>
          </div>
          <Metric label="Visited Vertices" value={activeTrace?.nodes_visited ?? 0} />
          <Metric label="Relaxed Edges" value={activeTrace?.relaxed_edges.length ?? 0} />
          {activeTrace?.trace_truncated && <div className="warn">Trace is long and has been truncated</div>}
        </section>

        <section className="panel">
          <div className="panel-title">A* vs Dijkstra Race</div>
          <button className="command" onClick={runAlgorithmCompare}>Run Race</button>
          {algorithmCompare && (
            <>
              <div className="race-grid">
                <button className="race-card" onClick={() => playCompareTrace('astar')}>
                  <span>A*</span>
                  <b>{fmt(algorithmCompare.astar.elapsed_ms, 2)}ms</b>
                  <em>{algorithmCompare.astar.nodes_visited} vertices · {algorithmCompare.astar.hops} hops</em>
                </button>
                <button className="race-card" onClick={() => playCompareTrace('dijkstra')}>
                  <span>Dijkstra</span>
                  <b>{fmt(algorithmCompare.dijkstra.elapsed_ms, 2)}ms</b>
                  <em>{algorithmCompare.dijkstra.nodes_visited} vertices · {algorithmCompare.dijkstra.hops} hops</em>
                </button>
              </div>
              <Metric label="Visit Reduction" value={`${fmt(algorithmCompare.visit_reduction_percent, 1)}%`} />
              <Metric label="Time Delta" value={`${fmt(algorithmCompare.time_delta_ms, 2)}ms`} />
            </>
          )}
        </section>

        <section className="panel">
          <div className="panel-title">Incident Lab</div>
          <button className={`command ${incidentMode ? 'purple' : ''}`} onClick={() => setIncidentMode((enabled) => !enabled)}>
            {incidentMode ? 'Click Map to Inject' : 'Enable Incident Mode'}
          </button>
          <div className="grid2">
            <label className="mini-field">Radius
              <input type="number" min={30} max={500} step={10} value={incidentRadius} onChange={(e) => setIncidentRadius(Number(e.target.value))} />
            </label>
            <label className="mini-field">Intensity
              <input type="number" min={10} max={300} step={10} value={incidentIntensity} onChange={(e) => setIncidentIntensity(Number(e.target.value))} />
            </label>
          </div>
          {incident && <Metric label="Affected Roads" value={incident.affected_edges} />}
        </section>

        <section className="panel">
          <div className="panel-title">POI Presets</div>
          <div className="scenario-grid">
            {poiScenarios.map((scenario) => (
              <button
                key={scenario.category}
                className={`chip ${poiScenario === scenario.label ? 'active' : ''}`}
                onClick={() => runPoiScenario(scenario)}
              >
                {scenario.label}
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">Layers</div>
          <Toggle label="Road Traffic" checked={layers.traffic} onChange={(traffic) => setLayers({ ...layers, traffic })} />
          <Toggle label="Congestion Heatmap" checked={layers.heat} onChange={(heat) => setLayers({ ...layers, heat })} />
          <Toggle label="Vehicle Animation" checked={layers.cars} onChange={(carsLayer) => setLayers({ ...layers, cars: carsLayer })} />
          <Toggle label="POIs & Districts" checked={layers.poi} onChange={(poi) => setLayers({ ...layers, poi })} />
          <Toggle label="Search Trace" checked={layers.trace} onChange={(trace) => setLayers({ ...layers, trace })} />
        </section>

        <section className="panel">
          <div className="panel-title">Congested Roads</div>
          <button className="command" onClick={() => setShowCongestedPanel((show) => !show)}>
            {showCongestedPanel ? 'Hide Top Roads' : 'Show Top Roads'}
          </button>
          {showCongestedPanel && (
            <div className="edge-table">
              {(analytics?.top_congested_edges || []).map((edge, i) => (
                <button
                  key={`${edge.u}-${edge.v}`}
                  className={highlightedEdge?.u === edge.u && highlightedEdge?.v === edge.v ? 'active' : ''}
                  onClick={() => flashCongestedEdge(edge)}
                >
                  <span>#{i + 1}</span>
                  <b>{edge.u} - {edge.v}</b>
                  <em>{fmt(edge.ratio * 100, 1)}%</em>
                </button>
              ))}
              {!(analytics?.top_congested_edges || []).length && <div className="empty-note">Start traffic simulation to show congested roads</div>}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-title">POI Search & Route</div>
          <label className="field">Service
            <select value={poiCategory} onChange={(e) => setPoiCategory(e.target.value)}>
              {Object.entries(poiNames).filter(([id]) => id !== 'all').map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <div className="grid2">
            <button className="command" onClick={() => searchPois()}>Search Nearby</button>
            <button className="command" onClick={async () => { await searchPois(poiCategory, 1); }}>Nearest Service</button>
          </div>
          <div className="poi-list">
            {pois.map((poi) => (
              <button key={`${poi.poi_type}-${poi.id}`} onClick={() => routeToPoi(poi)}>
                <b>{poiLabels[poi.poi_type] || '•'} {poi.name}</b>
                <span>{fmt(poi.distance, 0)} m · ID {poi.id}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">Export Results</div>
          <button className="command primary" onClick={exportDemoResult}>Export Markdown + JSON</button>
          <div className="export-hint">Includes map scale, route explanation, algorithm race, incident, and traffic metrics</div>
        </section>
      </aside>

      <main className="stage">
        <section className="dashboard">
          <StatCard label="Vertices / Roads" value={stats ? `${stats.vertices} / ${stats.edges}` : '—'} />
          <StatCard label="Active Cars" value={simState?.active_cars ?? analytics?.active_cars ?? 0} />
          <StatCard label="Avg. Congestion" value={`${fmt((analytics?.average_ratio ?? 0) * 100, 1)}%`} />
          <StatCard label="Congested Roads" value={congestedCount} accent="red" />
          <MiniLine data={analytics?.history || []} />
          <LevelBars counts={analytics?.level_counts || {}} />
        </section>

        <div id="map-frame">
          <div id="map" />
          <canvas ref={heatCanvasRef} className="map-canvas heat" />
          <canvas ref={edgeCanvasRef} className="map-canvas roads" />
          <canvas ref={vertexCanvasRef} className="map-canvas vertices" />
          <canvas ref={carCanvasRef} className="map-canvas cars" />
          <canvas ref={traceCanvasRef} className="map-canvas trace" />

          <div className={`status ${status.kind}`}>
            <span />
            {status.text}
          </div>

          {hoveredEdge && (
            <div className="hover-card" style={{ left: hoveredEdge.screenX, top: hoveredEdge.screenY }}>
              <b>{hoveredEdge.u} - {hoveredEdge.v}</b>
              <span>Length {fmt(hoveredEdge.length)} · Capacity {hoveredEdge.capacity}</span>
              <span>Cars {fmt(hoveredEdge.current_cars, 1)} · Congestion {fmt(hoveredEdge.ratio * 100, 1)}%</span>
              <span>Level {['Free', 'Slow', 'Congested', 'Severe'][hoveredEdge.level]} · Time {fmt(hoveredEdge.travel_time)}</span>
            </div>
          )}

          <div className="overview-panel">
            <div className="overview-header">
              <span>Overview</span>
              <b>{minimapData ? `${minimapData.vertices.length} pts` : 'Pending'}</b>
            </div>
            <canvas ref={overviewCanvasRef} onClick={handleOverviewClick} />
          </div>

          <div className="legend">
            {trafficColors.map((c, i) => <span key={c}><i style={{ background: c }} />{['Free', 'Slow', 'Congested', 'Severe'][i]}</span>)}
          </div>
        </div>
      </main>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="metric"><span>{label}</span><b>{value}</b></div>;
}

function StatCard({ label, value, accent }: { label: string; value: number | string; accent?: string }) {
  return <div className={`stat-card ${accent || ''}`}><span>{label}</span><b>{value}</b></div>;
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <label className="toggle"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /><span>{label}</span></label>;
}

function MiniLine({ data }: { data: AnalyticsDTO['history'] }) {
  const points = data.slice(-40);
  const w = 210;
  const h = 54;
  const latest = points[points.length - 1];
  const values = points.map((p) => p.average_ratio);
  const rawMin = values.length ? Math.min(...values) : 0;
  const rawMax = values.length ? Math.max(...values) : 0.1;
  const pad = Math.max(0.006, (rawMax - rawMin) * 0.18);
  const minY = Math.max(0, rawMin - pad);
  const maxY = Math.max(minY + 0.012, rawMax + pad);
  const d = points.map((p, i) => {
    const x = points.length <= 1 ? 0 : (i / (points.length - 1)) * w;
    const y = h - ((p.average_ratio - minY) / (maxY - minY)) * h;
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <div className="chart-card">
      <div className="chart-title"><span>Congestion Trend</span><b>{latest ? `${fmt(latest.average_ratio * 100, 1)}%` : '—'}</b></div>
      <svg className="mini-line" viewBox={`0 0 ${w} ${h}`}><path d={d || `M0,${h} L${w},${h}`} /></svg>
    </div>
  );
}

function LevelBars({ counts }: { counts: Record<string, number> }) {
  const total = Math.max(1, Object.values(counts).reduce((a, b) => a + Number(b), 0));
  return (
    <div className="level-card">
      <div className="chart-title"><span>Road Mix</span><b>{total}</b></div>
      <div className="level-bars">
        {[0, 1, 2, 3].map((level) => (
          <div key={level}>
            <span>{['Free', 'Slow', 'Cong.', 'Sev.'][level]}</span>
            <i style={{ width: `${(Number(counts[String(level)] || 0) / total) * 100}%`, background: trafficColors[level] }} />
          </div>
        ))}
      </div>
    </div>
  );
}
