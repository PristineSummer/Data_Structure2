# Navigation System 后端项目

本项目是《Data Structure Design》导航系统课设的成员 A 后端交付：负责图数据结构、地图生成、KD-Tree 空间查询、Dijkstra/A* 最短路径、交通模拟、交通感知路径、POI 后端能力、测试与性能基准。成员 B 可在此基础上接入 GUI，成员 C 可直接运行测试并整理报告材料。

项目范围不包含 GUI 实现、PPT 制作和可执行程序打包。

## 功能完成情况

| 课题功能 | 后端完成情况 |
|---|---|
| F1 地图显示 | `query_nearby_state()` 返回最近 100 点、关联边、附近 POI |
| F2 地图缩放 | `query_viewport_state()` 返回视口点/边，支持代表点模式 |
| F3 最短路径 | `shortest_path()` 支持 Dijkstra 和 A* |
| F4 交通模拟 | `TrafficSimulator` 支持背景流、显式车辆、拥堵等级、车辆快照；视口交通状态按需局部返回 |
| F5 交通感知路径 | `traffic_aware_path()` 按当前交通通行时间规划路径 |
| 文件 I/O | `GraphSerializer` 和 `NavigationEngine.save_map/load_map()` 支持 JSON 保存加载 |
| POI | 地图生成时写入 `Vertex.metadata["poi"]`，并支持 KD-Tree POI 查询 |

## 环境配置

在任意已安装依赖的 Python 环境中运行即可。下面假设当前目录是本项目根目录，并且 `python` 指向要使用的虚拟环境解释器：

```powershell
cd <project-root>
python -X utf8 -m pip install -r requirements.txt
```

如果依赖已经安装，可直接运行测试脚本。项目主要依赖：

- `numpy`
- `scipy`
- `matplotlib`
- `PySide6`
- `pytest`

## 快速开始

```python
from navigation import NavigationEngine

engine = NavigationEngine()
engine.generate_map(n_vertices=10000, width=2000, height=1500, seed=2026)
engine.save_map("data/generated/city_map.json")

nearby = engine.query_nearby_state(500, 400)
path = engine.shortest_path(0, 9999, algorithm="astar")
coords = engine.path_coordinates(path)
```

加载已有地图：

```python
from navigation import NavigationEngine

engine = NavigationEngine()
engine.load_map("data/generated/city_map.json")
```

## 成员 B：GUI 集成指南

建议 GUI 只依赖 `NavigationEngine`，不要直接操作底层模块：

```python
from navigation import NavigationEngine

engine = NavigationEngine()
engine.load_map("data/generated/city_map.json")

# 鼠标点击：附近点、道路、POI
state = engine.query_nearby_state(mouse_x, mouse_y, k=100, poi_k=20)

# 地图拖拽/缩放：视口内容
viewport = engine.query_viewport_state(
    x_min, y_min, x_max, y_max,
    use_representative=zoomed_out,
    grid_cols=30,
    grid_rows=20,
)

# 起终点选择：普通最短路径
start = engine.query_nearest_vertex(start_x, start_y)
end = engine.query_nearest_vertex(end_x, end_y)
result = engine.shortest_path(start.id, end.id)
path_points = engine.path_coordinates(result)

# 交通模拟：定时器每帧推进
engine.start_simulation(seed=2026, initial_density=(0.1, 0.7))
snapshot = engine.step_simulation()
cars = engine.get_car_snapshot(limit=500)

# 交通感知路径
traffic_result = engine.traffic_aware_path(start.id, end.id)
traffic_path_points = engine.path_coordinates(traffic_result)
```

更完整的字段说明见 [README_API.md](README_API.md)。

## 成员 C：测试与报告指南

完整回归命令：

```powershell
cd <project-root>
python -X utf8 test_phase1.py
python -X utf8 test_phase2.py
python -X utf8 test_traffic_simulator.py
python -X utf8 test_phase4.py
python -X utf8 benchmark_phase4.py
```

性能基准会输出 Markdown 表格，可直接放进报告的“软件测试/性能测试”部分。算法流程、复杂度表和答辩要点见 [algorithm_analysis.md](algorithm_analysis.md)。

当前 10000 点基准目标：

| 项目 | 目标 |
|---|---:|
| 地图生成 + 索引 | `< 3000 ms` |
| KNN 查询 | `< 10 ms/query` |
| A* 路径 | `< 50 ms/route` |
| 交通模拟 | `< 100 ms/step` |

## 项目结构

```text
Data_Structure/
├── navigation/
│   ├── graph.py                 # Vertex / Edge / Graph 邻接表
│   ├── map_generator.py         # Delaunay + MST 地图生成和 POI
│   ├── serializer.py            # JSON 文件 I/O
│   ├── kdtree.py                # 自实现 KD-Tree
│   ├── pathfinding.py           # Dijkstra / A*
│   ├── traffic_model.py         # 交通通行时间公式
│   ├── traffic_simulator.py     # 交通流和车辆模拟
│   ├── engine.py                # 成员 B 使用的统一 API
│   └── __init__.py              # 对外导出
├── test_phase1.py               # 图结构、地图生成、序列化测试
├── test_phase2.py               # KD-Tree、路径算法、Engine 旧接口测试
├── test_traffic_simulator.py    # 交通模拟测试
├── test_phase4.py               # 阶段四 API / POI / DTO 测试
├── benchmark_phase4.py          # 10000 点性能基准
├── README_API.md                # GUI API 文档
├── algorithm_analysis.md        # 算法说明和复杂度分析
├── implementation_plan.md       # 成员 A 分阶段计划
├── Announcement.md              # 课程要求
└── 三人总体分工.md              # 小组分工
```

## GitHub 提交说明

`References/` 是本地参考代码目录，不应上传 GitHub。当前 `.gitignore` 已包含：

```gitignore
/References/
```

只要 `References/` 还没有被 Git 跟踪，就会被忽略。如果已经误加入暂存区，可在仓库根目录执行：

```powershell
git rm -r --cached References
```

该命令只取消 Git 跟踪，不删除本地文件。

## 常见问题

### 1. 未加载地图就查询时报错？

这是预期行为。`NavigationEngine` 在未生成或加载地图时会抛出 `RuntimeError`，GUI 应提示用户先生成/打开地图。

### 2. 为什么不用邻接矩阵？

10000 点邻接矩阵空间开销太大，而路网是稀疏图。邻接表空间复杂度为 `O(V + E)`，更符合课设目标。

### 3. POI 会破坏旧 JSON 格式吗？

不会。POI 只写入每个顶点已有的 `metadata` 字段中，顶层 JSON 仍然是 `meta / vertices / edges`。

### 4. A* 和 Dijkstra 怎么切换？

```python
engine.shortest_path(start_id, end_id, algorithm="dijkstra")
engine.shortest_path(start_id, end_id, algorithm="astar")
```

默认使用 `astar`，通常更适合大规模二维地图。

### 5. 交通颜色从哪里取？

调用 `query_viewport_state(..., include_traffic=True)` 后，读取 `viewport.traffic[(u, v)].level`。等级 0-3 分别表示畅通、缓行、拥堵、严重拥堵。
