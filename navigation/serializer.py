"""
serializer.py — 图的 JSON 序列化/反序列化模块

支持将 Graph 对象保存为 JSON 文件和从 JSON 文件加载。
JSON 格式设计参考了 road-network-generator 项目的 file_saver.py，
但扩展支持了交通模拟所需的 capacity 和 current_cars 字段。

JSON 文件格式：
{
    "meta": {
        "version": "1.0",
        "width": 2000.0,
        "height": 1500.0,
        "seed": 42,
        "vertex_count": 10000,
        "edge_count": 28000
    },
    "vertices": [
        {"id": 0, "x": 123.45, "y": 678.90, "metadata": {}},
        ...
    ],
    "edges": [
        {"u": 0, "v": 1, "length": 34.56, "capacity": 50, "current_cars": 0},
        ...
    ]
}
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Iterable, Mapping, Union

from .graph import Vertex, Edge, Graph

logger = logging.getLogger(__name__)

# 当前序列化版本号
_FORMAT_VERSION = "1.0"


class GraphSerializer:
    """
    Graph 对象的 JSON 序列化器。

    使用方式：
        # 保存
        GraphSerializer.save(graph, "map_data.json")

        # 加载
        graph = GraphSerializer.load("map_data.json")
    """

    @staticmethod
    def save(graph: Graph, filepath: Union[str, Path], indent: int = 2) -> None:
        """
        将 Graph 对象保存为 JSON 文件。

        Args:
            graph: 要保存的图对象。
            filepath: 输出文件路径。
            indent: JSON 缩进空格数。设为 None 可压缩体积。

        Raises:
            IOError: 文件写入失败。
        """
        filepath = Path(filepath)
        t_start = time.time()

        data = {
            "meta": {
                "version": _FORMAT_VERSION,
                "width": graph.width,
                "height": graph.height,
                "seed": graph.seed,
                "vertex_count": graph.vertex_count,
                "edge_count": graph.edge_count,
            },
            "vertices": [],
            "edges": [],
        }

        # 序列化顶点
        for vertex in graph.vertices():
            data["vertices"].append({
                "id": vertex.id,
                "x": round(vertex.x, 4),
                "y": round(vertex.y, 4),
                "metadata": vertex.metadata,
            })

        # 序列化边（每条边只存一次）
        for edge in graph.edges():
            data["edges"].append({
                "u": edge.u,
                "v": edge.v,
                "length": round(edge.length, 4),
                "capacity": edge.capacity,
                "current_cars": edge.current_cars,
            })

        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            t_elapsed = time.time() - t_start
            file_size_mb = filepath.stat().st_size / (1024 * 1024)
            logger.info(
                f"图已保存到 {filepath} "
                f"({file_size_mb:.1f} MB, {t_elapsed:.2f}s)"
            )
        except Exception as e:
            logger.error(f"保存图失败: {filepath} — {e}")
            raise

    @staticmethod
    def load(filepath: Union[str, Path]) -> Graph:
        """
        从 JSON 文件加载 Graph 对象。

        Args:
            filepath: 输入文件路径。

        Returns:
            加载的 Graph 对象。

        Raises:
            FileNotFoundError: 文件不存在。
            ValueError: 文件格式不正确。
        """
        filepath = Path(filepath)
        t_start = time.time()

        if not filepath.exists():
            raise FileNotFoundError(f"地图文件不存在: {filepath}")

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 格式错误: {filepath} — {e}")

        # 验证格式
        if not isinstance(data, Mapping) or "meta" not in data or "vertices" not in data or "edges" not in data:
            raise ValueError(f"文件格式不正确，缺少必要的 meta/vertices/edges 字段: {filepath}")

        meta = data["meta"]
        vertices_data = data["vertices"]
        edges_data = data["edges"]
        if not isinstance(meta, Mapping):
            raise ValueError(f"文件格式不正确: meta 必须是对象: {filepath}")
        if not isinstance(vertices_data, list) or not isinstance(edges_data, list):
            raise ValueError(f"文件格式不正确: vertices/edges 必须是数组: {filepath}")

        graph = Graph()
        graph.width = meta.get("width", 0.0)
        graph.height = meta.get("height", 0.0)
        graph.seed = meta.get("seed")

        # 加载顶点
        for index, vdata in enumerate(vertices_data):
            GraphSerializer._require_object(vdata, f"vertices[{index}]")
            GraphSerializer._require_fields(vdata, ("id", "x", "y"), f"vertices[{index}]")
            metadata = vdata.get("metadata", {})
            if metadata is None:
                metadata = {}
            if not isinstance(metadata, dict):
                raise ValueError(f"文件格式不正确: vertices[{index}].metadata 必须是对象")
            vertex = Vertex(
                id=GraphSerializer._read_int(vdata["id"], f"vertices[{index}].id"),
                x=GraphSerializer._read_float(vdata["x"], f"vertices[{index}].x"),
                y=GraphSerializer._read_float(vdata["y"], f"vertices[{index}].y"),
                metadata=metadata,
            )
            graph.add_vertex(vertex)

        # 加载边
        for index, edata in enumerate(edges_data):
            GraphSerializer._require_object(edata, f"edges[{index}]")
            GraphSerializer._require_fields(edata, ("u", "v", "length"), f"edges[{index}]")
            edge = Edge(
                u=GraphSerializer._read_int(edata["u"], f"edges[{index}].u"),
                v=GraphSerializer._read_int(edata["v"], f"edges[{index}].v"),
                length=GraphSerializer._read_float(edata["length"], f"edges[{index}].length"),
                capacity=GraphSerializer._read_int(edata.get("capacity", 50), f"edges[{index}].capacity"),
                current_cars=GraphSerializer._read_int(edata.get("current_cars", 0), f"edges[{index}].current_cars"),
            )
            try:
                graph.add_edge(edge)
            except ValueError as exc:
                raise ValueError(f"文件格式不正确: edges[{index}] 引用了不存在或非法的顶点: {exc}") from exc

        t_elapsed = time.time() - t_start
        logger.info(
            f"图已从 {filepath} 加载: "
            f"V={graph.vertex_count}, E={graph.edge_count}, "
            f"耗时 {t_elapsed:.2f}s"
        )

        # 校验
        expected_v = meta.get("vertex_count", graph.vertex_count)
        expected_e = meta.get("edge_count", graph.edge_count)
        if graph.vertex_count != expected_v or graph.edge_count != expected_e:
            logger.warning(
                f"加载结果与元数据不一致: "
                f"期望 V={expected_v}/E={expected_e}, "
                f"实际 V={graph.vertex_count}/E={graph.edge_count}"
            )

        return graph

    @staticmethod
    def save_compact(graph: Graph, filepath: Union[str, Path]) -> None:
        """
        保存为紧凑格式（无缩进），适合大规模图减小文件体积。
        """
        GraphSerializer.save(graph, filepath, indent=None)

    @staticmethod
    def _require_object(value: object, label: str) -> Mapping:
        if not isinstance(value, Mapping):
            raise ValueError(f"文件格式不正确: {label} 必须是对象")
        return value

    @staticmethod
    def _require_fields(record: Mapping, fields: Iterable[str], label: str) -> None:
        missing = [field for field in fields if field not in record]
        if missing:
            raise ValueError(f"文件格式不正确: {label} 缺少字段 {', '.join(missing)}")

    @staticmethod
    def _read_int(value: object, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"文件格式不正确: {label} 必须是整数")
        return value

    @staticmethod
    def _read_float(value: object, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"文件格式不正确: {label} 必须是有限数字")
        return float(value)
