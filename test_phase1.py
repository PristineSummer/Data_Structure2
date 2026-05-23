"""
test_phase1.py — 阶段一单元测试

测试内容：
    1. Graph 基本操作（增删改查、连通性检查）
    2. MapGenerator 地图生成（正确性、连通性、度数分布）
    3. GraphSerializer 序列化/反序列化（保存/加载一致性）
    4. 性能基准测试（10000 节点生成时间）

运行方式：
    python -m pytest test_phase1.py -v
    或
    python test_phase1.py
"""

import os
import sys
import time
import math
import tempfile
import logging
import random

# 确保能找到 navigation 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from navigation.graph import Vertex, Edge, Graph
from navigation.map_generator import MapGenerator
from navigation.serializer import GraphSerializer

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


def _edge_segments(graph: Graph):
    """Collect graph edges as geometry segments for crossing validation."""
    segments = []
    for edge in graph.edges():
        u = graph.get_vertex(edge.u)
        v = graph.get_vertex(edge.v)
        segments.append((edge.u, edge.v, (u.x, u.y), (v.x, v.y)))
    return segments


def _find_first_road_crossing(graph: Graph, sample_pairs: int = None, seed: int = 0):
    """
    Find the first strict crossing between two non-adjacent roads.

    sample_pairs=None runs a full O(E^2) check.  sample_pairs=N runs a
    deterministic random sample for large maps.
    """
    segments = _edge_segments(graph)
    if sample_pairs is None:
        for i in range(len(segments)):
            u1, v1, p1, p2 = segments[i]
            for j in range(i + 1, len(segments)):
                u2, v2, p3, p4 = segments[j]
                if len({u1, v1, u2, v2}) < 4:
                    continue
                if MapGenerator._segments_intersect(p1, p2, p3, p4):
                    return (u1, v1, u2, v2)
        return None

    rng = random.Random(seed)
    if len(segments) < 2:
        return None
    for _ in range(sample_pairs):
        i, j = rng.sample(range(len(segments)), 2)
        if i > j:
            i, j = j, i
        u1, v1, p1, p2 = segments[i]
        u2, v2, p3, p4 = segments[j]
        if len({u1, v1, u2, v2}) < 4:
            continue
        if MapGenerator._segments_intersect(p1, p2, p3, p4):
            return (u1, v1, u2, v2)
    return None


# ====================================================================
# 测试 1：Graph 基本操作
# ====================================================================

def test_graph_add_vertices():
    """测试顶点的添加与查询。"""
    g = Graph()
    v0 = Vertex(0, 1.0, 2.0)
    v1 = Vertex(1, 3.0, 4.0)
    g.add_vertex(v0)
    g.add_vertex(v1)
    assert g.vertex_count == 2
    assert g.has_vertex(0)
    assert g.has_vertex(1)
    assert not g.has_vertex(2)
    assert g.get_vertex(0) == v0
    print("  ✓ test_graph_add_vertices")


def test_graph_add_edges():
    """测试边的添加与查询。"""
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 3.0, 4.0))
    g.add_vertex(Vertex(2, 6.0, 0.0))

    e01 = Edge(0, 1, length=5.0)
    e12 = Edge(1, 2, length=5.0)
    g.add_edge(e01)
    g.add_edge(e12)

    assert g.edge_count == 2
    assert g.has_edge(0, 1)
    assert g.has_edge(1, 0)  # 无向
    assert not g.has_edge(0, 2)
    assert g.degree(1) == 2
    assert g.degree(0) == 1

    # 重复添加不应增加边
    g.add_edge(Edge(0, 1, length=5.0))
    assert g.edge_count == 2
    print("  ✓ test_graph_add_edges")


def test_graph_remove():
    """测试删除边和顶点。"""
    g = Graph()
    for i in range(4):
        g.add_vertex(Vertex(i, float(i), 0.0))
    g.add_edge(Edge(0, 1, length=1.0))
    g.add_edge(Edge(1, 2, length=1.0))
    g.add_edge(Edge(2, 3, length=1.0))

    g.remove_edge(1, 2)
    assert g.edge_count == 2
    assert not g.has_edge(1, 2)

    g.remove_vertex(0)
    assert g.vertex_count == 3
    assert g.edge_count == 1  # 0-1 的边也被删除了
    assert not g.has_vertex(0)
    print("  ✓ test_graph_remove")


