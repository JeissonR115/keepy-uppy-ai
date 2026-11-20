from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Literal

from keepy_ai.bridge.errors import CPUBridgeProtocolError
from keepy_ai.bridge.models import MovementProbeResult
from keepy_ai.graph.geometry import (
    LevelGeometry,
    NavigationNode,
    Point,
    SupportSegment,
    generate_support_nodes,
    infer_player_clearance,
    support_segments,
)

EdgeAction = Literal["WALK", "JUMP", "DASH", "DROP"]
ACTION_COSTS: dict[EdgeAction, float] = {
    "WALK": 1.0,
    "JUMP": 1.2,
    "DASH": 0.9,
    "DROP": 1.1,
}
PROBE_MATCH_TOLERANCE = 8.0
SUPPORT_MATCH_TOLERANCE = 1.0
MAX_CANDIDATES_PER_QUADRANT = 1


@dataclass(frozen=True, slots=True)
class ProbeRequest:
    movement: Literal["jump", "dash"]
    start_position: Point
    target_position: Point
    horizontal: float | None = None
    direction: Point | None = None


ProbeFunction = Callable[[ProbeRequest], MovementProbeResult]


@dataclass(frozen=True, slots=True)
class NavigationEdge:
    source: int
    target: int
    action: EdgeAction
    cost: float
    bidirectional: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "from": self.source,
            "to": self.target,
            "action": self.action,
            "cost": self.cost,
            "bidirectional": self.bidirectional,
        }


@dataclass(frozen=True, slots=True)
class DiscardedCandidate:
    source: int
    target: int
    action: EdgeAction
    reason: str
    probe: MovementProbeResult

    def to_payload(self) -> dict[str, Any]:
        return {
            "from": self.source,
            "to": self.target,
            "action": self.action,
            "reason": self.reason,
            "probe": self.probe.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class GraphReport:
    level: str
    nodes: list[NavigationNode]
    edges: list[NavigationEdge]
    discarded: list[DiscardedCandidate]
    unreachable_node_ids: list[int]

    @property
    def edge_counts(self) -> dict[str, int]:
        return {
            action: sum(edge.action == action for edge in self.edges)
            for action in ("WALK", "JUMP", "DASH", "DROP", "WALL_JUMP")
        }

    def graph_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "level": self.level,
            "nodes": [node.to_payload() for node in self.nodes],
            "edges": [edge.to_payload() for edge in self.edges],
        }

    def report_payload(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "node_count": len(self.nodes),
            "edge_counts": self.edge_counts,
            "discarded_candidates": [
                candidate.to_payload() for candidate in self.discarded
            ],
            "unreachable_node_ids": self.unreachable_node_ids,
        }


def generate_navigation_graph(
    geometry: LevelGeometry, probe: ProbeFunction
) -> GraphReport:
    nodes = generate_support_nodes(geometry)
    if not nodes:
        raise CPUBridgeProtocolError(
            f"Level {geometry.level!r} produced no navigation nodes."
        )
    segments = support_segments(geometry)
    clearance = infer_player_clearance(geometry.spawns, segments)
    edges, occupied = _geometric_edges(nodes, segments, clearance)
    discarded: list[DiscardedCandidate] = []
    jump_range, jump_height, dash_range = _movement_candidate_limits(geometry)

    for source in nodes:
        for target, candidates in _limited_probe_candidates(
            source,
            nodes,
            segments,
            occupied,
            clearance,
            geometry.bounds.size.y,
            jump_range,
            jump_height,
            dash_range,
        ):
            pair = (source.id, target.id)
            for action, request in candidates:
                outcome = probe(request)
                accepted, reason = _probe_confirms_target(
                    outcome, request, geometry.level
                )
                if accepted:
                    edges.append(
                        NavigationEdge(
                            source.id, target.id, action, ACTION_COSTS[action]
                        )
                    )
                    occupied.add(pair)
                    break
                discarded.append(
                    DiscardedCandidate(
                        source.id, target.id, action, reason, outcome
                    )
                )

    unreachable = _unreachable_nodes(geometry.spawns, nodes, edges)
    edges.sort(key=lambda edge: (edge.source, edge.target, edge.action))
    discarded.sort(
        key=lambda candidate: (
            candidate.source,
            candidate.target,
            candidate.action,
        )
    )
    return GraphReport(geometry.level, nodes, edges, discarded, unreachable)


