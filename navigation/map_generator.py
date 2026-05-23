"""
map_generator.py — 基于 Delaunay 三角剖分的地图生成引擎

算法流程：
    1. 在二维平面上随机撒点（支持泊松盘采样以保证最小间距）。
    2. 使用 scipy.spatial.Delaunay 进行三角剖分，生成无交叉的边集。
    3. 对边进行稀疏化：删除过长边、限制最大度数。
    4. 保留最小生成树骨架，确保连通性。
    5. 对不连通分量进行桥接修复。
    6. 为每条边赋值长度和容量属性。

为什么选择 Delaunay 三角剖分？
    - Delaunay 三角剖分保证不会产生不合理的道路交叉（三角化的数学性质）。
    - 时间复杂度 O(N log N)，适合 10000+ 节点的场景。
    - 生成的边天然连接"自然邻近"的点，生成的路网看起来合理。

参考：road-network-generator 项目的分层城市生成思路、网格连通策略。
"""

from __future__ import annotations

import math
import random
import time
import logging
from collections import deque
from typing import List, Optional, Sequence, Tuple, Set, Dict

import numpy as np
from scipy.spatial import Delaunay

from .graph import Vertex, Edge, Graph

logger = logging.getLogger(__name__)

DEFAULT_POI_CATEGORIES = ("gas_station", "restaurant", "parking", "repair", "hospital")


