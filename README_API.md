# 成员 A 后端 API 说明

本文档面向成员 B 的 GUI 集成。所有能力统一通过 `navigation.NavigationEngine` 暴露；旧接口继续可用，阶段四新增 DTO 方便直接绘图和显示。

## F1-F5 对照表

| 功能 | 后端接口 | 主要返回 | GUI 用法 |
|---|---|---|---|
| F1 地图显示 | `query_nearby_state(x, y, k=100, poi_k=20, poi_categories=None, poi_radius=None)` | `NearbyState` | 点击/悬停坐标后显示最近点、道路和 POI |
| F2 地图缩放 | `query_viewport_state(x_min, y_min, x_max, y_max, use_representative=False, grid_cols=20, grid_rows=15, include_traffic=True)` | `ViewportState` | 拖拽/缩放时刷新当前视口，可启用代表点 |
| F3 最短路径 | `shortest_path(start_id, end_id, algorithm="astar")` + `path_coordinates(result)` | `PathResult` + 坐标列表 | 高亮静态最短路线 |
| F4 交通模拟 | `start_simulation(...)`, `step_simulation(...)`, `get_traffic_snapshot()`, `get_car_snapshot()` | `TrafficSnapshot`, `CarState` | 定时器驱动交通颜色和车辆动画 |
| F5 交通感知路径 | `traffic_aware_path(start_id, end_id, algorithm="astar")` + `path_coordinates(result)` | `PathResult` + 坐标列表 | 基于当前拥堵状态重新规划最短通行时间路径 |
| POI 查询 | `query_nearby_pois(x, y, k=20, categories=None, radius=None)` | `list[POIResult]` | 地图上显示加油站、餐厅、停车场等 |
| 统计信息 | `get_stats()` | `dict` | 状态栏、调试面板、报告截图 |

## 最小集成示例

```python
from navigation import NavigationEngine

engine = NavigationEngine()
engine.generate_map(
    n_vertices=10000,
    width=2000,
    height=1500,
    seed=2026,
    poi_density=0.08,
)
engine.save_map("data/generated/city_map.json")
```

已保存地图可以直接加载：

```python
engine = NavigationEngine()
engine.load_map("data/generated/city_map.json")
```

## 地图、缩放、POI

```python
# F1：点击坐标附近内容
state = engine.query_nearby_state(500, 400, k=100, poi_k=20)
for _, vertex in state.vertices:
    draw_point(vertex.x, vertex.y)
for edge in state.edges:
    draw_line(*engine.edge_coordinates(edge))
for poi in state.pois:
    draw_poi(poi.vertex.x, poi.vertex.y, poi.poi_type, poi.name)

# F2：当前视口，缩小时启用代表点。
# include_traffic=True 时只生成当前视口道路的交通状态，适合 GUI 定时刷新。
viewport = engine.query_viewport_state(
    x_min=0,
    y_min=0,
    x_max=1000,
    y_max=800,
    use_representative=True,
    grid_cols=30,
    grid_rows=20,
)
```

`query_viewport_state()` 会自动归一化反向坐标，例如 `(1000, 800, 0, 0)` 也能正确查询。

## 路径绘制

```python
start = engine.query_nearest_vertex(click_start_x, click_start_y)
end = engine.query_nearest_vertex(click_end_x, click_end_y)

result = engine.shortest_path(start.id, end.id, algorithm="astar")
if result.found:
    coords = engine.path_coordinates(result)
    draw_polyline(coords, color="blue")
```

`PathResult` 关键字段：

| 字段 | 含义 |
|---|---|
| `found` | 是否找到路径 |
| `distance` | 总权重；静态路径为距离，交通路径为通行时间 |
| `path` | 顶点 ID 序列 |
| `edges` | 经过的边对象 |
| `nodes_visited` | 搜索访问节点数 |
| `elapsed_ms` | 算法耗时 |
| `algorithm` | `dijkstra` 或 `astar` |

## 交通模拟与车辆动画

```python
engine.start_simulation(
    seed=2026,
    initial_density=(0.1, 0.7),
    background_update_interval=4,
)

# GUI 定时器中调用
snapshot = engine.step_simulation(steps=1)
viewport = engine.query_viewport_state(0, 0, 1000, 800, include_traffic=True)

for edge in viewport.edges:
    traffic = viewport.traffic.get((min(edge.u, edge.v), max(edge.u, edge.v)))
    color = traffic_color(traffic.level if traffic else 0)
    draw_line(*engine.edge_coordinates(edge), color=color)

for car in engine.get_car_snapshot(limit=500):
    if car.x is not None and car.y is not None:
        draw_car(car.x, car.y)
```

交通等级建议配色：

| `level` | 状态 | 建议颜色 |
|---:|---|---|
| 0 | 畅通 | 绿色 |
| 1 | 缓行 | 黄色 |
| 2 | 拥堵 | 橙色 |
| 3 | 严重拥堵 | 红色 |

## 交通感知路径

```python
traffic_result = engine.traffic_aware_path(start.id, end.id, algorithm="astar")
if traffic_result.found:
    draw_polyline(engine.path_coordinates(traffic_result), color="red")
```

`traffic_aware_path()` 会使用当前 `TrafficSimulator` 的边权；如果还没启动模拟器，则使用边上已有 `current_cars` 计算通行时间。

## 返回对象字段

### `POIResult`

| 字段 | 类型 | 含义 |
|---|---|---|
| `vertex` | `Vertex` | POI 所在顶点 |
| `distance` | `float` | 查询点到 POI 的距离 |
| `poi_type` | `str` | 类型：`gas_station`、`restaurant`、`parking`、`repair`、`hospital` 等 |
| `name` | `str` | 显示名称 |
| `metadata` | `dict` | 原始 POI 元数据 |

### `NearbyState`

| 字段 | 类型 | 含义 |
|---|---|---|
| `center` | `(float, float)` | 查询坐标 |
| `vertices` | `list[(distance, Vertex)]` | 最近顶点 |
| `edges` | `list[Edge]` | 关联道路 |
| `pois` | `list[POIResult]` | 附近 POI |

### `ViewportState`

| 字段 | 类型 | 含义 |
|---|---|---|
| `bounds` | `(x_min, y_min, x_max, y_max)` | 已归一化视口 |
| `vertices` | `list[Vertex]` | 视口顶点 |
| `edges` | `list[Edge]` | 视口内部道路 |
| `traffic` | `dict[(u, v), EdgeTrafficState]` | 当前视口道路交通状态 |
| `representative` | `bool` | 是否使用代表点模式 |

## 异常处理建议

GUI 层建议把这些异常转成弹窗或状态栏提示：

| 异常 | 典型原因 | GUI 建议 |
|---|---|---|
| `RuntimeError` | 未生成/加载地图就查询或寻路 | 提示用户先生成或打开地图 |
| `ValueError` | `k <= 0`、网格数非法、半径非法、顶点 ID 不存在等 | 高亮输入框并提示合法范围 |
| `FileNotFoundError` | 地图文件路径不存在 | 提示重新选择文件 |
| `ValueError` from loader | JSON 格式错误或字段缺失 | 提示地图文件损坏 |

## 旧接口兼容

以下接口仍保留原返回类型，便于旧测试和已有代码继续运行：

- `query_nearby(x, y, k=100) -> list[(distance, Vertex)]`
- `query_nearby_subgraph(x, y, k=100, include_boundary_edges=True) -> (vertices, edges)`
- `query_viewport(...) -> (vertices, edges)`
- `shortest_path(...) -> PathResult`
- `traffic_aware_path(...) -> PathResult`
