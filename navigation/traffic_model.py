"""
traffic_model.py - traffic travel-time and congestion helpers.

This module keeps the formula from the assignment in one place:

    t = c * L * f(n / v)

where f(x) = 1 when x <= threshold, otherwise 1 + exp(x).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TrafficParameters:
    """Parameters used by the traffic travel-time model."""

    c: float = 1.0
    threshold: float = 0.8

    def __post_init__(self) -> None:
        if self.c < 1.0:
            raise ValueError("c must be >= 1.0 so A* Euclidean heuristic remains admissible")
        if self.threshold < 0:
            raise ValueError("threshold must be non-negative")


def congestion_ratio(current_cars: float, capacity: int) -> float:
    """Return n / v. Non-positive capacity is treated as fully blocked."""
    if capacity <= 0:
        return float("inf")
    return max(0.0, current_cars) / capacity


def delay_factor(ratio: float, threshold: float = 0.8) -> float:
    """Return the assignment's piecewise f(x) delay multiplier."""
    if threshold < 0:
        raise ValueError("threshold must be non-negative")
    if ratio <= threshold:
        return 1.0
    return 1.0 + math.exp(ratio)


def travel_time(
    length: float,
    capacity: int,
    current_cars: float,
    c: float = 1.0,
    threshold: float = 0.8,
) -> float:
    """Calculate traffic-aware travel time for one road segment."""
    TrafficParameters(c=c, threshold=threshold)
    if capacity <= 0:
        return float("inf")
    ratio = congestion_ratio(current_cars, capacity)
    return c * length * delay_factor(ratio, threshold)


def congestion_level(current_cars: float, capacity: int) -> int:
    """
    Return a display-friendly congestion level:
    0 clear, 1 slow, 2 congested, 3 severe.
    """
    ratio = congestion_ratio(current_cars, capacity)
    if ratio <= 0.30:
        return 0
    if ratio <= 0.70:
        return 1
    if ratio <= 1.00:
        return 2
    return 3
