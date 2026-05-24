"""
web_server.py — Navigation System Web Server
将 NavigationEngine 封装为 REST API，同时提供 Leaflet 前端静态文件服务。

启动方式: python web_server.py
"""
import heapq, math, os, sys, threading, time, uuid, webbrowser
from pathlib import Path

try:
    from flask import Flask, jsonify, request, send_from_directory
except ImportError:
    print("请先安装 Flask: pip install flask")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from navigation.engine import NavigationEngine
from navigation.serializer import GraphSerializer
from navigation.traffic_model import congestion_ratio

# Static files are served by explicit routes below so React history fallback can
# handle non-API deep links before Flask's built-in static route returns 404.
app = Flask(__name__, static_folder=None)
engine = NavigationEngine()

_gen_result = {"status": "idle", "data": None}
_gen_lock   = threading.Lock()
_sim_stop_event = threading.Event()   # set() = stop requested
_sim_thread  = None
_sim_speed   = 1      # steps executed per 0.05 s tick
MAP_CACHE_DIR = Path("data/generated")
MAP_CACHE_VERSION = "web_v1"
_last_cache_info = {"hit": False, "key": "", "path": ""}
_analytics_lock = threading.Lock()
_analytics_cache = {"payload": None, "updated_at": 0.0, "time_step": -1, "map_key": ""}
_demo_lock = threading.Lock()
_demo_runs = {}
DEMO_STEPS = [
    "加载演示城市路网",
    "启动早高峰交通流",
    "选择跨城路线",
    "注入事故拥堵",
    "生成静态路径轨迹",
    "生成交通感知绕行",
    "汇总展示指标",
]


# ─── Static files ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("web_ui", "index.html")


# ─── Map management ────────────────────────────────────────────────────────

@app.route("/api/map/generate", methods=["POST"])
def generate_map():
    global _gen_result
    data = request.get_json() or {}
    n_actual = max(100, min(30000, int(data.get("n", 10000))))
    seed = int(data.get("seed", 2026))
    with _gen_lock:
        _gen_result = {"status": "running", "data": None}

    def _do():
        global _gen_result
        try:
            stats = _load_or_generate_map(n_actual, seed=seed)
            with _gen_lock:
                _gen_result = {"status": "done", "data": stats}
        except Exception as e:
            with _gen_lock:
                _gen_result = {"status": "error", "data": str(e)}

    threading.Thread(target=_do, daemon=True).start()
    return jsonify({"status": "running"})


@app.route("/api/map/generate/status")
def gen_status():
    with _gen_lock:
        return jsonify(_gen_result)