def _limited_probe_candidates(
    source: NavigationNode,
    nodes: list[NavigationNode],
    segments: list[SupportSegment],
    occupied: set[tuple[int, int]],
    clearance: float,
    level_height: float,
    jump_range: float,
    jump_height: float,
    dash_range: float,
) -> list[tuple[NavigationNode, list[tuple[EdgeAction, ProbeRequest]]]]:
    grouped: dict[
        EdgeAction,
        dict[tuple[int, int], list[tuple[float, NavigationNode, ProbeRequest]]],
    ] = {
        "DASH": defaultdict(list),
        "JUMP": defaultdict(list),
    }
    for target in nodes:
        pair = (source.id, target.id)
        if (
            source.id == target.id
            or pair in occupied
            or _shares_support(source, target, segments, clearance)
        ):
            continue
        dx = target.position.x - source.position.x
        dy = target.position.y - source.position.y
        distance = math.hypot(dx, dy)
        quadrant = (
            0 if abs(dx) < 0.5 else (1 if dx > 0 else -1),
            0 if abs(dy) < 0.5 else (1 if dy > 0 else -1),
        )
        if distance <= dash_range + clearance:
            grouped["DASH"][quadrant].append(
                (
                    distance,
                    target,
                    ProbeRequest(
                        movement="dash",
                        start_position=source.position,
                        target_position=target.position,
                        direction=Point(dx, dy),
                    ),
                )
            )
        if (
            abs(dx) <= jump_range + clearance
            and dy >= -jump_height - clearance
            and dy <= level_height
        ):
            grouped["JUMP"][quadrant].append(
                (
                    distance,
                    target,
                    ProbeRequest(
                        movement="jump",
                        start_position=source.position,
                        target_position=target.position,
                        horizontal=0.0 if abs(dx) < 0.5 else math.copysign(1.0, dx),
                    ),
                )
            )

    selected: dict[int, tuple[NavigationNode, dict[EdgeAction, ProbeRequest]]] = {}
    for action in ("DASH", "JUMP"):
        for candidates in grouped[action].values():
            candidates.sort(key=lambda item: (item[0], item[1].id))
            for _distance, target, request in candidates[
                :MAX_CANDIDATES_PER_QUADRANT
            ]:
                selected.setdefault(target.id, (target, {}))[1][action] = request
    result = []
    for target, requests in sorted(
        selected.values(),
        key=lambda item: (
            math.hypot(
                item[0].position.x - source.position.x,
                item[0].position.y - source.position.y,
            ),
            item[0].id,
        ),
    ):
        actions = [
            (action, requests[action])
            for action in ("DASH", "JUMP")
            if action in requests
        ]
        result.append((target, actions))
    return result


def _geometric_edges(
    nodes: list[NavigationNode],
    segments: list[SupportSegment],
    clearance: float,
) -> tuple[list[NavigationEdge], set[tuple[int, int]]]:
    edges: list[NavigationEdge] = []
    occupied: set[tuple[int, int]] = set()
    segment_members: list[tuple[SupportSegment, list[NavigationNode]]] = []
    for segment in segments:
        members = sorted(
            [
                node
                for node in nodes
                if _on_support(node, segment, clearance)
            ],
            key=lambda node: (node.position.x, node.id),
        )
        segment_members.append((segment, members))
        for left, right in zip(members, members[1:]):
            pair = (left.id, right.id)
            reverse = (right.id, left.id)
            if pair in occupied or reverse in occupied:
                continue
            edges.append(
                NavigationEdge(
                    left.id, right.id, "WALK", ACTION_COSTS["WALK"], True
                )
            )
            occupied.update((pair, reverse))

    for source in nodes:
        source_segments = [
            segment
            for segment, members in segment_members
            if source in members
            and (
                segment.one_way
                or min(
                    abs(source.position.x - segment.start_x),
                    abs(source.position.x - segment.end_x),
                )
                <= clearance + SUPPORT_MATCH_TOLERANCE
            )
        ]
        if not source_segments:
            continue
        for target in nodes:
            pair = (source.id, target.id)
            if (
                pair in occupied
                or source.id == target.id
                or target.position.y <= source.position.y + SUPPORT_MATCH_TOLERANCE
                or abs(target.position.x - source.position.x)
                > clearance + SUPPORT_MATCH_TOLERANCE
            ):
                continue
            target_segments = [
                segment
                for segment, members in segment_members
                if target in members and segment.y > source.position.y + clearance
            ]
            if not target_segments:
                continue
            for source_segment in source_segments:
                if any(
                    _blocks_drop(
                        source.position,
                        target.position,
                        segment,
                    )
                    for segment, _members in segment_members
                    if not segment.one_way and segment is not source_segment
                ):
                    continue
                edges.append(
                    NavigationEdge(
                        source.id, target.id, "DROP", ACTION_COSTS["DROP"]
                    )
                )
                occupied.add(pair)
                break
    return edges, occupied


