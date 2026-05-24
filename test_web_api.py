"""
Regression tests for the Flask web API.

Run:
    python -X utf8 test_web_api.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web_server import app


def assert_status(response, status_code: int = 200) -> Dict[str, Any]:
    payload = response.get_json()
    assert response.status_code == status_code, payload
    assert isinstance(payload, dict), payload
    return payload


def wait_for_generated_map(client, n: int = 320, seed: int = 2026) -> Dict[str, Any]:
    response = client.post("/api/map/generate", json={"n": n, "seed": seed})
    assert_status(response)

    deadline = time.time() + 20
    last_payload: Dict[str, Any] = {}
    while time.time() < deadline:
        status_response = client.get("/api/map/generate/status")
        last_payload = assert_status(status_response)
        if last_payload.get("status") == "done":
            data = last_payload.get("data")
            assert isinstance(data, dict), last_payload
            assert data["vertices"] >= 100
            assert data["edges"] > 0
            assert data["poi_count"] > 0
            return data
        if last_payload.get("status") == "error":
            raise AssertionError(last_payload)
        time.sleep(0.05)

    raise AssertionError(f"map generation timed out: {last_payload}")


def corner_vertices(client) -> Tuple[int, int]:
    start = assert_status(client.get("/api/nearest?x=0&y=0"))
    end = assert_status(client.get("/api/nearest?x=2000&y=1500"))
    assert start["id"] != end["id"]
    return int(start["id"]), int(end["id"])


def assert_trace_payload(payload: Dict[str, Any]) -> None:
    assert payload["found"] is True
    assert isinstance(payload["path_vertex_ids"], list)
    assert len(payload["path_vertex_ids"]) >= 2
    assert isinstance(payload["visited"], list)
    assert isinstance(payload["relaxed_edges"], list)
    assert "trace_truncated" in payload
    assert len(payload["visited"]) <= 40
    assert len(payload["relaxed_edges"]) <= 40
    if payload["visited"]:
        first_visit = payload["visited"][0]
        assert {"id", "x", "y"}.issubset(first_visit.keys())
    if payload["relaxed_edges"]:
        first_edge = payload["relaxed_edges"][0]
        assert {"u", "v", "x1", "y1", "x2", "y2"}.issubset(first_edge.keys())


def test_trace_path_and_traffic_path(client) -> None:
    start, end = corner_vertices(client)

    path = assert_status(client.get(
        f"/api/path?start={start}&end={end}&algo=astar&trace=true&max_trace=40"
    ))
    assert_trace_payload(path)

    traffic_path = assert_status(client.get(
        f"/api/traffic_path?start={start}&end={end}&algo=astar&trace=true&max_trace=40"
    ))
    assert_trace_payload(traffic_path)
    assert isinstance(traffic_path["edge_levels"], list)
    assert "static_distance" in traffic_path
    assert "congestion_count" in traffic_path
    print("  OK test_trace_path_and_traffic_path")


def test_map_cache_api(client) -> None:
    first = wait_for_generated_map(client, n=180, seed=3030)
    second = wait_for_generated_map(client, n=180, seed=3030)
    assert "cache_key" in first
    assert second["cache_key"] == first["cache_key"]
    assert second["cache_hit"] is True
    print("  OK test_map_cache_api")


def test_algorithm_compare_api(client) -> None:
    start, end = corner_vertices(client)
    compare = assert_status(client.get(
        f"/api/compare_algorithms?start={start}&end={end}&trace=true&max_trace=40"
    ))
    assert {"astar", "dijkstra", "visit_reduction_percent", "time_delta_ms",
            "distance_delta"}.issubset(compare.keys())
    assert_trace_payload(compare["astar"])
    assert_trace_payload(compare["dijkstra"])
    assert compare["astar"]["nodes_visited"] > 0
    assert compare["dijkstra"]["nodes_visited"] > 0
    print("  OK test_algorithm_compare_api")


def test_route_explain_api(client) -> None:
    start, end = corner_vertices(client)
    explain = assert_status(client.get(
        f"/api/route/explain?start={start}&end={end}&algo=astar&trace=true&max_trace=40"
    ))
    required = {"static_path", "traffic_path", "static_edge_levels", "traffic_edge_levels",
                "static_edge_details", "traffic_edge_details", "worst_static_edge",
                "avoided_congested_edges", "summary", "metrics"}
    assert required.issubset(explain.keys())
    assert_trace_payload(explain["static_path"])
    assert_trace_payload(explain["traffic_path"])
    assert isinstance(explain["summary"], str) and explain["summary"]
    assert isinstance(explain["static_edge_levels"], list)
    assert isinstance(explain["traffic_edge_details"], list)
    print("  OK test_route_explain_api")


def test_viewport_traffic_fields_and_analytics(client) -> None:
    started = assert_status(client.post("/api/sim/start", json={
        "cars": 80,
        "seed": 2026,
        "density_low": 0.10,
        "density_high": 0.25,
    }))
    assert started["status"] == "started"
    time.sleep(0.15)

    viewport = assert_status(client.get(
        "/api/viewport?x_min=0&y_min=0&x_max=2000&y_max=1500&traffic=true"
    ))
    assert viewport["edges"], viewport
    required = {"length", "capacity", "current_cars", "ratio", "level", "travel_time"}
    assert required.issubset(viewport["edges"][0].keys())

    lod_viewport = assert_status(client.get(
        "/api/viewport?x_min=0&y_min=0&x_max=2000&y_max=1500"
        "&traffic=true&lod=auto&representative=true&max_edges=120&max_vertices=120"
    ))
    assert {"representative", "lod", "truncated", "total_vertices_in_view",
            "total_edges_returned"}.issubset(lod_viewport.keys())
    assert lod_viewport["representative"] is True
    assert len(lod_viewport["vertices"]) <= 120
    assert len(lod_viewport["edges"]) <= 120

    analytics = assert_status(client.get("/api/analytics/traffic"))
    assert {"level_counts", "top_congested_edges", "history", "average_ratio",
            "max_ratio", "active_cars"}.issubset(analytics.keys())
    assert set(analytics["level_counts"].keys()) == {"0", "1", "2", "3"}
    assert isinstance(analytics["top_congested_edges"], list)
    print("  OK test_viewport_traffic_fields_and_analytics")


def test_manual_inject_then_explain(client) -> None:
    start, end = corner_vertices(client)
    injected = assert_status(client.post("/api/traffic/inject", json={
        "x": 1000,
        "y": 750,
        "radius": 160,
        "intensity": 120,
    }))
    assert injected["affected"] >= 0

    explain = assert_status(client.get(
        f"/api/route/explain?start={start}&end={end}&algo=astar&trace=true&max_trace=40"
    ))
    assert explain["static_path"]["found"] is True
    assert explain["traffic_path"]["found"] is True
    assert isinstance(explain["metrics"], dict)
    print("  OK test_manual_inject_then_explain")


def test_poi_api(client) -> None:
    categories = assert_status(client.get("/api/poi/categories"))
    category_ids = {item["id"] for item in categories["categories"]}
    assert {"gas_station", "restaurant", "parking", "repair", "hospital"}.issubset(category_ids)

    pois = assert_status(client.get("/api/poi/search?x=1000&y=750&k=20"))
    assert pois["pois"], pois
    first = pois["pois"][0]
    assert {"id", "x", "y", "distance", "poi_type", "name", "metadata"}.issubset(first.keys())

    filtered = assert_status(client.get(
        f"/api/poi/search?x=1000&y=750&k=20&category={first['poi_type']}"
    ))
    assert filtered["pois"], filtered
    assert all(poi["poi_type"] == first["poi_type"] for poi in filtered["pois"])
    print("  OK test_poi_api")


def test_minimap_api(client) -> None:
    minimap = assert_status(client.get("/api/minimap"))
    assert isinstance(minimap["vertices"], list)
    assert isinstance(minimap["edges"], list)
    assert minimap["vertices"], minimap
    assert minimap["edges"], minimap
    assert {"id", "x", "y"}.issubset(minimap["vertices"][0].keys())
    required_edge_fields = {"x1", "y1", "x2", "y2", "road_class", "is_arterial", "score", "level", "capacity"}
    assert required_edge_fields.issubset(minimap["edges"][0].keys())
    assert len(minimap["edges"]) >= min(50, len(minimap["vertices"]))
    print("  OK test_minimap_api")


def test_route_subgraph_api(client) -> None:
    start, end = corner_vertices(client)
    path = assert_status(client.get(
        f"/api/path?start={start}&end={end}&algo=astar&trace=true&max_trace=40"
    ))
    subgraph = assert_status(client.get(
        "/api/route/subgraph?"
        f"path={','.join(str(vid) for vid in path['path_vertex_ids'])}"
        "&max_nodes=90&max_edges=140"
    ))
    assert {"nodes", "edges", "path_vertex_ids", "visited_ids", "relaxed_edges", "truncated"}.issubset(subgraph.keys())
    assert subgraph["nodes"], subgraph
    assert subgraph["edges"], subgraph
    assert len(subgraph["nodes"]) <= 90
    assert len(subgraph["edges"]) <= 140
    assert {"id", "x", "y"}.issubset(subgraph["nodes"][0].keys())
    assert {"u", "v", "road_class", "score", "is_path"}.issubset(subgraph["edges"][0].keys())
    print("  OK test_route_subgraph_api")


def test_demo_setup_async(client) -> None:
    started = assert_status(client.post("/api/demo/setup?async=true", json={"n": 240, "seed": 4040}))
    assert {"run_id", "status", "step_index", "steps", "progress", "message"}.issubset(started.keys())
    run_id = started["run_id"]
    deadline = time.time() + 30
    latest = started
    while time.time() < deadline:
        latest = assert_status(client.get(f"/api/demo/status?run_id={run_id}"))
        if latest["status"] in {"done", "error"}:
            break
        time.sleep(0.1)
    assert latest["status"] == "done", latest
    assert latest["result"]["static_path"]["found"] is True
    assert latest["result"]["traffic_path"]["found"] is True
    assert latest["progress"] == 1.0
    client.post("/api/sim/stop")
    print("  OK test_demo_setup_async")


def test_demo_setup(client) -> None:
    demo = assert_status(client.post("/api/demo/setup", json={"n": 320, "seed": 2026}))
    assert {"start", "end", "incident", "static_path", "traffic_path", "metrics"}.issubset(demo.keys())
    assert demo["incident"]["affected_edges"] >= 0
    assert demo["static_path"]["found"] is True
    assert demo["traffic_path"]["found"] is True
    assert isinstance(demo["static_path"]["visited"], list)
    assert isinstance(demo["traffic_path"]["relaxed_edges"], list)
    assert "affected_edges" in demo["metrics"]
    assert "route_explain" in demo
    assert isinstance(demo["route_explain"]["summary"], str)
    client.post("/api/sim/stop")
    print("  OK test_demo_setup")


def run_all_tests() -> None:
    print("Running web API tests...")
    with app.test_client() as client:
        wait_for_generated_map(client)
        test_map_cache_api(client)
        test_trace_path_and_traffic_path(client)
        test_algorithm_compare_api(client)
        test_viewport_traffic_fields_and_analytics(client)
        test_route_explain_api(client)
        test_manual_inject_then_explain(client)
        test_poi_api(client)
        test_minimap_api(client)
        test_route_subgraph_api(client)
        test_demo_setup_async(client)
        test_demo_setup(client)
        client.post("/api/sim/stop")
    print("All web API tests passed.")


if __name__ == "__main__":
    run_all_tests()
