import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import L, { Map as LeafletMap } from 'leaflet';
import { api } from './api';
import type { AnalyticsDTO, CarDTO, DemoDTO, EdgeDTO, MinimapDTO, PathDTO, POI, SimulationState, Stats, VertexDTO, ViewportDTO } from './types';

const trafficColors = ['#22c55e', '#eab308', '#f97316', '#ef4444'];
const poiLabels: Record<string, string> = {
  gas_station: '⛽',
  restaurant: '餐',
  parking: 'P',
  repair: '修',
  hospital: '医',
};
const poiNames: Record<string, string> = {
  all: '全部',
  gas_station: '加油站',
  restaurant: '餐厅',
  parking: '停车场',
  repair: '维修',
  hospital: '医院',
};

const ll = (x: number, y: number): L.LatLngExpression => [-y, x];
const glx = (lat: number, lng: number) => ({ x: lng, y: -lat });
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));
const fmt = (n?: number, digits = 1) => Number.isFinite(n) ? Number(n).toFixed(digits) : '—';
const MAP_SIZE_MIN = 100;
const MAP_SIZE_MAX = 30000;
const MAP_SIZE_PRESETS = [1000, 5000, 10000, 20000];
const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));
const normalizeMapSize = (n: number) => Math.round(clamp(Number.isFinite(n) ? n : 10000, MAP_SIZE_MIN, MAP_SIZE_MAX));

type StepState = 'idle' | 'active' | 'done';

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
  { label: `生成 ${n} 点地图`, state: 'idle' },
  { label: '启动早高峰交通流', state: 'idle' },
  { label: '选择跨城路线', state: 'idle' },
  { label: '注入事故拥堵', state: 'idle' },
  { label: '对比静态/避堵路径', state: 'idle' },
];

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

