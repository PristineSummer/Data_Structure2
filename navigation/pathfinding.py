"""
pathfinding.py — 最短路径算法模块

实现两种最短路径算法：
    1. Dijkstra —— 基于最小堆（优先队列）的经典最短路径算法
    2. A*       —— 在 Dijkstra 基础上增加启发式函数，加速搜索

设计要点：
    - 权重函数参数化（策略模式）：通过 weight_func 参数支持：
        - 静态权重：边的欧氏距离（F3 最短路径）
        - 动态权重：基于当前交通状况的通行时间（F5 交通感知最短路径）
    - 返回 PathResult 结构，包含完整路径、经过的边、搜索统计信息。
    - Dijkstra 和 A* 共享接口签名，方便 GUI 层切换算法。

时间复杂度：
    Dijkstra: O((V + E) log V)  —— 使用二叉堆
    A*:       最坏 O((V + E) log V)，实际远优于 Dijkstra

参考：Smart-Traffic-Routing-System 项目的 algorithms.py（Dijkstra 结构）。
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .graph import Vertex, Edge, Graph


# ---------------------------------------------------------------------------
# PathResult — 路径搜索结果
# ---------------------------------------------------------------------------

@dataclass
class PathResult:
    """
    路径搜索的结果。

    Attributes:
        found:          是否找到路径。
        distance:       路径总权重（距离或通行时间）。
        path:           路径上的顶点 ID 序列。
        edges:          路径上经过的边列表。
        nodes_visited:  搜索过程中访问过的节点数（用于性能对比）。
        elapsed_ms:     搜索耗时（毫秒）。
        algorithm:      使用的算法名称。
        visited:        可选搜索动画轨迹：节点弹出顺序。
        relaxed_edges:  可选搜索动画轨迹：成功松弛的边。
        trace_truncated: 搜索轨迹是否因 max_trace 截断。
    """
    found: bool = False
    distance: float = float('inf')
    path: List[int] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    nodes_visited: int = 0
    elapsed_ms: float = 0.0
    algorithm: str = ""
    visited: List[int] = field(default_factory=list)
    relaxed_edges: List[Tuple[int, int]] = field(default_factory=list)
    trace_truncated: bool = False

    def __repr__(self) -> str:
        if not self.found:
            return f"PathResult(not found, algo={self.algorithm})"
        return (
            f"PathResult(dist={self.distance:.2f}, "
            f"hops={len(self.path)-1}, "
            f"visited={self.nodes_visited}, "
            f"{self.elapsed_ms:.1f}ms, "
            f"algo={self.algorithm})"
        )


# ---------------------------------------------------------------------------
# 权重函数类型
# ---------------------------------------------------------------------------

# weight_func(edge) -> float
# 默认返回边的欧氏距离长度
WeightFunc = Callable[[Edge], float]


def default_weight(edge: Edge) -> float:
    """默认权重函数：返回边的欧氏距离。"""
    return edge.length


def make_traffic_weight(c: float = 1.0, threshold: float = 0.8) -> WeightFunc:
    """
    工厂函数：创建交通感知权重函数。

    返回一个符合 WeightFunc 签名的闭包，封装 c 和 threshold 参数。
    这比直接带默认参数的函数更符合策略模式设计意图，
    也避免了需要 lambda 或 functools.partial 的问题。

    Args:
        c: 通行时间公式中的常数因子。
        threshold: 拥堵阈值（n/v 超过此值时通行时间指数增长）。

    Returns:
        WeightFunc: 一个 edge -> float 的权重函数。

    Usage:
        weight_fn = make_traffic_weight(c=1.0, threshold=0.8)
        result = dijkstra(graph, start, end, weight_func=weight_fn)
    """
    def weight_func(edge: Edge) -> float:
        return edge.travel_time(c=c, threshold=threshold)
    return weight_func


# ---------------------------------------------------------------------------
# Dijkstra 最短路径
# ---------------------------------------------------------------------------

def dijkstra(
    graph: Graph,
    start_id: int,
    end_id: int,
    weight_func: WeightFunc = default_weight,
    *,
    trace: bool = False,
    max_trace: int = 2500,
) -> PathResult:
    """
    使用 Dijkstra 算法查找从 start_id 到 end_id 的最短路径。

    算法流程：
        1. 初始化：所有顶点距离设为 +∞，起点距离设为 0。
        2. 将 (0, start_id) 推入最小堆。
        3. 每次从堆中弹出距离最小的节点 u：
           a. 如果 u == end_id，搜索结束。
           b. 对 u 的每个邻居 v，如果经过 u 到 v 的距离更短，更新 v 的距离并入堆。
        4. 通过前驱节点映射回溯路径。

    Args:
        graph:       图对象。
        start_id:    起点顶点 ID。
        end_id:      终点顶点 ID。
        weight_func: 权重函数，默认使用边的欧氏距离。

    Returns:
        PathResult 对象。

    时间复杂度: O((V + E) log V)
    空间复杂度: O(V)
    """
    t_start = time.perf_counter()

    result = PathResult(algorithm="dijkstra")
    max_trace = max(0, int(max_trace))

    # 验证起终点
    if not graph.has_vertex(start_id) or not graph.has_vertex(end_id):
        result.elapsed_ms = (time.perf_counter() - t_start) * 1000
        return result

    # 起终点相同
    if start_id == end_id:
        result.found = True
        result.distance = 0.0
        result.path = [start_id]
        result.nodes_visited = 1
        _record_visit(result, start_id, trace, max_trace)
        result.elapsed_ms = (time.perf_counter() - t_start) * 1000
        return result

    # 距离表和前驱表
    dist: Dict[int, float] = {start_id: 0.0}
    prev: Dict[int, int] = {}      # prev[v] = u，表示最短路径中 v 的前驱是 u
    prev_edge: Dict[int, Edge] = {}  # prev_edge[v] = 从 prev[v] 到 v 的边

    # 最小堆：(距离, 顶点 ID)
    # 使用 counter 打破距离相同时的比较
    counter = 0
    heap: List[Tuple[float, int, int]] = [(0.0, counter, start_id)]

    visited = set()
    nodes_visited = 0

    while heap:
        d, _, u = heapq.heappop(heap)

        if u in visited:
            continue
        visited.add(u)
        nodes_visited += 1
        _record_visit(result, u, trace, max_trace)

        # 到达终点
        if u == end_id:
            # 回溯路径
            path = _reconstruct_path(prev, start_id, end_id)
            edges = _reconstruct_edges(prev_edge, path)
            result.found = True
            result.distance = d
            result.path = path
            result.edges = edges
            result.nodes_visited = nodes_visited
            result.elapsed_ms = (time.perf_counter() - t_start) * 1000
            return result

        # 松弛邻居
        for edge in graph.get_neighbors(u):
            v = edge.other(u)
            if v in visited:
                continue

            w = weight_func(edge)
            new_dist = d + w

            if v not in dist or new_dist < dist[v]:
                dist[v] = new_dist
                prev[v] = u
                prev_edge[v] = edge
                _record_relaxed_edge(result, u, v, trace, max_trace)
                counter += 1
                heapq.heappush(heap, (new_dist, counter, v))

    # 未找到路径
    result.nodes_visited = nodes_visited
    result.elapsed_ms = (time.perf_counter() - t_start) * 1000
    return result


# ---------------------------------------------------------------------------
# A* 最短路径
# ---------------------------------------------------------------------------

def astar(
    graph: Graph,
    start_id: int,
    end_id: int,
    weight_func: WeightFunc = default_weight,
    *,
    trace: bool = False,
    max_trace: int = 2500,
) -> PathResult:
    """
    使用 A* 算法查找从 start_id 到 end_id 的最短路径。

    A* 是 Dijkstra 的优化版本，通过启发式函数 h(n) 引导搜索方向：
        f(n) = g(n) + h(n)
    其中：
        g(n) = 从起点到 n 的实际距离
        h(n) = 从 n 到终点的启发式估计（欧氏距离）

    启发式函数选择欧氏距离的理由：
        - Admissible（可容许）：欧氏距离 ≤ 实际最短路径距离，不会高估。
        - Consistent（一致性）：h(u) ≤ cost(u,v) + h(v)，满足三角不等式。
        - 这两个性质保证 A* 找到的路径是最优的。

    Args:
        graph:       图对象。
        start_id:    起点顶点 ID。
        end_id:      终点顶点 ID。
        weight_func: 权重函数，默认使用边的欧氏距离。

    Returns:
        PathResult 对象。

    时间复杂度: 最坏 O((V + E) log V)，实际远优于 Dijkstra
    空间复杂度: O(V)
    """
    t_start = time.perf_counter()

    result = PathResult(algorithm="astar")
    max_trace = max(0, int(max_trace))

    if not graph.has_vertex(start_id) or not graph.has_vertex(end_id):
        result.elapsed_ms = (time.perf_counter() - t_start) * 1000
        return result

    if start_id == end_id:
        result.found = True
        result.distance = 0.0
        result.path = [start_id]
        result.nodes_visited = 1
        _record_visit(result, start_id, trace, max_trace)
        result.elapsed_ms = (time.perf_counter() - t_start) * 1000
        return result

    # 获取终点坐标用于启发式计算
    end_vertex = graph.get_vertex(end_id)
    end_x, end_y = end_vertex.x, end_vertex.y

    def heuristic(vid: int) -> float:
        """启发式函数：到终点的欧氏距离。"""
        vertex = graph.get_vertex(vid)
        if vertex is None:
            return float("inf")
        return math.hypot(vertex.x - end_x, vertex.y - end_y)

    # g 值：从起点到各节点的实际距离
    g_score: Dict[int, float] = {start_id: 0.0}
    prev: Dict[int, int] = {}
    prev_edge: Dict[int, Edge] = {}

    # 最小堆：(f = g + h, counter, vertex_id)
    counter = 0
    h_start = heuristic(start_id)
    heap: List[Tuple[float, int, int]] = [(h_start, counter, start_id)]

    visited = set()
    nodes_visited = 0

    while heap:
        f, _, u = heapq.heappop(heap)

        if u in visited:
            continue
        visited.add(u)
        nodes_visited += 1
        _record_visit(result, u, trace, max_trace)

        if u == end_id:
            path = _reconstruct_path(prev, start_id, end_id)
            edges = _reconstruct_edges(prev_edge, path)
            result.found = True
            result.distance = g_score[u]
            result.path = path
            result.edges = edges
            result.nodes_visited = nodes_visited
            result.elapsed_ms = (time.perf_counter() - t_start) * 1000
            return result

        g_u = g_score.get(u, float('inf'))

        for edge in graph.get_neighbors(u):
            v = edge.other(u)
            if v in visited:
                continue

            w = weight_func(edge)
            tentative_g = g_u + w

            if v not in g_score or tentative_g < g_score[v]:
                g_score[v] = tentative_g
                prev[v] = u
                prev_edge[v] = edge
                _record_relaxed_edge(result, u, v, trace, max_trace)
                f_v = tentative_g + heuristic(v)
                counter += 1
                heapq.heappush(heap, (f_v, counter, v))

    result.nodes_visited = nodes_visited
    result.elapsed_ms = (time.perf_counter() - t_start) * 1000
    return result


# ---------------------------------------------------------------------------
# 统一接口
# ---------------------------------------------------------------------------

def shortest_path(
    graph: Graph,
    start_id: int,
    end_id: int,
    algorithm: str = "astar",
    weight_func: WeightFunc = default_weight,
    *,
    trace: bool = False,
    max_trace: int = 2500,
) -> PathResult:
    """
    统一的最短路径接口，支持选择算法。

    Args:
        graph:       图对象。
        start_id:    起点顶点 ID。
        end_id:      终点顶点 ID。
        algorithm:   算法名称，"dijkstra" 或 "astar"。
        weight_func: 权重函数。

    Returns:
        PathResult 对象。
    """
    if algorithm == "dijkstra":
        return dijkstra(graph, start_id, end_id, weight_func, trace=trace, max_trace=max_trace)
    elif algorithm == "astar":
        return astar(graph, start_id, end_id, weight_func, trace=trace, max_trace=max_trace)
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}. Use 'dijkstra' or 'astar'.")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _record_visit(result: PathResult, vertex_id: int, trace: bool, max_trace: int) -> None:
    """Record one popped node for GUI animation when tracing is enabled."""
    if not trace:
        return
    if len(result.visited) < max_trace:
        result.visited.append(vertex_id)
    else:
        result.trace_truncated = True


def _record_relaxed_edge(result: PathResult, u: int, v: int, trace: bool, max_trace: int) -> None:
    """Record one successful relaxation edge for GUI animation."""
    if not trace:
        return
    if len(result.relaxed_edges) < max_trace:
        result.relaxed_edges.append((u, v))
    else:
        result.trace_truncated = True

def _reconstruct_path(prev: Dict[int, int], start: int, end: int) -> List[int]:
    """从前驱表回溯路径。"""
    path = [end]
    current = end
    while current != start:
        current = prev[current]
        path.append(current)
    path.reverse()
    return path


def _reconstruct_edges(prev_edge: Dict[int, Edge], path: List[int]) -> List[Edge]:
    """从路径中提取经过的边列表。"""
    edges = []
    for i in range(1, len(path)):
        vid = path[i]
        if vid in prev_edge:
            edges.append(prev_edge[vid])
    return edges
