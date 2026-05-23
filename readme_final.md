# Navigation System - 综合说明文档

本项目是《Data Structure Design》导航系统课设项目，主要包含底层的导航地图数据结构、路线规划算法、交通模拟机制，以及配合展示的 GUI 和 Web 界面。

## 项目核心功能

本项目通过 `navigation.NavigationEngine` 提供了所有的核心功能能力：

1. **地图生成与数据 I/O**
   - 随机生成包含指定数量顶点的城市地图（基于 Delaunay 三角剖分与 MST 生成路网）。
   - 支持将生成的地图加载与保存为 JSON 格式。
2. **地图信息查询 (F1/F2/POI)**
   - **附近状态查询**：根据给定坐标查询最近的顶点、关联道路以及特定的 POI（如加油站、餐厅、停车场）。
   - **视口状态查询**：根据地图的可视范围矩形查询内部的点与边，在缩小地图时支持“代表点模式”以优化查询与渲染性能。
3. **最短路径规划 (F3)**
   - 提供基于 Dijkstra 与 A* 算法的最短路径搜索。可以通过算法参数切换，其中 A* 算法更适合大规模的二维地图寻路。
4. **交通模拟机制 (F4)**
   - 支持动态生成交通背景流。
   - 显式管理车辆位置与移动状态，并将不同的道路标记为不同的拥堵等级（畅通、缓行、拥堵、严重拥堵），支持生成车辆和路况快照以供界面定时刷新。
5. **交通感知路径 (F5)**
   - 根据当前的实时交通情况（通过模拟计算的道路通过时间）重新规划最短通行时间的路径，从而实现避堵。
6. **GUI / Web 交互**
   - 提供了基于 `main_gui.py` 的桌面可视化应用，可以直观地显示地图、进行寻路点击、展示路况颜色及车辆动画。
   - 同时还提供了 Web 版本的实现（位于 `web_ui` 目录下及 `web_server.py`）。

## 如何使用本项目

### 1. 环境配置

请在安装了相关依赖的 Python 环境中运行。在项目根目录下执行以下命令以安装所需库（如 numpy, scipy, PySide6 等）：

```powershell
python -X utf8 -m pip install -r requirements.txt
```

### 2. 代码级接口调用

可以在其他 Python 脚本中直接引用 `NavigationEngine` 来调用核心功能：

```python
from navigation import NavigationEngine

# 初始化引擎并生成包含 10000 个点的城市地图
engine = NavigationEngine()
engine.generate_map(n_vertices=10000, width=2000, height=1500, seed=2026, poi_density=0.08)

# 将地图保存至本地
engine.save_map("city_map.json")

# 也可以直接加载已存在的地图
# engine.load_map("city_map.json")

# 查询 (500, 400) 坐标附近的点、边以及 20 个 POI 信息
nearby_state = engine.query_nearby_state(x=500, y=400, k=100, poi_k=20)

# 使用 A* 算法规划两点间的最短路径
path_result = engine.shortest_path(start_id=0, end_id=9999, algorithm="astar")
path_coords = engine.path_coordinates(path_result) # 获取具体坐标用于绘制

# 启动并推进交通模拟
engine.start_simulation(seed=2026, initial_density=(0.1, 0.7))
engine.step_simulation(steps=1)

# 基于当前拥堵情况，规划最优通行时间路径
traffic_aware_result = engine.traffic_aware_path(start_id=0, end_id=9999, algorithm="astar")
```

### 3. 运行可视化界面

如果需要以图形化界面直接体验导航系统：
- **运行桌面客户端**：在根目录下运行 `python main_gui.py`，启动基于 PySide6 的可视化导航应用。
- **运行 Web 服务**：在根目录下运行 `python web_server.py`，然后访问 `http://localhost:5678/`。生产页面位于 `web_ui`，由 Flask 直接托管；前端源码位于 `web_client`，开发或重新构建时运行 `npm install && npm run build`。

### 4. 运行功能测试与性能评估

若要验证底层结构的正确性以及测试性能指标，可以运行相关的测试脚本：

```powershell
python -X utf8 test_phase1.py               # 测试图结构、地图生成、序列化
python -X utf8 test_phase2.py               # 测试 KD-Tree 与路径算法
python -X utf8 test_traffic_simulator.py    # 测试交通模拟
python -X utf8 test_phase4.py               # 测试 API / POI / DTO
python -X utf8 test_web_api.py              # 测试 Web API / 演示 / POI / 算法轨迹
python -X utf8 benchmark_phase4.py          # 运行 10000 点的综合性能基准评估
```
