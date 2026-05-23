"""
Phase 4 acceptance tests for the member A backend API.

Run:
    python -X utf8 test_phase4.py
"""

from __future__ import annotations

import os
import sys
import tempfile

from navigation import (
    Edge,
    MapGenerator,
    NavigationEngine,
    NearbyState,
    POIResult,
    ViewportState,
    edge_key,
)


def assert_raises(exc_type, func, message: str = "") -> None:
    try:
        func()
    except exc_type:
        return
    except Exception as exc:  # pragma: no cover - diagnostic path
        raise AssertionError(f"{message} expected {exc_type.__name__}, got {type(exc).__name__}: {exc}")
    raise AssertionError(f"{message} expected {exc_type.__name__}")


def collect_pois(graph):
    rows = []
    for vertex in graph.vertices():
        poi = vertex.metadata.get("poi")
        if poi:
            rows.append((vertex.id, poi.get("type"), poi.get("name")))
    return rows


def test_poi_generation_reproducible():
    gen = MapGenerator()
    g1 = gen.generate(n_vertices=300, width=500, height=400, seed=2026, poi_density=0.2)
    g2 = gen.generate(n_vertices=300, width=500, height=400, seed=2026, poi_density=0.2)

    assert collect_pois(g1) == collect_pois(g2)
    assert len(collect_pois(g1)) > 0
    print("  ✓ test_poi_generation_reproducible")


def test_poi_query_filters_radius_and_sorting():
    engine = NavigationEngine()
    engine.generate_map(
        n_vertices=300,
        width=500,
        height=400,
        seed=42,
        poi_density=0.5,
        poi_categories=("gas_station", "restaurant"),
    )

    pois = engine.query_nearby_pois(250, 200, k=50)
    assert pois
    assert all(isinstance(poi, POIResult) for poi in pois)
    distances = [poi.distance for poi in pois]
    assert distances == sorted(distances)

    poi_type = pois[0].poi_type
    filtered = engine.query_nearby_pois(250, 200, k=50, categories=[poi_type])
    assert filtered
    assert all(poi.poi_type == poi_type for poi in filtered)

    radius = pois[0].distance + 1e-9
    in_radius = engine.query_nearby_pois(250, 200, k=50, radius=radius)
    assert in_radius
    assert all(poi.distance <= radius for poi in in_radius)
    print("  ✓ test_poi_query_filters_radius_and_sorting")


def test_nearby_state_structure():
    engine = NavigationEngine()
    engine.generate_map(n_vertices=300, width=500, height=400, seed=7, poi_density=0.3)

    state = engine.query_nearby_state(250, 200, k=25, poi_k=8)
    assert isinstance(state, NearbyState)
    assert state.center == (250.0, 200.0)
    assert len(state.vertices) == 25
    assert all(isinstance(distance, float) and vertex is not None for distance, vertex in state.vertices)
    assert state.edges
    assert len(state.pois) <= 8
    print("  ✓ test_nearby_state_structure")


def test_viewport_state_with_traffic():
    engine = NavigationEngine()
    engine.generate_map(n_vertices=350, width=500, height=400, seed=9, poi_density=0.2)
    engine.start_simulation(seed=9, initial_density=(0.2, 0.6), background_update_interval=2)
    engine.step_simulation(steps=2)

    state = engine.query_viewport_state(500, 400, 0, 0, include_traffic=True)
    assert isinstance(state, ViewportState)
    assert state.bounds == (0.0, 0.0, 500.0, 400.0)
    assert state.vertices
    assert state.edges
    assert state.traffic
    edge_keys = {edge_key(edge.u, edge.v) for edge in state.edges}
    assert set(state.traffic).issubset(edge_keys)
    print("  ✓ test_viewport_state_with_traffic")


def test_coordinate_helpers():
    engine = NavigationEngine()
    engine.generate_map(n_vertices=250, width=500, height=400, seed=11, poi_density=0.2)

    result = engine.shortest_path(0, 249)
    assert result.found
    path_coords = engine.path_coordinates(result)
    assert len(path_coords) == len(result.path)
    assert all(len(coord) == 2 for coord in path_coords)

    edge_coords = engine.edge_coordinates(result.edges[0])
    assert len(edge_coords) == 2
    assert all(len(coord) == 2 for coord in edge_coords)
    print("  ✓ test_coordinate_helpers")


def test_save_load_keeps_poi_index():
    engine = NavigationEngine()
    engine.generate_map(n_vertices=300, width=500, height=400, seed=13, poi_density=0.35)
    before = engine.query_nearby_pois(250, 200, k=10)
    assert before

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = tmp.name

    try:
        engine.save_map(path)
        loaded = NavigationEngine()
        loaded.load_map(path)
        after = loaded.query_nearby_pois(250, 200, k=10)
        assert [(poi.vertex.id, poi.poi_type, poi.name) for poi in before] == [
            (poi.vertex.id, poi.poi_type, poi.name) for poi in after
        ]
    finally:
        os.unlink(path)
    print("  ✓ test_save_load_keeps_poi_index")


def test_stats_and_exports():
    engine = NavigationEngine()
    engine.generate_map(n_vertices=200, width=500, height=400, seed=15, poi_density=0.25)
    stats = engine.get_stats()
    assert stats["vertices"] == 200
    assert stats["edges"] > 0
    assert stats["connected"] is True
    assert stats["poi_count"] == stats["indexed_pois"]
    assert stats["poi_count"] > 0
    assert stats["simulation_running"] is False
    assert Edge is not None
    print("  ✓ test_stats_and_exports")


def test_invalid_phase4_parameters():
    engine = NavigationEngine()
    assert_raises(RuntimeError, lambda: engine.query_nearby_state(0, 0), "unloaded query")

    engine.generate_map(n_vertices=100, width=300, height=200, seed=17, poi_density=0.2)
    assert_raises(ValueError, lambda: engine.query_nearby_pois(0, 0, k=0), "invalid k")
    assert_raises(ValueError, lambda: engine.query_nearby_pois(0, 0, radius=0), "invalid radius")
    assert_raises(ValueError, lambda: engine.query_viewport_state(0, 0, 1, 1, grid_cols=0), "invalid grid")
    assert_raises(
        ValueError,
        lambda: engine.generate_map(n_vertices=100, width=300, height=200, poi_density=-0.1),
        "invalid poi_density",
    )
    print("  ✓ test_invalid_phase4_parameters")


def run_all_tests():
    tests = [
        test_poi_generation_reproducible,
        test_poi_query_filters_radius_and_sorting,
        test_nearby_state_structure,
        test_viewport_state_with_traffic,
        test_coordinate_helpers,
        test_save_load_keeps_poi_index,
        test_stats_and_exports,
        test_invalid_phase4_parameters,
    ]

    total = len(tests)
    passed = 0
    failed = 0
    print("\n" + "=" * 60)
    print("  阶段四后端 API / POI / GUI DTO 测试")
    print("=" * 60)
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  ✗ {test_func.__name__}: {exc}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"  测试汇总: {passed}/{total} 通过, {failed} 失败")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
