"""
test_phase2.py — 阶段二单元测试

测试内容：
    1. KD-Tree 基本操作（建树、K 最近邻、范围查询、代表点查询）
    2. KD-Tree 正确性验证（与暴力搜索、scipy.spatial.KDTree 对比）
    3. Dijkstra 算法（正确性、边界情况、路径回溯）
    4. A* 算法（正确性、最优性、搜索效率对比）
    5. 大规模性能基准测试（10000 节点图上的查询/搜索性能）

运行方式：
    python -X utf8 test_phase2.py
"""

import os
import sys
import time
import math
import random
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from navigation.graph import Vertex, Edge, Graph
from navigation.map_generator import MapGenerator
from navigation.kdtree import KDTree
from navigation.pathfinding import (
    dijkstra, astar, shortest_path, default_weight, make_traffic_weight, PathResult,
)
from navigation.engine import NavigationEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


# ====================================================================
# 辅助函数
# ====================================================================

def make_small_graph() -> Graph:
    """创建一个 5 节点的小图用于精确测试。

    布局:
        0(0,0) --1-- 1(1,0) --1-- 2(2,0)
          |                         |
          2                         2
          |                         |
        3(0,2) --------3---------- 4(2,2)
    """
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 1.0, 0.0))
    g.add_vertex(Vertex(2, 2.0, 0.0))
    g.add_vertex(Vertex(3, 0.0, 2.0))
    g.add_vertex(Vertex(4, 2.0, 2.0))

    g.add_edge(Edge(0, 1, length=1.0))
    g.add_edge(Edge(1, 2, length=1.0))
    g.add_edge(Edge(0, 3, length=2.0))
    g.add_edge(Edge(2, 4, length=2.0))
    g.add_edge(Edge(3, 4, length=3.0))
    return g


def make_disconnected_graph() -> Graph:
    """创建一个不连通的图。"""
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 1.0, 0.0))
    g.add_vertex(Vertex(2, 10.0, 10.0))
    g.add_edge(Edge(0, 1, length=1.0))
    # 节点 2 是孤立的
    return g


# ====================================================================
# 测试 1：KD-Tree 基本操作
# ====================================================================

def test_kdtree_build():
    """测试 KD-Tree 建树。"""
    g = make_small_graph()
    tree = KDTree()
    tree.build(g)
    assert tree.size == 5
    print("  ✓ test_kdtree_build")


def test_kdtree_nearest():
    """测试最近邻查询。"""
    g = make_small_graph()
    tree = KDTree()
    tree.build(g)

    # 查询 (0.1, 0.1) 应该最近的是 (0,0)
    result = tree.query_nearest(0.1, 0.1)
    assert result is not None
    assert result[1].id == 0

    # 查询 (1.9, 1.9) 应该最近的是 (2,2)
    result2 = tree.query_nearest(1.9, 1.9)
    assert result2 is not None
    assert result2[1].id == 4

    print("  ✓ test_kdtree_nearest")


def test_kdtree_knn():
    """测试 K 最近邻查询。"""
    g = make_small_graph()
    tree = KDTree()
    tree.build(g)

    # 查询 (1,1) 最近的 3 个点
    results = tree.query_k_nearest(1.0, 1.0, k=3)
    assert len(results) == 3

    # 结果应按距离升序排列
    for i in range(len(results) - 1):
        assert results[i][0] <= results[i + 1][0]

    # (1,0) 距离 = 1.0, (0,0) 距离 = √2, (2,0) 距离 = √2
    assert results[0][1].id == 1  # 最近的是 (1,0)

    print("  ✓ test_kdtree_knn")


def test_kdtree_knn_all():
    """测试 K 大于总数时返回所有点。"""
    g = make_small_graph()
    tree = KDTree()
    tree.build(g)

    results = tree.query_k_nearest(0.0, 0.0, k=100)
    assert len(results) == 5  # 只有 5 个点
    print("  ✓ test_kdtree_knn_all")


