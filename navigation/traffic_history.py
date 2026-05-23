"""
traffic_history.py - 交通历史记录器
用于存储和查询不同时间步的交通状态。
"""

from typing import Dict, List, Optional, Tuple
from .traffic_simulator import TrafficSnapshot, EdgeTrafficState, EdgeKey

class TrafficHistory:
    """
    存储交通模拟的历史快照。
    """
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.history: Dict[int, TrafficSnapshot] = {}
        self.time_steps: List[int] = []

    def add_snapshot(self, snapshot: TrafficSnapshot):
        """添加一个新的交通快照。"""
        t = snapshot.time_step
        if t in self.history:
            return
        
        self.history[t] = snapshot
        self.time_steps.append(t)
        
        # 保持历史记录在限制范围内
        if len(self.time_steps) > self.max_history:
            oldest_t = self.time_steps.pop(0)
            del self.history[oldest_t]

    def get_snapshot(self, time_step: int) -> Optional[TrafficSnapshot]:
        """获取指定时间步的快照。如果不存在，返回最接近的一个。"""
        if not self.time_steps:
            return None
        
        if time_step in self.history:
            return self.history[time_step]
        
        # 查找最接近的时间步
        closest_t = min(self.time_steps, key=lambda t: abs(t - time_step))
        return self.history[closest_t]

    def clear(self):
        """清除所有历史记录。"""
        self.history.clear()
        self.time_steps.clear()

    @property
    def latest_time(self) -> int:
        """返回最新的时间步。"""
        return self.time_steps[-1] if self.time_steps else 0