def _on_support(
    node: NavigationNode, segment: SupportSegment, clearance: float
) -> bool:
    return (
        abs(node.position.y + clearance - segment.y) <= SUPPORT_MATCH_TOLERANCE
        and segment.start_x - SUPPORT_MATCH_TOLERANCE
        <= node.position.x
        <= segment.end_x + SUPPORT_MATCH_TOLERANCE
    )


def _blocks_drop(
    source: Point, target: Point, segment: SupportSegment
) -> bool:
    if not min(source.y, target.y) < segment.y < max(source.y, target.y):
        return False
    x_min = min(source.x, target.x)
    x_max = max(source.x, target.x)
    return segment.start_x <= x_max and segment.end_x >= x_min


def _shares_support(
    source: NavigationNode,
    target: NavigationNode,
    segments: list[SupportSegment],
    clearance: float,
) -> bool:
    return any(
        _on_support(source, segment, clearance)
        and _on_support(target, segment, clearance)
        for segment in segments
    )


def _movement_candidate_limits(
    geometry: LevelGeometry,
) -> tuple[float, float, float]:
    constants = geometry.movement_constants
    required = (
        "GRAVITY",
        "JUMP_SPEED",
        "VAR_JUMP_TIME",
        "MAX_RUN",
        "DASH_SPEED",
        "DASH_TIME",
    )
    missing = [name for name in required if name not in constants]
    if missing:
        raise CPUBridgeProtocolError(
            "Level geometry is missing movement constants: " + ", ".join(missing)
        )
    gravity = constants["GRAVITY"]
    jump_speed = abs(constants["JUMP_SPEED"])
    variable_time = constants["VAR_JUMP_TIME"]
    max_run = constants["MAX_RUN"]
    dash_speed = constants["DASH_SPEED"]
    dash_time = constants["DASH_TIME"]
    if gravity <= 0 or jump_speed <= 0 or max_run <= 0 or dash_time <= 0:
        raise CPUBridgeProtocolError(
            "Movement constants used for graph candidates must be positive."
        )
    jump_height = jump_speed**2 / (2 * gravity) + jump_speed * variable_time
    jump_time = 2 * jump_speed / gravity + variable_time
    jump_range = max_run * jump_time
    dash_range = dash_speed * dash_time + max_run * dash_time
    return jump_range, jump_height, dash_range


def _probe_confirms_target(
    result: MovementProbeResult,
    request: ProbeRequest,
    level: str,
) -> tuple[bool, str]:
    if result.level != level or result.movement != request.movement:
        return False, "probe_result_mismatch"
    start_distance = math.hypot(
        result.start_position.x - request.start_position.x,
        result.start_position.y - request.start_position.y,
    )
    if start_distance > 0.5:
        return False, "probe_start_position_mismatch"
    if not result.action_started:
        return False, result.reason or "action_not_started"
    if not result.landed or result.landing_position is None:
        return False, result.reason or "did_not_land"
    distance = math.hypot(
        result.landing_position.x - request.target_position.x,
        result.landing_position.y - request.target_position.y,
    )
    if distance > PROBE_MATCH_TOLERANCE:
        return False, f"landing_mismatch:{distance:.2f}"
    return True, ""


def _unreachable_nodes(
    spawns: dict[str, Point],
    nodes: list[NavigationNode],
    edges: list[NavigationEdge],
) -> list[int]:
    roots = {
        min(
            nodes,
            key=lambda node: (
                math.hypot(
                    node.position.x - spawn.x,
                    node.position.y - spawn.y,
                ),
                node.id,
            ),
        ).id
        for spawn in spawns.values()
    }
    adjacency: dict[int, set[int]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source].add(edge.target)
        if edge.bidirectional:
            adjacency[edge.target].add(edge.source)

    reachable = set(roots)
    pending = deque(roots)
    while pending:
        source = pending.popleft()
        for target in adjacency[source] - reachable:
            reachable.add(target)
            pending.append(target)
    return sorted(node.id for node in nodes if node.id not in reachable)