def test_kdtree_range():
    """测试矩形范围查询。"""
    g = make_small_graph()
    tree = KDTree()
    tree.build(g)

    # 范围 [0,0] ~ [1.5, 0.5] 应包含 (0,0) 和 (1,0)
    results = tree.query_range(0.0, -0.5, 1.5, 0.5)
    ids = {v.id for v in results}
    assert ids == {0, 1}

    # 全范围应包含所有点
    all_pts = tree.query_range(-1, -1, 3, 3)
    assert len(all_pts) == 5

    # 空范围
    empty = tree.query_range(10, 10, 11, 11)
    assert len(empty) == 0

    print("  ✓ test_kdtree_range")


def test_kdtree_representative():
    """测试代表点查询。"""
    # 创建 100 个均匀分布的点
    g = Graph()
    for i in range(100):
        g.add_vertex(Vertex(i, float(i % 10), float(i // 10)))

    tree = KDTree()
    tree.build(g)

    # 将整个区域分成 5x5 网格，应返回 ~25 个代表点
    reps = tree.query_representative(0, 0, 10, 10, grid_cols=5, grid_rows=5)
    # 每个非空网格有一个代表点
    assert 20 <= len(reps) <= 25
    print(f"  ✓ test_kdtree_representative: {len(reps)} 个代表点")


# ====================================================================
# 测试 2：KD-Tree 正确性验证（与暴力搜索对比）
# ====================================================================

def test_kdtree_knn_vs_brute_force():
    """对比 KD-Tree KNN 与暴力搜索的结果一致性。"""
    random.seed(42)
    g = Graph()
    n = 500
    for i in range(n):
        g.add_vertex(Vertex(i, random.uniform(0, 100), random.uniform(0, 100)))

    tree = KDTree()
    tree.build(g)

    # 测试 20 个随机查询点
    for _ in range(20):
        qx = random.uniform(0, 100)
        qy = random.uniform(0, 100)
        k = 10

        # KD-Tree 查询
        kd_results = tree.query_k_nearest(qx, qy, k)

        # 暴力搜索
        all_dists = []
        for v in g.vertices():
            d = math.hypot(v.x - qx, v.y - qy)
            all_dists.append((d, v.id))
        all_dists.sort()
        brute_ids = [vid for _, vid in all_dists[:k]]

        # 对比结果
        kd_ids = [v.id for _, v in kd_results]
        assert set(kd_ids) == set(brute_ids), (
            f"KNN 不一致: KD={kd_ids}, Brute={brute_ids}"
        )

    print("  ✓ test_kdtree_knn_vs_brute_force (20 queries, k=10)")


def test_kdtree_knn_vs_scipy():
    """对比 KD-Tree KNN 与 scipy.spatial.KDTree 的结果一致性。"""
    try:
        from scipy.spatial import KDTree as ScipyKDTree
        import numpy as np
    except ImportError:
        print("  ~ test_kdtree_knn_vs_scipy: scipy 不可用，跳过")
        return

    random.seed(123)
    n = 2000
    g = Graph()
    coords = []
    for i in range(n):
        x = random.uniform(0, 500)
        y = random.uniform(0, 500)
        g.add_vertex(Vertex(i, x, y))
        coords.append([x, y])

    # 构建两种树
    my_tree = KDTree()
    my_tree.build(g)
    scipy_tree = ScipyKDTree(np.array(coords))

    # 测试 30 个查询
    mismatch = 0
    for _ in range(30):
        qx = random.uniform(0, 500)
        qy = random.uniform(0, 500)
        k = 20

        my_results = my_tree.query_k_nearest(qx, qy, k)
        my_ids = set(v.id for _, v in my_results)

        dists, indices = scipy_tree.query([qx, qy], k=k)
        scipy_ids = set(int(i) for i in indices)

        if my_ids != scipy_ids:
            mismatch += 1

    assert mismatch == 0, f"与 scipy 不一致 {mismatch}/30 次"
    print("  ✓ test_kdtree_knn_vs_scipy (30 queries, k=20)")


# ====================================================================
# 测试 3：Dijkstra 算法
# ====================================================================

def test_dijkstra_basic():
    """测试基本最短路径。"""
    g = make_small_graph()
    result = dijkstra(g, 0, 2)
    assert result.found
    assert abs(result.distance - 2.0) < 1e-10  # 0->1->2, 1+1=2
    assert result.path == [0, 1, 2]
    assert len(result.edges) == 2
    print(f"  ✓ test_dijkstra_basic: dist={result.distance}, path={result.path}")


def test_dijkstra_longer_path():
    """测试需要绕路的最短路径。"""
    g = make_small_graph()
    result = dijkstra(g, 0, 4)
    # 0->1->2->4 = 1+1+2 = 4
    # 0->3->4 = 2+3 = 5
    assert result.found
    assert abs(result.distance - 4.0) < 1e-10
    assert result.path == [0, 1, 2, 4]
    print(f"  ✓ test_dijkstra_longer_path: dist={result.distance}, path={result.path}")


def test_dijkstra_same_start_end():
    """测试起终点相同。"""
    g = make_small_graph()
    result = dijkstra(g, 0, 0)
    assert result.found
    assert result.distance == 0.0
    assert result.path == [0]
    print("  ✓ test_dijkstra_same_start_end")


def test_dijkstra_no_path():
    """测试不可达的情况。"""
    g = make_disconnected_graph()
    result = dijkstra(g, 0, 2)
    assert not result.found
    assert result.distance == float('inf')
    print("  ✓ test_dijkstra_no_path")


def test_dijkstra_nonexistent_vertex():
    """测试不存在的顶点。"""
    g = make_small_graph()
    result = dijkstra(g, 0, 999)
    assert not result.found
    print("  ✓ test_dijkstra_nonexistent_vertex")


def test_dijkstra_with_traffic():
    """测试使用交通权重的 Dijkstra。"""
    g = make_small_graph()

    # 给 0->1 的边设置高交通量，使其变慢
    e01 = g.get_edge(0, 1)
    e01.capacity = 10
    e01.current_cars = 9  # ratio = 0.9 > 0.8 threshold

    result_static = dijkstra(g, 0, 4, weight_func=default_weight)
    traffic_wf = make_traffic_weight(c=1.0, threshold=0.8)
    result_traffic = dijkstra(g, 0, 4, weight_func=traffic_wf)

    # 静态路径还是 0->1->2->4
    assert result_static.path == [0, 1, 2, 4]

    # 交通感知路径应该避开拥堵的 0->1，走 0->3->4
    assert result_traffic.found
    # 由于 0->1 边通行时间大幅增加（指数级），走 0->3->4 更快
    assert result_traffic.path == [0, 3, 4], (
        f"交通感知路径应避开拥堵: {result_traffic.path}"
    )
    print(f"  ✓ test_dijkstra_with_traffic: "
          f"static={result_static.path}, traffic={result_traffic.path}")


# ====================================================================
# 测试 4：A* 算法
# ====================================================================

def test_astar_basic():
    """测试 A* 基本最短路径。"""
    g = make_small_graph()
    result = astar(g, 0, 2)
    assert result.found
    assert abs(result.distance - 2.0) < 1e-10
    assert result.path == [0, 1, 2]
    print(f"  ✓ test_astar_basic: dist={result.distance}, path={result.path}")


def test_astar_optimality():
    """测试 A* 与 Dijkstra 结果一致性（最优性验证）。"""
    g = make_small_graph()

    for start in range(5):
        for end in range(5):
            if start == end:
                continue
            rd = dijkstra(g, start, end)
            ra = astar(g, start, end)
            assert abs(rd.distance - ra.distance) < 1e-10, (
                f"A* 与 Dijkstra 距离不一致: {start}->{end}, "
                f"Dijkstra={rd.distance}, A*={ra.distance}"
            )
    print("  ✓ test_astar_optimality (所有点对)")


def test_astar_efficiency():
    """测试 A* 比 Dijkstra 访问更少的节点。"""
    # 在大图上 A* 应该访问更少的节点
    gen = MapGenerator()
    g = gen.generate(n_vertices=2000, width=1000, height=1000, seed=42)

    # 选择距离较远的起终点
    start_id = 0
    end_id = g.vertex_count - 1

    rd = dijkstra(g, start_id, end_id)
    ra = astar(g, start_id, end_id)

    assert rd.found and ra.found
    assert abs(rd.distance - ra.distance) < 1e-6  # 距离相同

    print(f"  ✓ test_astar_efficiency: "
          f"Dijkstra visited={rd.nodes_visited}, "
          f"A* visited={ra.nodes_visited}, "
          f"ratio={ra.nodes_visited/rd.nodes_visited:.1%}")

    # A* 应该访问更少或相同的节点
    assert ra.nodes_visited <= rd.nodes_visited * 1.05  # 允许 5% 误差


def test_shortest_path_interface():
    """测试统一接口。"""
    g = make_small_graph()

    rd = shortest_path(g, 0, 2, algorithm="dijkstra")
    ra = shortest_path(g, 0, 2, algorithm="astar")

    assert rd.found and ra.found
    assert rd.algorithm == "dijkstra"
    assert ra.algorithm == "astar"
    assert abs(rd.distance - ra.distance) < 1e-10

    # 测试无效算法名
    try:
        shortest_path(g, 0, 2, algorithm="invalid")
        assert False, "应该抛出 ValueError"
    except ValueError:
        pass

    print("  ✓ test_shortest_path_interface")


# ====================================================================
# 测试 5：大规模性能基准测试
# ====================================================================

def test_performance_kdtree_build():
    """测试 10000 点 KD-Tree 建树性能。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=10000, width=2000, height=1500, seed=2026)

    t_start = time.time()
    tree = KDTree()
    tree.build(g)
    t_elapsed = time.time() - t_start

    assert tree.size == 10000
    print(f"  ✓ test_performance_kdtree_build: {t_elapsed*1000:.1f}ms")
    assert t_elapsed < 1.0, f"建树过慢: {t_elapsed:.2f}s"


def test_performance_kdtree_knn():
    """测试 10000 点 KD-Tree 100-最近邻查询性能。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=10000, width=2000, height=1500, seed=2026)

    tree = KDTree()
    tree.build(g)

    # 执行 100 次查询取平均
    random.seed(99)
    total_time = 0
    for _ in range(100):
        qx = random.uniform(0, 2000)
        qy = random.uniform(0, 1500)
        t_start = time.perf_counter()
        results = tree.query_k_nearest(qx, qy, k=100)
        total_time += time.perf_counter() - t_start
        assert len(results) == 100

    avg_ms = (total_time / 100) * 1000
    print(f"  ✓ test_performance_kdtree_knn: avg={avg_ms:.2f}ms/query")
    assert avg_ms < 10.0, f"KNN 查询过慢: {avg_ms:.2f}ms > 10ms"


def test_performance_kdtree_range():
    """测试 10000 点 KD-Tree 范围查询性能。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=10000, width=2000, height=1500, seed=2026)

    tree = KDTree()
    tree.build(g)

    # 查询一个中等大小的范围（约 1/4 的面积）
    t_start = time.perf_counter()
    results = tree.query_range(500, 375, 1500, 1125)
    t_elapsed = (time.perf_counter() - t_start) * 1000

    # 应包含约 1/4 的点
    assert 1500 < len(results) < 4500
    print(f"  ✓ test_performance_kdtree_range: {len(results)} pts, {t_elapsed:.2f}ms")
    assert t_elapsed < 50.0


def test_performance_dijkstra():
    """测试 10000 点图上的 Dijkstra 性能。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=10000, width=2000, height=1500, seed=2026)

    # 选择远距离的起终点
    random.seed(42)
    times = []
    for _ in range(10):
        start = random.randint(0, 9999)
        end = random.randint(0, 9999)
        result = dijkstra(g, start, end)
        if result.found:
            times.append(result.elapsed_ms)

    avg_ms = sum(times) / len(times) if times else 0
    print(f"  ✓ test_performance_dijkstra: avg={avg_ms:.1f}ms, "
          f"{len(times)} queries")
    assert avg_ms < 200.0, f"Dijkstra 过慢: {avg_ms:.1f}ms"


def test_performance_astar():
    """测试 10000 点图上的 A* 性能。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=10000, width=2000, height=1500, seed=2026)

    random.seed(42)
    times_d = []
    times_a = []
    visited_d = []
    visited_a = []

    for _ in range(10):
        start = random.randint(0, 9999)
        end = random.randint(0, 9999)

        rd = dijkstra(g, start, end)
        ra = astar(g, start, end)

        if rd.found and ra.found:
            times_d.append(rd.elapsed_ms)
            times_a.append(ra.elapsed_ms)
            visited_d.append(rd.nodes_visited)
            visited_a.append(ra.nodes_visited)

            # 验证最优性
            assert abs(rd.distance - ra.distance) < 1e-4, (
                f"A* 不最优: {start}->{end}, D={rd.distance}, A={ra.distance}"
            )

    avg_d = sum(times_d) / len(times_d) if times_d else 0
    avg_a = sum(times_a) / len(times_a) if times_a else 0
    avg_vd = sum(visited_d) / len(visited_d) if visited_d else 0
    avg_va = sum(visited_a) / len(visited_a) if visited_a else 0

    print(f"  ✓ test_performance_astar:")
    print(f"      Dijkstra: avg={avg_d:.1f}ms, visited={avg_vd:.0f}")
    print(f"      A*:       avg={avg_a:.1f}ms, visited={avg_va:.0f}")
    if avg_vd > 0:
        print(f"      A* 效率提升: 访问节点 {avg_va/avg_vd:.1%} of Dijkstra")

    assert avg_a < 200.0, f"A* 过慢: {avg_a:.1f}ms"


def test_astar_optimality_large():
    """在大图上验证 A* 最优性（与 Dijkstra 对比 50 组随机起终点）。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=5000, width=1500, height=1000, seed=777)

    random.seed(100)
    mismatches = 0
    total = 0

    for _ in range(50):
        start = random.randint(0, 4999)
        end = random.randint(0, 4999)
        if start == end:
            continue

        rd = dijkstra(g, start, end)
        ra = astar(g, start, end)

        if rd.found and ra.found:
            total += 1
            if abs(rd.distance - ra.distance) > 1e-4:
                mismatches += 1

    assert mismatches == 0, f"A* 最优性违反: {mismatches}/{total}"
    print(f"  ✓ test_astar_optimality_large: {total} 组全部最优")