export default function App() {
  const mapRef = useRef<LeafletMap | null>(null);
  const edgeCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const heatCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const vertexCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const carCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const traceCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const overviewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const statusTimerRef = useRef<number | null>(null);
  const highlightTimerRef = useRef<number | null>(null);

  const [status, setStatus] = useState({ text: '就绪 - 点击生成地图或启动演示', kind: 'idle' });
  const [mapSize, setMapSize] = useState(10000);
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
  const [activeTrace, setActiveTrace] = useState<PathDTO | null>(null);
  const [traceIndex, setTraceIndex] = useState(0);
  const [tracePlaying, setTracePlaying] = useState(false);
  const [traceSpeed, setTraceSpeed] = useState(4);
  const [algorithm, setAlgorithm] = useState<'astar' | 'dijkstra'>('astar');
  const [simRunning, setSimRunning] = useState(false);
  const [poiCategory, setPoiCategory] = useState('gas_station');
  const [pois, setPois] = useState<POI[]>([]);
  const [incident, setIncident] = useState<DemoDTO['incident'] | null>(null);
  const [highlightedEdge, setHighlightedEdge] = useState<EdgeDTO | null>(null);
  const [highlightVisible, setHighlightVisible] = useState(true);
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoStepIndex, setDemoStepIndex] = useState<number | null>(null);
  const [demoSteps, setDemoSteps] = useState<DemoStep[]>(() => makeDemoSteps(10000));

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
    setOk(`定位拥堵道路 ${edge.u} - ${edge.v}`);
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

  const drawRoads = useCallback(() => {
    const canvas = edgeCanvasRef.current;
    const map = mapRef.current;
    if (!canvas || !map) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.lineCap = 'round';
    viewport.edges.forEach((edge) => {
      const a = mapPoint(edge.x1, edge.y1);
      const b = mapPoint(edge.x2, edge.y2);
      if (!a || !b) return;
      const width = clamp(1 + Math.log1p(edge.capacity) / 2.4, 1.4, 5.6);
      ctx.strokeStyle = layers.traffic ? trafficColors[edge.level] : edge.capacity > 120 ? '#7f8ea3' : '#b8c4d3';
      ctx.globalAlpha = layers.traffic ? 0.82 : 0.62;
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
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    if (!layers.heat) return;
    viewport.edges.forEach((edge) => {
      if (edge.ratio < 0.35 && edge.level < 1) return;
      const a = mapPoint(edge.x1, edge.y1);
      const b = mapPoint(edge.x2, edge.y2);
      if (!a || !b) return;
      const ratio = clamp(edge.ratio, 0, 2.5);
      ctx.strokeStyle = trafficColors[edge.level];
      ctx.globalAlpha = 0.08 + Math.min(0.28, ratio * 0.12);
      ctx.lineWidth = 14 + ratio * 8;
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
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    if (!layers.cars) return;
    const stride = Math.max(1, Math.ceil(cars.length / 800));
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
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = color;
    ctx.lineWidth = 9;
    ctx.globalAlpha = 0.16;
    ctx.setLineDash([]);
    ctx.beginPath();
    path.path.forEach((pt, idx) => {
      const p = mapPoint(pt.x, pt.y);
      if (!p) return;
      if (idx === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.stroke();
    ctx.globalAlpha = 0.95;
    ctx.lineWidth = 4;
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

    drawPathLine(ctx, staticPath, '#2563eb');
    if (trafficPath?.edge_levels && trafficPath.path.length > 1) {
      trafficPath.path.slice(0, -1).forEach((pt, i) => {
        const next = trafficPath.path[i + 1];
        const a = mapPoint(pt.x, pt.y);
        const b = mapPoint(next.x, next.y);
        if (!a || !b) return;
        const color = trafficColors[trafficPath.edge_levels?.[i] || 0];
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.18;
        ctx.lineWidth = 9;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.globalAlpha = 0.96;
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      });
      ctx.globalAlpha = 1;
    } else {
      drawPathLine(ctx, trafficPath, '#7c3aed', true);
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

    const marker = (v: VertexDTO | null, label: string, color: string) => {
      if (!v) return;
      const p = mapPoint(v.x, v.y);
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
  }, [activeTrace, drawPathLine, end, highlightedEdge, highlightVisible, incident, layers.trace, mapPoint, start, staticPath, traceIndex, trafficPath]);

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
    const data = await api.viewport({
      x_min: b.getWest(),
      y_min: -b.getNorth(),
      x_max: b.getEast(),
      y_max: -b.getSouth(),
      traffic: true,
      representative: false,
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
      setStatus((prev) => ({ ...prev, text: `${prev.text.split(' | ')[0]} | 坐标 (${fmt(x, 0)}, ${fmt(y, 0)})` }));
    });
    map.on('contextmenu', () => clearRoutes());
    map.on('click', async (e) => {
      const { x, y } = glx(e.latlng.lat, e.latlng.lng);
      try {
        const v = await api.nearest(x, y);
        if (!startRef.current) {
          setStart(v);
          setOk(`起点已设置 ID:${v.id}`);
        } else if (!endRef.current) {
          setEnd(v);
          setOk(`终点已设置 ID:${v.id}`);
        } else {
          setStart(v);
          setEnd(null);
          setStaticPath(null);
          setTrafficPath(null);
          setActiveTrace(null);
          setOk(`重新选择起点 ID:${v.id}`);
        }
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
  useEffect(() => { refreshViewportRef.current = refreshViewport; }, [refreshViewport]);
  useEffect(() => { drawAllRef.current = drawAll; }, [drawAll]);

  useEffect(() => { drawAll(); }, [drawAll, viewport, cars, staticPath, trafficPath, activeTrace, traceIndex, layers, start, end, incident]);
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
    const id = window.setInterval(() => {
      setTraceIndex((idx) => {
        const next = idx + traceSpeed;
        if (next >= maxLen) {
          window.clearInterval(id);
          setTracePlaying(false);
          return maxLen;
        }
        return next;
      });
    }, 70);
    return () => window.clearInterval(id);
  }, [activeTrace, tracePlaying, traceSpeed]);

  useEffect(() => {
    if (!simRunning) return;
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
    }, 850);
    return () => window.clearInterval(id);
  }, [refreshViewport, simRunning]);

  const generateMap = async () => {
    const n = selectedMapSize;
    setBusy(`生成 ${n} 点地图中...`);
    setMinimapData(null);
    setHighlightedEdge(null);
    await api.generateMap(n, 2026);
    for (;;) {
      const res = await api.generationStatus();
      if (res.status === 'done' && typeof res.data === 'object' && res.data) {
        setStats(res.data);
        fitMap(res.data);
        setOk(`${res.data.vertices} 点地图生成完毕，可开始演示`);
        await new Promise((r) => setTimeout(r, 100));
        await refreshViewportRef.current?.();
        await loadMinimap();
        setAnalytics(await api.analytics());
        break;
      }
      if (res.status === 'error') {
        setError(String(res.data || '生成失败'));
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
  };

  const startSimulation = async () => {
    if (!stats) return setError('请先生成地图');
    await api.simStart(1800);
    await api.simSpeed(5);
    setSimRunning(true);
    setOk('早高峰交通模拟运行中');
  };

  const stopSimulation = async () => {
    await api.simStop();
    setSimRunning(false);
    setCars([]);
    setOk('模拟已停止');
  };

  const runPath = async () => {
    if (!start || !end) return setError('请先在地图上选择起点和终点');
    setBusy('计算静态最短路径并收集算法轨迹...');
    const path = await api.path(start.id, end.id, algorithm, true);
    setStaticPath(path);
    setActiveTrace(path);
    setTraceIndex(0);
    setTracePlaying(true);
    setOk(`${path.algorithm} 路径完成，访问 ${path.nodes_visited} 个节点`);
  };

  const runTrafficPath = async () => {
    if (!start || !end) return setError('请先选择起点和终点');
    setBusy('计算交通感知路径...');
    const path = await api.trafficPath(start.id, end.id, algorithm, true);
    setTrafficPath(path);
    setActiveTrace(path);
    setTraceIndex(0);
    setTracePlaying(true);
    setOk(`交通路径完成，拥堵路段 ${path.congestion_count ?? 0}`);
  };

  function clearRoutes() {
    setStart(null);
    setEnd(null);
    setStaticPath(null);
    setTrafficPath(null);
    setActiveTrace(null);
    setIncident(null);
    setTraceIndex(0);
    setTracePlaying(false);
  }

  const runDemo = async () => {
    const n = selectedMapSize;
    setDemoRunning(true);
    setDemoTimeline(0, -1, n);
    setBusy(`准备 ${n} 点演示地图...`);
    setMinimapData(null);
    setTrafficPath(null);
    setStaticPath(null);
    setIncident(null);
    setHighlightedEdge(null);
    try {
      const demo = await api.demo(n);
      if (demo.error) {
        setError(demo.error);
        return;
      }

      setDemoTimeline(1, 0, n);
      setBusy('启动早高峰交通流...');
      setStats(demo.stats);
      fitMap(demo.stats);
      setSimRunning(true);
      setAnalytics(await api.analytics());
      await loadMinimap();
      await refreshViewportRef.current?.();
      await sleep(550);

      setDemoTimeline(2, 1, n);
      setBusy('选择跨城起终点...');
      setStart(demo.start);
      setEnd(demo.end);
      fitRoute([demo.start, demo.end]);
      await sleep(650);

      setDemoTimeline(3, 2, n);
      setBusy('注入事故拥堵并刷新路况...');
      setIncident(demo.incident);
      await refreshViewportRef.current?.();
      await sleep(650);

      setDemoTimeline(4, 3, n);
      setBusy('播放普通路径搜索轨迹...');
      setStaticPath(demo.static_path);
      setTrafficPath(null);
      setActiveTrace(demo.static_path);
      setTraceIndex(0);
      setTracePlaying(true);
      fitRoute(demo.static_path.path);
      await sleep(1300);

      setBusy('切换到交通感知绕行路径...');
      setTrafficPath(demo.traffic_path);
      setActiveTrace(demo.traffic_path);
      setTraceIndex(0);
      setTracePlaying(true);
      await sleep(700);

      setDemoTimeline(null, 4, n);
      setOk(`演示就绪：事故影响 ${demo.incident.affected_edges} 条边`);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setDemoRunning(false);
    }
  };

  const searchPois = async (category = poiCategory, limit = 12) => {
    if (!stats) return setError('请先生成地图');
    const center = start || currentMapCenter(stats);
    const data = await api.poiSearch(center.x, center.y, category, limit, 700);
    setPois(data.pois);
    setOk(`找到 ${data.pois.length} 个 ${poiNames[category] || 'POI'}`);
    if (data.pois[0]) {
      mapRef.current?.panTo(ll(data.pois[0].x, data.pois[0].y));
    }
  };

  const routeToPoi = async (poi: POI) => {
    if (!stats) return;
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
    setActiveTrace(path);
    setTraceIndex(0);
    setTracePlaying(true);
  };

  function currentMapCenter(fallback: Stats) {
    const c = mapRef.current?.getCenter();
    return c ? glx(c.lat, c.lng) : { x: fallback.width / 2, y: fallback.height / 2 };
  }

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

  return (
    <div className="shell">
      <aside className="sidebar">
        <header className="brand">
          <div className="brand-mark">NAV</div>
          <div>
            <h1>Navigation System Pro</h1>
            <p>数据结构课设 · Web 展示版</p>
          </div>
        </header>

        <section className="panel primary-panel">
          <div className="panel-title">一键演示</div>
          <button className="command primary" onClick={runDemo} disabled={demoRunning}>
            {demoRunning && demoStepIndex !== null ? `演示中 ${demoStepIndex + 1}/5` : '运行高分演示剧本'}
          </button>
          <div className="timeline">
            {demoSteps.map((step) => <div key={step.label} className={`timeline-row ${step.state}`}><span />{step.label}</div>)}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">地图与算法</div>
          <label className="field">点数
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
            <button className="command" onClick={generateMap} disabled={demoRunning}>生成 {selectedMapSize} 点</button>
            <button className="command" onClick={simRunning ? stopSimulation : startSimulation}>{simRunning ? '停止模拟' : '启动交通'}</button>
          </div>
          <label className="field">算法
            <select value={algorithm} onChange={(e) => setAlgorithm(e.target.value as 'astar' | 'dijkstra')}>
              <option value="astar">A* 搜索</option>
              <option value="dijkstra">Dijkstra</option>
            </select>
          </label>
          <div className="grid2">
            <button className="command" onClick={runPath}>普通最短路</button>
            <button className="command purple" onClick={runTrafficPath}>交通感知路径</button>
          </div>
          <button className="command ghost" onClick={clearRoutes}>清除路径</button>
        </section>

        <section className="panel">
          <div className="panel-title">算法动画</div>
          <div className="trace-controls">
            <button className="chip" onClick={() => setTracePlaying((p) => !p)}>{tracePlaying ? '暂停' : '播放'}</button>
            {[1, 4, 10].map((s) => <button key={s} className={`chip ${traceSpeed === s ? 'active' : ''}`} onClick={() => setTraceSpeed(s)}>{s}x</button>)}
            <button className="chip" onClick={() => setTraceIndex(0)}>重播</button>
          </div>
          <Metric label="访问节点" value={activeTrace?.nodes_visited ?? 0} />
          <Metric label="松弛边数" value={activeTrace?.relaxed_edges.length ?? 0} />
          {activeTrace?.trace_truncated && <div className="warn">轨迹较长，已截断展示</div>}
        </section>

        <section className="panel">
          <div className="panel-title">图层</div>
          <Toggle label="道路路况" checked={layers.traffic} onChange={(traffic) => setLayers({ ...layers, traffic })} />
          <Toggle label="拥堵热力图" checked={layers.heat} onChange={(heat) => setLayers({ ...layers, heat })} />
          <Toggle label="车辆动画" checked={layers.cars} onChange={(carsLayer) => setLayers({ ...layers, cars: carsLayer })} />
          <Toggle label="POI 与城市分区" checked={layers.poi} onChange={(poi) => setLayers({ ...layers, poi })} />
          <Toggle label="算法搜索轨迹" checked={layers.trace} onChange={(trace) => setLayers({ ...layers, trace })} />
        </section>

        <section className="panel">
          <div className="panel-title">POI 搜索导航</div>
          <label className="field">服务类型
            <select value={poiCategory} onChange={(e) => setPoiCategory(e.target.value)}>
              {Object.entries(poiNames).filter(([id]) => id !== 'all').map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <div className="grid2">
            <button className="command" onClick={() => searchPois()}>搜索附近</button>
            <button className="command" onClick={async () => { await searchPois(poiCategory, 1); }}>最近服务点</button>
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
      </aside>

      <main className="stage">
        <section className="dashboard">
          <StatCard label="节点 / 道路" value={stats ? `${stats.vertices} / ${stats.edges}` : '—'} />
          <StatCard label="活跃车辆" value={simState?.active_cars ?? analytics?.active_cars ?? 0} />
          <StatCard label="平均拥堵率" value={`${fmt((analytics?.average_ratio ?? 0) * 100, 1)}%`} />
          <StatCard label="拥堵道路" value={congestedCount} accent="red" />
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

          <div className="route-card">
            <div>
              <b>S</b> {start ? `ID ${start.id} (${fmt(start.x, 0)}, ${fmt(start.y, 0)})` : '点击地图选择起点'}
            </div>
            <div>
              <b>E</b> {end ? `ID ${end.id} (${fmt(end.x, 0)}, ${fmt(end.y, 0)})` : '再次点击选择终点'}
            </div>
            {staticPath && <div className="path-row blue">静态路径 {fmt(staticPath.distance)} · {staticPath.hops} 跳 · {fmt(staticPath.elapsed_ms, 2)}ms</div>}
            {trafficPath && <div className="path-row purple">交通路径 {fmt(trafficPath.distance)} · 拥堵段 {trafficPath.congestion_count ?? 0}</div>}
          </div>

          <div className="overview-panel">
            <div className="overview-header">
              <span>全景 overview</span>
              <b>{minimapData ? `${minimapData.vertices.length} 点` : '待生成'}</b>
            </div>
            <canvas ref={overviewCanvasRef} onClick={handleOverviewClick} />
          </div>

          <div className="legend">
            {trafficColors.map((c, i) => <span key={c}><i style={{ background: c }} />{['畅通', '缓行', '拥堵', '严重'][i]}</span>)}
          </div>
        </div>

        <section className="bottom-panel">
          <div className="panel-title">Top 拥堵道路</div>
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
          </div>
        </section>
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
  const maxY = Math.max(0.1, ...points.map((p) => p.max_ratio));
  const latest = points[points.length - 1];
  const d = points.map((p, i) => {
    const x = points.length <= 1 ? 0 : (i / (points.length - 1)) * w;
    const y = h - (p.average_ratio / maxY) * h;
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <div className="chart-card">
      <div className="chart-title"><span>拥堵趋势</span><b>{latest ? `${fmt(latest.average_ratio * 100, 1)}%` : '—'}</b></div>
      <svg className="mini-line" viewBox={`0 0 ${w} ${h}`}><path d={d || `M0,${h} L${w},${h}`} /></svg>
    </div>
  );
}

function LevelBars({ counts }: { counts: Record<string, number> }) {
  const total = Math.max(1, Object.values(counts).reduce((a, b) => a + Number(b), 0));
  return (
    <div className="level-card">
      <div className="chart-title"><span>路况占比</span><b>{total}</b></div>
      <div className="level-bars">
        {[0, 1, 2, 3].map((level) => (
          <div key={level}>
            <span>{['畅', '缓', '堵', '重'][level]}</span>
            <i style={{ width: `${(Number(counts[String(level)] || 0) / total) * 100}%`, background: trafficColors[level] }} />
          </div>
        ))}
      </div>
    </div>
  );
}
