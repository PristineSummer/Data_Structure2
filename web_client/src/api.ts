import type { AlgorithmCompareDTO, AnalyticsDTO, DemoDTO, MinimapDTO, NearbyDTO, PathDTO, POI, RouteExplainDTO, SimulationState, Stats, TrafficHistoryDTO, VertexDTO, ViewportDTO } from './types';

const jsonHeaders = { 'Content-Type': 'application/json' };

async function readJson<T>(response: Response): Promise<T> {
  const data = (await response.json()) as T;
  if (!response.ok) {
    const error = (data as { error?: string }).error || response.statusText;
    throw new Error(error);
  }
  return data;
}

export async function postJson<T>(url: string, body: unknown): Promise<T> {
  return readJson<T>(await fetch(url, { method: 'POST', headers: jsonHeaders, body: JSON.stringify(body) }));
}

export async function getJson<T>(url: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const qs = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined) qs.set(key, String(value));
  });
  return readJson<T>(await fetch(qs.size ? `${url}?${qs}` : url));
}

export const api = {
  generateMap: (n = 30000, seed = 2026) => postJson<{ status: string }>('/api/map/generate', { n, seed }),
  generationStatus: () => getJson<{ status: string; data: Stats | string | null }>('/api/map/generate/status'),
  stats: () => getJson<Stats>('/api/map/stats'),
  minimap: () => getJson<MinimapDTO>('/api/minimap'),
  viewport: (params: Record<string, string | number | boolean>) => getJson<ViewportDTO>('/api/viewport', params),
  nearest: (x: number, y: number) => getJson<VertexDTO>('/api/nearest', { x, y }),
  nearby: (x: number, y: number, k = 100) => getJson<NearbyDTO>('/api/nearby', { x, y, k }),
  path: (start: number, end: number, algo: string, trace = true) =>
    getJson<PathDTO>('/api/path', { start, end, algo, trace, max_trace: 2500 }),
  trafficPath: (start: number, end: number, algo: string, trace = true) =>
    getJson<PathDTO>('/api/traffic_path', { start, end, algo, trace, max_trace: 2500 }),
  compareAlgorithms: (start: number, end: number, trace = true) =>
    getJson<AlgorithmCompareDTO>('/api/compare_algorithms', { start, end, trace, max_trace: 2500 }),
  routeExplain: (start: number, end: number, algo: string, trace = true) =>
    getJson<RouteExplainDTO>('/api/route/explain', { start, end, algo, trace, max_trace: 2500 }),
  simStart: (cars = 1800) => postJson<{ status: string }>('/api/sim/start', { cars, density_low: 0.18, density_high: 0.58 }),
  simStop: () => postJson<{ status: string }>('/api/sim/stop', {}),
  simSpeed: (speed: number) => postJson<{ speed: number }>('/api/sim/speed', { speed }),
  simState: () => getJson<SimulationState>('/api/sim/state'),
  injectTraffic: (x: number, y: number, radius = 150, intensity = 120) =>
    postJson<{ affected: number; x: number; y: number; radius: number }>('/api/traffic/inject', { x, y, radius, intensity }),
  trafficHistory: (x: number, y: number, t: number, r = 300) =>
    getJson<TrafficHistoryDTO>('/api/traffic/history', { x, y, t, r }),
  analytics: () => getJson<AnalyticsDTO>('/api/analytics/traffic'),
  demo: (n = 30000, seed = 2026) => postJson<DemoDTO>('/api/demo/setup', { n, seed }),
  poiCategories: () => getJson<{ categories: Array<{ id: string; label: string }> }>('/api/poi/categories'),
  poiSearch: (x: number, y: number, category: string, k = 12, radius = 600) =>
    getJson<{ center: { x: number; y: number }; pois: POI[] }>('/api/poi/search', { x, y, category, k, radius }),
};