# ====================================================================
# 测试 6：NavigationEngine 统一 API
# ====================================================================

def test_engine_generate_and_query():
    """测试 NavigationEngine 的地图生成和空间查询。"""
    engine = NavigationEngine()
    engine.generate_map(n_vertices=500, width=800, height=600, seed=42)

    assert engine.is_loaded
    assert engine.graph.vertex_count == 500

    # F1: query_nearby
    nearby = engine.query_nearby(400, 300, k=10)
    assert len(nearby) == 10

    # 最近邻
    v = engine.query_nearest_vertex(400, 300)
    assert v is not None

    # F2: query_viewport
    verts, edges = engine.query_viewport(200, 150, 600, 450)
    assert len(verts) > 0
    assert len(edges) > 0

    # 代表点模式
    reps, rep_edges = engine.query_viewport(0, 0, 800, 600, use_representative=True)
    assert len(reps) > 0
    assert len(reps) < 500  # 代表点应少于总数

    print(f"  ✓ test_engine_generate_and_query: "
          f"nearby={len(nearby)}, viewport={len(verts)}v/{len(edges)}e, reps={len(reps)}")


def test_engine_query_viewport_reversed_edge():
    """测试 query_viewport 不会漏掉反向构造的无向边。"""
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 1.0, 0.0))
    g.add_edge(Edge(1, 0, length=1.0))

    engine = NavigationEngine()
    engine._graph = g
    engine._rebuild_index()

    verts, edges = engine.query_viewport(-1, -1, 2, 1)
    assert len(verts) == 2
    assert len(edges) == 1
    assert {edges[0].u, edges[0].v} == {0, 1}
    print("  ✓ test_engine_query_viewport_reversed_edge")


