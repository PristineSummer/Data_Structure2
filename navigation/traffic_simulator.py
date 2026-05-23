"""
traffic_simulator.py - hybrid traffic simulation.

The simulator combines two layers:

1. Explicit vehicles for dynamic route visualization.
2. Background edge flow for stable large-map congestion.

Both layers feed Edge.current_cars, so existing shortest-path code can use the
same dynamic travel-time formula without knowing where the cars came from.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .graph import Edge, Graph
from .pathfinding import astar
from .traffic_model import TrafficParameters

EdgeKey = Tuple[int, int]


def edge_key(u: int, v: int) -> EdgeKey:
    """Return the canonical key for an undirected edge."""
    return (min(u, v), max(u, v))


def _ratio_for(current_cars: float, capacity: int) -> float:
    if capacity <= 0:
        return float("inf")
    return max(0.0, current_cars) / capacity


def _delay_factor_for(ratio: float, threshold: float) -> float:
    if ratio <= threshold:
        return 1.0
    return 1.0 + math.exp(ratio)


def _travel_time_for(
    length: float,
    capacity: int,
    current_cars: float,
    c: float,
    threshold: float,
) -> float:
    if capacity <= 0:
        return float("inf")
    ratio = _ratio_for(current_cars, capacity)
    return c * length * _delay_factor_for(ratio, threshold)


def _congestion_level_for(current_cars: float, capacity: int) -> int:
    """Delegate to traffic_model for consistent 5-level congestion grading."""
    from .traffic_model import congestion_level as _model_level
    return _model_level(current_cars, capacity)


@dataclass(slots=True)
class Car:
    """Mutable internal vehicle state."""

    id: int
    start_id: int
    end_id: int
    route: List[int]
    route_index: int = 0
    current_edge: Optional[EdgeKey] = None
    from_id: Optional[int] = None
    to_id: Optional[int] = None
    progress: float = 0.0
    remaining_time: float = 0.0
    edge_travel_time: float = 0.0
    status: str = "active"
    reroutes: int = 0


@dataclass(frozen=True, slots=True)
class CarState:
    """Display-friendly vehicle snapshot for the GUI layer."""

    id: int
    start_id: int
    end_id: int
    route: Tuple[int, ...]
    current_edge: Optional[EdgeKey]
    from_id: Optional[int]
    to_id: Optional[int]
    progress: float
    remaining_time: float
    status: str
    x: Optional[float] = None
    y: Optional[float] = None


@dataclass(frozen=True, slots=True)
class EdgeTrafficState:
    """Snapshot of one road segment at a simulation step."""

    u: int
    v: int
    current_cars: float
    background_cars: float
    vehicle_cars: int
    capacity: int
    ratio: float
    level: int
    travel_time: float


@dataclass(frozen=True, slots=True)
class TrafficSnapshot:
    """Traffic state returned to the GUI layer after each step."""

    time_step: int
    edge_states: Dict[EdgeKey, EdgeTrafficState] = field(default_factory=dict)
    total_cars: float = 0.0
    active_cars: int = 0
    completed_cars: int = 0
    failed_spawns: int = 0
    average_ratio: float = 0.0
    max_ratio: float = 0.0


class TrafficSimulator:
    """
    Hybrid traffic simulator for 10000-node road networks.

    Explicit cars provide visible motion; background flow keeps congestion
    meaningful even when only a small number of cars are rendered.
    """

    def __init__(
        self,
        graph: Graph,
        *,
        c: float = 1.0,
        threshold: float = 0.8,
        base_outflow_rate: float = 0.25,
        max_outflow_rate: float = 0.65,
        reroute_on_node: bool = True,
        max_reroutes_per_step: int = 50,
        background_update_interval: int = 1,
        dynamic_background_routing: bool = True,
        background_route_sensitivity: float = 2.0,
        seed: Optional[int] = None,
    ) -> None:
        TrafficParameters(c=c, threshold=threshold)
        if base_outflow_rate <= 0:
            raise ValueError("base_outflow_rate must be positive")
        if max_outflow_rate <= 0:
            raise ValueError("max_outflow_rate must be positive")
        if max_reroutes_per_step < 0:
            raise ValueError("max_reroutes_per_step must be non-negative")
        if background_update_interval <= 0:
            raise ValueError("background_update_interval must be positive")
        if (
            isinstance(background_route_sensitivity, bool)
            or not isinstance(background_route_sensitivity, (int, float))
            or not math.isfinite(background_route_sensitivity)
            or background_route_sensitivity <= 0
        ):
            raise ValueError("background_route_sensitivity must be positive")

        self.graph = graph
        self.c = c
        self.threshold = threshold
        self.base_outflow_rate = base_outflow_rate
        self.max_outflow_rate = max_outflow_rate
        self.reroute_on_node = reroute_on_node
        self.max_reroutes_per_step = max_reroutes_per_step
        self.background_update_interval = background_update_interval
        self.dynamic_background_routing = dynamic_background_routing
        self.background_route_sensitivity = background_route_sensitivity
        self.time_step = 0
        self.failed_spawns = 0
        self._rng = random.Random(seed)

        self._edges: Dict[EdgeKey, Edge] = {}
        self._edge_capacities: Dict[EdgeKey, int] = {}
        self._edge_lengths: Dict[EdgeKey, float] = {}
        self._edge_endpoints: Dict[EdgeKey, Tuple[int, int]] = {}
        self._incident_edges: Dict[int, List[EdgeKey]] = defaultdict(list)
        self._background_cars: Dict[EdgeKey, float] = {}
        self._vehicle_counts: Dict[EdgeKey, int] = defaultdict(int)
        self._transition_candidates: Dict[Tuple[EdgeKey, int], List[EdgeKey]] = {}
        self._transition_weights: Dict[Tuple[EdgeKey, int], List[Tuple[EdgeKey, float]]] = {}
        self._cars: Dict[int, Car] = {}
        self._next_car_id = 1
        self._vertex_ids = list(graph.vertex_ids())
        # POI 吸引力：车辆生成时偏好 POI 点作为起点/终点
        self._poi_vertex_ids: List[int] = [
            vid for vid in self._vertex_ids
            if graph.get_vertex(vid) is not None
            and graph.get_vertex(vid).metadata.get("poi")
        ]
        self._poi_attraction = 0.85  # 85% 的概率选择 POI 点作为起点或终点

        for edge in graph.edges():
            key = edge_key(edge.u, edge.v)
            self._edges[key] = edge
            self._edge_capacities[key] = edge.capacity
            self._edge_lengths[key] = edge.length
            self._edge_endpoints[key] = (edge.u, edge.v)
            self._incident_edges[edge.u].append(key)
            self._incident_edges[edge.v].append(key)
            self._background_cars[key] = max(0.0, float(edge.current_cars))

        self._build_transition_weights()
        self._rebuild_vehicle_counts()
        self._sync_graph_edges()

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    @property
    def active_cars(self) -> int:
        return sum(1 for car in self._cars.values() if car.status == "active")

    @property
    def completed_cars(self) -> int:
        return sum(1 for car in self._cars.values() if car.status == "completed")

    @property
    def total_cars(self) -> float:
        return sum(self._edge_total_cars(key) for key in self._edges)

    def sync_from_graph(self) -> None:
        """Refresh background traffic from graph Edge.current_cars values."""
        self._rebuild_vehicle_counts()
        for key, edge in self._edges.items():
            vehicle_cars = self._vehicle_counts.get(key, 0)
            self._background_cars[key] = max(0.0, float(edge.current_cars) - vehicle_cars)
        self._sync_graph_edges()

    def set_edge_cars(self, u: int, v: int, count: float) -> None:
        """Set background traffic on one edge and mirror total load to the graph."""
        key = edge_key(u, v)
        if key not in self._edges:
            raise ValueError(f"edge ({u}, {v}) does not exist")
        self._background_cars[key] = max(0.0, float(count))
        self._sync_graph_edges([key])

    def add_edge_cars(self, u: int, v: int, count: float) -> None:
        """Add background cars to one edge."""
        key = edge_key(u, v)
        if key not in self._edges:
            raise ValueError(f"edge ({u}, {v}) does not exist")
        self._background_cars[key] = max(0.0, self._background_cars[key] + float(count))
        self._sync_graph_edges([key])

    def randomize_traffic(
        self,
        min_ratio: float = 0.0,
        max_ratio: float = 0.7,
        *,
        seed: Optional[int] = None,
    ) -> TrafficSnapshot:
        """Initialize background traffic as a random fraction of each edge capacity."""
        if min_ratio < 0 or max_ratio < min_ratio:
            raise ValueError("invalid traffic ratio range")
        rng = random.Random(seed) if seed is not None else self._rng
        for key, edge in self._edges.items():
            self._background_cars[key] = rng.uniform(min_ratio, max_ratio) * max(edge.capacity, 0)
        self._sync_graph_edges()
        return self.get_traffic_snapshot()

    def spawn_car(
        self,
        start_id: Optional[int] = None,
        end_id: Optional[int] = None,
        *,
        max_attempts: int = 20,
    ) -> Optional[int]:
        """Create one routed car. Returns the car id, or None if no route is found.
        When start/end are not specified, POI vertices are preferred with
        probability self._poi_attraction to create realistic traffic hotspots.
        """
        if len(self._vertex_ids) < 2:
            self.failed_spawns += 1
            return None

        def _pick_vertex(explicit_id: Optional[int]) -> int:
            if explicit_id is not None:
                return explicit_id
            if self._poi_vertex_ids and self._rng.random() < self._poi_attraction:
                return self._rng.choice(self._poi_vertex_ids)
            return self._rng.choice(self._vertex_ids)

        for _ in range(max_attempts):
            start = _pick_vertex(start_id)
            end = _pick_vertex(end_id)
            if start == end:
                if start_id is not None and end_id is not None:
                    break
                continue

            route = self._plan_route(start, end)
            if len(route) < 2:
                if start_id is not None and end_id is not None:
                    break
                continue

            car_id = self._next_car_id
            self._next_car_id += 1
            car = Car(id=car_id, start_id=start, end_id=end, route=route)
            if not self._enter_next_edge(car):
                self.failed_spawns += 1
                return None
            self._cars[car_id] = car
            self._vehicle_counts[car.current_edge] += 1
            self._sync_graph_edges([car.current_edge])
            return car_id

        self.failed_spawns += 1
        return None

    def spawn_cars(
        self,
        count: int,
        start_id: Optional[int] = None,
        end_id: Optional[int] = None,
    ) -> List[int]:
        """Create count explicit vehicles and return their ids."""
        if count <= 0:
            return []
        self._rebuild_vehicle_counts()
        created: List[int] = []
        for _ in range(int(count)):
            car_id = self.spawn_car(start_id=start_id, end_id=end_id)
            if car_id is not None:
                created.append(car_id)
        self._sync_graph_edges()
        return created

    def step(
        self,
        *,
        spawn_count: int = 0,
        external_inflow: Optional[Mapping[EdgeKey, float]] = None,
        time_delta: float = 1.0,
        return_snapshot: bool = True,
    ) -> Optional[TrafficSnapshot]:
        """
        Advance simulation by one step.

        Order:
            1. Move explicit vehicles.
            2. Advance background flow with New = Current - Outgoing + Incoming.
            3. Spawn new explicit vehicles if requested.
            4. Sync edge.current_cars from background + vehicles.
        """
        if time_delta <= 0:
            raise ValueError("time_delta must be positive")

        reroutes_left = self.max_reroutes_per_step
        previous_edges: Dict[int, Optional[EdgeKey]] = {
            car.id: car.current_edge for car in self._cars.values() if car.status == "active"
        }

        for car in list(self._cars.values()):
            if car.status != "active":
                continue
            used = self._advance_car(car, time_delta, reroutes_left)
            reroutes_left = max(0, reroutes_left - used)

        touched_edges = set(previous_edges.values())
        self._rebuild_vehicle_counts()
        touched_edges.update(car.current_edge for car in self._cars.values() if car.current_edge is not None)

        background_updated = (self.time_step % self.background_update_interval) == 0
        if background_updated:
            self._advance_background_flow(external_inflow=external_inflow)
        elif external_inflow:
            for raw_key, amount in external_inflow.items():
                key = edge_key(raw_key[0], raw_key[1])
                if key in self._background_cars and amount > 0:
                    self._background_cars[key] += float(amount)
                    touched_edges.add(key)

        if spawn_count > 0:
            self.spawn_cars(int(spawn_count))

        self.time_step += 1
        if background_updated or spawn_count > 0:
            self._sync_graph_edges()
        else:
            self._sync_graph_edges(key for key in touched_edges if key is not None)
        if return_snapshot:
            return self.get_traffic_snapshot()
        return None

    def get_edge_travel_time(self, edge: Edge) -> float:
        """Return travel time using current background + explicit vehicles."""
        key = edge_key(edge.u, edge.v)
        return self._edge_travel_time(key)

    def weight_func(self, edge: Edge) -> float:
        """Weight function compatible with Dijkstra/A*."""
        return self.get_edge_travel_time(edge)

    def get_traffic_snapshot(self) -> TrafficSnapshot:
        """Return all edge states for visualization and testing."""
        self._rebuild_vehicle_counts()
        states: Dict[EdgeKey, EdgeTrafficState] = {}
        ratios: List[float] = []
        for key in self._edges:
            state = self._make_edge_state(key)
            states[key] = state
            ratio = state.ratio
            ratios.append(0.0 if math.isinf(ratio) else ratio)

        return TrafficSnapshot(
            time_step=self.time_step,
            edge_states=states,
            total_cars=sum(state.current_cars for state in states.values()),
            active_cars=self.active_cars,
            completed_cars=self.completed_cars,
            failed_spawns=self.failed_spawns,
            average_ratio=(sum(ratios) / len(ratios)) if ratios else 0.0,
            max_ratio=max(ratios) if ratios else 0.0,
        )

    def get_edge_traffic_states(self, keys: Iterable[EdgeKey]) -> Dict[EdgeKey, EdgeTrafficState]:
        """Return traffic states only for the requested road segments."""
        self._rebuild_vehicle_counts()
        states: Dict[EdgeKey, EdgeTrafficState] = {}
        for raw_key in keys:
            key = edge_key(raw_key[0], raw_key[1])
            if key in self._edges:
                states[key] = self._make_edge_state(key)
        return states

    def get_car_snapshot(
        self,
        limit: Optional[int] = None,
        *,
        include_completed: bool = False,
    ) -> List[CarState]:
        """Return vehicle states for dynamic GUI rendering."""
        cars = [
            car for car in self._cars.values()
            if include_completed or car.status == "active"
        ]
        cars.sort(key=lambda car: car.id)
        if limit is not None:
            cars = cars[:max(0, int(limit))]
        return [self._to_car_state(car) for car in cars]

    def _advance_background_flow(
        self,
        *,
        external_inflow: Optional[Mapping[EdgeKey, float]] = None,
    ) -> None:
        incoming: Dict[EdgeKey, float] = {}
        outgoing: Dict[EdgeKey, float] = {}
        threshold = self.threshold
        base_outflow_rate = self.base_outflow_rate
        max_outflow_rate = self.max_outflow_rate
        bg = self._background_cars
        veh = self._vehicle_counts
        capacities = self._edge_capacities
        endpoints = self._edge_endpoints
        travel_times = self._compute_edge_travel_times() if self.dynamic_background_routing else None

        for key, current in bg.items():
            if current <= 0:
                continue
            capacity = capacities[key]
            total = current + veh.get(key, 0)
            ratio = _ratio_for(total, capacity)
            factor = _delay_factor_for(ratio, threshold)
            outflow_rate = min(max_outflow_rate, base_outflow_rate / factor)
            amount = min(current, current * outflow_rate)
            outgoing[key] = amount

            share = amount / 2.0
            u, v = endpoints[key]
            for node_id in (u, v):
                node_transitions = self._get_background_transitions(
                    key,
                    node_id,
                    travel_times=travel_times,
                )
                if not node_transitions:
                    incoming[key] = incoming.get(key, 0.0) + share
                else:
                    for target_key, weight in node_transitions:
                        incoming[target_key] = incoming.get(target_key, 0.0) + share * weight

        next_background: Dict[EdgeKey, float] = {}
        for key, current in bg.items():
            next_background[key] = max(0.0, current - outgoing.get(key, 0.0) + incoming.get(key, 0.0))

        if external_inflow:
            for raw_key, amount in external_inflow.items():
                key = edge_key(raw_key[0], raw_key[1])
                if key in next_background and amount > 0:
                    next_background[key] += float(amount)

        self._background_cars = next_background

    def _advance_car(self, car: Car, time_delta: float, reroutes_left: int) -> int:
        if car.current_edge is None:
            if not self._enter_next_edge(car):
                car.status = "failed"
            return 0

        if math.isinf(car.remaining_time):
            car.progress = 0.0
            return 0

        car.remaining_time = max(0.0, car.remaining_time - time_delta)
        if car.edge_travel_time > 0:
            car.progress = min(1.0, 1.0 - car.remaining_time / car.edge_travel_time)

        if car.remaining_time > 0:
            return 0

        arrived_node = car.to_id
        car.route_index += 1
        car.current_edge = None
        car.from_id = arrived_node
        car.to_id = None
        car.progress = 1.0

        if arrived_node == car.end_id:
            car.status = "completed"
            return 0

        reroutes_used = 0
        if self.reroute_on_node and reroutes_left > 0 and self._should_reroute(car):
            route = self._plan_route(arrived_node, car.end_id)
            if len(route) >= 2:
                car.route = route
                car.route_index = 0
                car.reroutes += 1
                reroutes_used = 1

        if not self._enter_next_edge(car):
            car.status = "failed"
        return reroutes_used

    def _enter_next_edge(self, car: Car) -> bool:
        if car.route_index >= len(car.route) - 1:
            return False
        from_id = car.route[car.route_index]
        to_id = car.route[car.route_index + 1]
        edge = self.graph.get_edge(from_id, to_id)
        if edge is None:
            return False

        key = edge_key(from_id, to_id)
        car.current_edge = key
        car.from_id = from_id
        car.to_id = to_id
        car.progress = 0.0
        edge_time = self.get_edge_travel_time(edge)
        car.edge_travel_time = edge_time
        car.remaining_time = edge_time
        return True

    def _should_reroute(self, car: Car) -> bool:
        """
        Replan only when the current planned next road is already congested.

        This keeps large simulations interactive while still demonstrating
        traffic-aware avoidance when the vehicle reaches a bad road.
        """
        if car.route_index >= len(car.route) - 1:
            return False
        next_u = car.route[car.route_index]
        next_v = car.route[car.route_index + 1]
        key = edge_key(next_u, next_v)
        edge = self._edges.get(key)
        if edge is None:
            return True
        return _ratio_for(self._edge_total_cars(key), edge.capacity) > self.threshold

    def _plan_route(self, start_id: int, end_id: int) -> List[int]:
        result = astar(self.graph, start_id, end_id, weight_func=self.weight_func)
        return result.path if result.found else []

    def _to_car_state(self, car: Car) -> CarState:
        x = y = None
        if car.from_id is not None and car.to_id is not None:
            from_v = self.graph.get_vertex(car.from_id)
            to_v = self.graph.get_vertex(car.to_id)
            if from_v is not None and to_v is not None:
                p = max(0.0, min(1.0, car.progress))
                x = from_v.x + (to_v.x - from_v.x) * p
                y = from_v.y + (to_v.y - from_v.y) * p

        return CarState(
            id=car.id,
            start_id=car.start_id,
            end_id=car.end_id,
            route=tuple(car.route),
            current_edge=car.current_edge,
            from_id=car.from_id,
            to_id=car.to_id,
            progress=car.progress,
            remaining_time=car.remaining_time,
            status=car.status,
            x=x,
            y=y,
        )

    def _distribute_from_node(
        self,
        source_key: EdgeKey,
        node_id: int,
        amount: float,
        incoming: Dict[EdgeKey, float],
    ) -> None:
        if amount <= 0:
            return

        transitions = self._get_background_transitions(source_key, node_id)
        if not transitions:
            incoming[source_key] += amount
            return

        for key, weight in transitions:
            incoming[key] += amount * weight

    def _get_background_transitions(
        self,
        source_key: EdgeKey,
        node_id: int,
        *,
        travel_times: Optional[Mapping[EdgeKey, float]] = None,
    ) -> List[Tuple[EdgeKey, float]]:
        """
        Return turn probabilities for background flow at a node.

        By default, background cars prefer roads with lower current travel time.
        This keeps the macroscopic traffic layer consistent with F5's
        traffic-aware shortest path weights while avoiding a full route search
        for every background car.
        """
        if not self.dynamic_background_routing:
            return self._transition_weights.get((source_key, node_id), [])

        candidates = self._transition_candidates.get((source_key, node_id), [])
        if not candidates:
            return []

        scores: List[float] = []
        sensitivity = self.background_route_sensitivity
        for key in candidates:
            edge_time = travel_times[key] if travel_times is not None else self._edge_travel_time(key)
            if math.isinf(edge_time) or edge_time <= 0:
                score = 0.0
            elif sensitivity == 2.0:
                score = 1.0 / (edge_time * edge_time)
            elif sensitivity == 1.0:
                score = 1.0 / edge_time
            else:
                score = 1.0 / (edge_time ** sensitivity)
            scores.append(score)

        total_score = sum(scores)
        if total_score <= 0:
            weight = 1.0 / len(candidates)
            return [(key, weight) for key in candidates]

        return [
            (key, score / total_score)
            for key, score in zip(candidates, scores)
        ]

    def _build_transition_weights(self) -> None:
        """
        Precompute background-flow turn weights.

        Dynamic edge travel times are still used for explicit vehicle routing.
        These static capacity/length preferences are retained as an optional
        fallback when dynamic_background_routing=False.
        """
        for source_key, edge in self._edges.items():
            for node_id in (edge.u, edge.v):
                candidates = [key for key in self._incident_edges.get(node_id, []) if key != source_key]
                self._transition_candidates[(source_key, node_id)] = candidates
                if not candidates:
                    self._transition_weights[(source_key, node_id)] = []
                    continue
                scores = []
                for key in candidates:
                    candidate = self._edges[key]
                    scores.append(max(1.0, candidate.capacity) / max(candidate.length, 1e-9))
                total_score = sum(scores)
                if total_score <= 0:
                    weight = 1.0 / len(candidates)
                    self._transition_weights[(source_key, node_id)] = [(key, weight) for key in candidates]
                else:
                    self._transition_weights[(source_key, node_id)] = [
                        (key, score / total_score)
                        for key, score in zip(candidates, scores)
                    ]

    def _edge_total_cars(self, key: EdgeKey) -> float:
        return self._background_cars.get(key, 0.0) + self._vehicle_counts.get(key, 0)

    def _edge_travel_time(self, key: EdgeKey, total_cars: Optional[float] = None) -> float:
        capacity = self._edge_capacities[key]
        cars = self._edge_total_cars(key) if total_cars is None else total_cars
        return _travel_time_for(
            self._edge_lengths[key],
            capacity,
            cars,
            self.c,
            self.threshold,
        )

    def _compute_edge_travel_times(self) -> Dict[EdgeKey, float]:
        bg = self._background_cars
        veh = self._vehicle_counts
        capacities = self._edge_capacities
        lengths = self._edge_lengths
        c = self.c
        threshold = self.threshold
        return {
            key: _travel_time_for(
                lengths[key],
                capacities[key],
                bg.get(key, 0.0) + veh.get(key, 0),
                c,
                threshold,
            )
            for key in self._edges
        }

    def _make_edge_state(self, key: EdgeKey) -> EdgeTrafficState:
        background = self._background_cars.get(key, 0.0)
        vehicles = self._vehicle_counts.get(key, 0)
        total = background + vehicles
        capacity = self._edge_capacities[key]
        ratio = _ratio_for(total, capacity)
        u, v = self._edge_endpoints[key]
        return EdgeTrafficState(
            u=u,
            v=v,
            current_cars=total,
            background_cars=background,
            vehicle_cars=vehicles,
            capacity=capacity,
            ratio=ratio,
            level=_congestion_level_for(total, capacity),
            travel_time=_travel_time_for(
                self._edge_lengths[key],
                capacity,
                total,
                self.c,
                self.threshold,
            ),
        )

    def _rebuild_vehicle_counts(self) -> None:
        counts: Dict[EdgeKey, int] = defaultdict(int)
        for car in self._cars.values():
            if car.status == "active" and car.current_edge is not None:
                counts[car.current_edge] += 1
        self._vehicle_counts = counts

    def _sync_graph_edges(self, keys: Optional[Iterable[EdgeKey]] = None) -> None:
        keys_to_sync = list(keys) if keys is not None else list(self._edges)
        bg = self._background_cars
        veh = self._vehicle_counts
        edges = self._edges
        for key in keys_to_sync:
            if key is None or key not in edges:
                continue
            edges[key].current_cars = int(round(max(0.0, bg.get(key, 0.0) + veh.get(key, 0))))
