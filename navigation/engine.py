"""
engine.py — NavigationEngine 统一 API

为成员 B 提供一个统一的高层入口，隐藏底层各模块的复杂性。
成员 B 只需与 NavigationEngine 交互即可完成 F1-F5 的所有后端调用。

使用方式：
    from navigation.engine import NavigationEngine

    engine = NavigationEngine()
    engine.generate_map(n_vertices=10000, width=2000, height=1500, seed=42)
    engine.save_map("map.json")

    # F1: 查询最近的 100 个点
    nearby = engine.query_nearby(x=500, y=400, k=100)

    # F2: 查询视口内的点和边
    vertices, edges = engine.query_viewport(100, 100, 800, 600)

    # F3: 最短路径
    result = engine.shortest_path(start_id=0, end_id=999)

    # F5: 交通感知最短路径
    result = engine.traffic_aware_path(start_id=0, end_id=999)
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from .graph import Vertex, Edge, Graph
from .map_generator import MapGenerator
from .serializer import GraphSerializer
from .kdtree import KDTree
from .pathfinding import (
    PathResult, dijkstra, astar, shortest_path,
    default_weight, make_traffic_weight, WeightFunc,
)
from .traffic_simulator import CarState, EdgeTrafficState, TrafficSimulator, TrafficSnapshot, edge_key
from .traffic_history import TrafficHistory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class POIResult:
    """GUI-friendly POI query result."""

    vertex: Vertex
    distance: float
    poi_type: str
    name: str
    metadata: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class NearbyState:
    """Combined local state around one coordinate for F1-style rendering."""

    center: Tuple[float, float]
    vertices: List[Tuple[float, Vertex]]
    edges: List[Edge]
    pois: List[POIResult]


@dataclass(frozen=True)
class ViewportState:
    """Combined viewport state for map drawing and optional traffic overlays."""

    bounds: Tuple[float, float, float, float]
    vertices: List[Vertex]
    edges: List[Edge]
    traffic: Dict[Tuple[int, int], EdgeTrafficState] = field(default_factory=dict)
    representative: bool = False


class NavigationEngine:
    """
    导航系统统一 API。

    封装了地图生成、空间查询、路径搜索等所有后端功能，
    供成员 B 的 GUI 层直接调用。
    """

    def __init__(self) -> None:
        self._graph: Optional[Graph] = None
        self._kdtree: Optional[KDTree] = None
        self._poi_kdtree: Optional[KDTree] = None
        self._traffic_simulator: Optional[TrafficSimulator] = None
        self._traffic_history = TrafficHistory(max_history=2000)
        self._generator = MapGenerator()

    @property
    def graph(self) -> Optional[Graph]:
        """获取当前加载的图对象。"""
        return self._graph

    @property
    def is_loaded(self) -> bool:
        """是否已加载/生成地图。"""
        return self._graph is not None

    @property
    def traffic_simulator(self) -> Optional[TrafficSimulator]:
        """获取当前交通模拟器（未启动时为 None）。"""
        return self._traffic_simulator

    # ---- 地图管理 ----

    def generate_map(
        self,
        n_vertices: int = 10000,
        width: float = 2000.0,
        height: float = 1500.0,
        seed: Optional[int] = None,
        poi_density: float = 0.08,
        poi_categories: Optional[Sequence[str]] = None,
    ) -> Graph:
        """
        生成一张新的随机地图并自动构建空间索引。

        Returns:
            生成的 Graph 对象。
        """
        self._graph = self._generator.generate(
            n_vertices=n_vertices,
            width=width,
            height=height,
            seed=seed,
            poi_density=poi_density,
            poi_categories=poi_categories,
        )
        self._rebuild_index()
        self._traffic_simulator = None
        logger.info(f"地图已生成并索引: V={self._graph.vertex_count}, E={self._graph.edge_count}")
        return self._graph

    def save_map(self, filepath: str) -> None:
        """保存当前地图到 JSON 文件。"""
        self._ensure_loaded()
        GraphSerializer.save(self._graph, filepath)

    def load_map(self, filepath: str) -> Graph:
        """
        从 JSON 文件加载地图并自动构建空间索引。

        Returns:
            加载的 Graph 对象。
        """
        self._graph = GraphSerializer.load(filepath)
        self._rebuild_index()
        self._traffic_simulator = None
        logger.info(f"地图已加载并索引: V={self._graph.vertex_count}, E={self._graph.edge_count}")
        return self._graph

    # ---- F1: 空间查询 ----

    def query_nearby(
        self, x: float, y: float, k: int = 100
    ) -> List[Tuple[float, Vertex]]:
        """
        查找离 (x, y) 最近的 k 个顶点。

        用于 F1: 输入坐标，显示最近 100 个点及其关联边。

        Returns:
            [(distance, Vertex), ...] 按距离升序。
        """
        self._ensure_indexed()
        self._validate_positive_int("k", k)
        x = self._validate_finite_number("x", x)
        y = self._validate_finite_number("y", y)
        return self._kdtree.query_k_nearest(x, y, k)

    def query_nearby_subgraph(
        self,
        x: float,
        y: float,
        k: int = 100,
        include_boundary_edges: bool = True,
    ) -> Tuple[List[Tuple[float, Vertex]], List[Edge]]:
        """
        查找最近的 k 个顶点及其关联边，直接服务 F1 地图显示。

        Args:
            x, y: 查询坐标。
            k: 最近顶点数量。
            include_boundary_edges: True 时返回与最近顶点相连的所有边；
                False 时只返回最近顶点集合内部的边。

        Returns:
            (nearby_vertices, edges)，其中 nearby_vertices 为
            [(distance, Vertex), ...]。
        """
        self._ensure_indexed()
        self._validate_positive_int("k", k)
        x = self._validate_finite_number("x", x)
        y = self._validate_finite_number("y", y)
        nearby = self._kdtree.query_k_nearest(x, y, k)
        vid_set: Set[int] = {v.id for _, v in nearby}

        edges: List[Edge] = []
        seen_edges: Set[Tuple[int, int]] = set()
        for _, vertex in nearby:
            for edge in self._graph.get_neighbors(vertex.id):
                other_id = edge.other(vertex.id)
                if not include_boundary_edges and other_id not in vid_set:
                    continue
                key = edge_key(edge.u, edge.v)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(edge)

        return nearby, edges

    def query_nearest_vertex(self, x: float, y: float) -> Optional[Vertex]:
        """查找离 (x, y) 最近的单个顶点。"""
        self._ensure_indexed()
        x = self._validate_finite_number("x", x)
        y = self._validate_finite_number("y", y)
        result = self._kdtree.query_nearest(x, y)
        return result[1] if result else None

    def query_nearby_pois(
        self,
        x: float,
        y: float,
        k: int = 20,
        categories: Optional[Sequence[str]] = None,
        radius: Optional[float] = None,
    ) -> List[POIResult]:
        """
        查询附近 POI，按距离升序返回。

        Args:
            x, y: 查询坐标。
            k: 最多返回 POI 数量。
            categories: 可选 POI 类型过滤。
            radius: 可选搜索半径。
        """
        self._ensure_indexed()
        self._validate_positive_int("k", k)
        x = self._validate_finite_number("x", x)
        y = self._validate_finite_number("y", y)
        self._validate_optional_radius(radius)
        category_filter = self._normalize_category_filter(categories)

        if self._poi_kdtree is None or self._poi_kdtree.size == 0:
            return []

        candidates = self._poi_kdtree.query_k_nearest(x, y, self._poi_kdtree.size)
        pois: List[POIResult] = []
        for distance, vertex in candidates:
            if radius is not None and distance > radius:
                continue
            poi_metadata = self._get_poi_metadata(vertex)
            if poi_metadata is None:
                continue
            poi_type = str(poi_metadata["type"])
            if category_filter is not None and poi_type not in category_filter:
                continue
            pois.append(
                POIResult(
                    vertex=vertex,
                    distance=distance,
                    poi_type=poi_type,
                    name=str(poi_metadata.get("name") or poi_type),
                    metadata=dict(poi_metadata),
                )
            )
            if len(pois) >= k:
                break
        return pois

    def query_nearby_state(
        self,
        x: float,
        y: float,
        k: int = 100,
        poi_k: int = 20,
        poi_categories: Optional[Sequence[str]] = None,
        poi_radius: Optional[float] = None,
    ) -> NearbyState:
        """
        一次性返回附近顶点、关联边和 POI，方便 GUI 点选/悬停渲染。
        """
        self._validate_positive_int("poi_k", poi_k)
        x = self._validate_finite_number("x", x)
        y = self._validate_finite_number("y", y)
        nearby, edges = self.query_nearby_subgraph(x, y, k=k)
        pois = self.query_nearby_pois(
            x,
            y,
            k=poi_k,
            categories=poi_categories,
            radius=poi_radius,
        )
        return NearbyState(center=(float(x), float(y)), vertices=nearby, edges=edges, pois=pois)

    # ---- F2: 视口查询 ----

    def query_viewport(
        self,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
        use_representative: bool = False,
        grid_cols: int = 20,
        grid_rows: int = 15,
    ) -> Tuple[List[Vertex], List[Edge]]:
        """
        查询视口范围内的顶点和边。

        用于 F2: 地图缩放时获取当前视口的内容。

        Args:
            x_min, y_min, x_max, y_max: 视口范围。
            use_representative: 是否使用代表点模式（缩放级别高时）。
            grid_cols, grid_rows: 代表点模式的网格参数。

        Returns:
            (vertices, edges) — 视口内的顶点和它们之间的边。
        """
        self._ensure_indexed()
        self._validate_positive_int("grid_cols", grid_cols)
        self._validate_positive_int("grid_rows", grid_rows)
        x_min, y_min, x_max, y_max = self._normalize_bounds(x_min, y_min, x_max, y_max)

        if use_representative:
            vertices = self._kdtree.query_representative(
                x_min, y_min, x_max, y_max, grid_cols, grid_rows
            )
        else:
            vertices = self._kdtree.query_range(x_min, y_min, x_max, y_max)

        # 收集视口内顶点之间的边
        vid_set: Set[int] = {v.id for v in vertices}
        edges: List[Edge] = []
        seen_edges: Set[Tuple[int, int]] = set()
        for v in vertices:
            for edge in self._graph.get_neighbors(v.id):
                other_id = edge.other(v.id)
                key = edge_key(edge.u, edge.v)
                if other_id in vid_set and key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(edge)

        return vertices, edges

    def query_viewport_state(
        self,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
        use_representative: bool = False,
        grid_cols: int = 20,
        grid_rows: int = 15,
        include_traffic: bool = True,
    ) -> ViewportState:
        """
        一次性返回视口内顶点、边和可选交通状态，方便地图缩放/拖拽刷新。
        """
        bounds = self._normalize_bounds(x_min, y_min, x_max, y_max)
        vertices, edges = self.query_viewport(
            *bounds,
            use_representative=use_representative,
            grid_cols=grid_cols,
            grid_rows=grid_rows,
        )

        traffic: Dict[Tuple[int, int], EdgeTrafficState] = {}
        if include_traffic and self._traffic_simulator is not None:
            traffic = self._traffic_simulator.get_edge_traffic_states(
                edge_key(edge.u, edge.v) for edge in edges
            )

        return ViewportState(
            bounds=bounds,
            vertices=vertices,
            edges=edges,
            traffic=traffic,
            representative=use_representative,
        )

    # ---- F3: 最短路径 ----

    def shortest_path(
        self,
        start_id: int,
        end_id: int,
        algorithm: str = "astar",
        trace: bool = False,
        max_trace: int = 2500,
    ) -> PathResult:
        """
        计算静态最短路径（权重 = 欧氏距离）。

        Args:
            start_id: 起点顶点 ID。
            end_id: 终点顶点 ID。
            algorithm: "dijkstra" 或 "astar"。

        Returns:
            PathResult 对象。
        """
        self._ensure_loaded()
        return shortest_path(
            self._graph, start_id, end_id,
            algorithm=algorithm, weight_func=default_weight,
            trace=trace, max_trace=max_trace,
        )

    # ---- F5: 交通感知最短路径 ----

    def traffic_aware_path(
        self,
        start_id: int,
        end_id: int,
        algorithm: str = "astar",
        c: float = 1.0,
        threshold: float = 0.8,
        trace: bool = False,
        max_trace: int = 2500,
    ) -> PathResult:
        """
        计算交通感知最短路径（权重 = 基于当前交通的通行时间）。

        Args:
            start_id: 起点顶点 ID。
            end_id: 终点顶点 ID。
            algorithm: "dijkstra" 或 "astar"。
            c: 通行时间公式常数。
            threshold: 拥堵阈值。

        Returns:
            PathResult 对象。
        """
        self._ensure_loaded()
        if self._traffic_simulator is not None:
            weight_fn = self._traffic_simulator.weight_func
        else:
            weight_fn = make_traffic_weight(c=c, threshold=threshold)
        return shortest_path(
            self._graph, start_id, end_id,
            algorithm=algorithm, weight_func=weight_fn,
            trace=trace, max_trace=max_trace,
        )

    # ---- F4: 交通模拟 ----

    def start_simulation(
        self,
        *,
        car_count: int = 0,
        c: float = 1.0,
        threshold: float = 0.8,
        base_outflow_rate: float = 0.25,
        max_outflow_rate: float = 0.65,
        reroute_on_node: bool = True,
        max_reroutes_per_step: int = 50,
        background_update_interval: int = 1,
        dynamic_background_routing: bool = True,
        background_route_sensitivity: float = 2.0,
        seed: Optional[int] = None,
        initial_density: Optional[Tuple[float, float]] = None,
    ) -> TrafficSimulator:
        """
        启动交通模拟器。

        initial_density=(low, high) 时，会按容量比例随机初始化每条边的
        current_cars；为 None 时保留图中已有的 current_cars。
        """
        self._ensure_loaded()
        if isinstance(car_count, bool) or not isinstance(car_count, int) or car_count < 0:
            raise ValueError("car_count must be a non-negative integer")
        self._traffic_simulator = TrafficSimulator(
            self._graph,
            c=c,
            threshold=threshold,
            base_outflow_rate=base_outflow_rate,
            max_outflow_rate=max_outflow_rate,
            reroute_on_node=reroute_on_node,
            max_reroutes_per_step=max_reroutes_per_step,
            background_update_interval=background_update_interval,
            dynamic_background_routing=dynamic_background_routing,
            background_route_sensitivity=background_route_sensitivity,
            seed=seed,
        )
        if initial_density is not None:
            if isinstance(initial_density, (str, bytes)):
                raise ValueError("initial_density must be a pair: (low, high)")
            try:
                density_values = tuple(initial_density)
            except TypeError as exc:
                raise ValueError("initial_density must be a pair: (low, high)") from exc
            if len(density_values) != 2:
                raise ValueError("initial_density must be a pair: (low, high)")
            low, high = density_values
            low = self._validate_finite_number("initial_density low", low)
            high = self._validate_finite_number("initial_density high", high)
            if low < 0 or high < low:
                raise ValueError("initial_density must satisfy 0 <= low <= high")
            self._traffic_simulator.randomize_traffic(low, high, seed=seed)
        if car_count > 0:
            self._traffic_simulator.spawn_cars(car_count)
        return self._traffic_simulator

    def inject_traffic_event(
        self,
        x: float,
        y: float,
        radius: float = 100.0,
        intensity: float = 50.0,
    ) -> int:
        """
        在指定坐标附近注入交通事件（增加背景交通流）。

        Args:
            x, y: 事件中心坐标。
            radius: 影响半径。
            intensity: 增加的交通流强度（车辆数）。

        Returns:
            受影响的边数量。
        """
        self._ensure_indexed()
        x = self._validate_finite_number("x", x)
        y = self._validate_finite_number("y", y)
        self._validate_optional_radius(radius)

        # 查找半径内的所有顶点
        nearby_vertices = self._kdtree.query_range(
            x - radius, y - radius, x + radius, y + radius
        )
        vid_set = {v.id for v in nearby_vertices}

        # 查找这些顶点关联的边
        affected_edges = set()
        for v in nearby_vertices:
            for edge in self._graph.get_neighbors(v.id):
                # 如果边的两个端点都在范围内，或者至少一个在范围内（取决于需求，这里选至少一个）
                affected_edges.add(edge_key(edge.u, edge.v))

        if not affected_edges:
            return 0

        simulator = self._ensure_simulator()
        # 将强度平摊到每条边上，或者每条边都增加强度
        # 这里选择每条边增加 intensity，模拟局部拥堵
        for u, v in affected_edges:
            simulator.add_edge_cars(u, v, intensity)

        logger.info(f"已在 ({x}, {y}) 注入事件，影响 {len(affected_edges)} 条边")
        return len(affected_edges)

    def step_simulation(self, steps: int = 1, spawn_count: int = 0) -> TrafficSnapshot:
        """推进交通模拟若干步，并返回最后一步的快照。"""
        if steps <= 0:
            raise ValueError("steps must be positive")
        simulator = self._ensure_simulator()
        snapshot = simulator.get_traffic_snapshot()
        for _ in range(steps):
            snapshot = simulator.step(spawn_count=spawn_count)
            self._traffic_history.add_snapshot(snapshot)
        return snapshot

    def query_traffic_at_time(
        self,
        x: float,
        y: float,
        time_step: int,
        radius: float = 300.0,
    ) -> Tuple[List[Edge], Dict[Tuple[int, int], EdgeTrafficState]]:
        """
        查询指定时间点和坐标附近的交通流。

        Returns:
            (edges, traffic_states) — traffic_states 保证为每条返回的边
            都包含对应的 EdgeTrafficState，优先使用历史快照数据。
        """
        self._ensure_indexed()
        x = self._validate_finite_number("x", x)
        y = self._validate_finite_number("y", y)
        
        # 获取该时间的快照
        snapshot = self._traffic_history.get_snapshot(time_step)
        if not snapshot:
            # 如果没有历史记录，尝试获取当前模拟器的状态
            if self._traffic_simulator:
                snapshot = self._traffic_simulator.get_traffic_snapshot()
            else:
                return [], {}

        # 查找范围内的顶点
        vertices = self._kdtree.query_range(x - radius, y - radius, x + radius, y + radius)
        vid_set = {v.id for v in vertices}
        
        # 收集边及其对应的交通状态
        edges = []
        traffic_states = {}
        seen_edges = set()
        
        for v in vertices:
            for edge in self._graph.get_neighbors(v.id):
                key = edge_key(edge.u, edge.v)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(edge)
                    if key in snapshot.edge_states:
                        traffic_states[key] = snapshot.edge_states[key]
                    else:
                        # 为未在快照中的边构建 fallback 状态
                        from .traffic_model import congestion_level as calc_level, congestion_ratio
                        cars = float(edge.current_cars)
                        cap = edge.capacity
                        ratio = congestion_ratio(cars, cap)
                        traffic_states[key] = EdgeTrafficState(
                            u=edge.u, v=edge.v,
                            current_cars=cars,
                            background_cars=cars,
                            vehicle_cars=0,
                            capacity=cap,
                            ratio=ratio,
                            level=calc_level(cars, cap),
                            travel_time=edge.travel_time(),
                        )
        
        return edges, traffic_states

    def get_traffic_snapshot(self) -> TrafficSnapshot:
        """返回当前交通状态快照。"""
        return self._ensure_simulator().get_traffic_snapshot()

    def get_traffic_state(self) -> TrafficSnapshot:
        """get_traffic_snapshot 的别名，方便 GUI 层调用。"""
        return self.get_traffic_snapshot()

    def get_car_snapshot(self, limit: Optional[int] = None) -> List[CarState]:
        """返回当前活动车辆状态，供 GUI 动态绘制车辆位置。"""
        return self._ensure_simulator().get_car_snapshot(limit=limit)

    # ---- GUI 绘制辅助 ----

    def path_coordinates(
        self,
        path_result_or_ids: Union[PathResult, Sequence[int]],
    ) -> List[Tuple[float, float]]:
        """
        将 PathResult 或顶点 ID 序列转换为坐标序列，GUI 可直接画折线。
        """
        self._ensure_loaded()
        if isinstance(path_result_or_ids, PathResult):
            vertex_ids = path_result_or_ids.path
        else:
            vertex_ids = list(path_result_or_ids)

        coordinates: List[Tuple[float, float]] = []
        for vertex_id in vertex_ids:
            vertex = self._graph.get_vertex(vertex_id)
            if vertex is None:
                raise ValueError(f"unknown vertex id in path: {vertex_id}")
            coordinates.append((vertex.x, vertex.y))
        return coordinates

    def edge_coordinates(self, edge: Edge) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """将 Edge 转换为两端点坐标，GUI 可直接画道路线段。"""
        self._ensure_loaded()
        u = self._graph.get_vertex(edge.u)
        v = self._graph.get_vertex(edge.v)
        if u is None or v is None:
            raise ValueError(f"edge references missing vertex: ({edge.u}, {edge.v})")
        return (u.x, u.y), (v.x, v.y)

    def get_stats(self) -> Dict:
        """返回图规模、连通性、POI 数量和交通模拟摘要。"""
        self._ensure_loaded()
        stats = dict(self._graph.stats())
        poi_count = sum(1 for vertex in self._graph.vertices() if self._get_poi_metadata(vertex))
        stats.update(
            {
                "width": self._graph.width,
                "height": self._graph.height,
                "seed": self._graph.seed,
                "poi_count": poi_count,
                "indexed_vertices": self._kdtree.size if self._kdtree is not None else 0,
                "indexed_pois": self._poi_kdtree.size if self._poi_kdtree is not None else 0,
                "simulation_running": self._traffic_simulator is not None,
            }
        )
        if self._traffic_simulator is not None:
            snapshot = self._traffic_simulator.get_traffic_snapshot()
            stats["traffic"] = {
                "time_step": snapshot.time_step,
                "total_cars": snapshot.total_cars,
                "active_cars": snapshot.active_cars,
                "average_ratio": snapshot.average_ratio,
                "max_ratio": snapshot.max_ratio,
            }
        else:
            stats["traffic"] = None
        return stats

    # ---- 内部方法 ----

    def _rebuild_index(self) -> None:
        """重建普通 KD-Tree 与 POI KD-Tree 空间索引。"""
        if self._graph is None:
            return
        self._kdtree = KDTree()
        self._kdtree.build(self._graph)
        poi_vertices = [
            vertex
            for vertex in self._graph.vertices()
            if self._get_poi_metadata(vertex) is not None
        ]
        self._poi_kdtree = KDTree()
        self._poi_kdtree.build_from_vertices(poi_vertices)

    def _ensure_loaded(self) -> None:
        """确保地图已加载。"""
        if self._graph is None:
            raise RuntimeError("地图未加载。请先调用 generate_map() 或 load_map()。")

    def _ensure_indexed(self) -> None:
        """确保地图已加载且空间索引已构建。"""
        self._ensure_loaded()
        if self._kdtree is None or self._poi_kdtree is None:
            self._rebuild_index()

    def _ensure_simulator(self) -> TrafficSimulator:
        """确保交通模拟器已创建。"""
        self._ensure_loaded()
        if self._traffic_simulator is None:
            self.start_simulation()
        return self._traffic_simulator

    @staticmethod
    def _validate_positive_int(name: str, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    @staticmethod
    def _validate_optional_radius(radius: Optional[float]) -> None:
        if radius is None:
            return
        if (
            isinstance(radius, bool)
            or not isinstance(radius, (int, float))
            or not math.isfinite(float(radius))
            or float(radius) <= 0
        ):
            raise ValueError("radius must be a positive finite number")

    @staticmethod
    def _validate_finite_number(name: str, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{name} must be a finite number")
        return float(value)

    @classmethod
    def _normalize_bounds(
        cls,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
    ) -> Tuple[float, float, float, float]:
        x1 = cls._validate_finite_number("x_min", x_min)
        y1 = cls._validate_finite_number("y_min", y_min)
        x2 = cls._validate_finite_number("x_max", x_max)
        y2 = cls._validate_finite_number("y_max", y_max)
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    @staticmethod
    def _normalize_category_filter(categories: Optional[Sequence[str]]) -> Optional[Set[str]]:
        if categories is None:
            return None
        if isinstance(categories, str):
            raise ValueError("categories must be a non-empty sequence of strings")
        normalized: Set[str] = set()
        for category in categories:
            if not isinstance(category, str) or not category.strip():
                raise ValueError("categories must contain non-empty strings")
            normalized.add(category.strip())
        if not normalized:
            raise ValueError("categories must be a non-empty sequence of strings")
        return normalized

    @staticmethod
    def _get_poi_metadata(vertex: Vertex) -> Optional[Mapping]:
        poi = vertex.metadata.get("poi") if isinstance(vertex.metadata, dict) else None
        if not isinstance(poi, Mapping):
            return None
        if not poi.get("type"):
            return None
        return poi

    def __repr__(self) -> str:
        if self._graph is None:
            return "NavigationEngine(not loaded)"
        return f"NavigationEngine(V={self._graph.vertex_count}, E={self._graph.edge_count})"