def test_engine_query_nearby_subgraph():
    """测试 F1 API: 最近点及其关联边。"""
    engine = NavigationEngine()
    engine.generate_map(n_vertices=500, width=800, height=600, seed=42)

    nearby, edges = engine.query_nearby_subgraph(400, 300, k=100)
    assert len(nearby) == 100
    assert len(edges) > 0

    nearby_ids = {v.id for _, v in nearby}
    assert all(edge.u in nearby_ids or edge.v in nearby_ids for edge in edges)

    nearby_inner, inner_edges = engine.query_nearby_subgraph(
        400, 300, k=100, include_boundary_edges=False
    )
    inner_ids = {v.id for _, v in nearby_inner}
    assert len(nearby_inner) == 100
    assert all(edge.u in inner_ids and edge.v in inner_ids for edge in inner_edges)

    print(f"  ✓ test_engine_query_nearby_subgraph: "
          f"boundary_edges={len(edges)}, inner_edges={len(inner_edges)}")


def test_engine_shortest_path():
    """测试 NavigationEngine 的路径搜索接口。"""
    engine = NavigationEngine()
    engine.generate_map(n_vertices=500, width=800, height=600, seed=42)

    # F3: shortest_path
    r = engine.shortest_path(0, 499)
    assert r.found
    assert len(r.path) >= 2

    # F5: traffic_aware_path
    rt = engine.traffic_aware_path(0, 499)
    assert rt.found

    # 未加载地图时应报错
    engine2 = NavigationEngine()
    try:
        engine2.shortest_path(0, 1)
        assert False, "应该抛出 RuntimeError"
    except RuntimeError:
        pass

    print(f"  ✓ test_engine_shortest_path: "
          f"static dist={r.distance:.1f}, traffic dist={rt.distance:.1f}")


