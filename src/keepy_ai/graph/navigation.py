from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from keepy_ai.graph.geometry import Point

_GRAPH_ACTIONS = frozenset({"WALK", "JUMP", "DASH", "DROP"})
_MAX_TARGET_NODE_DISTANCE = 48.0
_GRAPH_NODE_SNAP_DISTANCE = 24.0


class NavigationGraphError(ValueError):
    """A navigation graph is missing or does not match the supported schema."""


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: int
    position: Point


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: int
    target: int
    action: str
    cost: float
    bidirectional: bool


@dataclass(frozen=True, slots=True)
class GraphTraversal:
    source: int
    target: int
    action: str
    edge_index: int


@dataclass(frozen=True, slots=True)
class NavigationGraph:
    level: str
    nodes: dict[int, GraphNode]
    edges: tuple[GraphEdge, ...]

    @classmethod
    def from_payload(
        cls, value: Any, *, expected_level: str | None = None
    ) -> NavigationGraph:
        if not isinstance(value, dict):
            raise NavigationGraphError("graph must be an object.")
        if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
            raise NavigationGraphError("unsupported graph schema_version.")
        level = value.get("level")
        if not isinstance(level, str) or not level:
            raise NavigationGraphError("graph level must be a non-empty string.")
        if expected_level is not None and level != expected_level:
            raise NavigationGraphError(
                f"graph level {level!r} does not match active level {expected_level!r}."
            )
        raw_nodes = value.get("nodes")
        raw_edges = value.get("edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise NavigationGraphError("graph nodes and edges must be arrays.")
        nodes: dict[int, GraphNode] = {}
        for index, raw_node in enumerate(raw_nodes):
            name = f"nodes[{index}]"
            if not isinstance(raw_node, dict):
                raise NavigationGraphError(f"{name} must be an object.")
            node_id = _integer(raw_node.get("id"), f"{name}.id", positive=True)
            if node_id in nodes:
                raise NavigationGraphError(f"duplicate node id {node_id}.")
            raw_position = raw_node.get("position")
            if not isinstance(raw_position, dict):
                raise NavigationGraphError(f"{name}.position must be an object.")
            nodes[node_id] = GraphNode(
                node_id,
                Point(
                    _number(raw_position.get("x"), f"{name}.position.x"),
                    _number(raw_position.get("y"), f"{name}.position.y"),
                ),
            )
        if not nodes:
            raise NavigationGraphError("graph must contain at least one node.")

        edges = []
        for index, raw_edge in enumerate(raw_edges):
            name = f"edges[{index}]"
            if not isinstance(raw_edge, dict):
                raise NavigationGraphError(f"{name} must be an object.")
            source = _integer(raw_edge.get("from"), f"{name}.from", positive=True)
            target = _integer(raw_edge.get("to"), f"{name}.to", positive=True)
            if source not in nodes or target not in nodes:
                raise NavigationGraphError(f"{name} references an unknown node.")
            if source == target:
                raise NavigationGraphError(f"{name} cannot be a self-edge.")
            action = raw_edge.get("action")
            if not isinstance(action, str) or action not in _GRAPH_ACTIONS:
                raise NavigationGraphError(f"{name}.action is unsupported.")
            cost = _number(raw_edge.get("cost"), f"{name}.cost")
            if cost <= 0:
                raise NavigationGraphError(f"{name}.cost must be positive.")
            bidirectional = raw_edge.get("bidirectional", False)
            if not isinstance(bidirectional, bool):
                raise NavigationGraphError(f"{name}.bidirectional must be boolean.")
            edges.append(GraphEdge(source, target, action, cost, bidirectional))
        return cls(level, nodes, tuple(edges))


@dataclass(frozen=True, slots=True)
class RoutePlan:
    node_ids: tuple[int, ...]
    traversals: tuple[GraphTraversal, ...]
    destination: Point
    cost: float
    waypoint: Point
    next_traversal: GraphTraversal | None

    @property
    def first_traversal(self) -> GraphTraversal | None:
        return self.next_traversal


def load_navigation_graph(path: Path, expected_level: str) -> NavigationGraph:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise NavigationGraphError(f"cannot read graph {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise NavigationGraphError(
            f"{path}:{error.lineno}: invalid graph JSON: {error.msg}."
        ) from error
    return NavigationGraph.from_payload(payload, expected_level=expected_level)


def find_route(
    graph: NavigationGraph,
    start: Point,
    target: Point,
    *,
    edge_penalties: Mapping[int, float] | None = None,
) -> RoutePlan | None:
    start_id = min(
        graph.nodes,
        key=lambda node_id: (
            _distance(graph.nodes[node_id].position, start),
            node_id,
        ),
    )
    adjacency: dict[int, list[tuple[int, int, float, str]]] = {
        node_id: [] for node_id in graph.nodes
    }
    for edge_index, edge in enumerate(graph.edges):
        penalty = (edge_penalties or {}).get(edge_index, 0.0)
        if not math.isfinite(penalty) or penalty < 0:
            raise ValueError("Route edge penalties must be finite and non-negative.")
        weight = edge.cost + penalty
        adjacency[edge.source].append((edge.target, edge_index, weight, edge.action))
        if edge.bidirectional:
            adjacency[edge.target].append((edge.source, edge_index, weight, edge.action))
    for traversals in adjacency.values():
        traversals.sort(key=lambda item: (item[0], item[1]))

    distances = {node_id: math.inf for node_id in graph.nodes}
    previous: dict[int, tuple[int, int, str]] = {}
    distances[start_id] = 0.0
    pending = [(0.0, start_id)]
    while pending:
        distance, source = heapq.heappop(pending)
        if distance != distances[source]:
            continue
        for destination, edge_index, weight, action in adjacency[source]:
            candidate = distance + weight
            if candidate + 1e-12 >= distances[destination]:
                continue
            distances[destination] = candidate
            previous[destination] = (source, edge_index, action)
            heapq.heappush(pending, (candidate, destination))

    reachable = [node_id for node_id in graph.nodes if math.isfinite(distances[node_id])]
    reachable = [
        node_id
        for node_id in reachable
        if _distance(graph.nodes[node_id].position, target)
        <= _MAX_TARGET_NODE_DISTANCE
    ]
    if not reachable:
        return None
    goal_id = min(
        reachable,
        key=lambda node_id: (
            _distance(graph.nodes[node_id].position, target),
            distances[node_id],
            node_id,
        ),
    )
    reversed_node_ids = [goal_id]
    reversed_traversals: list[GraphTraversal] = []
    current = goal_id
    while current != start_id:
        source, edge_index, action = previous[current]
        reversed_traversals.append(
            GraphTraversal(source, current, action, edge_index)
        )
        reversed_node_ids.append(source)
        current = source
    node_ids = tuple(reversed(reversed_node_ids))
    traversals = tuple(reversed(reversed_traversals))
    destination = graph.nodes[goal_id].position
    start_position = graph.nodes[start_id].position
    if _distance(start_position, start) > _GRAPH_NODE_SNAP_DISTANCE:
        waypoint = start_position
        next_traversal = None
    elif traversals:
        next_traversal = traversals[0]
        waypoint = graph.nodes[next_traversal.target].position
    else:
        waypoint = target
        next_traversal = None
    return RoutePlan(
        node_ids,
        traversals,
        destination,
        distances[goal_id],
        waypoint,
        next_traversal,
    )


def _integer(value: Any, name: str, *, positive: bool = False) -> int:
    if type(value) is not int:
        raise NavigationGraphError(f"{name} must be an integer.")
    if positive and value <= 0:
        raise NavigationGraphError(f"{name} must be positive.")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NavigationGraphError(f"{name} must be numeric.")
    if not math.isfinite(value):
        raise NavigationGraphError(f"{name} must be finite.")
    return float(value)


def _distance(left: Point, right: Point) -> float:
    return math.hypot(left.x - right.x, left.y - right.y)
