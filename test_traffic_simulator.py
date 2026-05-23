"""
test_traffic_simulator.py - phase three traffic simulation tests.

Run:
    python -X utf8 test_traffic_simulator.py
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from navigation.engine import NavigationEngine
from navigation.graph import Edge, Graph, Vertex
from navigation.map_generator import MapGenerator
from navigation.traffic_model import congestion_level, travel_time
from navigation.traffic_simulator import TrafficSimulator


def make_triangle_graph() -> Graph:
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 1.0, 0.0))
    g.add_vertex(Vertex(2, 0.5, 1.0))
    g.add_edge(Edge(0, 1, length=1.0, capacity=100, current_cars=60))
    g.add_edge(Edge(1, 2, length=1.0, capacity=100, current_cars=10))
    g.add_edge(Edge(0, 2, length=1.0, capacity=100, current_cars=0))
    return g


def make_routing_graph() -> Graph:
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 1.0, 0.0))
    g.add_vertex(Vertex(2, 2.0, 0.0))
    g.add_vertex(Vertex(3, 1.0, 1.0))
    g.add_edge(Edge(0, 1, length=1.0, capacity=100, current_cars=80))
    g.add_edge(Edge(1, 2, length=1.0, capacity=50, current_cars=200))
    g.add_edge(Edge(1, 3, length=1.0, capacity=100, current_cars=0))
    return g


def make_dynamic_turn_graph() -> Graph:
    g = Graph()
    for i in range(4):
        g.add_vertex(Vertex(i, float(i), 0.0))
    g.add_edge(Edge(0, 1, length=1.0, capacity=100, current_cars=100))
    g.add_edge(Edge(1, 2, length=1.0, capacity=1000, current_cars=1200))
    g.add_edge(Edge(1, 3, length=1.0, capacity=10, current_cars=0))
    return g


def make_path_graph() -> Graph:
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 1.0, 0.0))
    g.add_vertex(Vertex(2, 2.0, 0.0))
    g.add_vertex(Vertex(3, 0.0, 2.0))
    g.add_vertex(Vertex(4, 2.0, 2.0))
    g.add_edge(Edge(0, 1, length=1.0, capacity=10))
    g.add_edge(Edge(1, 2, length=1.0, capacity=100))
    g.add_edge(Edge(0, 3, length=2.0, capacity=100))
    g.add_edge(Edge(2, 4, length=2.0, capacity=100))
    g.add_edge(Edge(3, 4, length=3.0, capacity=100))
    return g


def make_progress_graph() -> Graph:
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 10.0, 0.0))
    g.add_vertex(Vertex(2, 20.0, 0.0))
    g.add_edge(Edge(0, 1, length=10.0, capacity=100))
    g.add_edge(Edge(1, 2, length=10.0, capacity=100))
    return g


def make_reroute_graph() -> Graph:
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 1.0, 0.0))
    g.add_vertex(Vertex(2, 2.0, 0.0))
    g.add_vertex(Vertex(3, 1.0, 2.0))
    g.add_vertex(Vertex(4, 3.0, 0.0))
    g.add_edge(Edge(0, 1, length=1.0, capacity=100))
    g.add_edge(Edge(1, 2, length=1.0, capacity=10))
    g.add_edge(Edge(2, 4, length=1.0, capacity=100))
    g.add_edge(Edge(1, 3, length=2.0, capacity=100))
    g.add_edge(Edge(3, 4, length=2.0, capacity=100))
    return g


def test_traffic_model_boundaries():
    """Traffic formula and congestion levels follow the assignment."""
    assert abs(travel_time(10.0, 100, 50, c=1.0, threshold=0.8) - 10.0) < 1e-9
    expected = 10.0 * (1.0 + math.exp(0.9))
    assert abs(travel_time(10.0, 100, 90, c=1.0, threshold=0.8) - expected) < 1e-9
    assert travel_time(10.0, 0, 1) == float("inf")
    assert congestion_level(20, 100) == 0
    assert congestion_level(50, 100) == 1
    assert congestion_level(80, 100) == 2
    assert congestion_level(120, 100) == 3
    print("  ✓ test_traffic_model_boundaries")


def test_flow_conservation_step():
    """Background traffic evolves by New = Current - Outgoing + Incoming."""
    g = make_triangle_graph()
    sim = TrafficSimulator(g, seed=1)
    before_total = sim.total_cars
    before_counts = {key: state.current_cars for key, state in sim.get_traffic_snapshot().edge_states.items()}

    snapshot = sim.step()
    after_counts = {key: state.current_cars for key, state in snapshot.edge_states.items()}

    assert snapshot.time_step == 1
    assert abs(snapshot.total_cars - before_total) < 1e-6
    assert any(abs(after_counts[key] - before_counts[key]) > 1e-6 for key in before_counts)
    for edge in g.edges():
        state = snapshot.edge_states[(min(edge.u, edge.v), max(edge.u, edge.v))]
        assert edge.current_cars == int(round(state.current_cars))
    print("  ✓ test_flow_conservation_step")


def test_dynamic_routing_prefers_clearer_edges():
    """Background outgoing flow prefers lower-time adjacent roads."""
    g = make_routing_graph()
    sim = TrafficSimulator(g, seed=2)
    before = sim.get_traffic_snapshot().edge_states
    snapshot = sim.step()
    after = snapshot.edge_states

    clear_key = (1, 3)
    congested_key = (1, 2)
    clear_delta = after[clear_key].current_cars - before[clear_key].current_cars
    congested_delta = after[congested_key].current_cars - before[congested_key].current_cars

    assert clear_delta > 0
    assert clear_delta > congested_delta
    assert after[congested_key].travel_time > after[clear_key].travel_time
    print("  ✓ test_dynamic_routing_prefers_clearer_edges")


def test_background_turn_weights_use_current_travel_time():
    """Background turn weights should react to current congestion, not raw capacity."""
    sim = TrafficSimulator(make_dynamic_turn_graph(), seed=21)
    weights = dict(sim._get_background_transitions((0, 1), 1))

    assert weights[(1, 3)] > weights[(1, 2)]
    assert weights[(1, 3)] > 0.9
    print("  ✓ test_background_turn_weights_use_current_travel_time")


def test_spawn_cars_creates_vehicle_routes():
    """spawn_cars creates explicit vehicles with valid paths."""
    sim = TrafficSimulator(make_path_graph(), seed=3)
    ids = sim.spawn_cars(3, start_id=0, end_id=4)
    cars = sim.get_car_snapshot()

    assert len(ids) == 3
    assert len(cars) == 3
    assert all(car.status == "active" for car in cars)
    assert all(car.route[0] == 0 and car.route[-1] == 4 for car in cars)
    assert all(car.current_edge is not None for car in cars)
    assert sim.get_traffic_snapshot().active_cars == 3
    print("  ✓ test_spawn_cars_creates_vehicle_routes")


def test_vehicle_progress_and_edge_sync():
    """A vehicle moves along an edge and contributes to Edge.current_cars."""
    g = make_progress_graph()
    sim = TrafficSimulator(g, seed=4)
    car_id = sim.spawn_car(start_id=0, end_id=2)
    assert car_id is not None

    snapshot_before = sim.get_traffic_snapshot()
    assert snapshot_before.edge_states[(0, 1)].vehicle_cars == 1
    assert g.get_edge(0, 1).current_cars == 1

    sim.step(time_delta=1.0)
    car = sim.get_car_snapshot()[0]
    assert 0.0 < car.progress < 1.0
    assert car.current_edge == (0, 1)
    assert g.get_edge(0, 1).current_cars == 1
    print("  ✓ test_vehicle_progress_and_edge_sync")


def test_vehicle_completion_removes_edge_load():
    """Completed vehicles leave the active set and no longer occupy an edge."""
    g = Graph()
    g.add_vertex(Vertex(0, 0.0, 0.0))
    g.add_vertex(Vertex(1, 1.0, 0.0))
    g.add_edge(Edge(0, 1, length=1.0, capacity=100))

    sim = TrafficSimulator(g, seed=5)
    assert sim.spawn_car(start_id=0, end_id=1) is not None
    snapshot = sim.step(time_delta=1.0)

    assert snapshot.active_cars == 0
    assert snapshot.completed_cars == 1
    assert snapshot.edge_states[(0, 1)].vehicle_cars == 0
    assert g.get_edge(0, 1).current_cars == 0
    print("  ✓ test_vehicle_completion_removes_edge_load")


def test_vehicle_dynamic_reroute_avoids_congestion():
    """A car reroutes at an intermediate node when the next road becomes congested."""
    g = make_reroute_graph()
    sim = TrafficSimulator(g, seed=6, reroute_on_node=True, max_reroutes_per_step=10)
    assert sim.spawn_car(start_id=0, end_id=4) is not None
    assert sim.get_car_snapshot()[0].route == (0, 1, 2, 4)

    sim.set_edge_cars(1, 2, 20)
    sim.step(time_delta=1.0)
    car = sim.get_car_snapshot()[0]

    assert car.from_id == 1
    assert car.to_id == 3
    assert car.current_edge == (1, 3)
    assert car.route == (1, 3, 4)
    print("  ✓ test_vehicle_dynamic_reroute_avoids_congestion")


def test_snapshot_interfaces_are_gui_ready():
    """Traffic and car snapshots expose fields needed by GUI rendering."""
    sim = TrafficSimulator(make_progress_graph(), seed=7)
    sim.randomize_traffic(0.1, 0.1, seed=7)
    sim.spawn_car(start_id=0, end_id=2)
    snapshot = sim.get_traffic_snapshot()
    car = sim.get_car_snapshot(limit=1)[0]
    edge_state = snapshot.edge_states[(0, 1)]

    assert edge_state.current_cars == edge_state.background_cars + edge_state.vehicle_cars
    assert edge_state.capacity > 0
    assert edge_state.ratio > 0
    assert edge_state.level in {0, 1, 2, 3}
    assert edge_state.travel_time > 0
    assert car.x is not None and car.y is not None
    assert 0.0 <= car.progress <= 1.0
    print("  ✓ test_snapshot_interfaces_are_gui_ready")


def test_engine_simulation_api():
    """NavigationEngine exposes start/step/traffic/car/path APIs."""
    engine = NavigationEngine()
    engine.generate_map(n_vertices=200, width=500, height=400, seed=42)
    sim = engine.start_simulation(car_count=5, seed=42, initial_density=(0.1, 0.2))
    before = engine.get_traffic_snapshot()

    after = engine.step_simulation(steps=3, spawn_count=2)
    cars = engine.get_car_snapshot(limit=5)
    path = engine.traffic_aware_path(0, 199)

    assert sim.edge_count == engine.graph.edge_count
    assert after.time_step == 3
    assert after.total_cars >= before.total_cars
    assert len(after.edge_states) == engine.graph.edge_count
    assert len(cars) <= 5
    assert path.found
    print("  ✓ test_engine_simulation_api")


def test_traffic_aware_path_uses_simulator_state():
    """Traffic-aware path reacts to simulator-managed current_cars."""
    engine = NavigationEngine()
    engine._graph = make_path_graph()
    engine._rebuild_index()
    sim = engine.start_simulation()
    sim.set_edge_cars(0, 1, 9)

    static_result = engine.shortest_path(0, 4, algorithm="dijkstra")
    traffic_result = engine.traffic_aware_path(0, 4, algorithm="dijkstra")

    assert static_result.path == [0, 1, 2, 4]
    assert traffic_result.path == [0, 3, 4]
    print("  ✓ test_traffic_aware_path_uses_simulator_state")


def test_large_simulation_performance():
    """1000 cars on a 10000-node graph can run 100 steps fast enough for GUI use."""
    gen = MapGenerator()
    g = gen.generate(n_vertices=10000, width=2000, height=1500, seed=2026)
    sim = TrafficSimulator(
        g,
        seed=2026,
        reroute_on_node=True,
        max_reroutes_per_step=50,
        background_update_interval=10,
    )
    sim.randomize_traffic(0.05, 0.2, seed=2026)
    ids = sim.spawn_cars(1000)

    assert len(ids) >= 950, f"too many failed spawns: {len(ids)} created"

    t_start = time.perf_counter()
    for _ in range(100):
        sim.step(return_snapshot=False)
    snapshot = sim.get_traffic_snapshot()
    elapsed_ms = (time.perf_counter() - t_start) * 1000
    avg_ms = elapsed_ms / 100

    assert avg_ms < 100.0, f"traffic simulation too slow: {avg_ms:.1f}ms/step"
    assert snapshot.active_cars + snapshot.completed_cars == len(ids)
    assert snapshot.max_ratio > 0
    assert any(state.vehicle_cars > 0 for state in snapshot.edge_states.values())
    print(f"  ✓ test_large_simulation_performance: avg={avg_ms:.1f}ms/step")


def run_all_tests():
    tests = [
        test_traffic_model_boundaries,
        test_flow_conservation_step,
        test_dynamic_routing_prefers_clearer_edges,
        test_background_turn_weights_use_current_travel_time,
        test_spawn_cars_creates_vehicle_routes,
        test_vehicle_progress_and_edge_sync,
        test_vehicle_completion_removes_edge_load,
        test_vehicle_dynamic_reroute_avoids_congestion,
        test_snapshot_interfaces_are_gui_ready,
        test_engine_simulation_api,
        test_traffic_aware_path_uses_simulator_state,
        test_large_simulation_performance,
    ]

    total = 0
    passed = 0
    failed = 0
    for test_func in tests:
        total += 1
        try:
            test_func()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  ✗ {test_func.__name__}: {exc}")
            import traceback
            traceback.print_exc()

    print(f"\n测试汇总: {passed}/{total} 通过, {failed} 失败")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
