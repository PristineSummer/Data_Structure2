"""
graph.py — 图数据结构核心模块

设计思路：
- Vertex: 地图上的一个位置点，携带二维坐标及可选元数据。
- Edge: 两个顶点之间的道路，携带长度、容量、当前车辆数（交通模拟阶段使用）。
- Graph: 基于邻接表的无向图容器，支持增删改查、连通性检查、子图提取等操作。

数据结构选择理由：
    邻接表 dict[int, list[Edge]] 的空间复杂度为 O(V+E)，
    而邻接矩阵在 10000 节点时需要 ~400MB，不可接受。
    邻接表在遍历邻居时也更高效（O(degree) vs O(V)）。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Iterator, Set

from .traffic_model import congestion_level as calculate_congestion_level
from .traffic_model import travel_time as calculate_travel_time


# ---------------------------------------------------------------------------
# Vertex — 图中的顶点
# ---------------------------------------------------------------------------

@dataclass
class Vertex:
    """
    表示地图上的一个位置。

    Attributes:
        id: 顶点的唯一标识符（整数）。
        x:  水平坐标。
        y:  垂直坐标。
        metadata: 可选元数据字典，可用于存储 POI 类型等扩展信息。
    """
    id: int
    x: float
    y: float
    metadata: Dict = field(default_factory=dict)

    def distance_to(self, other: Vertex) -> float:
        """计算与另一个顶点之间的欧氏距离。"""
        return math.hypot(self.x - other.x, self.y - other.y)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Vertex):
            return NotImplemented
        return self.id == other.id

    def __repr__(self) -> str:
        return f"Vertex(id={self.id}, x={self.x:.1f}, y={self.y:.1f})"


# ---------------------------------------------------------------------------
# Edge — 图中的边
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    """
    表示两个顶点之间的一条道路。

    Attributes:
        u: 起始顶点 ID。
        v: 终止顶点 ID。
        length: 道路长度（欧氏距离，固定值）。
        capacity: 道路容量 v_cap —— 饱和前可容纳的最大车辆数（固定值）。
        current_cars: 当前道路上的车辆数 n（动态值，交通模拟阶段更新）。
    """
    u: int
    v: int
    length: float
    capacity: int = 50
    current_cars: int = 0

    def travel_time(self, c: float = 1.0, threshold: float = 0.8) -> float:
        """
        根据题目公式计算通行时间：
            t = c * L * f(n / v)
        其中 f(x) = 1 当 x <= threshold, f(x) = 1 + e^x 当 x > threshold。

        Args:
            c: 常数因子。
            threshold: 拥堵阈值。

        Returns:
            通行时间（浮点数）。
        """
        return calculate_travel_time(
            self.length,
            self.capacity,
            self.current_cars,
            c=c,
            threshold=threshold,
        )

    def congestion_level(self) -> int:
        """
        返回拥堵等级（0-3），供 GUI 渲染颜色：
            0 (绿色): ratio <= 0.3 畅通
            1 (黄色): 0.3 < ratio <= 0.7 缓行
            2 (橙色): 0.7 < ratio <= 1.0 拥堵
            3 (红色): ratio > 1.0 严重拥堵
        """
        return calculate_congestion_level(self.current_cars, self.capacity)

    def other(self, vertex_id: int) -> int:
        """给定一端的顶点 ID，返回另一端的顶点 ID。"""
        if vertex_id == self.u:
            return self.v
        elif vertex_id == self.v:
            return self.u
        else:
            raise ValueError(f"Vertex {vertex_id} is not an endpoint of edge ({self.u}, {self.v})")

    def __hash__(self) -> int:
        return hash((min(self.u, self.v), max(self.u, self.v)))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Edge):
            return NotImplemented
        return (min(self.u, self.v), max(self.u, self.v)) == (min(other.u, other.v), max(other.u, other.v))

    def __repr__(self) -> str:
        return f"Edge({self.u} <-> {self.v}, len={self.length:.1f}, cap={self.capacity})"


# ---------------------------------------------------------------------------
# Graph — 基于邻接表的无向图
# ---------------------------------------------------------------------------

class Graph:
    """
    基于邻接表的无向图。

    内部存储：
        _vertices: dict[int, Vertex]         —— 顶点 ID → Vertex 对象
        _adj:      dict[int, list[Edge]]      —— 邻接表，每个顶点对应一组 Edge
        _edge_set: set[tuple[int, int]]       —— 边的去重集合 (min_id, max_id)

    时间复杂度（主要操作）：
        add_vertex:     O(1)
        add_edge:       O(1) amortized
        get_neighbors:  O(degree)
        get_edge:       O(degree)  —— 可以考虑在后续阶段用 dict 优化到 O(1)
        remove_edge:    O(degree)
        vertex_count:   O(1)
        edge_count:     O(1)
    """

    def __init__(self) -> None:
        self._vertices: Dict[int, Vertex] = {}
        self._adj: Dict[int, List[Edge]] = {}
        self._edge_set: Set[Tuple[int, int]] = set()
        self._edge_count: int = 0
        # 地图元数据
        self.width: float = 0.0
        self.height: float = 0.0
        self.seed: Optional[int] = None

    # ---- 顶点操作 ----

    def add_vertex(self, vertex: Vertex) -> None:
        """添加一个顶点。如果 ID 已存在则覆盖。"""
        self._vertices[vertex.id] = vertex
        if vertex.id not in self._adj:
            self._adj[vertex.id] = []

    def get_vertex(self, vertex_id: int) -> Optional[Vertex]:
        """根据 ID 获取顶点，不存在返回 None。"""
        return self._vertices.get(vertex_id)

    def has_vertex(self, vertex_id: int) -> bool:
        return vertex_id in self._vertices

    def remove_vertex(self, vertex_id: int) -> None:
        """删除一个顶点及其所有关联边。"""
        if vertex_id not in self._vertices:
            return
        # 删除所有关联边
        edges_to_remove = list(self._adj.get(vertex_id, []))
        for edge in edges_to_remove:
            self.remove_edge(edge.u, edge.v)
        del self._vertices[vertex_id]
        if vertex_id in self._adj:
            del self._adj[vertex_id]

    @property
    def vertex_count(self) -> int:
        return len(self._vertices)

    @property
    def edge_count(self) -> int:
        return self._edge_count

    def vertices(self) -> Iterator[Vertex]:
        """迭代所有顶点。"""
        return iter(self._vertices.values())

    def vertex_ids(self) -> Iterator[int]:
        """迭代所有顶点 ID。"""
        return iter(self._vertices.keys())

    # ---- 边操作 ----

    def add_edge(self, edge: Edge) -> None:
        """
        添加一条无向边。如果边已存在则跳过。
        要求两端顶点都已添加到图中，且不能是自环。
        """
        if edge.u == edge.v:
            raise ValueError(f"Self-loop not allowed: vertex {edge.u}")
        key = (min(edge.u, edge.v), max(edge.u, edge.v))
        if key in self._edge_set:
            return  # 边已存在
        if edge.u not in self._vertices or edge.v not in self._vertices:
            raise ValueError(
                f"Cannot add edge ({edge.u}, {edge.v}): "
                f"both vertices must exist in the graph first."
            )
        self._edge_set.add(key)
        self._adj[edge.u].append(edge)
        self._adj[edge.v].append(edge)
        self._edge_count += 1

    def has_edge(self, u: int, v: int) -> bool:
        key = (min(u, v), max(u, v))
        return key in self._edge_set

    def get_edge(self, u: int, v: int) -> Optional[Edge]:
        """获取两顶点之间的边，不存在返回 None。"""
        if not self.has_edge(u, v):
            return None
        for edge in self._adj.get(u, []):
            if edge.other(u) == v:
                return edge
        return None

    def remove_edge(self, u: int, v: int) -> None:
        """删除一条边。"""
        key = (min(u, v), max(u, v))
        if key not in self._edge_set:
            return
        self._edge_set.remove(key)
        self._adj[u] = [e for e in self._adj[u] if not (e.other(u) == v)]
        self._adj[v] = [e for e in self._adj[v] if not (e.other(v) == u)]
        self._edge_count -= 1

    def get_neighbors(self, vertex_id: int) -> List[Edge]:
        """获取指定顶点的所有邻接边。"""
        return list(self._adj.get(vertex_id, []))

    def get_neighbor_ids(self, vertex_id: int) -> List[int]:
        """获取指定顶点的所有邻居 ID。"""
        return [e.other(vertex_id) for e in self._adj.get(vertex_id, [])]

    def degree(self, vertex_id: int) -> int:
        """获取顶点的度。"""
        return len(self._adj.get(vertex_id, []))

    def edges(self) -> Iterator[Edge]:
        """迭代所有边（每条边只返回一次）。"""
        seen: Set[Tuple[int, int]] = set()
        for vertex_id, edge_list in self._adj.items():
            for edge in edge_list:
                key = (min(edge.u, edge.v), max(edge.u, edge.v))
                if key not in seen:
                    seen.add(key)
                    yield edge

    # ---- 连通性检查 ----

    def is_connected(self) -> bool:
        """
        使用 BFS 检查图是否连通。
        时间复杂度: O(V + E)
        """
        if self.vertex_count == 0:
            return True
        start = next(iter(self._vertices))
        visited = set()
        queue = deque([start])
        visited.add(start)
        while queue:
            current = queue.popleft()  # O(1)，原 list.pop(0) 是 O(n)
            for edge in self._adj.get(current, []):
                neighbor = edge.other(current)
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return len(visited) == self.vertex_count

    def connected_components(self) -> List[Set[int]]:
        """
        使用 BFS 找出所有连通分量。
        返回每个分量的顶点 ID 集合列表。
        """
        visited: Set[int] = set()
        components: List[Set[int]] = []
        for vid in self._vertices:
            if vid in visited:
                continue
            component: Set[int] = set()
            queue = deque([vid])
            component.add(vid)
            visited.add(vid)
            while queue:
                current = queue.popleft()  # O(1)，原 list.pop(0) 是 O(n)
                for edge in self._adj.get(current, []):
                    neighbor = edge.other(current)
                    if neighbor not in visited:
                        visited.add(neighbor)
                        component.add(neighbor)
                        queue.append(neighbor)
            components.append(component)
        return components

    # ---- 子图提取 ----

    def subgraph(self, vertex_ids: Set[int]) -> Graph:
        """
        提取包含指定顶点集合的子图（包含这些顶点之间的所有边）。
        """
        sub = Graph()
        sub.width = self.width
        sub.height = self.height
        for vid in vertex_ids:
            v = self.get_vertex(vid)
            if v is not None:
                sub.add_vertex(v)
        for edge in self.edges():
            if edge.u in vertex_ids and edge.v in vertex_ids:
                sub.add_edge(edge)
        return sub

    # ---- 统计信息 ----

    def stats(self) -> Dict:
        """返回图的统计摘要信息。"""
        degrees = [self.degree(vid) for vid in self._vertices]
        if not degrees:
            return {"vertices": 0, "edges": 0}
        return {
            "vertices": self.vertex_count,
            "edges": self.edge_count,
            "min_degree": min(degrees),
            "max_degree": max(degrees),
            "avg_degree": sum(degrees) / len(degrees),
            "connected": self.is_connected(),
        }

    def __repr__(self) -> str:
        return f"Graph(V={self.vertex_count}, E={self.edge_count})"

    def __contains__(self, vertex_id: int) -> bool:
        return vertex_id in self._vertices

    def __len__(self) -> int:
        return self.vertex_count