def test_graph_connectivity():
    """测试连通性检查和分量检测。"""
    g = Graph()
    for i in range(6):
        g.add_vertex(Vertex(i, float(i), 0.0))
    # 连通分量 1: 0-1-2
    g.add_edge(Edge(0, 1, length=1.0))
    g.add_edge(Edge(1, 2, length=1.0))
    # 连通分量 2: 3-4-5
    g.add_edge(Edge(3, 4, length=1.0))
    g.add_edge(Edge(4, 5, length=1.0))

    assert not g.is_connected()
    comps = g.connected_components()
    assert len(comps) == 2

    # 连接两个分量
    g.add_edge(Edge(2, 3, length=1.0))
    assert g.is_connected()
    comps2 = g.connected_components()
    assert len(comps2) == 1
    print("  ✓ test_graph_connectivity")


def test_graph_neighbors():
    """测试邻居查询。"""
    g = Graph()
    for i in range(4):
        g.add_vertex(Vertex(i, float(i), 0.0))
    g.add_edge(Edge(0, 1, length=1.0))
    g.add_edge(Edge(0, 2, length=2.0))
    g.add_edge(Edge(0, 3, length=3.0))

    neighbors = g.get_neighbors(0)
    assert len(neighbors) == 3
    neighbor_ids = g.get_neighbor_ids(0)
    assert set(neighbor_ids) == {1, 2, 3}
    print("  ✓ test_graph_neighbors")


def test_vertex_distance():
    """测试顶点间距离计算。"""
    v0 = Vertex(0, 0.0, 0.0)
    v1 = Vertex(1, 3.0, 4.0)
    assert abs(v0.distance_to(v1) - 5.0) < 1e-10
    print("  ✓ test_vertex_distance")


def test_edge_travel_time():
    """测试通行时间公式。"""
    e = Edge(0, 1, length=10.0, capacity=100, current_cars=50)
    # n/v = 0.5, 小于默认阈值 0.8，所以 f(x) = 1
    t1 = e.travel_time(c=1.0, threshold=0.8)
    assert abs(t1 - 10.0) < 1e-10  # 1 * 10 * 1

    # 超过阈值的情况
    e.current_cars = 90  # n/v = 0.9 > 0.8
    t2 = e.travel_time(c=1.0, threshold=0.8)
    expected = 1.0 * 10.0 * (1.0 + math.exp(0.9))
    assert abs(t2 - expected) < 1e-6
    print("  ✓ test_edge_travel_time")


def test_edge_congestion_level():
    """测试拥堵等级计算。"""
    e = Edge(0, 1, length=10.0, capacity=100)
    e.current_cars = 20  # 0.2 -> level 0
    assert e.congestion_level() == 0
    e.current_cars = 50  # 0.5 -> level 1
    assert e.congestion_level() == 1
    e.current_cars = 80  # 0.8 -> level 2
    assert e.congestion_level() == 2
    e.current_cars = 120  # 1.2 -> level 3
    assert e.congestion_level() == 3
    print("  ✓ test_edge_congestion_level")


def test_graph_subgraph():
    """测试子图提取。"""
    g = Graph()
    for i in range(5):
        g.add_vertex(Vertex(i, float(i), 0.0))
    g.add_edge(Edge(0, 1, length=1.0))
    g.add_edge(Edge(1, 2, length=1.0))
    g.add_edge(Edge(2, 3, length=1.0))
    g.add_edge(Edge(3, 4, length=1.0))

    sub = g.subgraph({0, 1, 2})
    assert sub.vertex_count == 3
    assert sub.edge_count == 2
    assert sub.has_edge(0, 1)
    assert sub.has_edge(1, 2)
    assert not sub.has_edge(2, 3)
    print("  ✓ test_graph_subgraph")


def test_graph_self_loop_prevention():
    """测试自环防御。"""
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    try:
        g.add_edge(Edge(0, 0, length=0.0))
        assert False, "应该抛出 ValueError"
    except ValueError:
        pass
    assert g.edge_count == 0
    print("  ✓ test_graph_self_loop_prevention")


# ====================================================================
# 测试 2：MapGenerator 地图生成
# ====================================================================