class MapGenerator:
    """
    地图生成引擎。

    使用方式：
        gen = MapGenerator()
        graph = gen.generate(n_vertices=10000, width=2000, height=1500, seed=42)

    核心参数：
        n_vertices: 要生成的顶点数量。
        width, height: 地图平面的宽高。
        seed: 随机种子（可复现）。
        max_degree: 每个顶点的最大允许度数（稀疏化用）。
        max_edge_length_factor: 边长阈值因子 —— 超过
            "邻域平均边长 * factor" 的边将被删除。
        min_distance: 两点之间的最小距离（泊松盘采样参数）。
            若为 None 则根据面积自动计算。
        capacity_range: 道路容量的随机取值范围 (min, max)。
    """

    def __init__(
        self,
        max_degree: int = 6,
        max_edge_length_factor: float = 2.5,
        min_distance: Optional[float] = None,
        capacity_range: Tuple[int, int] = (20, 100),
    ) -> None:
        self._validate_config(
            max_degree=max_degree,
            max_edge_length_factor=max_edge_length_factor,
            min_distance=min_distance,
            capacity_range=capacity_range,
        )
        self.max_degree = max_degree
        self.max_edge_length_factor = max_edge_length_factor
        self.min_distance = min_distance
        self.capacity_range = capacity_range

    def generate(
        self,
        n_vertices: int = 10000,
        width: float = 2000.0,
        height: float = 1500.0,
        seed: Optional[int] = None,
        poi_density: float = 0.08,
        poi_categories: Optional[Sequence[str]] = None,
    ) -> Graph:
        """
        生成一个随机地图图结构。

        Args:
            n_vertices: 顶点数量。
            width: 地图宽度。
            height: 地图高度。
            seed: 随机种子。
            poi_density: 每个顶点生成 POI 的概率，范围 [0, 1]。
            poi_categories: 可选 POI 类型列表。

        Returns:
            生成的 Graph 对象。
        """
        self._validate_generation_args(n_vertices, width, height)
        self._validate_poi_density(poi_density)
        poi_categories_tuple = self._normalize_poi_categories(poi_categories)
        t_start = time.time()

        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        else:
            seed = random.randint(0, 2**31 - 1)
            random.seed(seed)
            np.random.seed(seed)

        logger.info(f"开始生成地图: N={n_vertices}, size={width}x{height}, seed={seed}")

        # 步骤 1：生成随机点
        points = self._generate_points(n_vertices, width, height)
        actual_n = len(points)
        logger.info(f"步骤 1/5 完成: 生成了 {actual_n} 个顶点")

        # 步骤 2：构建图骨架（Delaunay 三角剖分）
        graph = Graph()
        graph.width = width
        graph.height = height
        graph.seed = seed

        # 添加顶点
        for i, (x, y) in enumerate(points):
            graph.add_vertex(Vertex(id=i, x=x, y=y))

        # Delaunay 三角剖分
        coords = np.array(points)
        tri = Delaunay(coords)
        raw_edges = self._extract_edges_from_delaunay(tri)
        logger.info(f"步骤 2/5 完成: Delaunay 三角剖分产生 {len(raw_edges)} 条边")

        # 添加所有 Delaunay 边
        for u_id, v_id in raw_edges:
            vu = graph.get_vertex(u_id)
            vv = graph.get_vertex(v_id)
            length = vu.distance_to(vv)
            cap = random.randint(*self.capacity_range)
            graph.add_edge(Edge(u=u_id, v=v_id, length=length, capacity=cap))

        # 步骤 3：提取最小生成树骨架（Kruskal）
        mst_edges = self._kruskal_mst(graph)
        mst_set = set()
        for e in mst_edges:
            mst_set.add((min(e.u, e.v), max(e.u, e.v)))
        logger.info(f"步骤 3/5 完成: 最小生成树有 {len(mst_edges)} 条边")

        # 步骤 3.5：MST 边为主干道，容量提升 2-3 倍
        # 主干道应比普通街道有更高容量，模拟真实的道路层级结构
        for e in mst_edges:
            boost = random.uniform(2.0, 3.0)
            e.capacity = int(e.capacity * boost)

        # 步骤 4：稀疏化 —— 删除过长边，限制度数，但保留 MST 边
        self._sparsify(graph, mst_set)
        logger.info(f"步骤 4/5 完成: 稀疏化后 {graph.edge_count} 条边")

        # 步骤 5：连通性修复
        self._ensure_connectivity(graph)
        logger.info(f"步骤 5/5 完成: 连通性已保证")

        # POI 信息写入 Vertex.metadata，保持 JSON 顶层结构不变。
        self._assign_pois(graph, poi_density, poi_categories_tuple)

        t_elapsed = time.time() - t_start
        stats = graph.stats()
        logger.info(
            f"地图生成完成: {stats['vertices']} 顶点, {stats['edges']} 边, "
            f"avg_degree={stats['avg_degree']:.1f}, "
            f"耗时 {t_elapsed:.2f}s, seed={seed}"
        )
        return graph

    @staticmethod
    def _validate_config(
        *,
        max_degree: int,
        max_edge_length_factor: float,
        min_distance: Optional[float],
        capacity_range: Tuple[int, int],
    ) -> None:
        """Validate generator configuration and fail with GUI-friendly messages."""
        if isinstance(max_degree, bool) or not isinstance(max_degree, int) or max_degree < 1:
            raise ValueError("max_degree must be a positive integer")
        if not MapGenerator._is_positive_finite(max_edge_length_factor):
            raise ValueError("max_edge_length_factor must be a positive finite number")
        if min_distance is not None:
            if not MapGenerator._is_positive_finite(min_distance):
                raise ValueError("min_distance must be a positive finite number")
        if (
            not isinstance(capacity_range, tuple)
            or len(capacity_range) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in capacity_range)
        ):
            raise ValueError("capacity_range must be a tuple of two positive integers")
        min_cap, max_cap = capacity_range
        if min_cap <= 0 or max_cap <= 0 or min_cap > max_cap:
            raise ValueError("capacity_range must satisfy 0 < min_capacity <= max_capacity")

    @staticmethod
    def _validate_generation_args(n_vertices: int, width: float, height: float) -> None:
        """Validate map size arguments before reaching Delaunay."""
        if isinstance(n_vertices, bool) or not isinstance(n_vertices, int) or n_vertices < 3:
            raise ValueError("n_vertices must be an integer >= 3")
        if not MapGenerator._is_positive_finite(width):
            raise ValueError("width must be a positive finite number")
        if not MapGenerator._is_positive_finite(height):
            raise ValueError("height must be a positive finite number")

    @staticmethod
    def _validate_poi_density(poi_density: float) -> None:
        if (
            isinstance(poi_density, bool)
            or not isinstance(poi_density, (int, float))
            or not math.isfinite(float(poi_density))
            or not 0 <= float(poi_density) <= 1
        ):
            raise ValueError("poi_density must be a finite number in [0, 1]")

    @staticmethod
    def _normalize_poi_categories(poi_categories: Optional[Sequence[str]]) -> Tuple[str, ...]:
        if poi_categories is None:
            return DEFAULT_POI_CATEGORIES
        if isinstance(poi_categories, str):
            raise ValueError("poi_categories must be a non-empty sequence of strings")

        normalized: List[str] = []
        seen: Set[str] = set()
        for category in poi_categories:
            if not isinstance(category, str) or not category.strip():
                raise ValueError("poi_categories must contain non-empty strings")
            value = category.strip()
            if value not in seen:
                seen.add(value)
                normalized.append(value)

        if not normalized:
            raise ValueError("poi_categories must be a non-empty sequence of strings")
        return tuple(normalized)

    @staticmethod
    def _assign_pois(graph: Graph, poi_density: float, poi_categories: Sequence[str]) -> None:
        if poi_density == 0:
            return

        selected_vertices = [
            vertex
            for vertex in graph.vertices()
            if random.random() < poi_density
        ]
        if not selected_vertices and graph.vertex_count > 0:
            selected_vertices = [random.choice(list(graph.vertices()))]

        counters = {category: 0 for category in poi_categories}
        for vertex in selected_vertices:
            poi_type = random.choice(tuple(poi_categories))
            counters[poi_type] += 1
            vertex.metadata["poi"] = {
                "type": poi_type,
                "category": poi_type,
                "name": f"{poi_type}_{counters[poi_type]}",
            }

    @staticmethod
    def _is_positive_finite(value: object) -> bool:
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value > 0
        )

    # ------------------------------------------------------------------
    # 步骤 1：点生成
    # ------------------------------------------------------------------

    def _generate_points(
        self, n: int, width: float, height: float
    ) -> List[Tuple[float, float]]:
        """
        使用基于网格的泊松盘采样生成带最小间距约束的随机点。

        如果泊松盘采样无法生成足够的点（空间太小），
        则回退到简单随机 + 去重策略。
        """
        min_dist = self.min_distance
        if min_dist is None:
            # 自动计算：保证在给定面积下 n 个点能放得下
            area = width * height
            # 理论上泊松盘采样最多能放 area / (min_dist^2 * pi/4) 个点
            # 反推 min_dist，留 30% 余量
            min_dist = math.sqrt(area / (n * 1.8))

        points = self._poisson_disk_sampling(n, width, height, min_dist)

        if len(points) < n * 0.9:
            logger.warning(
                f"泊松盘采样只得到 {len(points)} 个点 (目标 {n})，"
                f"回退到网格抖动策略"
            )
            points = self._grid_jitter_sampling(n, width, height, min_dist * 0.5)

        return points[:n]  # 截断到目标数量

    def _poisson_disk_sampling(
        self, n: int, width: float, height: float, min_dist: float
    ) -> List[Tuple[float, float]]:
        """
        快速泊松盘采样（Bridson 算法简化版）。
        在二维平面上生成尽可能多的点，使任意两点距离 >= min_dist。

        时间复杂度: O(N)（期望）。
        """
        cell_size = min_dist / math.sqrt(2)
        cols = max(1, int(math.ceil(width / cell_size)))
        rows = max(1, int(math.ceil(height / cell_size)))
        grid: Dict[Tuple[int, int], Tuple[float, float]] = {}

        points: List[Tuple[float, float]] = []
        active: List[Tuple[float, float]] = []
        k = 30  # 每个活跃点尝试 k 次

        # 第一个点
        x0 = random.uniform(0, width)
        y0 = random.uniform(0, height)
        p0 = (x0, y0)
        points.append(p0)
        active.append(p0)
        gc = (int(x0 / cell_size), int(y0 / cell_size))
        grid[gc] = p0

        while active and len(points) < n * 1.2:
            idx = random.randint(0, len(active) - 1)
            px, py = active[idx]
            found = False
            for _ in range(k):
                angle = random.uniform(0, 2 * math.pi)
                r = random.uniform(min_dist, 2 * min_dist)
                nx_ = px + r * math.cos(angle)
                ny_ = py + r * math.sin(angle)

                if nx_ < 0 or nx_ >= width or ny_ < 0 or ny_ >= height:
                    continue

                ci = int(nx_ / cell_size)
                cj = int(ny_ / cell_size)

                too_close = False
                for di in range(-2, 3):
                    if too_close:
                        break
                    for dj in range(-2, 3):
                        ni, nj = ci + di, cj + dj
                        if (ni, nj) in grid:
                            ox, oy = grid[(ni, nj)]
                            if (nx_ - ox) ** 2 + (ny_ - oy) ** 2 < min_dist ** 2:
                                too_close = True
                                break

                if not too_close:
                    new_point = (nx_, ny_)
                    points.append(new_point)
                    active.append(new_point)
                    grid[(ci, cj)] = new_point
                    found = True
                    break

            if not found:
                active.pop(idx)

        return points

    def _grid_jitter_sampling(
        self, n: int, width: float, height: float, jitter: float
    ) -> List[Tuple[float, float]]:
        """
        网格抖动采样：在均匀网格上加随机偏移，保证空间分布均匀。
        作为泊松盘采样的后备方案。
        """
        aspect = width / height
        n_cols = max(1, int(math.sqrt(n * aspect)))
        n_rows = max(1, int(n / n_cols))

        dx = width / n_cols
        dy = height / n_rows

        points: List[Tuple[float, float]] = []
        for i in range(n_rows):
            for j in range(n_cols):
                x = (j + 0.5) * dx + random.uniform(-jitter, jitter)
                y = (i + 0.5) * dy + random.uniform(-jitter, jitter)
                x = max(0, min(width - 0.01, x))
                y = max(0, min(height - 0.01, y))
                points.append((x, y))
                if len(points) >= n:
                    break
            if len(points) >= n:
                break

        # 如果网格点数不够，补充随机点
        while len(points) < n:
            points.append((random.uniform(0, width), random.uniform(0, height)))

        return points

    # ------------------------------------------------------------------
    # 步骤 2：从 Delaunay 三角剖分提取边
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_edges_from_delaunay(tri: Delaunay) -> Set[Tuple[int, int]]:
        """
        从 Delaunay 三角剖分结果中提取所有不重复的边。

        Args:
            tri: scipy.spatial.Delaunay 对象。

        Returns:
            边集合，每条边用 (min_id, max_id) 表示。
        """
        edges: Set[Tuple[int, int]] = set()
        for simplex in tri.simplices:
            for i in range(3):
                for j in range(i + 1, 3):
                    u, v = int(simplex[i]), int(simplex[j])
                    edges.add((min(u, v), max(u, v)))
        return edges

    # ------------------------------------------------------------------
    # 步骤 3：最小生成树（Kruskal with Union-Find）
    # ------------------------------------------------------------------

    def _kruskal_mst(self, graph: Graph) -> List[Edge]:
        """
        使用 Kruskal 算法提取最小生成树。

        使用 Union-Find（并查集）实现，时间复杂度 O(E log E)。
        MST 的边集将被保护，不会在稀疏化阶段被删除。
        """
        # 按长度排序所有边
        all_edges = sorted(graph.edges(), key=lambda e: e.length)

        # Union-Find
        parent: Dict[int, int] = {vid: vid for vid in graph.vertex_ids()}
        rank: Dict[int, int] = {vid: 0 for vid in graph.vertex_ids()}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]  # 路径压缩
                x = parent[x]
            return x

        def union(a: int, b: int) -> bool:
            ra, rb = find(a), find(b)
            if ra == rb:
                return False
            if rank[ra] < rank[rb]:
                ra, rb = rb, ra
            parent[rb] = ra
            if rank[ra] == rank[rb]:
                rank[ra] += 1
            return True

        mst: List[Edge] = []
        for edge in all_edges:
            if union(edge.u, edge.v):
                mst.append(edge)
                if len(mst) == graph.vertex_count - 1:
                    break
        return mst

    # ------------------------------------------------------------------
    # 步骤 4：稀疏化
    # ------------------------------------------------------------------

    def _sparsify(self, graph: Graph, mst_edges: Set[Tuple[int, int]]) -> None:
        """
        对图进行稀疏化处理：
        1. 删除过长的边（超过邻域平均边长的 max_edge_length_factor 倍）。
        2. 对超过 max_degree 度的顶点，保留最短的 max_degree 条边。
        3. MST 中的边永远不会被删除（保证连通性）。
        """
        # --- 阶段 A：删除过长边 ---
        # 计算每个顶点邻域的平均边长
        avg_lengths: Dict[int, float] = {}
        for vid in graph.vertex_ids():
            neighbors = graph.get_neighbors(vid)
            if neighbors:
                avg_lengths[vid] = sum(e.length for e in neighbors) / len(neighbors)
            else:
                avg_lengths[vid] = float('inf')

        edges_to_remove: List[Tuple[int, int]] = []
        for edge in graph.edges():
            key = (min(edge.u, edge.v), max(edge.u, edge.v))
            if key in mst_edges:
                continue  # MST 边不删
            avg_local = (avg_lengths.get(edge.u, 0) + avg_lengths.get(edge.v, 0)) / 2
            if edge.length > avg_local * self.max_edge_length_factor:
                edges_to_remove.append((edge.u, edge.v))

        for u, v in edges_to_remove:
            graph.remove_edge(u, v)

        # --- 阶段 B：限制最大度数 ---
        for vid in list(graph.vertex_ids()):
            neighbors = graph.get_neighbors(vid)
            if len(neighbors) <= self.max_degree:
                continue
            # 按边长排序，保留最短的 max_degree 条
            neighbors_sorted = sorted(neighbors, key=lambda e: e.length)
            to_keep = set()
            for e in neighbors_sorted[:self.max_degree]:
                to_keep.add((min(e.u, e.v), max(e.u, e.v)))
            # 保留 MST 边
            for e in neighbors_sorted:
                key = (min(e.u, e.v), max(e.u, e.v))
                if key in mst_edges:
                    to_keep.add(key)

            for e in neighbors_sorted:
                key = (min(e.u, e.v), max(e.u, e.v))
                if key not in to_keep:
                    graph.remove_edge(e.u, e.v)

    # ------------------------------------------------------------------
    # 步骤 5：连通性修复
    # ------------------------------------------------------------------

    def _ensure_connectivity(self, graph: Graph) -> None:
        """
        检查连通性，如果有不连通分量则找最近点对进行连接。

        策略参考 road-network-generator 的 make_connected 方法：
        找到最大分量，然后将其余分量依次连接到最大分量。

        改进：桥接边添加后会进行线段交叉检测，
        如果与已有边交叉则尝试次近点对，避免产生不合理的道路交叉。
        """
        components = graph.connected_components()
        if len(components) <= 1:
            return

        logger.info(f"发现 {len(components)} 个连通分量，开始桥接修复...")

        # 找到最大分量
        main_comp = max(components, key=len)
        main_coords = np.array([
            [graph.get_vertex(vid).x, graph.get_vertex(vid).y]
            for vid in main_comp
        ])
        main_ids = list(main_comp)

        # 收集所有已有边的线段信息，用于交叉检测
        existing_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        for edge in graph.edges():
            vu = graph.get_vertex(edge.u)
            vv = graph.get_vertex(edge.v)
            existing_segments.append(((vu.x, vu.y), (vv.x, vv.y)))

        connected_count = 0
        crossed_count = 0
        for comp in components:
            if comp is main_comp:
                continue

            # 找到 comp 到 main_comp 的最近点对（按距离排序，取多个候选）
            comp_coords = np.array([
                [graph.get_vertex(vid).x, graph.get_vertex(vid).y]
                for vid in comp
            ])
            comp_ids = list(comp)

            # 收集所有候选点对，按距离排序
            candidates: List[Tuple[float, int, int]] = []
            for i, cid in enumerate(comp_ids):
                dists = np.sqrt(
                    (main_coords[:, 0] - comp_coords[i, 0]) ** 2 +
                    (main_coords[:, 1] - comp_coords[i, 1]) ** 2
                )
                # 取每个 comp 点的最近 main 点
                j = int(np.argmin(dists))
                candidates.append((dists[j], cid, main_ids[j]))

            candidates.sort(key=lambda x: x[0])

            # 从最近的候选开始尝试，找到一个不交叉的
            bridge_added = False
            max_attempts = min(len(candidates), 10)  # 最多尝试 10 个候选
            for attempt_idx in range(max_attempts):
                _, best_u, best_v = candidates[attempt_idx]
                vu = graph.get_vertex(best_u)
                vv = graph.get_vertex(best_v)
                new_seg = ((vu.x, vu.y), (vv.x, vv.y))

                # 检测是否与已有边交叉
                has_intersection = False
                for seg in existing_segments:
                    if self._segments_intersect(new_seg[0], new_seg[1], seg[0], seg[1]):
                        has_intersection = True
                        break

                if not has_intersection:
                    length = vu.distance_to(vv)
                    cap = random.randint(*self.capacity_range)
                    graph.add_edge(Edge(u=best_u, v=best_v, length=length, capacity=cap))
                    existing_segments.append(new_seg)
                    bridge_added = True
                    connected_count += 1
                    break
                else:
                    crossed_count += 1

            if not bridge_added:
                # 所有候选都交叉，退而求其次：用最近点对强制连接（保证连通性优先）
                _, best_u, best_v = candidates[0]
                vu = graph.get_vertex(best_u)
                vv = graph.get_vertex(best_v)
                length = vu.distance_to(vv)
                cap = random.randint(*self.capacity_range)
                graph.add_edge(Edge(u=best_u, v=best_v, length=length, capacity=cap))
                existing_segments.append(((vu.x, vu.y), (vv.x, vv.y)))
                connected_count += 1
                logger.warning(
                    f"桥接边 ({best_u}, {best_v}) 无法避免交叉，强制连接以保证连通性"
                )

            # 更新 main_comp 和 main_coords
            main_comp = main_comp | comp
            main_coords = np.vstack([main_coords, comp_coords])
            main_ids.extend(comp_ids)

        if crossed_count > 0:
            logger.info(f"桥接修复完成，连接了 {connected_count} 个分量，"
                        f"避免了 {crossed_count} 次交叉")
        else:
            logger.info(f"桥接修复完成，连接了 {connected_count} 个分量")

    @staticmethod
    def _segments_intersect(
        p1: Tuple[float, float], p2: Tuple[float, float],
        p3: Tuple[float, float], p4: Tuple[float, float],
    ) -> bool:
        """
        检测两条线段 (p1,p2) 和 (p3,p4) 是否严格相交（不含共享端点）。

        使用叉积方向法：
        如果两线段的端点分居对方两侧，则相交。
        共享端点的情况不算交叉（同一路口的两条路连接是合理的）。
        """
        # 共享端点不算交叉
        eps = 1e-9
        if (abs(p1[0]-p3[0]) < eps and abs(p1[1]-p3[1]) < eps) or \
           (abs(p1[0]-p4[0]) < eps and abs(p1[1]-p4[1]) < eps) or \
           (abs(p2[0]-p3[0]) < eps and abs(p2[1]-p3[1]) < eps) or \
           (abs(p2[0]-p4[0]) < eps and abs(p2[1]-p4[1]) < eps):
            return False

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        d1 = cross(p3, p4, p1)
        d2 = cross(p3, p4, p2)
        d3 = cross(p1, p2, p3)
        d4 = cross(p1, p2, p4)

        if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
           ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
            return True

        return False
