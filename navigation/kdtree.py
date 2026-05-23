"""
kdtree.py — KD-Tree 空间索引

手动实现的二维 KD-Tree，用于支持：
    - K 最近邻查询 (F1: 输入坐标显示最近 100 个点)
    - 矩形范围查询  (F2: 地图缩放时获取视口内的点)
    - 代表点查询    (F2: 缩放级别高时每个网格只显示一个代表点)

为什么自己实现而不直接用 scipy.spatial.KDTree？
    1. 课程设计的核心考核是数据结构的应用，自己实现 KD-Tree 最能体现能力。
    2. 答辩时 KD-Tree 是必问的数据结构，必须理解建树、分割、回溯搜索的全过程。
    3. 提供 scipy KDTree 作为对比验证手段，确保自实现的正确性。

数据结构：
    KD-Tree 是一种二叉搜索树，每一层按交替的维度（x 或 y）进行分割：
    - 偶数层按 x 坐标分割
    - 奇数层按 y 坐标分割
    每个节点存储一个点，左子树包含分割维度上坐标较小的点，右子树包含较大的点。

时间复杂度：
    - 建树: O(N log N)  —— 每层 O(N) quickselect 选中位数
    - K 最近邻查询: O(k log N)（平均情况）
    - 范围查询: O(√N + k)（平均情况，k 为结果数）
"""

from __future__ import annotations

import math
import heapq
import random
from typing import List, Optional, Tuple

from .graph import Vertex, Graph


# ---------------------------------------------------------------------------
# KDNode — KD-Tree 的节点
# ---------------------------------------------------------------------------

class KDNode:
    """KD-Tree 的内部节点。"""
    __slots__ = ('vertex', 'left', 'right', 'axis')

    def __init__(
        self,
        vertex: Vertex,
        left: Optional[KDNode] = None,
        right: Optional[KDNode] = None,
        axis: int = 0,
    ) -> None:
        self.vertex = vertex
        self.left = left
        self.right = right
        self.axis = axis  # 0 = x, 1 = y


# ---------------------------------------------------------------------------
# KDTree — 二维 KD-Tree
# ---------------------------------------------------------------------------