def test_map_generator_small():
    """测试小规模地图生成。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=100, width=500, height=500, seed=42)
    assert g.vertex_count == 100
    assert g.edge_count > 0
    assert g.is_connected()
    stats = g.stats()
    assert stats["min_degree"] >= 1
    print(f"  ✓ test_map_generator_small: V={stats['vertices']}, E={stats['edges']}, "
          f"avg_deg={stats['avg_degree']:.1f}")


def test_map_generator_invalid_inputs():
    """测试地图生成参数校验能给出清晰异常。"""
    invalid_cases = [
        lambda: MapGenerator(max_degree=0),
        lambda: MapGenerator(max_edge_length_factor=0),
        lambda: MapGenerator(min_distance=-1),
        lambda: MapGenerator(capacity_range=(100, 20)),
        lambda: MapGenerator().generate(n_vertices=2, width=500, height=500),
        lambda: MapGenerator().generate(n_vertices=100, width=0, height=500),
        lambda: MapGenerator().generate(n_vertices=100, width=500, height=float("inf")),
    ]

    for case in invalid_cases:
        try:
            case()
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass

    print("  ✓ test_map_generator_invalid_inputs")


def test_map_generator_medium():
    """测试中等规模地图生成。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=1000, width=1000, height=1000, seed=123)
    assert g.vertex_count == 1000
    assert g.is_connected()
    stats = g.stats()
    # 稀疏化后平均度数应在合理范围内
    assert 2.0 <= stats["avg_degree"] <= 8.0
    print(f"  ✓ test_map_generator_medium: V={stats['vertices']}, E={stats['edges']}, "
          f"avg_deg={stats['avg_degree']:.1f}")


def test_map_generator_large():
    """测试大规模地图生成（10000 点，课题要求的最低规模）。"""
    gen = MapGenerator()
    t_start = time.time()
    g = gen.generate(n_vertices=10000, width=2000, height=1500, seed=2026)
    t_elapsed = time.time() - t_start

    assert g.vertex_count == 10000
    assert g.is_connected()

    stats = g.stats()
    assert 2.0 <= stats["avg_degree"] <= 8.0
    assert stats["max_degree"] <= 20  # 合理上限

    print(f"  ✓ test_map_generator_large: V={stats['vertices']}, E={stats['edges']}, "
          f"avg_deg={stats['avg_degree']:.1f}, max_deg={stats['max_degree']}, "
          f"time={t_elapsed:.2f}s")

    # 性能要求：< 5 秒
    assert t_elapsed < 5.0, f"地图生成过慢: {t_elapsed:.2f}s > 5s"


def test_map_generator_reproducible():
    """测试相同 seed 生成相同结果。"""
    gen = MapGenerator()
    g1 = gen.generate(n_vertices=200, width=500, height=500, seed=999)
    g2 = gen.generate(n_vertices=200, width=500, height=500, seed=999)

    assert g1.vertex_count == g2.vertex_count
    assert g1.edge_count == g2.edge_count

    # 检查顶点坐标一致
    for vid in g1.vertex_ids():
        v1 = g1.get_vertex(vid)
        v2 = g2.get_vertex(vid)
        assert abs(v1.x - v2.x) < 1e-10
        assert abs(v1.y - v2.y) < 1e-10
    print("  ✓ test_map_generator_reproducible")


def test_map_generator_degree_distribution():
    """测试度数分布的合理性。"""
    gen = MapGenerator(max_degree=6)
    g = gen.generate(n_vertices=2000, width=1000, height=1000, seed=77)

    degrees = [g.degree(vid) for vid in g.vertex_ids()]
    # 大部分顶点的度数应在 2-6 之间
    normal_degree_count = sum(1 for d in degrees if 2 <= d <= 6)
    ratio = normal_degree_count / len(degrees)
    assert ratio > 0.7, f"度数分布异常: 只有 {ratio:.0%} 的顶点度数在 [2,6]"
    print(f"  ✓ test_map_generator_degree_distribution: {ratio:.0%} 在 [2,6] 范围内")


def test_map_generator_capacity_hierarchy():
    """测试 MST 主干道容量是否高于普通街道。"""
    gen = MapGenerator(capacity_range=(20, 60))
    g = gen.generate(n_vertices=500, width=800, height=600, seed=42)

    # 统计所有边的容量
    capacities = [e.capacity for e in g.edges()]
    avg_cap = sum(capacities) / len(capacities)
    max_cap = max(capacities)

    # MST 边被 boost 了 2-3x，所以最大容量应超过原始范围的上限 (60)
    assert max_cap > 60, f"MST 容量提升未生效: max_cap={max_cap}"
    # 平均容量应高于原始范围的中点 (40)，因为 MST 边被 boost 了
    assert avg_cap > 40, f"平均容量偏低: avg_cap={avg_cap:.1f}"
    print(f"  ✓ test_map_generator_capacity_hierarchy: "
          f"avg_cap={avg_cap:.1f}, max_cap={max_cap}")


