export type TrafficLevel = 0 | 1 | 2 | 3;

export interface Stats {
  vertices: number;
  edges: number;
  poi_count: number;
  connected: boolean;
  width: number;
  height: number;
  seed?: number;
  simulation_running: boolean;
  cache_hit?: boolean;
  cache_key?: string;
}

export interface VertexDTO {
  id: number;
  x: number;
  y: number;
  is_poi?: boolean;
  poi_type?: string;
  poi_name?: string;
}

export interface EdgeDTO {
  u: number;
  v: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  length: number;
  capacity: number;
  current_cars: number;
  ratio: number;
  level: TrafficLevel;
  travel_time: number;
}

export interface ViewportDTO {
  vertices: VertexDTO[];
  edges: EdgeDTO[];
  representative?: boolean;
  lod?: string;
  truncated?: boolean;
  total_vertices_in_view?: number;
  total_edges_returned?: number;
  error?: string;
}

export interface MinimapDTO {
  vertices: Array<{ id: number; x: number; y: number }>;
  edges: Array<{ x1: number; y1: number; x2: number; y2: number }>;
  error?: string;
}

export interface TraceVertex {
  id: number;
  x?: number;
  y?: number;
}

export interface TraceEdge {
  u: number;
  v: number;
  x1?: number;
  y1?: number;
  x2?: number;
  y2?: number;
}

export interface PathDTO {
  found?: boolean;
  path: Array<{ x: number; y: number }>;
  path_vertex_ids: number[];
  distance: number;
  hops: number;
  nodes_visited: number;
  elapsed_ms: number;
  algorithm: string;
  edge_levels?: TrafficLevel[];
  static_distance?: number;
  saved?: number;
  congestion_count?: number;
  trace_truncated: boolean;
  visited: TraceVertex[];
  relaxed_edges: TraceEdge[];
  error?: string;
}

export interface CarDTO {
  x: number;
  y: number;
}

export interface SimulationState {
  time_step: number;
  total_cars: number;
  active_cars: number;
  average_ratio: number;
  max_ratio: number;
  cars?: CarDTO[];
  error?: string;
}

export interface AnalyticsDTO {
  time_step: number;
  active_cars: number;
  average_ratio: number;
  max_ratio: number;
  level_counts: Record<string, number>;
  top_congested_edges: EdgeDTO[];
  history: Array<{ time_step: number; average_ratio: number; max_ratio: number; active_cars: number }>;
  error?: string;
}

export interface POI {
  id: number;
  x: number;
  y: number;
  distance: number;
  poi_type: string;
  name: string;
}

export interface DemoDTO {
  stats: Stats;
  start: VertexDTO;
  end: VertexDTO;
  incident: { x: number; y: number; radius: number; intensity: number; affected_edges: number };
  static_path: PathDTO;
  traffic_path: PathDTO;
  metrics: Record<string, number>;
  route_explain?: RouteExplainDTO;
  error?: string;
}

export interface AlgorithmCompareDTO {
  astar: PathDTO;
  dijkstra: PathDTO;
  visit_reduction_percent: number;
  time_delta_ms: number;
  distance_delta: number;
  error?: string;
}

export interface RouteExplainDTO {
  static_path: PathDTO;
  traffic_path: PathDTO;
  static_edge_levels: TrafficLevel[];
  traffic_edge_levels: TrafficLevel[];
  static_edge_details: EdgeDTO[];
  traffic_edge_details: EdgeDTO[];
  worst_static_edge: EdgeDTO | null;
  worst_traffic_edge: EdgeDTO | null;
  static_congested_edges: number;
  traffic_congested_edges: number;
  avoided_congested_edges: number;
  summary: string;
  metrics: Record<string, number>;
  error?: string;
}

export interface HoveredEdgeDTO extends EdgeDTO {
  screenX: number;
  screenY: number;
}

export interface ExportSnapshotDTO {
  exported_at: string;
  stats: Stats | null;
  start: VertexDTO | null;
  end: VertexDTO | null;
  incident: DemoDTO['incident'] | null;
  algorithm_compare: AlgorithmCompareDTO | null;
  route_explain: RouteExplainDTO | null;
  analytics: AnalyticsDTO | null;
  pois: POI[];
}