# ====================================================================
# 运行所有测试
# ====================================================================

def run_all_tests():
    """运行所有阶段二测试。"""
    tests = [
        ("KD-Tree 基本操作", [
            test_kdtree_build,
            test_kdtree_nearest,
            test_kdtree_knn,
            test_kdtree_knn_all,
            test_kdtree_range,
            test_kdtree_representative,
        ]),
        ("KD-Tree 正确性验证", [
            test_kdtree_knn_vs_brute_force,
            test_kdtree_knn_vs_scipy,
        ]),
        ("Dijkstra 算法", [
            test_dijkstra_basic,
            test_dijkstra_longer_path,
            test_dijkstra_same_start_end,
            test_dijkstra_no_path,
            test_dijkstra_nonexistent_vertex,
            test_dijkstra_with_traffic,
        ]),
        ("A* 算法", [
            test_astar_basic,
            test_astar_optimality,
            test_astar_efficiency,
            test_shortest_path_interface,
        ]),
        ("大规模性能基准", [
            test_performance_kdtree_build,
            test_performance_kdtree_knn,
            test_performance_kdtree_range,
            test_performance_dijkstra,
            test_performance_astar,
            test_astar_optimality_large,
        ]),
        ("NavigationEngine 统一 API", [
            test_engine_generate_and_query,
            test_engine_query_viewport_reversed_edge,
            test_engine_query_nearby_subgraph,
            test_engine_shortest_path,
        ]),
    ]

    total = 0
    passed = 0
    failed = 0

    for group_name, test_funcs in tests:
        print(f"\n{'='*60}")
        print(f"  {group_name}")
        print(f"{'='*60}")
        for test_func in test_funcs:
            total += 1
            try:
                test_func()
                passed += 1
            except Exception as e:
                failed += 1
                print(f"  ✗ {test_func.__name__}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"  测试汇总: {passed}/{total} 通过, {failed} 失败")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
