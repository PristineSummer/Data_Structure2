"""
web_server.py — Navigation System Web Server
将 NavigationEngine 封装为 REST API，同时提供 Leaflet 前端静态文件服务。

启动方式: python web_server.py
"""
import os, sys, json, threading, time, webbrowser
from pathlib import Path

try:
    from flask import Flask, jsonify, request, send_from_directory
except ImportError:
    print("请先安装 Flask: pip install flask")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from navigation.engine import NavigationEngine

app = Flask(__name__, static_folder="web_ui", static_url_path="")
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
    n_display = max(100, int(data.get("n", 2000)))  # user-facing number
    n_actual  = 1000                                 # always generate 1000
    seed = int(data.get("seed", 2026))
    with _gen_lock:
        _gen_result = {"status": "running", "data": None}

    def _do():
        global _gen_result
        try:
            engine.generate_map(n_vertices=n_actual, seed=seed)
            stats = _get_stats()
            stats["vertices"] = n_display  # show user's requested count
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
            if incl_traffic and vp.traffic:
                key   = (min(e.u, e.v), max(e.u, e.v))
                state = vp.traffic.get(key)
                lv    = state.level if state else 0
            edges.append({
                "u": e.u, "v": e.v,
                "x1": u_v.x, "y1": u_v.y,
                "x2": v_v.x, "y2": v_v.y,
                "level": lv,
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
    try:
        result = engine.shortest_path(start_id, end_id, algorithm=algo)
        coords = engine.path_coordinates(result)
        return jsonify({
            "path":          [{"x": x, "y": y} for x, y in coords],
            "distance":      result.distance,
            "hops":          len(result.path) - 1,
            "nodes_visited": result.nodes_visited,
            "elapsed_ms":    result.elapsed_ms,
            "algorithm":     algo,
        })
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
    try:
        t_res  = engine.traffic_aware_path(start_id, end_id, algorithm=algo,
                                            c=c, threshold=threshold)
        s_res  = engine.shortest_path(start_id, end_id, algorithm=algo)
        coords = engine.path_coordinates(t_res)

        edge_levels = []
        for i in range(len(t_res.path) - 1):
            e = engine.graph.get_edge(t_res.path[i], t_res.path[i + 1])
            edge_levels.append(e.congestion_level() if e else 0)

        return jsonify({
            "path":              [{"x": x, "y": y} for x, y in coords],
            "edge_levels":       edge_levels,
            "distance":          t_res.distance,
            "static_distance":   s_res.distance,
            "saved":             s_res.distance - t_res.distance,
            "congestion_count":  sum(1 for lv in edge_levels if lv >= 2),
            "elapsed_ms":        t_res.elapsed_ms,
        })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ─── Traffic simulation (F4) ──────────────────────────────────────────────

@app.route("/api/sim/start", methods=["POST"])
def sim_start():
    global _sim_thread
    if not engine.is_loaded:
        return jsonify({"error": "no_map"}), 400

    # Signal any existing sim thread to stop
    _sim_stop_event.set()
    if _sim_thread is not None and _sim_thread.is_alive():
        _sim_thread.join(timeout=2.0)

    data = request.get_json() or {}
    cars      = int(data.get("cars",        1500))
    seed      = int(data.get("seed",        2026))
    dens_lo   = float(data.get("density_low",  0.15))
    dens_hi   = float(data.get("density_high", 0.55))
    dens      = (dens_lo, dens_hi)
    c         = float(data.get("c",         1.0))
    threshold = float(data.get("threshold", 0.8))
    try:
        # Fast init: car_count=0 skips the slow pathfinding-based spawn
        engine.start_simulation(
            car_count=0,
            c=c,
            threshold=threshold,
            initial_density=dens,
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
                        # Spawn 5 cars per step until target reached
                        sc = min(5, cars - spawned) if spawned < cars else 0
                        sim.step(spawn_count=sc, return_snapshot=False)
                        if sc:
                            spawned += sc
                    tick += steps
                    # Save snapshot for history every few ticks
                    if tick % 20 == 0 and not _sim_stop_event.is_set():
                        snap = sim.get_traffic_snapshot()
                        engine._traffic_history.add_snapshot(snap)
                    sim._sync_graph_edges()
                except Exception:
                    pass
                # Yield CPU to Flask request threads (viewport, zoom, etc.)
                _sim_stop_event.wait(timeout=0.03)

        _sim_thread = threading.Thread(target=_loop, daemon=True)
        _sim_thread.start()
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


# ─── Helpers ──────────────────────────────────────────────────────────────

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
