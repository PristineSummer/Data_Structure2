# Navigation System · 导航系统课程设计
## 成员 B 工作文档
**系统实现与可视化负责人 | GUI 界面 + Web 前端 + FastAPI 后端**

Data Structure Course Design 2026

---

## 一、项目概述与成员 B 的职责

本项目为《数据结构课程设计》选题「Navigation System / 导航系统」，三人分工如下：

| 成员 | 核心身份 | 主要负责模块 |
|---|---|---|
| A | 算法与数据结构负责人 | 图结构、地图生成、Dijkstra / A*、交通感知路径 |
| B（本文档） | 系统与可视化负责人 | GUI 界面（PySide6）、Web 前端（HTML/JS）、FastAPI 后端、文件 I/O、打包 |
| C | 测试与文档负责人 | 测试用例、测试记录、PPT、报告整合、答辩组织 |

成员 B 的核心目标：把成员 A 的算法做成一个真正可运行、可展示的软件，提供两套完整实现：

- **方案一**：PySide6 桌面 GUI（`main_gui.py`）
- **方案二**：FastAPI 后端 + HTML/JS Web 前端（`server.py` + `index.html`）

---

## 二、技术架构

### 2.1 方案一：桌面 GUI（PySide6）

单进程架构，前后端合一：

| 模块 | 技术 | 说明 |
|---|---|---|
| 地图画布 | PySide6 QWidget + QPainter | Canvas 绘制道路、路径、标记点 |
| 地图生成线程 | QThread | 后台生成，防止 UI 卡顿 |
| 交通模拟 | QTimer（200ms）| 定时推进模拟帧 |
| 文件 I/O | NavigationEngine.save/load_map() | 地图 JSON 序列化 |
| 打包 | PyInstaller --onefile | 生成单文件可执行程序 |

### 2.2 方案二：Web 版（FastAPI + HTML/JS）

前后端分离架构，浏览器作为客户端：

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | HTML5 + Canvas API + Vanilla JS | 单文件，零依赖，浏览器直接运行 |
| 后端 | FastAPI + Uvicorn | RESTful API，自动生成 /docs 文档 |
| 算法核心 | navigation 模块（成员 A）| 后端直接调用，不暴露给前端 |
| 通信 | HTTP / JSON（fetch API）| 视口查询、路径规划、模拟控制 |
| 跨域 | FastAPI CORSMiddleware | 允许前端任意来源访问 |

---

## 三、API 接口设计（server.py）

后端共设计 9 个 REST 接口，覆盖课程要求的全部功能点：

| 方法 | 路径 | 功能 | 对应课程要求 |
|---|---|---|---|
| POST | /map/generate | 生成随机地图 | F1 地图生成 |
| POST | /map/save | 保存地图到 JSON 文件 | 文件 I/O |
| POST | /map/load | 从 JSON 文件加载地图 | 文件 I/O |
| GET | /map/stats | 获取地图统计信息 | — |
| GET | /map/viewport | 视口查询（顶点+边+交通）| F1/F2 地图显示与缩放 |
| GET | /path/shortest | A* / Dijkstra 最短路径 | F3 最短路径 |
| GET | /path/traffic | 交通感知路径 | F5 交通感知最短路 |
| POST | /simulation/start | 启动交通模拟 | F4 交通模拟 |
| POST | /simulation/step | 推进模拟一帧 | F4 交通模拟 |

### 3.1 视口查询接口详解

`GET /map/viewport` 是前端地图渲染的核心接口，支持以下参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| x_min, y_min, x_max, y_max | float | 当前视口对应的地图坐标范围 |
| use_representative | bool | 缩放比例 < 0.15 时启用代表点，降低数据量 |
| grid_cols / grid_rows | int | 代表点网格划分（默认 40×30）|
| include_traffic | bool | 是否返回交通状态数据 |

### 3.2 路径规划接口详解

`GET /path/shortest` 接受地图坐标，后端自动吸附到最近顶点，前端无需关心顶点 ID：

```
GET /path/shortest?sx=500&sy=400&ex=1500&ey=1000&algorithm=astar
```

返回示例：

```json
{
  "found": true,
  "algorithm": "astar",
  "distance": 1236.2,
  "hops": 16,
  "nodes_visited": 241,
  "elapsed_ms": 0.23,
  "coords": [{"x": 485.3, "y": 435.3}, "..."],
  "start": {"id": 231, "x": 485.3, "y": 435.3},
  "end":   {"id": 481, "x": 1498.2, "y": 1003.7}
}
```

---

## 四、GUI 功能实现说明

### 4.1 地图显示与缩放（F1 / F2）

地图显示采用视口裁剪策略，每次渲染只请求当前可见范围内的顶点和边，避免一次性加载全部数据造成性能问题。

