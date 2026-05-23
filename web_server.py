"""
web_server.py — Navigation System Web Server
将 NavigationEngine 封装为 REST API，同时提供 Leaflet 前端静态文件服务。

启动方式: python web_server.py
"""
import math, os, sys, threading, time, webbrowser
from pathlib import Path

try:
    from flask import Flask, jsonify, request, send_from_directory
except ImportError:
    print("请先安装 Flask: pip install flask")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from navigation.engine import NavigationEngine
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


# ─── Static files ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("web_ui", "index.html")


# ─── Map management ────────────────────────────────────────────────────────

@app.route("/api/map/generate", methods=["POST"])
def generate_map():
    global _gen_result
    data = request.get_json() or {}
    n_actual = max(100, int(data.get("n", 10000)))
    seed = int(data.get("seed", 2026))
    with _gen_lock:
        _gen_result = {"status": "running", "data": None}

    def _do():
        global _gen_result
        try:
            engine.generate_map(n_vertices=n_actual, seed=seed)
            stats = _get_stats()
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
    """Return a heavily downsampled full-graph overview for the minimap canvas."""
    if not engine.is_loaded:
        return jsonify({"vertices": [], "edges": []})
    try:
        s = engine.get_stats()
        w = s.get("width",  2000)
        h = s.get("height", 1500)
        vp = engine.query_viewport_state(
            0, 0, w, h,
            use_representative=True,
            grid_cols=50, grid_rows=38,
            include_traffic=False,
        )
        vertices = [{"id": v.id, "x": v.x, "y": v.y} for v in vp.vertices]
        vid_map  = {v.id: v for v in vp.vertices}
        edges    = []
        for e in vp.edges:
            u_v = vid_map.get(e.u)
            v_v = vid_map.get(e.v)
            if u_v and v_v:
                edges.append({"x1": u_v.x, "y1": u_v.y,
                               "x2": v_v.x, "y2": v_v.y})
        return jsonify({"vertices": vertices, "edges": edges})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Viewport (F2) ────────────────────────────────────────────────────────

@app.route("/api/viewport")
def viewport():
    if not engine.is_loaded:
        return jsonify({"vertices": [], "edges": []})
    try:
        x_min = float(request.args.get("x_min", 0))
        y_min = float(request.args.get("y_min", 0))
        x_max = float(request.args.get("x_max", 2000))
        y_max = float(request.args.get("y_max", 1500))
        grid_cols      = max(5, int(request.args.get("grid_cols", 40)))
        grid_rows      = max(5, int(request.args.get("grid_rows", 30)))
        use_rep        = request.args.get("representative", "false").lower() == "true"
        incl_traffic   = request.args.get("traffic", "false").lower() == "true"

        vp = engine.query_viewport_state(
            x_min, y_min, x_max, y_max,
            use_representative=use_rep,
            grid_cols=grid_cols, grid_rows=grid_rows,
            include_traffic=incl_traffic,
        )

        vertices = []
        for v in vp.vertices:
            poi = v.metadata.get("poi") if isinstance(v.metadata, dict) else None
            vertices.append({
                "id": v.id, "x": v.x, "y": v.y,
                "is_poi":   bool(poi and poi.get("type")),
                "poi_type": str(poi["type"])  if poi else "",
                "poi_name": str(poi.get("name", poi["type"])) if poi else "",
            })

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
            })

        return jsonify({"vertices": vertices, "edges": edges})
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
        return jsonify(_traffic_analytics_payload())
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/demo/setup", methods=["POST"])
def demo_setup():
    data = request.get_json() or {}
    n = max(100, min(30000, int(data.get("n", 10000))))
    seed = int(data.get("seed", 2026))
    try:
        current_vertices = engine.get_stats().get("vertices", 0) if engine.is_loaded else 0
        if not engine.is_loaded or int(current_vertices) != n:
            engine.generate_map(n_vertices=n, width=2000, height=1500, seed=seed, poi_density=0.08)
        _start_background_simulation(cars=1800, seed=seed, density=(0.18, 0.58), c=1.0, threshold=0.8)

        start_v, end_v, static_res = _choose_demo_route()
        incident = _incident_from_path(static_res)
        affected = engine.inject_traffic_event(
            incident["x"], incident["y"],
            radius=incident["radius"],
            intensity=incident["intensity"],
        )
        for _ in range(5):
            engine.step_simulation(steps=1, spawn_count=5)

        traffic_res = engine.traffic_aware_path(
            start_v.id, end_v.id, algorithm="astar", trace=True, max_trace=2500
        )
        static_trace_res = engine.shortest_path(
            start_v.id, end_v.id, algorithm="astar", trace=True, max_trace=2500
        )

        static_payload = _path_payload(static_trace_res, include_trace=True)
        traffic_payload = _path_payload(traffic_res, include_trace=True)
        incident["affected_edges"] = affected

        return jsonify({
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
            },
        })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Helpers ──────────────────────────────────────────────────────────────

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


def _traffic_analytics_payload():
    level_counts = {"0": 0, "1": 0, "2": 0, "3": 0}
    top = []
    if engine.traffic_simulator is None:
        active_cars = 0
        average_ratio = 0.0
        max_ratio = 0.0
        time_step = 0
        states = []
        for edge in engine.graph.edges():
            ratio = congestion_ratio(float(edge.current_cars), edge.capacity)
            states.append((edge.u, edge.v, edge.capacity, float(edge.current_cars), ratio, edge.congestion_level(), edge.travel_time()))
    else:
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
            top.append({
                "u": u, "v": v,
                "x1": u_v.x, "y1": u_v.y,
                "x2": v_v.x, "y2": v_v.y,
                "capacity": capacity,
                "current_cars": round(current_cars, 2),
                "ratio": round(ratio, 4) if math.isfinite(ratio) else ratio,
                "level": level,
                "travel_time": round(travel_time, 2) if math.isfinite(travel_time) else travel_time,
            })
    top.sort(key=lambda row: (row["ratio"], row["current_cars"]), reverse=True)

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
        "top_congested_edges": top[:10],
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
