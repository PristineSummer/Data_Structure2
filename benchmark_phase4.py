"""
Phase 4 backend benchmark.

Run:
    python -X utf8 benchmark_phase4.py
"""

from __future__ import annotations

import random
import sys
import time
from typing import Callable, List, Tuple

from navigation import NavigationEngine


SEED = 2026
N_VERTICES = 10000
WIDTH = 2000.0
HEIGHT = 1500.0

THRESHOLDS = {
    "地图生成": 3000.0,
    "KNN 查询": 10.0,
    "A* 平均": 50.0,
    "交通模拟": 100.0,
}


def measure_ms(func: Callable[[], None]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000.0


def markdown_row(name: str, value_ms: float, threshold_ms: float, note: str = "") -> str:
    status = "PASS" if value_ms < threshold_ms else "FAIL"
    return f"| {name} | {value_ms:.2f} ms | < {threshold_ms:.0f} ms | {status} | {note} |"


def main() -> int:
    rng = random.Random(SEED)
    engine = NavigationEngine()
    rows: List[str] = []

    def build_map() -> None:
        engine.generate_map(
            n_vertices=N_VERTICES,
            width=WIDTH,
            height=HEIGHT,
            seed=SEED,
            poi_density=0.08,
        )

    generate_ms = measure_ms(build_map)
    rows.append(markdown_row("地图生成", generate_ms, THRESHOLDS["地图生成"], "10000 vertices + KDTree + POI index"))

    queries: List[Tuple[float, float]] = [
        (rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT))
        for _ in range(100)
    ]

    def run_knn() -> None:
        for x, y in queries:
            result = engine.query_nearby(x, y, k=100)
            if not result:
                raise AssertionError("KNN returned no vertices")

    knn_avg_ms = measure_ms(run_knn) / len(queries)
    rows.append(markdown_row("KNN 查询", knn_avg_ms, THRESHOLDS["KNN 查询"], "100 runs, average per query"))

    vertex_ids = list(engine.graph.vertex_ids())
    pairs = []
    for _ in range(12):
        start = rng.choice(vertex_ids)
        end = rng.choice(vertex_ids)
        while end == start:
            end = rng.choice(vertex_ids)
        pairs.append((start, end))

    def run_astar() -> None:
        for start, end in pairs:
            result = engine.shortest_path(start, end, algorithm="astar")
            if not result.found:
                raise AssertionError(f"A* failed for {start}->{end}")

    astar_avg_ms = measure_ms(run_astar) / len(pairs)
    rows.append(markdown_row("A* 平均", astar_avg_ms, THRESHOLDS["A* 平均"], "12 random routes, average per route"))

    simulator = engine.start_simulation(
        seed=SEED,
        car_count=1000,
        initial_density=(0.05, 0.20),
        background_update_interval=10,
        max_reroutes_per_step=50,
    )

    def run_traffic() -> None:
        for _ in range(100):
            simulator.step(return_snapshot=False)

    traffic_avg_ms = measure_ms(run_traffic) / 100.0
    rows.append(markdown_row("交通模拟", traffic_avg_ms, THRESHOLDS["交通模拟"], "1000 cars, 100 steps, average per step"))

    print("# Phase 4 Benchmark")
    print()
    print(f"- seed: `{SEED}`")
    print(f"- map: `{N_VERTICES}` vertices, `{engine.graph.edge_count}` edges")
    print(f"- POI count: `{engine.get_stats()['poi_count']}`")
    print()
    print("| Benchmark | Actual | Threshold | Status | Note |")
    print("|---|---:|---:|---|---|")
    for row in rows:
        print(row)

    failed = [
        ("地图生成", generate_ms, THRESHOLDS["地图生成"]),
        ("KNN 查询", knn_avg_ms, THRESHOLDS["KNN 查询"]),
        ("A* 平均", astar_avg_ms, THRESHOLDS["A* 平均"]),
        ("交通模拟", traffic_avg_ms, THRESHOLDS["交通模拟"]),
    ]
    failed = [item for item in failed if item[1] >= item[2]]
    if failed:
        print()
        print("Benchmark failed:")
        for name, actual, threshold in failed:
            print(f"- {name}: {actual:.2f} ms >= {threshold:.0f} ms")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