def test_map_generator_no_crossings_small_medium():
    """全量检测小/中规模地图没有不合理道路交叉。"""
    cases = [
        (100, 500, 500, 42),
        (1000, 1000, 1000, 123),
    ]
    for n, width, height, seed in cases:
        gen = MapGenerator()
        g = gen.generate(n_vertices=n, width=width, height=height, seed=seed)
        crossing = _find_first_road_crossing(g)
        assert crossing is None, f"{n} 点地图发现道路交叉: {crossing}"
    print("  ✓ test_map_generator_no_crossings_small_medium")


def test_map_generator_no_crossings_large_sampled():
    """大规模地图使用确定性随机抽样检测道路交叉。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=10000, width=2000, height=1500, seed=2026)
    crossing = _find_first_road_crossing(g, sample_pairs=50000, seed=2026)
    assert crossing is None, f"10000 点地图抽样发现道路交叉: {crossing}"
    print("  ✓ test_map_generator_no_crossings_large_sampled: 50000 sampled pairs")


# ====================================================================
# 测试 3：GraphSerializer 序列化/反序列化
# ====================================================================

def test_serializer_save_load():
    """测试保存与加载的一致性。"""
    gen = MapGenerator()
    g_original = gen.generate(n_vertices=500, width=800, height=600, seed=42)

    # 使用临时文件
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
        tmp_path = tmp.name

    try:
        GraphSerializer.save(g_original, tmp_path)
        g_loaded = GraphSerializer.load(tmp_path)

        assert g_loaded.vertex_count == g_original.vertex_count
        assert g_loaded.edge_count == g_original.edge_count
        assert g_loaded.width == g_original.width
        assert g_loaded.height == g_original.height
        assert g_loaded.seed == g_original.seed

        # 检查顶点一致
        for vid in g_original.vertex_ids():
            v_orig = g_original.get_vertex(vid)
            v_load = g_loaded.get_vertex(vid)
            assert v_load is not None
            assert abs(v_orig.x - v_load.x) < 0.01
            assert abs(v_orig.y - v_load.y) < 0.01

        # 检查加载后仍然连通
        assert g_loaded.is_connected()
        print(f"  ✓ test_serializer_save_load: V={g_loaded.vertex_count}, E={g_loaded.edge_count}")
    finally:
        os.unlink(tmp_path)


def test_serializer_compact():
    """测试紧凑格式保存。"""
    gen = MapGenerator()
    g = gen.generate(n_vertices=1000, width=1000, height=1000, seed=55)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
        tmp_path = tmp.name

    try:
        # 普通格式
        GraphSerializer.save(g, tmp_path)
        normal_size = os.path.getsize(tmp_path)

        # 紧凑格式
        compact_path = tmp_path + ".compact.json"
        GraphSerializer.save_compact(g, compact_path)
        compact_size = os.path.getsize(compact_path)

        assert compact_size < normal_size
        print(f"  ✓ test_serializer_compact: normal={normal_size/1024:.0f}KB, "
              f"compact={compact_size/1024:.0f}KB, "
              f"ratio={compact_size/normal_size:.0%}")
    finally:
        os.unlink(tmp_path)
        if os.path.exists(compact_path):
            os.unlink(compact_path)


def test_serializer_file_not_found():
    """测试加载不存在的文件。"""
    try:
        GraphSerializer.load("nonexistent_file_12345.json")
        assert False, "应该抛出 FileNotFoundError"
    except FileNotFoundError:
        pass
    print("  ✓ test_serializer_file_not_found")


# ====================================================================
# 运行所有测试
# ====================================================================

def run_all_tests():
    """运行所有测试并输出汇总。"""
    tests = [
        # Graph 基本操作
        ("Graph 基本操作", [
            test_graph_add_vertices,
            test_graph_add_edges,
            test_graph_remove,
            test_graph_connectivity,
            test_graph_neighbors,
            test_vertex_distance,
            test_edge_travel_time,
            test_edge_congestion_level,
            test_graph_subgraph,
            test_graph_self_loop_prevention,
        ]),
        # MapGenerator
        ("MapGenerator 地图生成", [
            test_map_generator_small,
            test_map_generator_invalid_inputs,
            test_map_generator_medium,
            test_map_generator_large,
            test_map_generator_reproducible,
            test_map_generator_degree_distribution,
            test_map_generator_capacity_hierarchy,
            test_map_generator_no_crossings_small_medium,
            test_map_generator_no_crossings_large_sampled,
        ]),
        # Serializer
        ("GraphSerializer 序列化", [
            test_serializer_save_load,
            test_serializer_compact,
            test_serializer_file_not_found,
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

    print(f"\n{'='*60}")
    print(f"  测试汇总: {passed}/{total} 通过, {failed} 失败")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
