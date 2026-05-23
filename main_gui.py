"""
Navigation System — GUI 主程序 v4 (Modern Light Theme)
成员 B：GUI 界面 + F1 坐标查询 + F3 静态路径 + F4 交通模拟 + F5 交通感知路径 + 时间交通查询
"""

import sys, os, math

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QFrame, QMessageBox,
    QGroupBox, QGridLayout, QSpinBox, QDoubleSpinBox,
    QCheckBox, QComboBox, QScrollArea, QSizePolicy, QTabWidget,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QLinearGradient, QRadialGradient,
    QPainterPath, QWheelEvent, QMouseEvent, QKeyEvent, QFontMetrics,
    QPalette,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 色彩 tokens  —— 现代浅色主题 (Google Maps 风)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
C = {
    # 地图底色
    "map_bg":      QColor("#E8EFF5"),
    "map_water":   QColor("#C9DCF0"),
    "map_road":    QColor("#FFFFFF"),
    "map_road2":   QColor("#D8DFE8"),
    "map_grid":    QColor("#DCE4EC"),

    # 面板 UI
    "bg":          QColor("#F0F4F8"),
    "panel":       QColor("#FFFFFF"),
    "surface":     QColor("#F8FAFC"),
    "border":      QColor("#E2E8F0"),
    "border2":     QColor("#CBD5E1"),

    # 文字
    "text":        QColor("#1E293B"),
    "muted":       QColor("#64748B"),
    "dim":         QColor("#94A3B8"),

    # 品牌色 (Google Blue)
    "brand":       QColor("#1A73E8"),
    "brand_light": QColor("#EBF3FD"),
    "brand_dark":  QColor("#1557B0"),

    # 状态色
    "green":       QColor("#16A34A"),
    "green_light": QColor("#DCFCE7"),
    "red":         QColor("#DC2626"),
    "red_light":   QColor("#FEE2E2"),
    "amber":       QColor("#D97706"),
    "amber_light": QColor("#FEF3C7"),
    "orange":      QColor("#EA580C"),
    "purple":      QColor("#7C3AED"),
    "purple_light":QColor("#EDE9FE"),

    # 地图元素
    "edge":        QColor("#BCC8D8"),
    "edge_hi":     QColor("#94A3B8"),
    "vertex":      QColor("#94A3B8"),
    "path_blue":   QColor("#1A73E8"),
    "path_purple": QColor("#7C3AED"),
}

