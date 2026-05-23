"""
Navigation System — 导航系统后端核心模块

本包包含导航系统的核心数据结构与算法实现：
- graph: 图数据结构（Vertex, Edge, Graph）
- map_generator: 基于 Delaunay 三角剖分的地图生成引擎
- serializer: 图的 JSON 序列化/反序列化
- kdtree: KD-Tree 空间索引（K 近邻、范围查询）
- pathfinding: 最短路径算法（Dijkstra, A*）
- traffic_model / traffic_simulator: 交通通行时间与宏观流量模拟
- engine: NavigationEngine 统一 API（供成员 B 集成）
"""

from .graph import Vertex, Edge, Graph
from .map_generator import MapGenerator
from .serializer import GraphSerializer
from .kdtree import KDTree
from .pathfinding import (
    PathResult, dijkstra, astar, shortest_path,
    default_weight, make_traffic_weight, WeightFunc,
)
from .engine import NavigationEngine, POIResult, NearbyState, ViewportState
from .traffic_model import (
    TrafficParameters, congestion_ratio, delay_factor,
    travel_time, congestion_level,
)
from .traffic_simulator import (
    Car, CarState, EdgeTrafficState, TrafficSnapshot, TrafficSimulator, edge_key,
)

__version__ = "0.4.0"
__all__ = [
    "Vertex", "Edge", "Graph",
    "MapGenerator",
    "GraphSerializer",
    "KDTree",
    "PathResult", "dijkstra", "astar", "shortest_path",
    "default_weight", "make_traffic_weight", "WeightFunc",
    "NavigationEngine", "POIResult", "NearbyState", "ViewportState",
    "TrafficParameters", "congestion_ratio", "delay_factor",
    "travel_time", "congestion_level",
    "Car", "CarState", "EdgeTrafficState", "TrafficSnapshot", "TrafficSimulator", "edge_key",
]