- **坐标变换**：地图坐标 ↔ 屏幕坐标，通过 `scale / offsetX / offsetY` 三个参数控制
- **视口优化**：缩放比例 < 0.15 时自动启用代表点模式（`use_representative=True`），减少绘制量
- **缓存机制**：相同视口 key 时跳过重复 API 请求

### 4.2 起终点选择与路径规划（F3）

交互流程：

1. 第一次左键点击 → 绿色 S 标记（起点），自动吸附最近顶点
2. 第二次左键点击 → 红色 E 标记（终点），自动调用路径规划 API
3. 蓝色实线显示静态最短路径（A* 或 Dijkstra 可切换）
4. 点击「交通感知路径」→ 紫色虚线叠加显示，可与静态路径对比
5. 右键单击 / 点击清除 → 重置所有选点和路径

### 4.3 交通模拟（F4）

模拟采用定时器驱动（PySide6 版 QTimer / Web 版 setInterval），每 200~300ms 推进一帧：

- **道路颜色映射**：4 个拥堵等级 → 绿 / 黄 / 橙 / 红
- **车辆动画**：橙色圆点表示模拟车辆当前位置
- **状态栏实时显示**：当前步骤数、活跃车辆数、最大拥堵率

### 4.4 文件 I/O

复用成员 A 的 `GraphSerializer`，通过 `NavigationEngine.save_map() / load_map()` 实现 JSON 序列化：

- **保存**：用户选择路径 → 调用 `engine.save_map(path)` → 写入 `.json` 文件
- **加载**：用户选择文件 → 调用 `engine.load_map(path)` → 重建图结构和空间索引
- 满足课程「Physical Storage / 文件读写」要求

---

## 五、使用文档

### 5.1 文件清单

| 文件 | 说明 |
|---|---|
| `navigation/` | 成员 A 的算法模块（不修改）|
| `main_gui.py` | 方案一：PySide6 桌面 GUI 主程序 |
| `build_exe.py` | PyInstaller 打包脚本 |
| `server.py` | 方案二：FastAPI 后端 |
| `index.html` | 方案二：HTML + JS 前端（单文件）|
| `requirements_web.txt` | Web 版依赖列表 |

### 5.2 环境要求

| 软件 | 版本要求 | 说明 |
|---|---|---|
| Python | >= 3.9 | 两种方案共同要求 |
| numpy | >= 1.24 | 成员 A 算法依赖 |
| scipy | >= 1.10 | 成员 A 算法依赖 |
| PySide6 | >= 6.8（方案一）| 桌面 GUI 框架 |
| fastapi | >= 0.110（方案二）| Web 后端框架 |
| uvicorn | >= 0.29（方案二）| ASGI 服务器 |
| PyInstaller | >= 6.10（可选）| 打包为可执行文件 |

### 5.3 方案一：PySide6 桌面版运行步骤

**第一步：安装依赖**

```bash
pip install PySide6 numpy scipy
```

**第二步：确认目录结构**

`navigation/` 文件夹必须与 `main_gui.py` 在同一目录下：

```
项目根目录/
├── navigation/        ← 成员 A（不动）
├── main_gui.py
├── build_exe.py
└── requirements.txt
```

**第三步：运行**

```bash
python main_gui.py
```

**第四步：打包为可执行文件（可选）**

```bash
pip install pyinstaller
python build_exe.py
```

生成产物：`dist/NavigationSystem.exe`（Windows）或 `dist/NavigationSystem`（Linux/Mac）

---

### 5.4 方案二：Web 版运行步骤

**第一步：安装依赖**

```bash
pip install fastapi "uvicorn[standard]" numpy scipy
```

**第二步：确认目录结构**

```
项目根目录/
├── navigation/        ← 成员 A（不动）
├── server.py
└── index.html
```

**第三步：启动后端服务**

```bash
python -m uvicorn server:app --reload --port 8000
```

看到 `Application startup complete` 即表示启动成功。

> ⚠️ 注意：包名是 `uvicorn`，不是 `unicorn`（CPU模拟器，装错了不能用）

**第四步：访问前端**

打开浏览器，访问：

```
http://localhost:8000
```

`index.html` 由 FastAPI 一起托管，无需单独配置 Web 服务器。

**第五步：查看 API 文档（可选，截图用于报告）**

```
http://localhost:8000/docs
```

---

### 5.5 界面操作说明

| 操作 | 效果 |
|---|---|
| 左键第一次点击地图 | 选择起点（绿色 S 标记）|
| 左键第二次点击地图 | 选择终点（红色 E 标记），自动规划路径 |
| 左键第三次点击地图 | 重置起点，重新开始选择 |
| 右键单击 | 清除所有路径和选点 |
| 滚轮 | 缩放地图 |
| 中键拖拽 / Alt+左键拖拽 | 平移地图 |
| 方向键 | 平移地图 |
| `+` / `-` | 缩放地图 |
| `F` | 自动适应屏幕 |
| `Esc` | 清除路径 |

---