class KDTree:
    """
    二维 KD-Tree 空间索引。

    使用方式：
        tree = KDTree()
        tree.build(graph)           # 从 Graph 构建，O(N log N)
        nearest = tree.query_k_nearest(x, y, k=100)  # K 最近邻
        in_view = tree.query_range(x_min, y_min, x_max, y_max)  # 范围查询
    """

    def __init__(self) -> None:
        self._root: Optional[KDNode] = None
        self._size: int = 0

    @property
    def size(self) -> int:
        return self._size

    # ---- 建树 ----

    def build(self, graph: Graph) -> None:
        """
        从 Graph 对象的所有顶点构建 KD-Tree。

        算法：
            1. 收集所有顶点到数组。
            2. 在当前维度上使用 quickselect（introselect）找到中位数。
            3. 以中位数为分割点，递归构建左右子树，交替切换维度。

        使用 quickselect 而非 sort 的理由：
            sort 在每层是 O(n log n)，总复杂度为 O(N log² N)。
            quickselect 在每层是 O(n)，总复杂度为 O(N log N)。

        时间复杂度: O(N log N) —— 每层 O(N) quickselect
        空间复杂度: O(N)
        """
        vertices = list(graph.vertices())
        self._size = len(vertices)
        self._root = self._build_recursive(vertices, 0, len(vertices), depth=0)

    def build_from_vertices(self, vertices: List[Vertex]) -> None:
        """直接从顶点列表构建 KD-Tree。"""
        verts = list(vertices)
        self._size = len(verts)
        self._root = self._build_recursive(verts, 0, len(verts), depth=0)

    def _build_recursive(
        self, points: List[Vertex], lo: int, hi: int, depth: int
    ) -> Optional[KDNode]:
        """
        递归建树（原地操作，使用索引避免切片拷贝）。

        Args:
            points: 共享的顶点数组（原地重排）。
            lo: 当前子数组的起始索引（含）。
            hi: 当前子数组的结束索引（不含）。
            depth: 当前递归深度。
        """
        if lo >= hi:
            return None

        axis = depth % 2  # 0 = x, 1 = y
        mid = (lo + hi) // 2

        # 使用 quickselect（introselect）将第 mid 小的元素放到 points[mid]
        # 同时保证 points[lo:mid] 都 <= points[mid]，points[mid+1:hi] 都 >= points[mid]
        self._nth_element(points, lo, hi, mid, axis)

        return KDNode(
            vertex=points[mid],
            left=self._build_recursive(points, lo, mid, depth + 1),
            right=self._build_recursive(points, mid + 1, hi, depth + 1),
            axis=axis,
        )

    @staticmethod
    def _nth_element(
        arr: List[Vertex], lo: int, hi: int, k: int, axis: int
    ) -> None:
        """
        Quickselect（三数取中 pivot）原地选第 k 小元素。

        完成后 arr[k] 是第 k 小的元素，arr[lo:k] 都 <= arr[k]，
        arr[k+1:hi] 都 >= arr[k]。

        时间复杂度: O(n) 期望，最坏可能退化到 O(n^2)
        """
        while lo < hi - 1:
            # 三数取中作为 pivot
            mid_idx = (lo + hi - 1) // 2
            a = arr[lo].x if axis == 0 else arr[lo].y
            b = arr[mid_idx].x if axis == 0 else arr[mid_idx].y
            c = arr[hi - 1].x if axis == 0 else arr[hi - 1].y

            # 将中位数放到 lo 位置作为 pivot
            if (a <= b <= c) or (c <= b <= a):
                arr[lo], arr[mid_idx] = arr[mid_idx], arr[lo]
            elif (b <= c <= a) or (a <= c <= b):
                arr[lo], arr[hi - 1] = arr[hi - 1], arr[lo]
            # else: a is already the median, leave it at lo

            pivot_val = arr[lo].x if axis == 0 else arr[lo].y

            # Lomuto partition
            i = lo + 1
            j = lo + 1
            while j < hi:
                val_j = arr[j].x if axis == 0 else arr[j].y
                if val_j < pivot_val:
                    arr[i], arr[j] = arr[j], arr[i]
                    i += 1
                j += 1
            pivot_pos = i - 1
            arr[lo], arr[pivot_pos] = arr[pivot_pos], arr[lo]

            if pivot_pos == k:
                return
            elif k < pivot_pos:
                hi = pivot_pos
            else:
                lo = pivot_pos + 1

    # ---- K 最近邻查询 ----

    def query_k_nearest(
        self, x: float, y: float, k: int = 100
    ) -> List[Tuple[float, Vertex]]:
        """
        查找距离给定坐标最近的 k 个顶点。

        算法：
            使用最大堆（size=k）维护当前最近的 k 个点。
            递归遍历 KD-Tree，利用分割超平面进行剪枝：
            如果查询点到分割超平面的距离 > 当前第 k 近距离，
            则不需要搜索另一侧子树。

        Args:
            x, y: 查询坐标。
            k: 返回的最近邻数量。

        Returns:
            按距离升序排列的 (distance, Vertex) 列表。

        时间复杂度: O(k log N)（平均情况）
        """
        if self._root is None or k <= 0:
            return []

        # 用最大堆维护 k 个最近点（取负距离实现最大堆）
        heap: List[Tuple[float, int, Vertex]] = []  # (-dist, id, vertex)

        self._knn_search(self._root, x, y, k, heap)

        # 转换结果，按距离升序
        result = [(-neg_dist, v) for neg_dist, _, v in heap]
        result.sort(key=lambda t: t[0])
        return result

    def _knn_search(
        self,
        node: Optional[KDNode],
        x: float,
        y: float,
        k: int,
        heap: List[Tuple[float, int, Vertex]],
    ) -> None:
        """递归 KNN 搜索，使用最大堆剪枝。"""
        if node is None:
            return

        # 计算查询点到当前节点的距离
        dx = x - node.vertex.x
        dy = y - node.vertex.y
        dist = math.hypot(dx, dy)

        # 尝试将当前节点加入堆
        if len(heap) < k:
            heapq.heappush(heap, (-dist, node.vertex.id, node.vertex))
        elif dist < -heap[0][0]:
            heapq.heapreplace(heap, (-dist, node.vertex.id, node.vertex))

        # 决定先搜索哪一侧
        if node.axis == 0:
            diff = dx  # x 维度
        else:
            diff = dy  # y 维度

        # 先搜索查询点所在的一侧
        if diff <= 0:
            near_side, far_side = node.left, node.right
        else:
            near_side, far_side = node.right, node.left

        self._knn_search(near_side, x, y, k, heap)

        # 检查是否需要搜索另一侧
        # 只有当堆未满或查询点到分割超平面的距离 < 当前第 k 近距离时才搜索
        if len(heap) < k or abs(diff) < -heap[0][0]:
            self._knn_search(far_side, x, y, k, heap)

    # ---- 最近邻查询（单点） ----

    def query_nearest(self, x: float, y: float) -> Optional[Tuple[float, Vertex]]:
        """
        查找距离给定坐标最近的单个顶点。

        Returns:
            (distance, Vertex) 或 None（树为空时）。
        """
        result = self.query_k_nearest(x, y, k=1)
        return result[0] if result else None

    # ---- 矩形范围查询 ----

    def query_range(
        self,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
    ) -> List[Vertex]:
        """
        查找落在指定矩形范围内的所有顶点。

        用于地图缩放时获取当前视口（viewport）内的所有点。

        Args:
            x_min, y_min: 矩形左下角。
            x_max, y_max: 矩形右上角。

        Returns:
            范围内所有 Vertex 的列表。

        时间复杂度: O(sqrt(N) + k)（平均情况）
        """
        result: List[Vertex] = []
        if self._root is None:
            return result
        self._range_search(self._root, x_min, y_min, x_max, y_max, result)
        return result

    def _range_search(
        self,
        node: Optional[KDNode],
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
        result: List[Vertex],
    ) -> None:
        """递归范围搜索。"""
        if node is None:
            return

        vx, vy = node.vertex.x, node.vertex.y

        # 检查当前节点是否在范围内
        if x_min <= vx <= x_max and y_min <= vy <= y_max:
            result.append(node.vertex)

        # 利用分割维度剪枝
        if node.axis == 0:
            # x 维度分割
            if x_min <= vx:  # 范围可能延伸到左子树
                self._range_search(node.left, x_min, y_min, x_max, y_max, result)
            if x_max >= vx:  # 范围可能延伸到右子树
                self._range_search(node.right, x_min, y_min, x_max, y_max, result)
        else:
            # y 维度分割
            if y_min <= vy:
                self._range_search(node.left, x_min, y_min, x_max, y_max, result)
            if y_max >= vy:
                self._range_search(node.right, x_min, y_min, x_max, y_max, result)

    # ---- 代表点查询（缩放用） ----

    def query_representative(
        self,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
        grid_cols: int = 20,
        grid_rows: int = 15,
    ) -> List[Vertex]:
        """
        在给定视口内，将空间网格化并返回每个网格的代表点。

        用于 F2 地图缩放：当缩放级别很高（视口很大）时，
        显示所有点会造成视觉混乱。此方法将视口分成网格，
        每个网格只返回一个离网格中心最近的代表点。

        Args:
            x_min, y_min, x_max, y_max: 视口范围。
            grid_cols, grid_rows: 网格的列数和行数。

        Returns:
            代表点列表。
        """
        # 获取范围内所有点
        all_in_range = self.query_range(x_min, y_min, x_max, y_max)
        if not all_in_range:
            return []

        cell_w = (x_max - x_min) / grid_cols if grid_cols > 0 else 1.0
        cell_h = (y_max - y_min) / grid_rows if grid_rows > 0 else 1.0

        # 每个网格保留离网格中心最近的一个点
        grid: dict = {}
        for v in all_in_range:
            ci = min(int((v.x - x_min) / cell_w), grid_cols - 1)
            cj = min(int((v.y - y_min) / cell_h), grid_rows - 1)
            cell_key = (ci, cj)
            # 网格中心
            cx = x_min + (ci + 0.5) * cell_w
            cy = y_min + (cj + 0.5) * cell_h
            dist = math.hypot(v.x - cx, v.y - cy)
            if cell_key not in grid or dist < grid[cell_key][0]:
                grid[cell_key] = (dist, v)

        return [v for _, v in grid.values()]

    def __repr__(self) -> str:
        return f"KDTree(size={self._size})"