@app.route("/api/map/load", methods=["POST"])
def load_map():
    data     = request.get_json() or {}
    filepath = data.get("filepath", "")
    if not os.path.exists(filepath):
        return jsonify({"error": f"文件不存在: {filepath}"}), 400
    try:
        engine.load_map(filepath)
        _set_cache_info(False, "", "")
        _invalidate_analytics_cache()
        return jsonify({"status": "ok", "stats": _get_stats()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/map/save", methods=["POST"])
def save_map():
    if not engine.is_loaded:
        return jsonify({"error": "地图未加载"}), 400
    data     = request.get_json() or {}
    filepath = data.get("filepath", "map.json")
    try:
        engine.save_map(filepath)
        return jsonify({"status": "ok", "filepath": os.path.abspath(filepath)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/map/stats")
def map_stats():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    return jsonify(_get_stats())


@app.route("/api/minimap")
def minimap_data():
    """Return a representative full-graph overview for the minimap canvas."""
    if not engine.is_loaded:
        return jsonify({"vertices": [], "edges": []})
    try:
        graph = engine.graph
        w = getattr(graph, "width", 2000)
        h = getattr(graph, "height", 1500)
        max_vertices = max(400, min(6000, int(request.args.get("max_vertices", 2600))))
        max_edges = max(600, min(12000, int(request.args.get("max_edges", 3600))))
        grid_cols = max(12, min(120, int(request.args.get("grid_cols", 70))))
        grid_rows = max(10, min(90, int(request.args.get("grid_rows", 52))))
        vp = engine.query_viewport_state(
            0, 0, w, h,
            use_representative=True,
            grid_cols=64, grid_rows=48,
            include_traffic=False,
        )
        vertices = [{"id": v.id, "x": v.x, "y": v.y} for v in vp.vertices]
        if len(vertices) > max_vertices:
            stride = max(1, math.ceil(len(vertices) / max_vertices))
            vertices = vertices[::stride][:max_vertices]

        edges = _sample_minimap_edges(max_edges=max_edges, grid_cols=grid_cols, grid_rows=grid_rows)
        return jsonify({"vertices": vertices, "edges": edges})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Viewport (F2) ────────────────────────────────────────────────────────

@app.route("/api/viewport")
def viewport():
    if not engine.is_loaded:
        return jsonify({"vertices": [], "edges": []})
    try:
        stats = engine.get_stats()
        map_w = float(stats.get("width", 2000))
        map_h = float(stats.get("height", 1500))
        x_min = float(request.args.get("x_min", 0))
        y_min = float(request.args.get("y_min", 0))
        x_max = float(request.args.get("x_max", 2000))
        y_max = float(request.args.get("y_max", 1500))
        grid_cols      = max(5, int(request.args.get("grid_cols", 40)))
        grid_rows      = max(5, int(request.args.get("grid_rows", 30)))
        lod            = request.args.get("lod", "detail").lower()
        max_vertices   = max(100, int(request.args.get("max_vertices", 3500)))
        max_edges      = max(100, int(request.args.get("max_edges", 7000)))
        viewport_area  = abs((x_max - x_min) * (y_max - y_min))
        map_area       = max(1.0, map_w * map_h)
        area_ratio     = viewport_area / map_area
        requested_rep  = request.args.get("representative", "false").lower() == "true"
        auto_rep       = lod == "auto" and (
            area_ratio > 0.20
            or (stats.get("vertices", 0) > 18000 and area_ratio > 0.08)
        )
        use_rep        = requested_rep or auto_rep or lod in {"overview", "summary"}
        incl_traffic   = request.args.get("traffic", "false").lower() == "true"

        vp = engine.query_viewport_state(
            x_min, y_min, x_max, y_max,
            use_representative=False,
            grid_cols=grid_cols, grid_rows=grid_rows,
            include_traffic=incl_traffic,
        )
        source_vertex_count = len(vp.vertices)
        if use_rep:
            display_vertices, _ = engine.query_viewport(
                x_min, y_min, x_max, y_max,
                use_representative=True,
                grid_cols=grid_cols,
                grid_rows=grid_rows,
            )
        else:
            display_vertices = vp.vertices

        vertices = []
        for v in display_vertices:
            poi = v.metadata.get("poi") if isinstance(v.metadata, dict) else None
            vertices.append({
                "id": v.id, "x": v.x, "y": v.y,
                "is_poi":   bool(poi and poi.get("type")),
                "poi_type": str(poi["type"])  if poi else "",
                "poi_name": str(poi.get("name", poi["type"])) if poi else "",
            })
            if use_rep and len(vertices) >= max_vertices:
                break

        vid_map = {v.id: v for v in vp.vertices}
        edges = []
        for e in vp.edges:
            u_v = vid_map.get(e.u)
            v_v = vid_map.get(e.v)
            if u_v is None or v_v is None:
                continue
            lv = 0
            cars = float(e.current_cars)
            ratio = congestion_ratio(cars, e.capacity)
            travel_time = e.travel_time()
            if incl_traffic and vp.traffic:
                key   = (min(e.u, e.v), max(e.u, e.v))
                state = vp.traffic.get(key)
                if state:
                    lv = state.level
                    cars = float(state.current_cars)
                    ratio = state.ratio
                    travel_time = state.travel_time
                else:
                    lv = e.congestion_level()
            else:
                lv = e.congestion_level()
            road_class, is_arterial, road_score = _edge_visual_rank(e, level=lv, ratio=ratio)
            edges.append({
                "u": e.u, "v": e.v,
                "x1": u_v.x, "y1": u_v.y,
                "x2": v_v.x, "y2": v_v.y,
                "level": lv,
                "length": e.length,
                "capacity": e.capacity,
                "current_cars": round(cars, 3),
                "ratio": round(ratio, 4) if math.isfinite(ratio) else ratio,
                "travel_time": round(travel_time, 3) if math.isfinite(travel_time) else travel_time,
                "road_class": road_class,
                "is_arterial": is_arterial,
                "score": round(road_score, 3),
            })
        edges = _limit_viewport_edges(edges, max_edges, use_rep=use_rep)

        truncated = source_vertex_count > len(vertices) or len(vp.edges) > len(edges)
        return jsonify({
            "vertices": vertices,
            "edges": edges,
            "representative": use_rep,
            "lod": "overview" if use_rep else "detail",
            "truncated": truncated,
            "total_vertices_in_view": source_vertex_count,
            "total_edges_returned": len(edges),
        })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Nearest vertex ────────────────────────────────────────────────────────

@app.route("/api/nearest")
def nearest():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    x = float(request.args.get("x", 0))
    y = float(request.args.get("y", 0))
    v = engine.query_nearest_vertex(x, y)
    if v is None:
        return jsonify({"error": "not found"}), 404
    poi = v.metadata.get("poi") if isinstance(v.metadata, dict) else None
    return jsonify({
        "id": v.id, "x": v.x, "y": v.y,
        "is_poi":   bool(poi and poi.get("type")),
        "poi_type": str(poi["type"]) if poi else "",
    })


# ─── Nearby subgraph (F1) ─────────────────────────────────────────────────

@app.route("/api/nearby")
def nearby():
    if not engine.is_loaded:
        return jsonify({"vertices": [], "edges": []})
    x = float(request.args.get("x", 0))
    y = float(request.args.get("y", 0))
    k = max(1, int(request.args.get("k", 100)))
    try:
        nearby_verts, nearby_edges = engine.query_nearby_subgraph(x, y, k=k)
        vid_map = {v.id: v for _, v in nearby_verts}
        vertices = [{"id": v.id, "x": v.x, "y": v.y, "dist": round(d, 2)}
                    for d, v in nearby_verts]
        edges = []
        for e in nearby_edges:
            u_v = vid_map.get(e.u) or engine.graph.get_vertex(e.u)
            v_v = vid_map.get(e.v) or engine.graph.get_vertex(e.v)
            if u_v and v_v:
                edges.append({"x1": u_v.x, "y1": u_v.y, "x2": v_v.x, "y2": v_v.y})
        return jsonify({"vertices": vertices, "edges": edges, "center": {"x": x, "y": y}})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Shortest path (F3) ───────────────────────────────────────────────────

@app.route("/api/path")
def find_path():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    start_id = int(request.args.get("start", 0))
    end_id   = int(request.args.get("end",   0))
    algo     = request.args.get("algo", "astar")
    trace    = request.args.get("trace", "false").lower() == "true"
    max_trace = max(0, int(request.args.get("max_trace", 2500)))
    try:
        result = engine.shortest_path(
            start_id, end_id, algorithm=algo,
            trace=trace, max_trace=max_trace,
        )
        return jsonify(_path_payload(result, include_trace=trace))
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Traffic-aware path (F5) ──────────────────────────────────────────────

@app.route("/api/traffic_path")
def traffic_path():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    start_id  = int(request.args.get("start", 0))
    end_id    = int(request.args.get("end",   0))
    algo      = request.args.get("algo", "astar")
    c         = float(request.args.get("c",         1.5))
    threshold = float(request.args.get("threshold", 0.8))
    trace     = request.args.get("trace", "false").lower() == "true"
    max_trace = max(0, int(request.args.get("max_trace", 2500)))
    try:
        t_res  = engine.traffic_aware_path(start_id, end_id, algorithm=algo,
                                            c=c, threshold=threshold,
                                            trace=trace, max_trace=max_trace)
        s_res  = engine.shortest_path(start_id, end_id, algorithm=algo)

        edge_levels = []
        for i in range(len(t_res.path) - 1):
            e = engine.graph.get_edge(t_res.path[i], t_res.path[i + 1])
            edge_levels.append(e.congestion_level() if e else 0)

        payload = _path_payload(t_res, include_trace=trace)
        payload.update({
            "edge_levels":       edge_levels,
            "distance":          t_res.distance,
            "static_distance":   s_res.distance,
            "saved":             s_res.distance - t_res.distance,
            "congestion_count":  sum(1 for lv in edge_levels if lv >= 2),
            "elapsed_ms":        t_res.elapsed_ms,
        })
        return jsonify(payload)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/compare_algorithms")
def compare_algorithms():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    start_id = int(request.args.get("start", 0))
    end_id = int(request.args.get("end", 0))
    trace = request.args.get("trace", "false").lower() == "true"
    max_trace = max(0, int(request.args.get("max_trace", 2500)))
    try:
        astar_res = engine.shortest_path(
            start_id, end_id, algorithm="astar",
            trace=trace, max_trace=max_trace,
        )
        dijkstra_res = engine.shortest_path(
            start_id, end_id, algorithm="dijkstra",
            trace=trace, max_trace=max_trace,
        )
        dijkstra_visits = max(1, dijkstra_res.nodes_visited)
        visit_reduction = (
            (dijkstra_res.nodes_visited - astar_res.nodes_visited)
            / dijkstra_visits
            * 100
        )
        return jsonify({
            "astar": _path_payload(astar_res, include_trace=trace),
            "dijkstra": _path_payload(dijkstra_res, include_trace=trace),
            "visit_reduction_percent": round(visit_reduction, 2),
            "time_delta_ms": round(dijkstra_res.elapsed_ms - astar_res.elapsed_ms, 3),
            "distance_delta": round(astar_res.distance - dijkstra_res.distance, 6),
        })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/route/explain")
def route_explain():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    start_id = int(request.args.get("start", 0))
    end_id = int(request.args.get("end", 0))
    algo = request.args.get("algo", "astar")
    trace = request.args.get("trace", "false").lower() == "true"
    max_trace = max(0, int(request.args.get("max_trace", 2500)))
    try:
        return jsonify(_route_explain_payload(
            start_id, end_id, algo,
            trace=trace, max_trace=max_trace,
        ))
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Traffic simulation (F4) ──────────────────────────────────────────────

@app.route("/api/sim/start", methods=["POST"])
def sim_start():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 400

    data = request.get_json() or {}
    cars      = int(data.get("cars",        1500))
    seed      = int(data.get("seed",        2026))
    dens_lo   = float(data.get("density_low",  0.15))
    dens_hi   = float(data.get("density_high", 0.55))
    dens      = (dens_lo, dens_hi)
    c         = float(data.get("c",         1.0))
    threshold = float(data.get("threshold", 0.8))
    try:
        _start_background_simulation(cars=cars, seed=seed, density=dens, c=c, threshold=threshold)
        return jsonify({"status": "started"})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/sim/stop", methods=["POST"])
def sim_stop():
    # Non-blocking: just signal the thread to stop, it will exit on its own
    _sim_stop_event.set()
    _invalidate_analytics_cache()
    return jsonify({"status": "stopped"})


@app.route("/api/sim/speed", methods=["POST"])
def set_sim_speed():
    global _sim_speed
    data = request.get_json() or {}
    _sim_speed = max(1, min(500, int(data.get("speed", 1))))
    return jsonify({"speed": _sim_speed})


@app.route("/api/sim/state")
def sim_state():
    if not engine.is_loaded or engine.traffic_simulator is None:
        return jsonify({"error": "no_simulation"}), 404
    stopped = _sim_stop_event.is_set()
    try:
        snap = engine.get_traffic_snapshot()
        result = _snap_dict(snap)
        if not stopped:
            cars = engine.get_car_snapshot(limit=2000)
            result["cars"] = [{"x": c.x, "y": c.y} for c in cars if c.x is not None]
        else:
            result["cars"] = []
        return jsonify(result)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/traffic/inject", methods=["POST"])
def inject_traffic():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    data = request.get_json() or {}
    try:
        x = float(data.get("x", 0))
        y = float(data.get("y", 0))
        radius = float(data.get("radius", 100))
        intensity = float(data.get("intensity", 50))
        affected = engine.inject_traffic_event(
            x, y, radius=radius, intensity=intensity,
        )
        _invalidate_analytics_cache()
        return jsonify({"affected": affected, "x": x, "y": y, "radius": radius})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/traffic/history")
def traffic_history():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    x      = float(request.args.get("x", 1000))
    y      = float(request.args.get("y",  750))
    t      = int(request.args.get("t", 0))
    radius = float(request.args.get("r", 300))
    try:
        edges, states = engine.query_traffic_at_time(x, y, t, radius=radius)
        result_edges = []
        for e in edges:
            u_v = engine.graph.get_vertex(e.u)
            v_v = engine.graph.get_vertex(e.v)
            if u_v and v_v:
                key   = (min(e.u, e.v), max(e.u, e.v))
                state = states.get(key)
                lv = state.level if state else 0
                result_edges.append({
                    "x1": u_v.x, "y1": u_v.y, "x2": v_v.x, "y2": v_v.y,
                    "level": lv,
                })
        return jsonify({"edges": result_edges, "center": {"x": x, "y": y}, "time": t})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── POI search ───────────────────────────────────────────────────────────

@app.route("/api/poi/categories")
def poi_categories():
    return jsonify({
        "categories": [
            {"id": "gas_station", "label": "加油站"},
            {"id": "restaurant", "label": "餐厅"},
            {"id": "parking", "label": "停车场"},
            {"id": "repair", "label": "维修"},
            {"id": "hospital", "label": "医院"},
        ]
    })


@app.route("/api/poi/search")
def poi_search():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    x = float(request.args.get("x", 1000))
    y = float(request.args.get("y", 750))
    category = request.args.get("category", "").strip()
    k = max(1, int(request.args.get("k", 12)))
    radius_arg = request.args.get("radius")
    radius = float(radius_arg) if radius_arg not in (None, "") else None
    categories = [category] if category and category != "all" else None
    try:
        pois = engine.query_nearby_pois(x, y, k=k, categories=categories, radius=radius)
        return jsonify({
            "center": {"x": x, "y": y},
            "pois": [_poi_payload(poi) for poi in pois],
        })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Analytics and demo orchestration ─────────────────────────────────────

@app.route("/api/analytics/traffic")
def analytics_traffic():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    try:
        return jsonify(_get_cached_analytics_payload())
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/demo/setup", methods=["POST"])
def demo_setup():
    data = request.get_json() or {}
    n = max(100, min(30000, int(data.get("n", 10000))))
    seed = int(data.get("seed", 2026))
    async_requested = request.args.get("async", "false").lower() == "true" or bool(data.get("async"))
    if async_requested:
        run_id = uuid.uuid4().hex[:12]
        _set_demo_run(run_id, status="running", step_index=0, progress=0.0, message=DEMO_STEPS[0])

        def _worker():
            try:
                result = _build_demo_payload(n, seed, run_id=run_id)
                _set_demo_run(
                    run_id, status="done", step_index=len(DEMO_STEPS) - 1,
                    progress=1.0, message="演示剧本准备完成", result=result,
                )
            except Exception as exc:
                _set_demo_run(
                    run_id, status="error", step_index=-1,
                    progress=1.0, message="演示剧本准备失败", error=str(exc),
                )

        threading.Thread(target=_worker, daemon=True).start()
        return jsonify(_get_demo_run(run_id))

    try:
        return jsonify(_build_demo_payload(n, seed))
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/demo/status")
def demo_status():
    run_id = request.args.get("run_id", "").strip()
    if not run_id:
        return jsonify({"error": "run_id required"}), 400
    status = _get_demo_run(run_id)
    if status is None:
        return jsonify({"error": "run_not_found"}), 404
    return jsonify(status)


@app.route("/api/route/subgraph")
def route_subgraph():
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 404
    raw_ids = request.args.get("path", "")
    start_id = request.args.get("start")
    end_id = request.args.get("end")
    algo = request.args.get("algo", "astar")
    max_nodes = max(20, min(600, int(request.args.get("max_nodes", 220))))
    max_edges = max(20, min(1200, int(request.args.get("max_edges", 520))))
    try:
        if raw_ids:
            path_ids = [int(part) for part in raw_ids.split(",") if part.strip()]
        elif start_id is not None and end_id is not None:
            result = engine.shortest_path(int(start_id), int(end_id), algorithm=algo, trace=True, max_trace=2500)
            path_ids = result.path
        else:
            return jsonify({"error": "path or start/end required"}), 400
        return jsonify(_route_subgraph_payload(path_ids, max_nodes=max_nodes, max_edges=max_edges))
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Helpers ──────────────────────────────────────────────────────────────

def _set_cache_info(hit: bool, key: str, path: str) -> None:
    _last_cache_info.update({"hit": bool(hit), "key": key, "path": path})


def _invalidate_analytics_cache() -> None:
    with _analytics_lock:
        _analytics_cache.update({"payload": None, "updated_at": 0.0, "time_step": -1, "map_key": ""})


def _analytics_map_key() -> str:
    if not engine.is_loaded:
        return "no_map"
    graph = engine.graph
    return f"{graph.vertex_count if graph else 0}:{getattr(graph, 'seed', None)}:{_last_cache_info.get('key', '')}"


def _store_analytics_payload(payload) -> None:
    with _analytics_lock:
        _analytics_cache.update({
            "payload": payload,
            "updated_at": time.time(),
            "time_step": int(payload.get("time_step", 0)),
            "map_key": _analytics_map_key(),
        })


def _get_cached_analytics_payload():
    now = time.time()
    simulator = engine.traffic_simulator
    current_step = int(getattr(simulator, "time_step", 0) or 0)
    map_key = _analytics_map_key()
    with _analytics_lock:
        payload = _analytics_cache.get("payload")
        if (
            payload is not None
            and _analytics_cache.get("map_key") == map_key
            and (now - float(_analytics_cache.get("updated_at", 0.0))) < 1.25
            and (simulator is None or int(_analytics_cache.get("time_step", -1)) >= current_step - 30)
        ):
            cached = dict(payload)
            cached["cache_hit"] = True
            cached["cache_age_ms"] = round((now - float(_analytics_cache.get("updated_at", now))) * 1000, 1)
            return cached

    payload = _traffic_analytics_payload()
    payload["cache_hit"] = False
    payload["cache_age_ms"] = 0
    _store_analytics_payload(payload)
    return payload


def _set_demo_run(run_id: str, **updates) -> None:
    with _demo_lock:
        state = _demo_runs.get(run_id, {
            "run_id": run_id,
            "status": "queued",
            "step_index": 0,
            "steps": DEMO_STEPS,
            "progress": 0.0,
            "message": "",
            "result": None,
            "error": "",
        })
        state.update(updates)
        state["run_id"] = run_id
        state["steps"] = DEMO_STEPS
        _demo_runs[run_id] = state


def _get_demo_run(run_id: str):
    with _demo_lock:
        state = _demo_runs.get(run_id)
        if state is None:
            return None
        return dict(state)


def _demo_progress(run_id: str, step_index: int, message: str = "") -> None:
    if not run_id:
        return
    progress = (step_index + 0.15) / max(1, len(DEMO_STEPS))
    _set_demo_run(
        run_id,
        status="running",
        step_index=max(0, min(step_index, len(DEMO_STEPS) - 1)),
        progress=round(min(progress, 0.96), 3),
        message=message or DEMO_STEPS[min(step_index, len(DEMO_STEPS) - 1)],
    )


def _build_demo_payload(n: int, seed: int, *, run_id: str = ""):
    _demo_progress(run_id, 0)
    current = engine.get_stats() if engine.is_loaded else {}
    if (
        not engine.is_loaded
        or int(current.get("vertices", 0)) != n
        or int(current.get("seed") or -1) != seed
    ):
        _load_or_generate_map(n, seed=seed, width=2000, height=1500, poi_density=0.08)

    _demo_progress(run_id, 1)
    _start_background_simulation(cars=1800, seed=seed, density=(0.18, 0.58), c=1.0, threshold=0.8)

    _demo_progress(run_id, 2)
    start_v, end_v, static_res = _choose_demo_route()
    incident = _incident_from_path(static_res)

    _demo_progress(run_id, 3)
    affected = engine.inject_traffic_event(
        incident["x"], incident["y"],
        radius=incident["radius"],
        intensity=incident["intensity"],
    )
    for _ in range(4):
        engine.step_simulation(steps=1, spawn_count=5)

    _demo_progress(run_id, 4)
    static_trace_res = engine.shortest_path(
        start_v.id, end_v.id, algorithm="astar", trace=True, max_trace=2500
    )

    _demo_progress(run_id, 5)
    traffic_res = engine.traffic_aware_path(
        start_v.id, end_v.id, algorithm="astar", trace=True, max_trace=2500
    )
    route_explain = _route_explain_payload(
        start_v.id, end_v.id, "astar",
        trace=False, max_trace=0,
        static_res=static_trace_res,
        traffic_res=traffic_res,
    )

    _demo_progress(run_id, 6)
    static_payload = _path_payload(static_trace_res, include_trace=True)
    traffic_payload = _path_payload(traffic_res, include_trace=True)
    incident["affected_edges"] = affected
    analytics = _get_cached_analytics_payload()

    return {
        "stats": _get_stats(),
        "start": _vertex_payload(start_v),
        "end": _vertex_payload(end_v),
        "incident": incident,
        "static_path": static_payload,
        "traffic_path": traffic_payload,
        "metrics": {
            "static_distance": static_trace_res.distance,
            "traffic_time": traffic_res.distance,
            "static_hops": max(0, len(static_trace_res.path) - 1),
            "traffic_hops": max(0, len(traffic_res.path) - 1),
            "avoided_congested_edges": _count_congested_edges(static_trace_res) - _count_congested_edges(traffic_res),
            "affected_edges": affected,
            "active_cars": analytics.get("active_cars", 0),
            "average_ratio": analytics.get("average_ratio", 0),
        },
        "route_explain": route_explain,
    }


def _map_cache_key(
    n_vertices: int,
    *,
    seed: int,
    width: float = 2000,
    height: float = 1500,
    poi_density: float = 0.08,
) -> str:
    density = int(round(poi_density * 10000))
    return (
        f"{MAP_CACHE_VERSION}_n{int(n_vertices)}_seed{int(seed)}_"
        f"w{int(width)}_h{int(height)}_poi{density}"
    )


def _map_cache_path(key: str) -> Path:
    return MAP_CACHE_DIR / f"{key}.compact.json"


def _load_or_generate_map(
    n_vertices: int,
    *,
    seed: int = 2026,
    width: float = 2000,
    height: float = 1500,
    poi_density: float = 0.08,
):
    key = _map_cache_key(
        n_vertices, seed=seed,
        width=width, height=height,
        poi_density=poi_density,
    )
    cache_path = _map_cache_path(key)
    if cache_path.exists():
        try:
            engine.load_map(str(cache_path))
            _set_cache_info(True, key, str(cache_path))
            _invalidate_analytics_cache()
            return _get_stats()
        except Exception:
            # Corrupt or stale cache: regenerate in place without failing the demo.
            pass

    engine.generate_map(
        n_vertices=n_vertices,
        width=width,
        height=height,
        seed=seed,
        poi_density=poi_density,
    )
    try:
        if engine.graph is not None:
            GraphSerializer.save_compact(engine.graph, cache_path)
    except Exception:
        pass
    _set_cache_info(False, key, str(cache_path))
    _invalidate_analytics_cache()
    return _get_stats()


def _limit_viewport_edges(edges, max_edges: int, *, use_rep: bool = False):
    if len(edges) <= max_edges:
        return edges

    def score(row):
        ratio = float(row.get("ratio", 0))
        if not math.isfinite(ratio):
            ratio = 10.0
        return (
            int(row.get("level", 0)),
            ratio,
            int(row.get("capacity", 0)),
            float(row.get("length", 0)),
        )

    if use_rep:
        limited = heapq.nlargest(max_edges, edges, key=score)
    else:
        stride = max(1, math.ceil(len(edges) / max_edges))
        limited = edges[::stride][:max_edges]
    return limited


def _edge_visual_rank(edge, *, level: int = None, ratio: float = None):
    level = edge.congestion_level() if level is None else int(level)
    if ratio is None:
        ratio = congestion_ratio(float(edge.current_cars), edge.capacity)
    safe_ratio = float(ratio) if math.isfinite(float(ratio)) else 3.0
    score = float(edge.capacity) * 1.0 + float(edge.length) * 0.28 + level * 120.0 + safe_ratio * 55.0
    if edge.capacity >= 160 or score >= 250:
        return "arterial", True, score
    if edge.capacity >= 95 or score >= 150:
        return "collector", False, score
    return "local", False, score


def _edge_payload_from_state(edge, u_v, v_v, *, current_cars=None, ratio=None, level=None, travel_time=None):
    cars = float(edge.current_cars if current_cars is None else current_cars)
    ratio = congestion_ratio(cars, edge.capacity) if ratio is None else ratio
    level = edge.congestion_level() if level is None else int(level)
    travel_time = edge.travel_time() if travel_time is None else travel_time
    road_class, is_arterial, score = _edge_visual_rank(edge, level=level, ratio=ratio)
    return {
        "u": edge.u,
        "v": edge.v,
        "x1": u_v.x,
        "y1": u_v.y,
        "x2": v_v.x,
        "y2": v_v.y,
        "length": round(edge.length, 3),
        "capacity": edge.capacity,
        "current_cars": round(cars, 3),
        "ratio": round(ratio, 4) if math.isfinite(ratio) else ratio,
        "level": level,
        "travel_time": round(travel_time, 3) if math.isfinite(travel_time) else travel_time,
        "road_class": road_class,
        "is_arterial": is_arterial,
        "score": round(score, 3),
    }


def _sample_minimap_edges(*, max_edges: int, grid_cols: int, grid_rows: int):
    graph = engine.graph
    map_w = max(1.0, float(getattr(graph, "width", 2000)))
    map_h = max(1.0, float(getattr(graph, "height", 1500)))
    cell_w = map_w / max(1, grid_cols)
    cell_h = map_h / max(1, grid_rows)
    grid_best = {}
    top_heap = []
    arterial = []
    counter = 0

    for edge in engine.graph.edges():
        u_v = engine.graph.get_vertex(edge.u)
        v_v = engine.graph.get_vertex(edge.v)
        if u_v is None or v_v is None:
            continue
        cars = float(edge.current_cars)
        ratio = congestion_ratio(cars, edge.capacity)
        level = edge.congestion_level()
        _, is_arterial, score = _edge_visual_rank(edge, level=level, ratio=ratio)
        sample = (score, edge, u_v, v_v, cars, ratio, level)

        mid_x = (u_v.x + v_v.x) / 2.0
        mid_y = (u_v.y + v_v.y) / 2.0
        cell = (
            min(grid_cols - 1, max(0, int(mid_x / cell_w))),
            min(grid_rows - 1, max(0, int(mid_y / cell_h))),
        )
        current = grid_best.get(cell)
        if current is None or score > current[0]:
            grid_best[cell] = sample

        top_item = (score, counter, sample)
        counter += 1
        top_keep = max(120, max_edges // 3)
        if len(top_heap) < top_keep:
            heapq.heappush(top_heap, top_item)
        elif top_item > top_heap[0]:
            heapq.heapreplace(top_heap, top_item)

        if is_arterial and len(arterial) < max_edges:
            arterial.append(sample)

    merged = {}
    def add_sample(sample):
        _, edge, u_v, v_v, cars, ratio, level = sample
        key = (edge.u, edge.v)
        if key not in merged:
            merged[key] = _edge_payload_from_state(edge, u_v, v_v, current_cars=cars, ratio=ratio, level=level)

    for sample in arterial:
        add_sample(sample)
    for sample in grid_best.values():
        add_sample(sample)
    for _, _, sample in sorted(top_heap, reverse=True):
        add_sample(sample)
    edges = list(merged.values())
    edges.sort(key=lambda row: (row.get("is_arterial", False), row.get("score", 0)), reverse=True)
    return edges[:max_edges]


def _start_background_simulation(
    *,
    cars: int = 1500,
    seed: int = 2026,
    density=(0.15, 0.55),
    c: float = 1.0,
    threshold: float = 0.8,
) -> None:
    global _sim_thread

    _sim_stop_event.set()
    if _sim_thread is not None and _sim_thread.is_alive():
        _sim_thread.join(timeout=2.0)

    engine.start_simulation(
        car_count=0,
        c=c,
        threshold=threshold,
        initial_density=density,
        seed=seed,
    )
    _invalidate_analytics_cache()
    _sim_stop_event.clear()

    def _loop():
        sim = engine.traffic_simulator
        if sim is None:
            return
        spawned = 0
        tick = 0
        while not _sim_stop_event.is_set():
            try:
                steps = max(1, _sim_speed)
                for _ in range(steps):
                    if _sim_stop_event.is_set():
                        return
                    sc = min(5, cars - spawned) if spawned < cars else 0
                    sim.step(spawn_count=sc, return_snapshot=False)
                    if sc:
                        spawned += sc
                tick += steps
                if tick % 20 == 0 and not _sim_stop_event.is_set():
                    snap = sim.get_traffic_snapshot()
                    engine._traffic_history.add_snapshot(snap)
                    payload = _traffic_analytics_payload(snapshot=snap)
                    payload["cache_hit"] = False
                    payload["cache_age_ms"] = 0
                    _store_analytics_payload(payload)
                sim._sync_graph_edges()
            except Exception:
                pass
            _sim_stop_event.wait(timeout=0.03)

    _sim_thread = threading.Thread(target=_loop, daemon=True)
    _sim_thread.start()


def _vertex_payload(vertex):
    poi = vertex.metadata.get("poi") if isinstance(vertex.metadata, dict) else None
    return {
        "id": vertex.id,
        "x": vertex.x,
        "y": vertex.y,
        "is_poi": bool(poi and poi.get("type")),
        "poi_type": str(poi.get("type", "")) if poi else "",
        "poi_name": str(poi.get("name", "")) if poi else "",
    }


def _poi_payload(poi):
    return {
        "id": poi.vertex.id,
        "x": poi.vertex.x,
        "y": poi.vertex.y,
        "distance": round(poi.distance, 2),
        "poi_type": poi.poi_type,
        "name": poi.name,
        "metadata": poi.metadata,
    }


def _path_payload(result, *, include_trace: bool = False):
    coords = engine.path_coordinates(result) if result.found else []
    payload = {
        "found": result.found,
        "path": [{"x": x, "y": y} for x, y in coords],
        "path_vertex_ids": list(result.path),
        "distance": result.distance,
        "hops": max(0, len(result.path) - 1),
        "nodes_visited": result.nodes_visited,
        "elapsed_ms": result.elapsed_ms,
        "algorithm": result.algorithm,
        "trace_truncated": bool(result.trace_truncated),
        "visited": [],
        "relaxed_edges": [],
    }
    if include_trace:
        payload["visited"] = [_trace_vertex(vid) for vid in result.visited]
        payload["relaxed_edges"] = [_trace_edge(u, v) for u, v in result.relaxed_edges]
    return payload


def _trace_vertex(vertex_id: int):
    vertex = engine.graph.get_vertex(vertex_id) if engine.graph else None
    if vertex is None:
        return {"id": vertex_id}
    return {"id": vertex_id, "x": vertex.x, "y": vertex.y}


def _trace_edge(u: int, v: int):
    u_v = engine.graph.get_vertex(u) if engine.graph else None
    v_v = engine.graph.get_vertex(v) if engine.graph else None
    payload = {"u": u, "v": v}
    if u_v is not None and v_v is not None:
        payload.update({"x1": u_v.x, "y1": u_v.y, "x2": v_v.x, "y2": v_v.y})
    return payload


def _edge_key(u: int, v: int):
    return (min(u, v), max(u, v))


def _edge_payload(u: int, v: int):
    edge = engine.graph.get_edge(u, v) if engine.graph else None
    u_v = engine.graph.get_vertex(u) if engine.graph else None
    v_v = engine.graph.get_vertex(v) if engine.graph else None
    if edge is None or u_v is None or v_v is None:
        return None

    cars = float(edge.current_cars)
    ratio = congestion_ratio(cars, edge.capacity)
    level = edge.congestion_level()
    travel_time = edge.travel_time()
    return _edge_payload_from_state(
        edge, u_v, v_v,
        current_cars=cars,
        ratio=ratio,
        level=level,
        travel_time=travel_time,
    )


def _path_edge_details(path_ids):
    details = []
    for i in range(len(path_ids) - 1):
        payload = _edge_payload(path_ids[i], path_ids[i + 1])
        if payload is not None:
            details.append(payload)
    return details


def _route_subgraph_payload(path_ids, *, max_nodes: int, max_edges: int):
    if not path_ids:
        return {
            "nodes": [],
            "edges": [],
            "path_vertex_ids": [],
            "visited_ids": [],
            "relaxed_edges": [],
            "truncated": False,
        }

    selected = []
    selected_set = set()
    queue = []
    for vid in path_ids:
        if vid not in selected_set and engine.graph.get_vertex(vid) is not None:
            selected.append(vid)
            selected_set.add(vid)
            queue.append(vid)
        if len(selected) >= max_nodes:
            break

    idx = 0
    while idx < len(queue) and len(selected) < max_nodes:
        vid = queue[idx]
        idx += 1
        neighbors = sorted(
            engine.graph.get_neighbors(vid),
            key=lambda e: (_edge_visual_rank(e)[2], -e.length),
            reverse=True,
        )
        for edge in neighbors[:8]:
            other = edge.other(vid)
            if other not in selected_set:
                selected.append(other)
                selected_set.add(other)
                queue.append(other)
                if len(selected) >= max_nodes:
                    break

    nodes = []
    for vid in selected:
        vertex = engine.graph.get_vertex(vid)
        if vertex is None:
            continue
        nodes.append({
            "id": vid,
            "x": vertex.x,
            "y": vertex.y,
            "is_path": vid in set(path_ids),
        })

    path_edges = {_edge_key(path_ids[i], path_ids[i + 1]) for i in range(len(path_ids) - 1)}
    edge_rows = []
    seen = set()
    for vid in selected:
        for edge in engine.graph.get_neighbors(vid):
            key = _edge_key(edge.u, edge.v)
            if key in seen or edge.u not in selected_set or edge.v not in selected_set:
                continue
            u_v = engine.graph.get_vertex(edge.u)
            v_v = engine.graph.get_vertex(edge.v)
            if u_v is None or v_v is None:
                continue
            row = _edge_payload_from_state(edge, u_v, v_v)
            row["is_path"] = key in path_edges
            edge_rows.append(row)
            seen.add(key)

    edge_rows.sort(key=lambda row: (row.get("is_path", False), row.get("score", 0)), reverse=True)
    truncated = len(edge_rows) > max_edges or len(selected) >= max_nodes
    return {
        "nodes": nodes[:max_nodes],
        "edges": edge_rows[:max_edges],
        "path_vertex_ids": path_ids,
        "visited_ids": path_ids[:max_nodes],
        "relaxed_edges": [{"u": row["u"], "v": row["v"]} for row in edge_rows[:max_edges] if row.get("is_path")],
        "truncated": truncated,
    }


def _worst_edge(details):
    if not details:
        return None
    return max(details, key=lambda row: (row.get("ratio", 0), row.get("current_cars", 0)))


def _sum_finite(details, field: str) -> float:
    total = 0.0
    for row in details:
        value = float(row.get(field, 0))
        if math.isfinite(value):
            total += value
    return total


def _route_explain_payload(
    start_id: int,
    end_id: int,
    algo: str = "astar",
    *,
    trace: bool = False,
    max_trace: int = 2500,
    static_res=None,
    traffic_res=None,
):
    if static_res is None:
        static_res = engine.shortest_path(
            start_id, end_id, algorithm=algo,
            trace=trace, max_trace=max_trace,
        )
    if traffic_res is None:
        traffic_res = engine.traffic_aware_path(
            start_id, end_id, algorithm=algo,
            trace=trace, max_trace=max_trace,
        )

    static_details = _path_edge_details(static_res.path)
    traffic_details = _path_edge_details(traffic_res.path)
    static_levels = [int(row["level"]) for row in static_details]
    traffic_levels = [int(row["level"]) for row in traffic_details]
    static_congested_keys = {
        _edge_key(row["u"], row["v"]) for row in static_details
        if int(row.get("level", 0)) >= 2
    }
    traffic_keys = {_edge_key(row["u"], row["v"]) for row in traffic_details}
    traffic_congested = sum(1 for row in traffic_details if int(row.get("level", 0)) >= 2)
    avoided = len(static_congested_keys - traffic_keys)
    static_traffic_time = _sum_finite(static_details, "travel_time")
    traffic_traffic_time = _sum_finite(traffic_details, "travel_time")
    static_length = _sum_finite(static_details, "length")
    traffic_length = _sum_finite(traffic_details, "length")
    time_delta = static_traffic_time - traffic_traffic_time
    length_delta = traffic_length - static_length

    if not static_res.found or not traffic_res.found:
        summary = "当前起终点暂未找到完整可通行路径，请重新选择路线。"
    elif avoided > 0 and time_delta >= 0:
        summary = (
            f"静态路线经过 {len(static_congested_keys)} 段拥堵/严重拥堵，"
            f"交通感知路线绕开了其中 {avoided} 段，预计节省 {time_delta:.1f} 通行时间。"
        )
    elif avoided > 0:
        summary = (
            f"交通感知路线绕开了 {avoided} 段拥堵道路，但绕行距离增加 {length_delta:.1f}，"
            "适合展示安全避堵而非最短距离。"
        )
    elif traffic_congested < len(static_congested_keys):
        summary = (
            f"交通感知路线将拥堵段从 {len(static_congested_keys)} 段降至 {traffic_congested} 段，"
            "主要收益来自降低高拥堵边的通行代价。"
        )
    else:
        summary = (
            "当前交通状态下两条路线差异较小，说明起终点之间暂未形成明显绕行机会。"
        )

    static_payload = _path_payload(static_res, include_trace=trace)
    traffic_payload = _path_payload(traffic_res, include_trace=trace)
    traffic_payload.update({
        "edge_levels": traffic_levels,
        "static_distance": static_res.distance,
        "saved": static_res.distance - traffic_res.distance,
        "congestion_count": traffic_congested,
    })

    return {
        "static_path": static_payload,
        "traffic_path": traffic_payload,
        "static_edge_levels": static_levels,
        "traffic_edge_levels": traffic_levels,
        "static_edge_details": static_details,
        "traffic_edge_details": traffic_details,
        "worst_static_edge": _worst_edge(static_details),
        "worst_traffic_edge": _worst_edge(traffic_details),
        "static_congested_edges": len(static_congested_keys),
        "traffic_congested_edges": traffic_congested,
        "avoided_congested_edges": avoided,
        "summary": summary,
        "metrics": {
            "static_length": round(static_length, 3),
            "traffic_length": round(traffic_length, 3),
            "extra_length": round(length_delta, 3),
            "static_traffic_time": round(static_traffic_time, 3),
            "traffic_traffic_time": round(traffic_traffic_time, 3),
            "time_delta": round(time_delta, 3),
        },
    }


def _traffic_analytics_payload(snapshot=None):
    level_counts = {"0": 0, "1": 0, "2": 0, "3": 0}
    top_heap = []
    counter = 0
    if snapshot is None and engine.traffic_simulator is None:
        active_cars = 0
        average_ratio = 0.0
        max_ratio = 0.0
        time_step = 0
        states = []
        for edge in engine.graph.edges():
            ratio = congestion_ratio(float(edge.current_cars), edge.capacity)
            states.append((edge.u, edge.v, edge.capacity, float(edge.current_cars), ratio, edge.congestion_level(), edge.travel_time()))
    else:
        if snapshot is None:
            snapshot = engine.get_traffic_snapshot()
        active_cars = snapshot.active_cars
        average_ratio = snapshot.average_ratio
        max_ratio = snapshot.max_ratio
        time_step = snapshot.time_step
        states = [
            (state.u, state.v, state.capacity, state.current_cars, state.ratio, state.level, state.travel_time)
            for state in snapshot.edge_states.values()
        ]

    for u, v, capacity, current_cars, ratio, level, travel_time in states:
        level_counts[str(max(0, min(3, level)))] += 1
        u_v = engine.graph.get_vertex(u)
        v_v = engine.graph.get_vertex(v)
        if u_v and v_v:
            edge = engine.graph.get_edge(u, v)
            road_class, is_arterial, score = ("local", False, 0.0)
            length = 0.0
            if edge:
                length = edge.length
                road_class, is_arterial, score = _edge_visual_rank(edge, level=level, ratio=ratio)
            row = {
                "u": u, "v": v,
                "x1": u_v.x, "y1": u_v.y,
                "x2": v_v.x, "y2": v_v.y,
                "length": round(length, 3),
                "capacity": capacity,
                "current_cars": round(current_cars, 2),
                "ratio": round(ratio, 4) if math.isfinite(ratio) else ratio,
                "level": level,
                "travel_time": round(travel_time, 2) if math.isfinite(travel_time) else travel_time,
                "road_class": road_class,
                "is_arterial": is_arterial,
                "score": round(score, 3),
            }
            score_ratio = float(ratio) if math.isfinite(ratio) else 10.0
            item = (score_ratio, float(current_cars), counter, row)
            counter += 1
            if len(top_heap) < 10:
                heapq.heappush(top_heap, item)
            elif item > top_heap[0]:
                heapq.heapreplace(top_heap, item)
    top = [item[3] for item in sorted(top_heap, reverse=True)]

    history = []
    for t in engine._traffic_history.time_steps[-80:]:
        snap = engine._traffic_history.history[t]
        history.append({
            "time_step": snap.time_step,
            "average_ratio": round(snap.average_ratio, 4),
            "max_ratio": round(snap.max_ratio, 4),
            "active_cars": snap.active_cars,
        })

    return {
        "time_step": time_step,
        "active_cars": active_cars,
        "average_ratio": round(average_ratio, 4),
        "max_ratio": round(max_ratio, 4),
        "level_counts": level_counts,
        "top_congested_edges": top,
        "history": history,
    }


def _choose_demo_route():
    stats = engine.get_stats()
    w = stats.get("width", 2000)
    h = stats.get("height", 1500)
    candidates = [
        ((w * 0.10, h * 0.15), (w * 0.90, h * 0.85)),
        ((w * 0.12, h * 0.82), (w * 0.88, h * 0.18)),
        ((w * 0.18, h * 0.50), (w * 0.92, h * 0.52)),
        ((w * 0.50, h * 0.12), (w * 0.52, h * 0.90)),
    ]
    best = None
    for (sx, sy), (ex, ey) in candidates:
        s_v = engine.query_nearest_vertex(sx, sy)
        e_v = engine.query_nearest_vertex(ex, ey)
        if not s_v or not e_v or s_v.id == e_v.id:
            continue
        result = engine.shortest_path(s_v.id, e_v.id, algorithm="astar")
        if result.found:
            score = result.distance + len(result.path) * 15
            if best is None or score > best[0]:
                best = (score, s_v, e_v, result)
    if best is None:
        vertices = list(engine.graph.vertices())
        s_v, e_v = vertices[0], vertices[-1]
        result = engine.shortest_path(s_v.id, e_v.id, algorithm="astar")
        return s_v, e_v, result
    return best[1], best[2], best[3]


def _incident_from_path(result):
    coords = engine.path_coordinates(result)
    if not coords:
        stats = engine.get_stats()
        return {"x": stats.get("width", 2000) / 2, "y": stats.get("height", 1500) / 2, "radius": 120, "intensity": 90}
    x, y = coords[len(coords) // 2]
    return {"x": x, "y": y, "radius": 150, "intensity": 120}


def _count_congested_edges(result) -> int:
    total = 0
    for i in range(len(result.path) - 1):
        edge = engine.graph.get_edge(result.path[i], result.path[i + 1])
        if edge and edge.congestion_level() >= 2:
            total += 1
    return total


def _get_stats():
    s = engine.get_stats()
    return {
        "vertices":           s.get("vertices", 0),
        "edges":              s.get("edges", 0),
        "poi_count":          s.get("poi_count", 0),
        "connected":          s.get("connected", False),
        "width":              s.get("width", 2000),
        "height":             s.get("height", 1500),
        "seed":               s.get("seed"),
        "simulation_running": s.get("simulation_running", False),
        "cache_hit":          bool(_last_cache_info.get("hit")),
        "cache_key":          _last_cache_info.get("key") or "",
    }


def _snap_dict(snap):
    return {
        "time_step":    snap.time_step,
        "total_cars":   snap.total_cars,
        "active_cars":  snap.active_cars,
        "average_ratio": round(snap.average_ratio, 3),
        "max_ratio":     round(snap.max_ratio, 3),
    }


@app.route("/<path:path>")
def spa_fallback(path):
    if path.startswith("api/"):
        return jsonify({"error": "not_found"}), 404
    static_root = Path(app.static_folder or "web_ui")
    requested = static_root / path
    if requested.is_file():
        return send_from_directory(str(static_root), path)
    return send_from_directory(str(static_root), "index.html")


# ─── Launch ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 5678
    url  = f"http://localhost:{port}"

    def _open():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()
    print(f"\n  [NAV]  Navigation System Web UI")
    print(f"  -->  {url}\n")
    print("  Ctrl+C to stop\n")
    app.run(host="localhost", port=port, debug=False, threaded=True)