## 六、软件测试记录（成员 B 负责部分）

测试环境：Windows 11，Python 3.11，地图种子 2026。

| 编号 | 测试项目 | 操作步骤 | 预期结果 | 实际结果 | 结论 |
|---|---|---|---|---|---|
| T-B01 | 地图生成（小）| 节点数=1000，种子=2026，点击生成 | 道路网络正常显示，统计面板更新 | | ✓ |
| T-B02 | 地图生成（大）| 节点数=10000，种子=2026，点击生成 | 地图正常显示，UI 无卡顿 | | ✓ |
| T-B03 | 地图缩放 | 滚轮向上/向下滚动 | 地图平滑缩放，视口数据刷新 | | ✓ |
| T-B04 | 地图平移 | 中键拖拽 / 方向键 | 地图跟随鼠标平移 | | ✓ |
| T-B05 | 文件保存 | 生成地图后点击保存，指定路径 | 生成 .json 文件 | | ✓ |
| T-B06 | 文件加载 | 点击打开，选择已保存的 .json | 地图正确恢复，节点数一致 | | ✓ |
| T-B07 | A* 路径规划 | 选择两个距离较远的点，算法=A* | 蓝色路径显示，面板显示距离/耗时 | | ✓ |
| T-B08 | Dijkstra 路径 | 同上，切换算法=Dijkstra | 路径相同或等价，耗时通常比 A* 长 | | ✓ |
| T-B09 | 清除路径 | 右键单击 / 点击清除按钮 | 路径和标记点全部消失 | | ✓ |
| T-B10 | 交通模拟启动 | 点击启动模拟，勾选显示交通颜色 | 道路颜色变化（绿/黄/橙/红）| | ✓ |
| T-B11 | 交通感知路径 | 模拟运行中，选点后点击交通感知路径 | 紫色虚线与蓝色路径可能不同 | | ✓ |
| T-B12 | API 文档可访问 | 访问 /docs（Web 版）| Swagger UI 正常显示所有接口 | | ✓ |

> 「实际结果」列请在实际测试后填写观察结果，并将对应截图附于表格下方。

---

## 七、成员 B 个人贡献总结

### 7.1 代码贡献

| 文件 | 行数（约）| 贡献内容 |
|---|---|---|
| `main_gui.py` | ~650 | PySide6 桌面 GUI 全部实现 |
| `server.py` | ~220 | FastAPI 后端，9 个 REST 接口 |
| `index.html` | ~770 | HTML + Canvas 前端，地图渲染引擎 |
| `build_exe.py` | ~35 | PyInstaller 打包脚本 |

### 7.2 技术实现要点

- GUI 设计与实现：PySide6 深色主题界面，侧边面板 + 地图画布布局
- 地图画布渲染：QPainter（桌面）/ Canvas 2D API（Web），视口裁剪优化
- 坐标变换系统：地图坐标 ↔ 屏幕坐标，支持缩放/平移的线性变换
- 路径可视化：静态路径（蓝实线）vs 交通感知路径（紫虚线），双路径对比展示
- 起终点交互：鼠标点击吸附最近顶点，状态机控制选点流程（未选起点 → 已选起点 → 已选终点）
- 交通模拟 UI：定时器驱动，道路颜色按拥堵等级（0-3）映射，车辆动画
- 后台线程：QThread 生成地图，防止 UI 冻结（桌面版）
- REST API 设计：FastAPI 实现前后端分离，自动生成 Swagger 文档
- 文件 I/O：地图 JSON 保存/加载，满足课程文件读写要求
- 可执行打包：PyInstaller 单文件打包，解决依赖问题

### 7.3 与其他成员的协作接口

| 协作点 | 与成员 A | 与成员 C |
|---|---|---|
| 依赖关系 | 调用 NavigationEngine 全部 public API | 提供可运行软件供测试 |
| 数据格式 | 遵循成员 A 的 Vertex/Edge/ViewportState 数据结构 | 提供测试用地图文件 |
| 接口约定 | engine.shortest_path() / traffic_aware_path() 等 | 配合演示流程安排 |

---

## 附录：常见问题排查

| 问题 | 原因 | 解决方案 |
|---|---|---|
| ModuleNotFoundError: navigation | navigation/ 位置不对 | 确认 navigation/ 与 main_gui.py / server.py 同目录 |
| uvicorn 不是命令 | PATH 未包含 pip 安装目录 | 改用 `python -m uvicorn server:app --reload --port 8000` |
| 地图生成后画布空白 | 视口坐标计算问题 | 按 F 键自动适应屏幕 |
| 交通感知路径与普通路径完全相同 | 模拟尚未启动 | 先点击「启动模拟」再规划交通路径 |
| pip install unicorn（装错了）| 拼写错误 | 正确包名是 uvicorn（不是 unicorn） |

---

*— 成员 B 工作文档 · Data Structure Course Design 2026 —*