TRAFFIC_COLORS = {
    0: QColor("#16A34A"),   # 畅通 — 绿
    1: QColor("#D97706"),   # 缓行 — 琥珀
    2: QColor("#EA580C"),   # 拥堵 — 橙
    3: QColor("#DC2626"),   # 严重 — 红
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 全局样式表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QSS = """
/* ── 全局 ── */
QMainWindow, QWidget#root {
    background: #F0F4F8;
    color: #1E293B;
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QWidget { color: #1E293B; }

/* ── 滚动条 ── */
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    background: #F1F5F9; width: 6px; border-radius: 3px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #CBD5E1; border-radius: 3px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #94A3B8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ── Tab ── */
QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: #FFFFFF; border-bottom: 2px solid #E2E8F0; }
QTabBar::tab {
    background: transparent; color: #64748B;
    padding: 10px 18px; border: none;
    border-bottom: 3px solid transparent;
    font-size: 12px; font-weight: 500; margin-bottom: -2px;
}
QTabBar::tab:selected {
    color: #1A73E8; border-bottom-color: #1A73E8; font-weight: 700;
}
QTabBar::tab:hover:!selected { color: #334155; background: #F8FAFC; }

/* ── 按钮通用（无色版，有色按钮由 make_btn 内联样式处理）── */
QPushButton {
    background: #FFFFFF; color: #374151;
    border: 1px solid #D1D5DB; border-radius: 8px;
    padding: 8px 14px; font-size: 12px; font-weight: 500;
}
QPushButton:hover:!disabled {
    background: #F8FAFC; border-color: #1A73E8; color: #1A73E8;
}
QPushButton:pressed:!disabled { background: #EBF3FD; }
QPushButton:disabled { color: #9CA3AF; border-color: #E5E7EB; background: #F9FAFB; }

/* ── 输入控件 ── */
QSpinBox, QDoubleSpinBox, QComboBox {
    background: #FFFFFF; border: 1.5px solid #E2E8F0;
    border-radius: 8px; padding: 6px 10px;
    color: #1E293B; font-size: 12px;
    selection-background-color: #1A73E8;
}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #1A73E8;
    background: #FAFCFF;
}
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {
    border-color: #94A3B8;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    border: none; background: transparent; width: 16px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 8px;
    selection-background-color: #EBF3FD;
    selection-color: #1A73E8;
    color: #1E293B;
    padding: 4px;
}

/* ── 标签 ── */
QLabel { color: #1E293B; }
QLabel#muted     { color: #64748B; font-size: 12px; }
QLabel#section   { font-size: 10px; font-weight: 700; color: #94A3B8;
                   text-transform: uppercase; letter-spacing: 1px; }
QLabel#val       { color: #1A73E8; font-weight: 700; font-size: 13px; }
QLabel#val_grn   { color: #16A34A; font-weight: 700; font-size: 13px; }
QLabel#val_amb   { color: #D97706; font-weight: 700; font-size: 13px; }
QLabel#val_red   { color: #DC2626; font-weight: 700; font-size: 13px; }
QLabel#title     { font-size: 16px; font-weight: 800; color: #1A73E8; }
QLabel#subtitle  { font-size: 11px; color: #94A3B8; }

/* ── Checkbox ── */
QCheckBox { color: #374151; font-size: 12px; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1.5px solid #D1D5DB; border-radius: 4px;
    background: #FFFFFF;
}
QCheckBox::indicator:checked {
    background: #1A73E8; border-color: #1A73E8;
    image: none;
}
QCheckBox::indicator:hover { border-color: #1A73E8; }

/* ── 状态栏 ── */
QStatusBar {
    background: #FFFFFF; border-top: 1px solid #E2E8F0;
    color: #64748B; font-size: 11px; padding: 0 8px;
}
QStatusBar::item { border: none; }

/* ── GroupBox ── */
QGroupBox {
    border: 1.5px solid #E2E8F0; border-radius: 10px;
    margin-top: 12px; padding-top: 8px;
    font-size: 10px; font-weight: 700;
    color: #94A3B8; background: #FFFFFF;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UI 组件
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Card(QFrame):
    """精致卡片容器，带阴影效果和可选的左侧色条装饰"""
    def __init__(self, parent=None, accent_color=None):
        super().__init__(parent)
        self._accent = accent_color
        self.setStyleSheet("""
            QFrame {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
        """)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 12, 14, 14)
        self._lay.setSpacing(8)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._accent:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(self._accent))
            # 左侧圆角色条
            r = QPainterPath()
            r.addRoundedRect(QRectF(0, 8, 4, self.height() - 16), 2, 2)
            p.drawPath(r)

    def layout(self): return self._lay
    def addWidget(self, w): self._lay.addWidget(w)
    def addLayout(self, l): self._lay.addLayout(l)

    def add_title(self, text, icon=""):
        row = QHBoxLayout()
        row.setSpacing(6)
        if icon:
            ic = QLabel(icon)
            ic.setStyleSheet("font-size:14px; color:#1A73E8; padding:0;")
            row.addWidget(ic)
        lbl = QLabel(text.upper())
        lbl.setObjectName("section")
        row.addWidget(lbl)
        row.addStretch()
        self._lay.addLayout(row)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #F1F5F9; max-height: 1px; margin: 0;")
        self._lay.addWidget(sep)
        return lbl

    def add_row(self, label, widget):
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label)
        lbl.setObjectName("muted")
        lbl.setMinimumWidth(72)
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        self._lay.addLayout(row)

    def add_info(self, label, val_id="val"):
        row = QHBoxLayout()
        row.setSpacing(4)
        k = QLabel(label)
        k.setObjectName("muted")
        v = QLabel("—")
        v.setObjectName(val_id)
        v.setAlignment(Qt.AlignRight)
        row.addWidget(k)
        row.addStretch()
        row.addWidget(v)
        self._lay.addLayout(row)
        return v


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #E2E8F0; max-height: 1px;")
    return f


# 有色按钮的内联样式表（不使用 objectName/ID 选择器，彻底规避 QSS 优先级问题）
_BTN_STYLES = {
    "primary": ("#1A73E8", "#FFFFFF", "#1557B0", "#1E7FF0", 700),
    "success": ("#16A34A", "#FFFFFF", "#15803D", "#15803D", 600),
    "danger":  ("#FFFFFF", "#DC2626", "#FECACA", "#FEF2F2", 500),
    "purple":  ("#7C3AED", "#FFFFFF", "#6D28D9", "#6D28D9", 600),
    "amber":   ("#FFFFFF", "#D97706", "#FDE68A", "#FFFBEB", 500),
}

def make_btn(text, style="", enabled=True):
    b = QPushButton(text)
    b.setEnabled(enabled)
    b.setCursor(Qt.PointingHandCursor)
    if style in _BTN_STYLES:
        bg, color, border, hover_bg, weight = _BTN_STYLES[style]
        # 内联样式直接设置到 widget 上，无需 ID 选择器
        b.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {color};
                border: 1px solid {border}; border-radius: 8px;
                padding: 8px 14px; font-size: 12px; font-weight: {weight};
            }}
            QPushButton:hover:!disabled {{
                background: {hover_bg}; color: {color}; border-color: {border};
            }}
            QPushButton:pressed:!disabled {{ background: {border}; }}
            QPushButton:disabled {{
                background: #F9FAFB; color: #9CA3AF; border-color: #E5E7EB;
            }}
        """)
    return b


def badge(text, color="#1A73E8", bg="#EBF3FD"):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        background: {bg}; color: {color};
        border-radius: 10px; padding: 2px 8px;
        font-size: 10px; font-weight: 700;
    """)
    return lbl


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 后台生成线程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class GenerateThread(QThread):
    done  = Signal(object)
    error = Signal(str)

    def __init__(self, n, seed):
        super().__init__()
        self.n = n
        self.seed = seed

    def run(self):
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from navigation import NavigationEngine
            eng = NavigationEngine()
            eng.generate_map(n_vertices=self.n, width=2000, height=1500, seed=self.seed, poi_density=0.02)
            self.done.emit(eng)
        except Exception as e:
            self.error.emit(str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 地图画布
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MapCanvas(QWidget):
    sig_status     = Signal(str)
    sig_path       = Signal(dict)
    sig_traffic    = Signal(dict)
    sig_nearby     = Signal(dict)
    sig_time_query = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(700, 500)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._drag_button  = None   # 记录发起拖拽的按键

        self.engine       = None
        self.scale        = 1.0
        self.offset_x     = 0.0
        self.offset_y     = 0.0
        self._drag_start  = None
        self._drag_off    = None

        self.start_v      = None
        self.end_v        = None
        self.path_pts     = []
        self.tpath_edges  = []
        self.tpath_pts    = []
        self.nearby_verts = []
        self.nearby_edges = []
        self.nearby_center= None
        self.time_query_edges  = []
        self.time_query_states = {}
        self.time_query_center = None

        self.show_traffic  = False
        self.show_cars     = False
        self.show_pois     = True
        self.show_nearby   = True
        self.algo          = "astar"
        self.sim_speed     = 1    # 每 tick 推进的模拟步数（1x⃒20x）

        self._vp       = None
        self._cars     = []
        self._vp_key   = None
        self._overview_pixmap = None  # 缓存的全局概览图
        self._overview_map_w = 0
        self._overview_map_h = 0
        self._hover_mx    = None
        self._hover_my    = None
        self.cell_size    = 75   # 聚合像素网格大小
        self._cell_rep    = {}   # (cx,cy) -> (sx,sy) 代表点屏幕坐标
        self._vid_to_cell = {}   # vertex_id -> (cx,cy)
        self._vid_to_screen = {} # vertex_id -> (sx,sy) 实际屏幕坐标
        self._cell_parent = {}   # vertex_id -> parent_vid (单元内BFS路径树)
        self._cell_rep_vid = {}  # (cx,cy) -> vertex_id 代表点顶点ID
        self._rep_cache_key = None  # (id(vp), scale) 缓存标识

        self._sim_timer = QTimer(self)
        self._sim_timer.timeout.connect(self._tick)

    # ── 引擎 & 视口 ──────────────────────────────────────────────
    def set_engine(self, engine):
        self.engine = engine
        self._auto_fit()
        self._refresh()
        self._build_overview()
        self.update()

    def _auto_fit(self):
        if not self.engine: return
        s = self.engine.get_stats()
        w, h = s.get("width", 2000), s.get("height", 1500)
        cw, ch = self.width() or 900, self.height() or 600
        self.scale = min(cw / w, ch / h) * 0.90
        self.offset_x = (cw - w * self.scale) / 2
        self.offset_y = (ch - h * self.scale) / 2

    def m2s(self, mx, my):
        return mx * self.scale + self.offset_x, my * self.scale + self.offset_y

    def s2m(self, sx, sy):
        return (sx - self.offset_x) / self.scale, (sy - self.offset_y) / self.scale

    def _vp_rect(self):
        x0, y0 = self.s2m(0, 0)
        x1, y1 = self.s2m(self.width(), self.height())
        return x0, y0, x1, y1

    def _refresh(self):
        if not self.engine: return
        r = self._vp_rect()
        key = (round(r[0]), round(r[1]), round(r[2]), round(r[3]),
               round(self.scale, 3), self.show_traffic)
        if key == self._vp_key: return
        self._vp_key = key
        try:
            self._vp = self.engine.query_viewport_state(
                r[0], r[1], r[2], r[3],
                use_representative=False,  # 在 GUI 层进行点聚合，以保留所有道路边
                grid_cols=40, grid_rows=30,
                include_traffic=self.show_traffic
            )
        except Exception:
            pass

    def _tick(self):
        if not self.engine: return
        self.engine.step_simulation(steps=self.sim_speed, spawn_count=3)
        # 始终获取车辆快照，避免切换 show_cars 时无数据
        self._cars = self.engine.get_car_snapshot(limit=2000)
        self._vp_key = None
        self._refresh()
        self.update()

    # ── 功能操作 ─────────────────────────────────────────────────
    def start_simulation(self):
        if not self.engine: return
        sim = self.engine.start_simulation(seed=2026, initial_density=(0.01, 0.15))
        sim.spawn_cars(600)  # 生成 POI 吸引的显式车辆
        self._cars = self.engine.get_car_snapshot(limit=2000)
        self._sim_timer.start(250)

    def stop_simulation(self):
        self._sim_timer.stop()

    def find_path(self):
        if not (self.engine and self.start_v and self.end_v): return
        try:
            r = self.engine.shortest_path(self.start_v.id, self.end_v.id, algorithm=self.algo)
            if r.found:
                self.path_pts = self.engine.path_coordinates(r)
                info = dict(
                    algorithm=r.algorithm, distance=r.distance,
                    hops=len(r.path)-1, nodes_visited=r.nodes_visited,
                    elapsed_ms=r.elapsed_ms
                )
                self.sig_path.emit(info)
                self.sig_status.emit(f"✅ {r.algorithm}  距离:{r.distance:.1f}  跳:{len(r.path)-1}  {r.elapsed_ms:.2f}ms")
            else:
                self.path_pts = []
                self.sig_status.emit("❌ 无可达路径")
        except Exception as e:
            self.sig_status.emit(f"路径出错: {e}")
        self.update()

    def find_traffic_path(self, c=1.0, threshold=0.8):
        if not (self.engine and self.start_v and self.end_v): return
        try:
            r = self.engine.traffic_aware_path(
                self.start_v.id, self.end_v.id,
                algorithm=self.algo, c=c, threshold=threshold
            )
            if r.found:
                self.tpath_pts = self.engine.path_coordinates(r)
                self.tpath_edges = []
                for i in range(len(r.path) - 1):
                    u_id, v_id = r.path[i], r.path[i+1]
                    u = self.engine.graph.get_vertex(u_id)
                    v = self.engine.graph.get_vertex(v_id)
                    edge = self.engine.graph.get_edge(u_id, v_id)
                    lv = edge.congestion_level() if edge else 0
                    self.tpath_edges.append({"ax": u.x, "ay": u.y, "bx": v.x, "by": v.y, "level": lv})
                sr = self.engine.shortest_path(self.start_v.id, self.end_v.id, algorithm=self.algo)
                info = {
                    "distance": r.distance,
                    "static_distance": sr.distance,
                    "saved": sr.distance - r.distance,
                    "congestion_count": sum(1 for e in self.tpath_edges if e["level"] >= 2),
                    "elapsed_ms": r.elapsed_ms,
                }
                self.sig_traffic.emit(info)
                self.sig_status.emit(f"🚀 交通感知路径已规划 ({r.elapsed_ms:.1f}ms)")
            else:
                self.tpath_pts = []
                self.tpath_edges = []
                self.sig_status.emit("❌ 无可达交通路径")
        except Exception as e:
            self.sig_status.emit(f"交通路径出错: {e}")
        self.update()

    def clear_path(self):
        self.start_v = self.end_v = None
        self.path_pts = []
        self.tpath_pts = []
        self.tpath_edges = []
        self.update()

    def find_nearby(self, x, y, k=100):
        if not self.engine: return
        try:
            nearby, edges = self.engine.query_nearby_subgraph(x, y, k=k)
            self.nearby_verts = nearby
            self.nearby_edges = edges
            self.nearby_center = (x, y)
            self.sig_nearby.emit({"center": (x, y), "v_count": len(nearby), "e_count": len(edges)})
            self.sig_status.emit(f"🔍 已找到 ({x:.0f},{y:.0f}) 附近的 {len(nearby)} 个节点")
        except Exception as e:
            self.sig_status.emit(f"查询出错: {e}")
        self.update()

    def clear_nearby(self):
        self.nearby_verts = []
        self.nearby_edges = []
        self.nearby_center = None
        self.update()

    def query_time_traffic(self, x, y, t, r=300):
        if not self.engine: return
        try:
            edges, states = self.engine.query_traffic_at_time(x, y, t, radius=r)
            self.time_query_edges = edges
            self.time_query_states = states
            self.time_query_center = (x, y)
            self.sig_time_query.emit({"center": (x, y), "time": t, "e_count": len(edges)})
            self.sig_status.emit(f"🕒 已查询 T={t} 时 ({x:.0f},{y:.0f}) 附近的交通流")
        except Exception as e:
            self.sig_status.emit(f"查询出错: {e}")
        self.update()

    def clear_time_query(self):
        self.time_query_edges = []
        self.time_query_states = {}
        self.time_query_center = None
        self.update()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 绘制系统
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 地图背景渐变
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor("#EDF2F7"))
        grad.setColorAt(1.0, QColor("#E2EAF4"))
        p.fillRect(self.rect(), QBrush(grad))

        if not self.engine:
            self._draw_empty_state(p)
            return

        # 预计算代表点映射（供 _draw_edges 和 _draw_vertices 共用）
        self._compute_rep_map()
        # 绘制轻微网格
        self._draw_grid(p)
        self._draw_edges(p)
        if self.show_nearby:
            self._draw_nearby(p)
        self._draw_time_query(p)
        self._draw_vertices(p)
        if self.show_pois:
            self._draw_pois(p)
        if self.show_cars:
            self._draw_cars(p)
        self._draw_paths(p)
        self._draw_markers(p)
        self._draw_hud(p)
        self._draw_overview(p)

    def _draw_empty_state(self, p):
        """无地图时的空状态页"""
        w, h = self.width(), self.height()
        # 绘制中央提示卡片
        card_w, card_h = 380, 200
        cx, cy = (w - card_w) // 2, (h - card_h) // 2

        # 卡片背景
        p.setPen(QPen(QColor("#E2E8F0"), 1.5))
        p.setBrush(QBrush(QColor("#FFFFFF")))
        path = QPainterPath()
        path.addRoundedRect(QRectF(cx, cy, card_w, card_h), 16, 16)
        p.drawPath(path)

        # 图标区域
        icon_y = cy + 36
        p.setFont(QFont("Segoe UI", 36))
        p.setPen(QColor("#1A73E8"))
        p.drawText(QRectF(cx, icon_y, card_w, 50), Qt.AlignCenter, "🗺")

        p.setFont(QFont("Segoe UI", 15, QFont.Bold))
        p.setPen(QColor("#1E293B"))
        p.drawText(QRectF(cx, icon_y + 58, card_w, 30), Qt.AlignCenter, "导航系统")

        p.setFont(QFont("Segoe UI", 11))
        p.setPen(QColor("#64748B"))
        p.drawText(QRectF(cx, icon_y + 90, card_w, 24), Qt.AlignCenter, "请在左侧面板生成或加载地图")
        p.drawText(QRectF(cx, icon_y + 110, card_w, 24), Qt.AlignCenter, "Navigation System v4 · Data Structure 2026")

    def _draw_grid(self, p):
        """绘制地图辅助网格"""
        if self.scale < 0.05: return
        grid_step = 200  # map units
        x0, y0 = self.s2m(0, 0)
        x1, y1 = self.s2m(self.width(), self.height())

        pen = QPen(QColor("#DCE4EC"), 0.8, Qt.DotLine)
        p.setPen(pen)

        xi = math.floor(x0 / grid_step) * grid_step
        while xi <= x1:
            sx, _ = self.m2s(xi, 0)
            p.drawLine(int(sx), 0, int(sx), self.height())
            xi += grid_step

        yi = math.floor(y0 / grid_step) * grid_step
        while yi <= y1:
            _, sy = self.m2s(0, yi)
            p.drawLine(0, int(sy), self.width(), int(sy))
            yi += grid_step

    def _compute_rep_map(self):
        """计算地图空间网格代表点与单元内 BFS 路径树。
        使用地图坐标空间（而非屏幕坐标）划分网格，
        使得平移视图时单元分配不变，彻底避免拖拽抖动。
        """
        vp = self._vp
        if not vp:
            self._cell_rep = {}
            self._vid_to_cell = {}
            self._vid_to_screen = {}
            self._cell_parent = {}
            self._cell_rep_vid = {}
            return

        # 地图空间网格尺寸（cell_size 像素对应的地图单位长度）
        map_cell = self.cell_size / self.scale if self.scale > 0 else self.cell_size

        # ── 每帧都要更新的屏幕坐标 ──
        self._vid_to_screen = {}
        for v in vp.vertices:
            self._vid_to_screen[v.id] = self.m2s(v.x, v.y)

        # ── 单元分配 + BFS 仅在视口数据/缩放变化时重建 ──
        cache_key = (id(vp), round(self.scale, 6))
        if cache_key == self._rep_cache_key:
            # 单元分配不变，只更新 _cell_rep 的屏幕坐标
            self._cell_rep = {}
            for cell, rep_vid in self._cell_rep_vid.items():
                s = self._vid_to_screen.get(rep_vid)
                if s:
                    self._cell_rep[cell] = s
            return

        self._rep_cache_key = cache_key
        self._vid_to_cell = {}
        self._cell_rep = {}
        self._cell_rep_vid = {}
        self._cell_parent = {}
        cell_vertices = {}  # (cx,cy) -> [vid, ...]

        for v in vp.vertices:
            cx, cy = int(v.x // map_cell), int(v.y // map_cell)
            self._vid_to_cell[v.id] = (cx, cy)
            if (cx, cy) not in self._cell_rep_vid:
                self._cell_rep_vid[(cx, cy)] = v.id
            cell_vertices.setdefault((cx, cy), []).append(v.id)

        # 更新 _cell_rep 屏幕坐标
        for cell, rep_vid in self._cell_rep_vid.items():
            s = self._vid_to_screen.get(rep_vid)
            if s:
                self._cell_rep[cell] = s

        # 从 _vp.edges 构建单元内邻接表（只含同一单元内的边）
        cell_adj = {}  # vid -> [neighbor_vid, ...]
        for edge in vp.edges:
            uc = self._vid_to_cell.get(edge.u)
            vc = self._vid_to_cell.get(edge.v)
            if uc is not None and vc is not None and uc == vc:
                cell_adj.setdefault(edge.u, []).append(edge.v)
                cell_adj.setdefault(edge.v, []).append(edge.u)

        # 每个单元内从代表点 BFS，建立 parent 路径树
        for cell, vids in cell_vertices.items():
            rep_vid = self._cell_rep_vid[cell]
            self._cell_parent[rep_vid] = None  # 根节点
            if len(vids) <= 1:
                continue
            queue = [rep_vid]
            qi = 0
            visited = {rep_vid}
            while qi < len(queue):
                cur = queue[qi]; qi += 1
                for nb in cell_adj.get(cur, []):
                    if nb not in visited:
                        visited.add(nb)
                        self._cell_parent[nb] = cur
                        queue.append(nb)

    def _path_within_cell_to_rep(self, vid):
        """从单元代表点到 vid 的屏幕坐标路径 [rep_screen, ..., vid_screen]。
        用于将跨单元边两端分别连回各自的代表点，形成完整折线。
        """
        if vid not in self._cell_parent:
            # 未被 BFS 访问（与代表点在单元内不连通），退化为直线
            cell = self._vid_to_cell.get(vid)
            rep_s = self._cell_rep.get(cell) if cell else None
            vid_s = self._vid_to_screen.get(vid)
            if not vid_s:
                return []
            if rep_s and rep_s != vid_s:
                return [rep_s, vid_s]
            return [vid_s]
        # 沿 parent 链回溯到代表点
        path = []
        cur = vid
        for _ in range(2000):  # 安全上限
            s = self._vid_to_screen.get(cur)
            if s:
                path.append(s)
            parent = self._cell_parent.get(cur)
            if parent is None:  # 到达根（代表点）
                break
            cur = parent
        path.reverse()
        return path  # [rep_screen, ..., vid_screen]

    def _draw_edges(self, p):
        """绘制边——保留原始道路形状为折线。
        跨单元边以代表点为起止，经过实际顶点位置形成折线路径。
        同一对单元之间只绘制第一条边（近似路径合并，避免拥挤）。
        """
        if not self._vp: return
        drawn_cell_pairs = set()
        for edge in self._vp.edges:
            u_cell = self._vid_to_cell.get(edge.u)
            v_cell = self._vid_to_cell.get(edge.v)
            if u_cell is None or v_cell is None:
                continue
            # 两端点在同一网格 → 内部边，不显示
            if u_cell == v_cell:
                continue
            # 跨格边去重（每对格子只画一条线）
            pair = (min(u_cell, v_cell), max(u_cell, v_cell))
            if pair in drawn_cell_pairs:
                continue
            drawn_cell_pairs.add(pair)
            # 构建折线：rep_A → … → u → v → … → rep_B
            seg_a = self._path_within_cell_to_rep(edge.u)  # [rep_A, ..., u]
            seg_b = self._path_within_cell_to_rep(edge.v)  # [rep_B, ..., v]
            full = seg_a + list(reversed(seg_b))  # [rep_A,...,u, v,...,rep_B]
            if len(full) < 2:
                continue
            # 构建 QPainterPath 折线
            qpath = QPainterPath()
            qpath.moveTo(full[0][0], full[0][1])
            for pt in full[1:]:
                qpath.lineTo(pt[0], pt[1])
            if self.show_traffic:
                state = self._vp.traffic.get((min(edge.u, edge.v), max(edge.u, edge.v)))
                lv = state.level if state else 0
                color = TRAFFIC_COLORS.get(lv, C["edge"])
                p.setPen(QPen(color, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            else:
                p.setPen(QPen(C["edge"], 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(qpath)

    def _draw_nearby(self, p):
        if not self.nearby_verts: return
        for edge in self.nearby_edges:
            u = self.engine.graph.get_vertex(edge.u)
            v = self.engine.graph.get_vertex(edge.v)
            sx0, sy0 = self.m2s(u.x, u.y)
            sx1, sy1 = self.m2s(v.x, v.y)
            p.setPen(QPen(C["amber"], 2.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(int(sx0), int(sy0), int(sx1), int(sy1))
        if self.nearby_center:
            self._draw_center_marker(p, *self.nearby_center, QColor("#D97706"), "C")

    def _draw_time_query(self, p):
        if not self.time_query_edges: return
        for edge in self.time_query_edges:
            u = self.engine.graph.get_vertex(edge.u)
            v = self.engine.graph.get_vertex(edge.v)
            sx0, sy0 = self.m2s(u.x, u.y)
            sx1, sy1 = self.m2s(v.x, v.y)
            key = (min(edge.u, edge.v), max(edge.u, edge.v))
            state = self.time_query_states.get(key)
            lv = state.level if state else 0
            p.setPen(QPen(TRAFFIC_COLORS.get(lv, C["brand"]), 3.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(int(sx0), int(sy0), int(sx1), int(sy1))
        if self.time_query_center:
            self._draw_center_marker(p, *self.time_query_center, C["brand"], "T")

    def _draw_center_marker(self, p, mx, my, color, label):
        sx, sy = self.m2s(mx, my)
        # 脉冲圆
        pulse_color = QColor(color)
        pulse_color.setAlpha(40)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(pulse_color))
        p.drawEllipse(QPointF(sx, sy), 22, 22)
        # 内圆
        p.setBrush(QBrush(color))
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(QPointF(sx, sy), 12, 12)
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.setPen(QPen(QColor("white")))
        p.drawText(int(sx) - 4, int(sy) + 4, label)

    def _draw_vertices(self, p):
        if not self._vp or not self._cell_rep: return
        r = max(3.0, min(self.scale * 3.0, 6.0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#1E293B")))
        # 直接使用 _compute_rep_map 已算好的代表点，每格只画一个点
        for (sx, sy) in self._cell_rep.values():
            p.drawEllipse(QPointF(sx, sy), r, r)

    def _draw_cars(self, p):
        p.setPen(QPen(QColor("#92400E"), 1.0))
        p.setBrush(QBrush(QColor("#F59E0B")))
        car_r = max(3.5, min(self.scale * 4, 7.0))
        for car in self._cars:
            if car.x is None: continue
            sx, sy = self.m2s(car.x, car.y)
            p.drawEllipse(QPointF(sx, sy), car_r, car_r)

    # POI 类型 → emoji 图标和颜色
    _POI_ICONS = {
        "hospital":    ("🏥", "#DC2626"),
        "restaurant":  ("🍔", "#EA580C"),
        "gas_station": ("⛽", "#D97706"),
        "parking":     ("🅿", "#2563EB"),
        "repair":      ("🔧", "#64748B"),
    }
    _POI_DEFAULT = ("📍", "#6366F1")

    def _draw_pois(self, p):
        """绘制 POI 兴趣点标记（emoji 图标），按代表点规则只显示可见的。"""
        if not self._vp or not self.engine:
            return
        # 收集视口中所有 POI 顶点
        poi_list = []
        for v in self._vp.vertices:
            poi_data = v.metadata.get("poi")
            if not poi_data:
                continue
            # 被代表点缩放掉的 POI：检查该顶点是否是其网格的代表点
            cell = self._vid_to_cell.get(v.id)
            rep_vid = self._cell_rep_vid.get(cell) if cell else None
            if rep_vid is not None and rep_vid != v.id:
                continue  # 该点被聚合掉了，不显示
            sx, sy = self.m2s(v.x, v.y)
            poi_type = poi_data.get("type", "")
            poi_list.append((sx, sy, poi_type))

        if not poi_list:
            return

        icon_size = max(10, min(int(self.scale * 14), 22))
        font = QFont("Segoe UI Emoji", icon_size)
        font.setStyleStrategy(QFont.PreferAntialias)
        p.setFont(font)

        for sx, sy, poi_type in poi_list:
            icon, bg_color = self._POI_ICONS.get(poi_type, self._POI_DEFAULT)
            # 绘制背景圆
            r = icon_size * 0.7
            bg = QColor(bg_color)
            bg.setAlpha(180)
            p.setPen(QPen(QColor("white"), 1.5))
            p.setBrush(QBrush(bg))
            p.drawEllipse(QPointF(sx, sy), r, r)
            # 绘制 emoji
            p.setPen(QColor("white"))
            fm = QFontMetrics(font)
            tw = fm.horizontalAdvance(icon)
            th = fm.height()
            p.drawText(int(sx - tw / 2), int(sy + th / 4), icon)

    def _draw_paths(self, p):
        def polyline(pts, color, w, dash=False):
            if len(pts) < 2: return
            # 绘制光晕
            halo = QColor(color)
            halo.setAlpha(50)
            pen_halo = QPen(halo, w + 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            path = QPainterPath()
            sx, sy = self.m2s(*pts[0])
            path.moveTo(sx, sy)
            for pt in pts[1:]:
                sx, sy = self.m2s(*pt)
                path.lineTo(sx, sy)
            p.setPen(pen_halo)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            # 实线
            pen = QPen(color, w, Qt.CustomDashLine if dash else Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            if dash: pen.setDashPattern([8, 5])
            p.setPen(pen)
            p.drawPath(path)

        polyline(self.path_pts, C["path_blue"], 3.5)

        if self.tpath_edges:
            for e in self.tpath_edges:
                sx0, sy0 = self.m2s(e["ax"], e["ay"])
                sx1, sy1 = self.m2s(e["bx"], e["by"])
                color = TRAFFIC_COLORS.get(e["level"], C["path_purple"])
                # 光晕
                halo = QColor(color); halo.setAlpha(45)
                p.setPen(QPen(halo, 10, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(int(sx0), int(sy0), int(sx1), int(sy1))
                # 实线
                pen = QPen(color, 4.0, Qt.CustomDashLine, Qt.RoundCap)
                pen.setDashPattern([8, 5])
                p.setPen(pen)
                p.drawLine(int(sx0), int(sy0), int(sx1), int(sy1))
        elif self.tpath_pts:
            polyline(self.tpath_pts, C["path_purple"], 3.5, dash=True)

    def _draw_markers(self, p):
        """绘制起终点水滴标记"""
        if self.start_v:
            self._draw_teardrop(p, self.start_v.x, self.start_v.y, C["brand"], "S")
        if self.end_v:
            self._draw_teardrop(p, self.end_v.x, self.end_v.y, C["red"], "E")

    def _draw_teardrop(self, p, mx, my, color, label):
        sx, sy = self.m2s(mx, my)
        # 外阴影
        shadow = QColor(color); shadow.setAlpha(30)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(shadow))
        p.drawEllipse(QPointF(sx, sy + 2), 16, 16)
        # 水滴形
        drop = QPainterPath()
        drop.moveTo(sx, sy + 14)      # 底尖
        drop.cubicTo(sx - 12, sy + 4, sx - 12, sy - 12, sx, sy - 14)
        drop.cubicTo(sx + 12, sy - 12, sx + 12, sy + 4, sx, sy + 14)
        drop.closeSubpath()
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(QBrush(color))
        p.drawPath(drop)
        # 内圆白点
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("white")))
        p.drawEllipse(QPointF(sx, sy - 2), 5, 5)
        # 标签
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        p.setPen(QPen(QColor("white")))
        p.drawText(int(sx) - 3, int(sy) + 1, label)

    def _build_overview(self):
        """构建全局概览图缓存（QPixmap），仅在加载地图时调用一次。"""
        from PySide6.QtGui import QPixmap
        if not self.engine:
            self._overview_pixmap = None
            return
        s = self.engine.get_stats()
        mw = s.get("width", 2000)
        mh = s.get("height", 1500)
        self._overview_map_w = mw
        self._overview_map_h = mh
        # 概览图固定大小
        ow, oh = 200, 150
        scale = min(ow / mw, oh / mh) * 0.92
        ox = (ow - mw * scale) / 2
        oy = (oh - mh * scale) / 2

        pixmap = QPixmap(ow, oh)
        pixmap.fill(QColor("#EDF2F7"))
        pp = QPainter(pixmap)
        pp.setRenderHint(QPainter.Antialiasing)
        # 绘制所有边
        pp.setPen(QPen(QColor("#CBD5E1"), 0.6, Qt.SolidLine, Qt.RoundCap))
        for edge in self.engine.graph.edges():
            u = self.engine.graph.get_vertex(edge.u)
            v = self.engine.graph.get_vertex(edge.v)
            if u and v:
                pp.drawLine(
                    int(u.x * scale + ox), int(u.y * scale + oy),
                    int(v.x * scale + ox), int(v.y * scale + oy),
                )
        # 绘制所有点
        pp.setPen(Qt.NoPen)
        pp.setBrush(QBrush(QColor("#64748B")))
        for v in self.engine.graph.vertices():
            pp.drawEllipse(QPointF(v.x * scale + ox, v.y * scale + oy), 1.0, 1.0)
        # 绘制 POI 标记（彩色大点）
        for v in self.engine.graph.vertices():
            poi_data = v.metadata.get("poi")
            if poi_data:
                poi_type = poi_data.get("type", "")
                _, bg_color = self._POI_ICONS.get(poi_type, self._POI_DEFAULT)
                pp.setPen(Qt.NoPen)
                pp.setBrush(QBrush(QColor(bg_color)))
                pp.drawEllipse(QPointF(v.x * scale + ox, v.y * scale + oy), 2.5, 2.5)
        pp.end()
        self._overview_pixmap = pixmap
        self._overview_scale = scale
        self._overview_ox = ox
        self._overview_oy = oy

    def _draw_overview(self, p):
        """在左上角绘制全局概览小地图，含当前视口框和起终点标记。"""
        if not self._overview_pixmap:
            return
        ow = self._overview_pixmap.width()
        oh = self._overview_pixmap.height()
        margin = 12
        # 交通图例可能占据左上角，概览放在下面一点
        top_offset = 52 if self.show_traffic else margin
        mx, my = margin, top_offset

        # 背景卡片
        p.setPen(QPen(QColor("#CBD5E1"), 1.5))
        p.setBrush(QBrush(QColor(255, 255, 255, 230)))
        card = QPainterPath()
        card.addRoundedRect(QRectF(mx - 4, my - 4, ow + 8, oh + 8), 8, 8)
        p.drawPath(card)

        # 绘制缓存的概览图
        p.drawPixmap(mx, my, self._overview_pixmap)

        sc = self._overview_scale
        ox = self._overview_ox + mx
        oy = self._overview_oy + my

        # 绘制当前视口矩形
        vx0, vy0 = self.s2m(0, 0)
        vx1, vy1 = self.s2m(self.width(), self.height())
        rx = vx0 * sc + ox
        ry = vy0 * sc + oy
        rw = (vx1 - vx0) * sc
        rh = (vy1 - vy0) * sc
        vp_color = QColor("#1A73E8")
        vp_color.setAlpha(40)
        p.setPen(QPen(QColor("#1A73E8"), 1.5))
        p.setBrush(QBrush(vp_color))
        p.drawRect(QRectF(rx, ry, rw, rh))

        # 绘制起终点标记
        if self.start_v:
            sx = self.start_v.x * sc + ox
            sy = self.start_v.y * sc + oy
            p.setPen(QPen(QColor("white"), 1.5))
            p.setBrush(QBrush(C["brand"]))
            p.drawEllipse(QPointF(sx, sy), 4, 4)
        if self.end_v:
            sx = self.end_v.x * sc + ox
            sy = self.end_v.y * sc + oy
            p.setPen(QPen(QColor("white"), 1.5))
            p.setBrush(QBrush(C["red"]))
            p.drawEllipse(QPointF(sx, sy), 4, 4)

    def _draw_hud(self, p):
        """绘制 HUD 覆盖层：右下比例尺 + 缩放信息"""
        w, h = self.width(), self.height()

        # ── 比例尺 ────────────────────────────────────
        # 确定比例尺长度（像素）→ 地图长度
        target_px = 120
        map_len = target_px / self.scale   # 像素对应的地图单位
        # 取最近的整百整千
        nice = [50, 100, 200, 500, 1000, 2000, 5000]
        chosen = min(nice, key=lambda x: abs(x - map_len))
        bar_px = int(chosen * self.scale)

        bar_x = w - bar_px - 16
        bar_y = h - 28

        # 比例尺背景
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, 200)))
        path = QPainterPath()
        path.addRoundedRect(QRectF(bar_x - 8, bar_y - 14, bar_px + 16 + 70, 24), 6, 6)
        p.drawPath(path)

        # 比例尺线
        p.setPen(QPen(QColor("#1A73E8"), 2.5, Qt.SolidLine, Qt.FlatCap))
        p.drawLine(bar_x, bar_y, bar_x + bar_px, bar_y)
        p.drawLine(bar_x, bar_y - 5, bar_x, bar_y + 5)
        p.drawLine(bar_x + bar_px, bar_y - 5, bar_x + bar_px, bar_y + 5)

        # 比例尺文字
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.setPen(QColor("#1A73E8"))
        label = f"{chosen}m" if chosen < 1000 else f"{chosen//1000}km"
        p.drawText(bar_x + bar_px + 6, bar_y + 4, label)

        # 缩放文字
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor("#64748B"))
        p.drawText(bar_x - 6, bar_y + 4, f"×{self.scale:.3f}")

        # ── 坐标提示（鼠标位置）────────────────────────
        if self._hover_mx is not None:
            coord_text = f"({self._hover_mx:.0f}, {self._hover_my:.0f})"
            p.setFont(QFont("Segoe UI", 9))
            fm = QFontMetrics(p.font())
            tw = fm.horizontalAdvance(coord_text) + 16
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 200)))
            path2 = QPainterPath()
            path2.addRoundedRect(QRectF(8, h - 28, tw, 20), 5, 5)
            p.drawPath(path2)
            p.setPen(QColor("#64748B"))
            p.drawText(16, h - 13, coord_text)

        # ── 交通图例（如开启交通模式）────────────────
        if self.show_traffic:
            legend_items = [("#16A34A", "畅通"), ("#D97706", "缓行"),
                            ("#EA580C", "拥堵"), ("#DC2626", "严重")]
            lx, ly = 16, 16
            # 背景
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 210)))
            path3 = QPainterPath()
            path3.addRoundedRect(QRectF(lx - 6, ly - 6, 190, 30), 8, 8)
            p.drawPath(path3)
            for i, (color, label) in enumerate(legend_items):
                x = lx + i * 46
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(color)))
                p.drawEllipse(QPointF(x + 6, ly + 9), 5, 5)
                p.setFont(QFont("Segoe UI", 9))
                p.setPen(QColor("#374151"))
                p.drawText(x + 14, ly + 14, label)

    # ── 鼠标 & 键盘事件 ──────────────────────────────────────────

    def mousePressEvent(self, e: QMouseEvent):
        if not self.engine: return
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and e.modifiers() & Qt.AltModifier):
            self._drag_start = e.position()
            self._drag_off = (self.offset_x, self.offset_y)
            self._drag_button = e.button()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.RightButton:
            self.clear_path()
            self.sig_status.emit("路径已清除")
            return
        if e.button() == Qt.LeftButton:
            mx, my = self.s2m(e.position().x(), e.position().y())
            try:
                v = self.engine.query_nearest_vertex(mx, my)
            except Exception:
                return
            if not self.start_v:
                self.start_v = v
                self.sig_status.emit(f"✅ 起点: {v.id}  ({v.x:.0f},{v.y:.0f}) — 请点终点")
            elif not self.end_v:
                self.end_v = v
                self.sig_status.emit(f"⏳ 终点: {v.id} — 规划中…")
                self.find_path()
            else:
                self.start_v = v
                self.end_v = None
                self.path_pts = []
                self.tpath_pts = []
                self.tpath_edges = []
                self.sig_status.emit(f"🔄 新起点: {v.id} — 请点终点")
            self.update()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drag_start:
            dx = e.position().x() - self._drag_start.x()
            dy = e.position().y() - self._drag_start.y()
            self.offset_x = self._drag_off[0] + dx
            self.offset_y = self._drag_off[1] + dy
            # 拖拽期间只更新画面（使用已有的 _vp 数据重绘），不重新查询视口
            # 避免网格代表点重新计算导致图形跳变
            self.update()
        else:
            mx, my = self.s2m(e.position().x(), e.position().y())
            self._hover_mx = mx
            self._hover_my = my
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        # 只在释放拖拽按键时结束拖拽，避免左键释放误清除中键拖拽状态
        if self._drag_start and e.button() == self._drag_button:
            self._drag_start = None
            self._drag_button = None
            self.setCursor(Qt.CrossCursor)
            # 拖拽结束后再刷新视口数据
            self._vp_key = None
            self._refresh()
            self.update()

    def wheelEvent(self, e: QWheelEvent):
        if not self.engine: return
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        cx, cy = e.position().x(), e.position().y()
        self.offset_x = cx - (cx - self.offset_x) * f
        self.offset_y = cy - (cy - self.offset_y) * f
        self.scale *= f
        self._vp_key = None; self._refresh(); self.update()

    def keyPressEvent(self, e: QKeyEvent):
        k = e.key()
        if   k == Qt.Key_Left:   self.offset_x += 60
        elif k == Qt.Key_Right:  self.offset_x -= 60
        elif k == Qt.Key_Up:     self.offset_y += 60
        elif k == Qt.Key_Down:   self.offset_y -= 60
        elif k in (Qt.Key_Plus, Qt.Key_Equal): self.scale *= 1.2
        elif k == Qt.Key_Minus:  self.scale /= 1.2
        elif k == Qt.Key_F:      self._auto_fit()
        elif k == Qt.Key_Escape: self.clear_path()
        else: return
        self._vp_key = None; self._refresh(); self.update()

    def leaveEvent(self, e):
        self._hover_mx = None
        self._hover_my = None
        self.update()

    def resizeEvent(self, e):
        self._vp_key = None
        self._refresh()
        super().resizeEvent(e)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 侧边栏
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SidePanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(330)
        self.setObjectName("root")
        self.setStyleSheet("""
            QWidget#root {
                background: #F0F4F8;
                border-right: 1px solid #E2E8F0;
            }
        """)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(72)
        header.setStyleSheet("""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #1A73E8, stop:1 #0D47A1);
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(10)

        # 图标
        icon_lbl = QLabel("🧭")
        icon_lbl.setStyleSheet("font-size: 28px; background: transparent;")
        hl.addWidget(icon_lbl)

        # 文字区
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        t = QLabel("Navigation System")
        t.setStyleSheet("""
            font-size: 15px; font-weight: 800; color: white;
            background: transparent;
            font-family: "Segoe UI", "PingFang SC", sans-serif;
        """)
        sub = QLabel("导航系统 · 数据结构 2026")
        sub.setStyleSheet("""
            font-size: 10px; color: rgba(255,255,255,0.75);
            background: transparent;
        """)
        text_col.addWidget(t)
        text_col.addWidget(sub)
        hl.addLayout(text_col)
        hl.addStretch()
        root.addWidget(header)

        # ── Tabs ────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { background: #F0F4F8; border: none; }
            QTabBar { background: #FFFFFF; }
            QTabBar::tab {
                background: transparent; color: #64748B;
                padding: 10px 0; margin: 0 4px;
                border: none; border-bottom: 3px solid transparent;
                font-size: 11px; font-weight: 600;
                min-width: 92px;
            }
            QTabBar::tab:selected { color: #1A73E8; border-bottom-color: #1A73E8; }
            QTabBar::tab:hover:!selected { color: #334155; }
        """)
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._tab_map(),     "🗺  地图")
        self.tabs.addTab(self._tab_query(),   "🔍  查询")
        self.tabs.addTab(self._tab_traffic(), "🚦  交通")

        # ── Footer 操作提示 ─────────────────────────────────────
        foot = QWidget()
        foot.setFixedHeight(30)
        foot.setStyleSheet("background: #FFFFFF; border-top: 1px solid #E2E8F0;")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(10, 0, 10, 0)
        tips = [("🖱", "滚轮缩放"), ("✋", "中键拖拽"), ("F", "适应"), ("Esc", "清除")]
        for icon, tip in tips:
            lbl = QLabel(f"{icon} {tip}")
            lbl.setStyleSheet("font-size: 10px; color: #94A3B8; background: transparent;")
            fl.addWidget(lbl)
            if tip != "清除":
                sep = QLabel("·")
                sep.setStyleSheet("color: #CBD5E1; background: transparent;")
                fl.addWidget(sep)
        fl.addStretch()
        root.addWidget(foot)

    def _scroll_tab(self):
        s = QScrollArea()
        w = QWidget()
        w.setStyleSheet("background: #F0F4F8;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)
        s.setWidget(w)
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea { background: #F0F4F8; border: none; }")
        return s, lay

    # ── Tab 1: 地图 ─────────────────────────────────────────────
    def _tab_map(self):
        w, lay = self._scroll_tab()

        # 生成地图 Card
        c1 = Card(accent_color=C["brand"])
        c1.add_title("生成地图", "⚡")

        self.spin_n = QSpinBox()
        self.spin_n.setRange(100, 30000)
        self.spin_n.setValue(2000)
        self.spin_n.setSingleStep(500)
        c1.add_row("节点数", self.spin_n)

        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(0, 99999)
        self.spin_seed.setValue(2026)
        c1.add_row("随机种子", self.spin_seed)

        self.btn_gen = make_btn("生成地图", "primary")
        self.btn_gen.setFixedHeight(38)
        c1.addWidget(self.btn_gen)

        io_row = QHBoxLayout()
        io_row.setSpacing(8)
        self.btn_open = make_btn("📂 加载地图")
        self.btn_save = make_btn("💾 保存地图")
        io_row.addWidget(self.btn_open)
        io_row.addWidget(self.btn_save)
        c1.addLayout(io_row)
        lay.addWidget(c1)

        # 地图统计 Card
        c2 = Card(accent_color=C["green"])
        c2.add_title("地图信息", "📊")
        self.lbl_v    = c2.add_info("节点数")
        self.lbl_e    = c2.add_info("边数")
        self.lbl_poi  = c2.add_info("POI 数量")
        self.lbl_conn = c2.add_info("连通状态", "val_grn")
        lay.addWidget(c2)

        # 显示选项 Card
        c3 = Card()
        c3.add_title("显示选项", "👁")
        
        self.spin_cell = QSpinBox()
        self.spin_cell.setRange(20, 250)
        self.spin_cell.setValue(75)
        self.spin_cell.setSingleStep(5)
        c3.add_row("代表点稀疏度 (px)", self.spin_cell)
        
        self.chk_pois    = QCheckBox("显示 POI 兴趣点")
        self.chk_pois.setChecked(True)
        self.chk_traffic = QCheckBox("显示交通流颜色")
        self.chk_cars    = QCheckBox("显示车辆（黄点）")
        c3.addWidget(self.chk_pois)
        c3.addWidget(self.chk_traffic)
        c3.addWidget(self.chk_cars)
        lay.addWidget(c3)

        lay.addStretch()
        return w

    # ── Tab 2: 查询（F1 + F3）────────────────────────────────────
    def _tab_query(self):
        w, lay = self._scroll_tab()

        # 路径设置
        c0 = Card(accent_color=C["brand"])
        c0.add_title("F3 路径规划", "🧭")
        tip = QLabel("左键① 选起点S  ·  左键② 选终点E\n左键③ 重置起点  ·  右键 清除全部")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #64748B; font-size: 11px; line-height: 1.6; background: #F8FAFC; border-radius: 6px; padding: 6px 8px;")
        c0.addWidget(tip)

        self.combo = QComboBox()
        self.combo.addItems(["A*（推荐，更快）", "Dijkstra"])
        c0.add_row("算法", self.combo)

        self.btn_clear = make_btn("✖ 清除路径", "danger")
        c0.addWidget(self.btn_clear)
        lay.addWidget(c0)

        # F3 结果
        c2 = Card(accent_color=C["brand"])
        c2.add_title("最短路径结果", "📏")
        self.v_algo = c2.add_info("算法")
        self.v_dist = c2.add_info("距离（单位）")
        self.v_hops = c2.add_info("经过节点数")
        self.v_vis  = c2.add_info("访问节点数")
        self.v_ms   = c2.add_info("计算耗时")
        lay.addWidget(c2)

        # F1 坐标查询
        c1 = Card(accent_color=C["amber"])
        c1.add_title("F1 附近节点查询", "📍")

        self.spin_nx = QDoubleSpinBox()
        self.spin_nx.setRange(-5000, 5000)
        c1.add_row("中心 X", self.spin_nx)

        self.spin_ny = QDoubleSpinBox()
        self.spin_ny.setRange(-5000, 5000)
        c1.add_row("中心 Y", self.spin_ny)

        self.spin_nk = QSpinBox()
        self.spin_nk.setRange(1, 500)
        self.spin_nk.setValue(100)
        c1.add_row("查询数量 k", self.spin_nk)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_nearby       = make_btn("🔍 查询附近", "primary")
        self.btn_nearby_clear = make_btn("✖ 清除", "danger")
        btn_row.addWidget(self.btn_nearby)
        btn_row.addWidget(self.btn_nearby_clear)
        c1.addLayout(btn_row)
        lay.addWidget(c1)

        # F1 结果
        c1r = Card(accent_color=C["amber"])
        c1r.add_title("F1 查询结果", "📊")
        self.f1_center = c1r.add_info("中心坐标")
        self.f1_count  = c1r.add_info("附近节点数")
        self.f1_edges  = c1r.add_info("关联边数")
        lay.addWidget(c1r)

        lay.addStretch()
        return w

    # ── Tab 3: 交通（F4 + F5 + 时间查询）────────────────────────
    def _tab_traffic(self):
        w, lay = self._scroll_tab()

        # F4 模拟控制
        c1 = Card(accent_color=C["green"])
        c1.add_title("F4 交通模拟", "🚗")
        sim_row = QHBoxLayout()
        sim_row.setSpacing(8)
        self.btn_start = make_btn("▶ 启动模拟", "success")
        self.btn_stop  = make_btn("⏹ 停止", "danger", enabled=False)
        self.btn_start.setFixedHeight(36)
        self.btn_stop.setFixedHeight(36)
        sim_row.addWidget(self.btn_start)
        sim_row.addWidget(self.btn_stop)
        c1.addLayout(sim_row)

        # 倍速控制
        self.spin_speed = QSpinBox()
        self.spin_speed.setRange(1, 20)
        self.spin_speed.setValue(1)
        self.spin_speed.setSuffix("×")
        c1.add_row("模拟倍速", self.spin_speed)

        lay.addWidget(c1)

        # 模拟状态
        c2 = Card(accent_color=C["green"])
        c2.add_title("模拟状态", "📈")
        self.sim_step = c2.add_info("当前时间步")
        self.sim_cars = c2.add_info("活跃车辆数")
        self.sim_avg  = c2.add_info("平均拥堵率", "val_amb")
        self.sim_max  = c2.add_info("最大拥堵率", "val_red")
        lay.addWidget(c2)

        # F5 交通感知路径
        c3 = Card(accent_color=C["purple"])
        c3.add_title("F5 交通感知路径", "🚀")

        self.f5_c = QDoubleSpinBox()
        self.f5_c.setRange(1.0, 10.0)
        self.f5_c.setValue(1.5)
        self.f5_c.setSingleStep(0.1)
        c3.add_row("惩罚系数 c", self.f5_c)

        self.f5_thr = QDoubleSpinBox()
        self.f5_thr.setRange(0.1, 1.0)
        self.f5_thr.setValue(0.8)
        self.f5_thr.setSingleStep(0.05)
        c3.add_row("拥堵阈值", self.f5_thr)

        self.btn_tpath = make_btn("🚀 规划交通路径", "purple", enabled=False)
        self.btn_tpath.setFixedHeight(36)
        c3.addWidget(self.btn_tpath)

        # 图例
        legend_row = QHBoxLayout()
        legend_row.setSpacing(4)
        for color, label in [("#16A34A","畅通"), ("#D97706","缓行"), ("#EA580C","拥堵"), ("#DC2626","严重")]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{color}; font-size:16px; background:transparent; padding:0;")
            lbl = QLabel(label)
            lbl.setStyleSheet("color:#64748B; font-size:10px; background:transparent;")
            legend_row.addWidget(dot)
            legend_row.addWidget(lbl)
        legend_row.addStretch()
        c3.addLayout(legend_row)
        lay.addWidget(c3)

        # F5 结果
        c3r = Card(accent_color=C["purple"])
        c3r.add_title("F5 路径结果", "📊")
        self.t_dist  = c3r.add_info("交通路径距离", "val_amb")
        self.t_sdist = c3r.add_info("静态路径距离")
        self.t_saved = c3r.add_info("节省距离")
        self.t_cong  = c3r.add_info("拥堵路段数", "val_red")
        self.t_ms    = c3r.add_info("计算耗时")
        lay.addWidget(c3r)

        # 时间交通查询
        c4 = Card(accent_color=C["brand"])
        c4.add_title("历史交通查询", "🕒")

        self.spin_time = QSpinBox()
        self.spin_time.setRange(0, 10000)
        self.spin_time.setValue(0)
        c4.add_row("时间步 T", self.spin_time)

        self.spin_tx = QDoubleSpinBox()
        self.spin_tx.setRange(-5000, 5000)
        self.spin_tx.setValue(1000)
        c4.add_row("中心 X", self.spin_tx)

        self.spin_ty = QDoubleSpinBox()
        self.spin_ty.setRange(-5000, 5000)
        self.spin_ty.setValue(750)
        c4.add_row("中心 Y", self.spin_ty)

        self.spin_tr = QDoubleSpinBox()
        self.spin_tr.setRange(10, 2000)
        self.spin_tr.setValue(300)
        self.spin_tr.setSingleStep(50)
        c4.add_row("查询半径", self.spin_tr)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)
        self.btn_time_query = make_btn("🔍 查询历史", "primary")
        self.btn_time_clear = make_btn("✖ 清除", "danger")
        btn_row2.addWidget(self.btn_time_query)
        btn_row2.addWidget(self.btn_time_clear)
        c4.addLayout(btn_row2)
        lay.addWidget(c4)

        # 时间查询结果
        c4r = Card(accent_color=C["brand"])
        c4r.add_title("查询结果", "📊")
        self.time_res_center = c4r.add_info("中心坐标")
        self.time_res_time   = c4r.add_info("查询时间步")
        self.time_res_edges  = c4r.add_info("受影响边数")
        lay.addWidget(c4r)

        lay.addStretch()
        return w

    # ── 数据更新方法 ─────────────────────────────────────────────

    def update_stats(self, eng):
        s = eng.get_stats()
        self.lbl_v.setText(str(s.get("vertices", "—")))
        self.lbl_e.setText(str(s.get("edges", "—")))
        self.lbl_poi.setText(str(s.get("poi_count", "—")))
        connected = s.get("connected", False)
        self.lbl_conn.setText("✅ 完全连通" if connected else "⚠ 未完全连通")
        self.lbl_conn.setObjectName("val_grn" if connected else "val_amb")

    def update_path(self, info):
        self.v_algo.setText(info.get("algorithm", "—"))
        self.v_dist.setText(f"{info.get('distance', 0):.1f}")
        self.v_hops.setText(str(info.get("hops", "—")))
        self.v_vis.setText(str(info.get("nodes_visited", "—")))
        self.v_ms.setText(f"{info.get('elapsed_ms', 0):.2f} ms")

    def update_traffic(self, info):
        self.t_dist.setText(f"{info.get('distance', 0):.1f}")
        self.t_sdist.setText(f"{info.get('static_distance', 0):.1f}")
        saved = info.get("saved", 0)
        self.t_saved.setText(f"{saved:+.1f}")
        self.t_cong.setText(str(info.get("congestion_count", "—")))
        self.t_ms.setText(f"{info.get('elapsed_ms', 0):.2f} ms")

    def update_nearby(self, info):
        c = info.get("center", (0, 0))
        self.f1_center.setText(f"({c[0]:.0f}, {c[1]:.0f})")
        self.f1_count.setText(str(info.get("v_count", "—")))
        self.f1_edges.setText(str(info.get("e_count", "—")))

    def update_time_query(self, info):
        c = info.get("center", (0, 0))
        self.time_res_center.setText(f"({c[0]:.0f}, {c[1]:.0f})")
        self.time_res_time.setText(str(info.get("time", "—")))
        self.time_res_edges.setText(str(info.get("e_count", "—")))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主窗口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Navigation System v4 · 导航系统")
        self.resize(1280, 820)
        self.setStyleSheet(QSS)
        self.engine = None
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.panel  = SidePanel()
        self.canvas = MapCanvas()
        layout.addWidget(self.panel)
        layout.addWidget(self.canvas, 1)

        p, c = self.panel, self.canvas

        # 连接信号
        p.btn_gen.clicked.connect(self._gen)
        p.btn_open.clicked.connect(self._open)
        p.btn_save.clicked.connect(self._save)
        p.btn_clear.clicked.connect(self._clear)
        p.combo.currentTextChanged.connect(
            lambda t: setattr(c, "algo", "astar" if "A*" in t else "dijkstra")
        )
        p.btn_start.clicked.connect(self._sim_start)
        p.btn_stop.clicked.connect(self._sim_stop)
        p.btn_tpath.clicked.connect(self._traffic_path)
        p.chk_traffic.stateChanged.connect(self._chk_traffic)
        p.spin_speed.valueChanged.connect(
            lambda v: setattr(c, "sim_speed", v)
        )
        p.chk_cars.stateChanged.connect(
            lambda s: (
                setattr(c, "show_cars", bool(s)),
                setattr(c, "_cars", c.engine.get_car_snapshot(limit=2000) if (bool(s) and c.engine and c.engine.traffic_simulator) else c._cars),
                c.update(),
            )
        )
        p.chk_pois.stateChanged.connect(
            lambda s: (setattr(c, "show_pois", bool(s)), c.update())
        )
        p.spin_cell.valueChanged.connect(
            lambda v: (setattr(c, "cell_size", v), c.update())
        )
        p.btn_nearby.clicked.connect(self._nearby)
        p.btn_nearby_clear.clicked.connect(self._nearby_clear)
        p.btn_time_query.clicked.connect(self._time_query)
        p.btn_time_clear.clicked.connect(self._time_clear)

        c.sig_status.connect(self.statusBar().showMessage)
        c.sig_path.connect(p.update_path)
        c.sig_traffic.connect(p.update_traffic)
        c.sig_nearby.connect(p.update_nearby)
        c.sig_time_query.connect(p.update_time_query)

        self.statusBar().showMessage("就绪 — 请生成或加载地图以开始导航")

    # ── 槽函数 ───────────────────────────────────────────────────

    def _gen(self):
        n = self.panel.spin_n.value()
        seed = self.panel.spin_seed.value()
        self.panel.btn_gen.setEnabled(False)
        self.panel.btn_gen.setText("⏳ 生成中…")
        self.statusBar().showMessage(f"⏳ 正在生成 {n} 节点地图，请稍候…")
        self._thread = GenerateThread(n, seed)
        self._thread.done.connect(self._map_ready)
        self._thread.error.connect(self._gen_err)
        self._thread.start()

    def _map_ready(self, engine):
        self.engine = engine
        self.canvas.set_engine(engine)
        self.panel.update_stats(engine)
        self.panel.btn_gen.setEnabled(True)
        self.panel.btn_gen.setText("生成地图")
        self.panel.btn_tpath.setEnabled(True)
        self.statusBar().showMessage("✅ 地图生成完毕 — 点击地图选择起终点")

    def _gen_err(self, msg):
        self.panel.btn_gen.setEnabled(True)
        self.panel.btn_gen.setText("生成地图")
        QMessageBox.critical(self, "生成失败", f"错误：{msg}")
        self.statusBar().showMessage("❌ 生成失败")

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开地图文件", "", "JSON 地图 (*.json);;所有文件 (*)"
        )
        if not path: return
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from navigation import NavigationEngine
            eng = NavigationEngine()
            eng.load_map(path)
            self._map_ready(eng)
            self.statusBar().showMessage(f"✅ 已加载: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))

    def _save(self):
        if not self.engine:
            QMessageBox.warning(self, "提示", "请先生成或加载地图")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存地图文件", "city_map.json", "JSON 地图 (*.json)"
        )
        if not path: return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.engine.save_map(path)
            self.statusBar().showMessage(f"✅ 已保存: {path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _clear(self):
        self.canvas.clear_path()
        self.statusBar().showMessage("路径已清除")

    def _traffic_path(self):
        c   = self.panel.f5_c.value()
        thr = self.panel.f5_thr.value()
        self.canvas.find_traffic_path(c=c, threshold=thr)

    def _sim_start(self):
        if not self.engine:
            QMessageBox.warning(self, "提示", "请先生成或加载地图")
            return
        self.canvas.start_simulation()
        self.panel.btn_start.setEnabled(False)
        self.panel.btn_stop.setEnabled(True)
        self.panel.chk_traffic.setChecked(True)
        self._sim_ui_timer = QTimer(self)
        self._sim_ui_timer.timeout.connect(self._update_sim_ui)
        self._sim_ui_timer.start(500)
        self.statusBar().showMessage("🚦 交通模拟已启动")

    def _sim_stop(self):
        self.canvas.stop_simulation()
        if hasattr(self, "_sim_ui_timer"):
            self._sim_ui_timer.stop()
        self.panel.btn_start.setEnabled(True)
        self.panel.btn_stop.setEnabled(False)
        self.statusBar().showMessage("⏹ 模拟已停止")

    def _update_sim_ui(self):
        if not self.engine: return
        try:
            s = self.engine.get_stats()
            t = s.get("traffic")
            if t:
                self.panel.sim_step.setText(str(t.get("time_step", "—")))
                self.panel.sim_cars.setText(str(t.get("active_cars", "—")))
                avg = t.get("average_ratio", 0)
                mx  = t.get("max_ratio", 0)
                self.panel.sim_avg.setText(f"{avg*100:.1f}%")
                self.panel.sim_max.setText(f"{mx*100:.1f}%")
        except Exception:
            pass

    def _chk_traffic(self, state):
        self.canvas.show_traffic = bool(state)
        self.canvas._vp_key = None
        self.canvas._refresh()
        self.canvas.update()

    def _nearby(self):
        if not self.engine:
            QMessageBox.warning(self, "提示", "请先生成或加载地图")
            return
        x = self.panel.spin_nx.value()
        y = self.panel.spin_ny.value()
        k = self.panel.spin_nk.value()
        self.canvas.find_nearby(x, y, k)
        self.panel.tabs.setCurrentIndex(1)  # 切到查询Tab

    def _nearby_clear(self):
        self.canvas.clear_nearby()
        self.statusBar().showMessage("F1 子图已清除")

    def _time_query(self):
        if not self.engine:
            QMessageBox.warning(self, "提示", "请先生成或加载地图")
            return
        x = self.panel.spin_tx.value()
        y = self.panel.spin_ty.value()
        t = self.panel.spin_time.value()
        r = self.panel.spin_tr.value()
        self.canvas.query_time_traffic(x, y, t, r)

    def _time_clear(self):
        self.canvas.clear_time_query()
        self.statusBar().showMessage("时间查询已清除")

    def closeEvent(self, e):
        self.canvas.stop_simulation()
        super().closeEvent(e)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Navigation System")
    # 设置全局调色板（浅色）
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#F0F4F8"))
    palette.setColor(QPalette.WindowText, QColor("#1E293B"))
    palette.setColor(QPalette.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.AlternateBase, QColor("#F8FAFC"))
    palette.setColor(QPalette.Text, QColor("#1E293B"))
    palette.setColor(QPalette.Button, QColor("#FFFFFF"))
    palette.setColor(QPalette.ButtonText, QColor("#1E293B"))
    palette.setColor(QPalette.Highlight, QColor("#1A73E8"))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
