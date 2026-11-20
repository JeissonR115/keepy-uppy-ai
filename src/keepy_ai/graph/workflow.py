from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Literal, Protocol

from keepy_ai.bridge.errors import CPUBridgeProtocolError
from keepy_ai.bridge.models import (
    BridgeMessage,
    CommandResultMessage,
    CPUObservation,
    EpisodeEventMessage,
    MovementProbeResult,
    ObservationMessage,
    Vector2,
)
from keepy_ai.graph.generator import ProbeRequest, generate_navigation_graph
from keepy_ai.graph.geometry import LevelGeometry, NavigationNode, Point

CURRENT_LEVELS = ("primary-flat", "hazard-arena", "classic", "sky-towers")
ROUTE_ARRIVAL_RADIUS = 8.0
ROUTE_DISTANCE_EPSILON = 0.01
ROUTE_START_TOLERANCE = 24.0
ROUTE_STEP_BATCH = 30


class GraphBridgeClient(Protocol):
    def reset(self, seed: int, level: str) -> int: ...

    def get_level_geometry(self, level: str | None = None) -> int: ...

    def probe_movement(
        self,
        movement: Literal["jump", "dash"],
        start_position: Vector2,
        *,
        level: str | None = None,
        horizontal: float | None = None,
        direction: Vector2 | None = None,
    ) -> int: ...

    def load_nav_graph(self, graph: dict[str, Any]) -> int: ...

    def set_nav_route(
        self, level: str, start_node: int, destination_node: int
    ) -> int: ...

    def step(self, n: int = 1) -> int: ...

    def receive(self) -> BridgeMessage: ...


def generate_graphs(
    client: GraphBridgeClient,
    levels: Iterable[str],
    *,
    graph_directory: Path,
    seed: int,
    route_step_limit: int,
) -> list[dict[str, Any]]:
    selected_levels = tuple(levels)
    if not selected_levels:
        raise ValueError("At least one level must be selected.")
    if len(set(selected_levels)) != len(selected_levels):
        raise ValueError("Selected levels must be unique.")
    unknown_levels = set(selected_levels) - set(CURRENT_LEVELS)
    if unknown_levels:
        raise ValueError(
            "Unsupported level(s): " + ", ".join(sorted(unknown_levels))
        )
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer.")
    if (
        isinstance(route_step_limit, bool)
        or not isinstance(route_step_limit, int)
        or route_step_limit <= 0
    ):
        raise ValueError("route_step_limit must be a positive integer.")

    reports = []
    for level_index, level in enumerate(selected_levels):
        reset_sequence = client.reset(seed + level_index, level)
        reset_result = _command_result(client, reset_sequence)
        observation = CPUObservation.from_payload(reset_result.get("observation"))
        if observation.level != level:
            raise CPUBridgeProtocolError(
                f"Reset selected {observation.level!r}, expected {level!r}."
            )

        geometry_sequence = client.get_level_geometry(level)
        geometry = LevelGeometry.from_payload(
            _command_result(client, geometry_sequence)
        )
        if geometry.level != level:
            raise CPUBridgeProtocolError(
                f"Geometry export returned {geometry.level!r}, expected {level!r}."
            )

        def probe(request: ProbeRequest) -> MovementProbeResult:
            kwargs: dict[str, Any] = {"level": level}
            if request.movement == "jump":
                kwargs["horizontal"] = request.horizontal
            else:
                if request.direction is None:
                    raise CPUBridgeProtocolError(
                        "A dash movement candidate is missing its direction."
                    )
                kwargs["direction"] = Vector2(
                    request.direction.x, request.direction.y
                )
            sequence = client.probe_movement(
                request.movement,
                Vector2(request.start_position.x, request.start_position.y),
                **kwargs,
            )
            return MovementProbeResult.from_payload(
                _command_result(client, sequence)
            )

        report = generate_navigation_graph(geometry, probe)
        graph = report.graph_payload()
        load_sequence = client.load_nav_graph(graph)
        load_result = _command_result(client, load_sequence)
        if load_result.get("loaded") is not True:
            raise CPUBridgeProtocolError(
                f"Godot did not confirm loading the {level!r} navigation graph."
            )

        graph_path = graph_directory / f"{level}.json"
        _write_json_atomically(graph_path, graph)
        route_check = _exercise_route(
            client,
            level,
            report.nodes,
            graph,
            observation,
            route_step_limit,
        )
        reports.append(
            {
                **report.report_payload(),
                "graph_path": str(graph_path),
                "route_check": route_check,
            }
        )
    return reports


def _command_result(client: GraphBridgeClient, sequence: int) -> dict[str, Any]:
    while True:
        message = client.receive()
        if isinstance(message, EpisodeEventMessage):
            continue
        if isinstance(message, ObservationMessage):
            raise CPUBridgeProtocolError(
                "Received an unsolicited observation while waiting for a command result."
            )
        if not isinstance(message, CommandResultMessage) or message.sequence != sequence:
            raise CPUBridgeProtocolError(
                f"Expected command result {sequence}, received an out-of-order message."
            )
        return message.result


def _exercise_route(
    client: GraphBridgeClient,
    level: str,
    nodes: list[NavigationNode],
    graph: dict[str, Any],
    observation: CPUObservation,
    step_limit: int,
) -> dict[str, Any]:
    player_position = observation.players["player_2"].position
    start_node = min(
        nodes,
        key=lambda node: (
            math.hypot(
                node.position.x - player_position.x,
                node.position.y - player_position.y,
            ),
            node.id,
        ),
    )
    start_distance = math.hypot(
        start_node.position.x - player_position.x,
        start_node.position.y - player_position.y,
    )
    if start_distance > ROUTE_START_TOLERANCE:
        raise CPUBridgeProtocolError(
            f"Player 2 is {start_distance:.2f} pixels from its nearest route node "
            f"(limit {ROUTE_START_TOLERANCE:g})."
        )

    destination_node: NavigationNode | None = None
    route_node_ids: list[int] | None = None
    fallback_route: tuple[NavigationNode, list[int]] | None = None
    for candidate in _reachable_destinations(graph, start_node):
        route_sequence = client.set_nav_route(level, start_node.id, candidate.id)
        route_result = _command_result(client, route_sequence)
        candidate_route = _route_node_ids(
            route_result, start_node.id, candidate.id
        )
        if fallback_route is None:
            fallback_route = (candidate, candidate_route)
        if _route_has_non_walk_edge(graph, candidate_route):
            destination_node = candidate
            route_node_ids = candidate_route
            break
    if destination_node is None or route_node_ids is None:
        if fallback_route is None:
            raise CPUBridgeProtocolError(
                f"Graph for {level!r} has no reachable destination from "
                f"node {start_node.id}."
            )
        destination_node = fallback_route[0]
        route_sequence = client.set_nav_route(
            level, start_node.id, destination_node.id
        )
        route_result = _command_result(client, route_sequence)
        route_node_ids = _route_node_ids(
            route_result, start_node.id, destination_node.id
        )

    steps = 0
    final_position = player_position
    while steps < step_limit:
        batch = min(ROUTE_STEP_BATCH, step_limit - steps)
        step_sequence = client.step(batch)
        result = _command_result(client, step_sequence)
        state = CPUObservation.from_payload(result.get("observation"))
        final_position = state.players["player_2"].position
        completed_steps = result.get("steps")
        if (
            isinstance(completed_steps, bool)
            or not isinstance(completed_steps, int)
            or completed_steps < 0
        ):
            raise CPUBridgeProtocolError(
                "Route-check step result has an invalid steps count."
            )
        steps += completed_steps
        distance = math.hypot(
            final_position.x - destination_node.position.x,
            final_position.y - destination_node.position.y,
        )
        if distance <= ROUTE_ARRIVAL_RADIUS + ROUTE_DISTANCE_EPSILON:
            return {
                "passed": True,
                "start_node": start_node.id,
                "destination_node": destination_node.id,
                "route_node_ids": route_node_ids,
                "steps": steps,
                "distance_to_destination": distance,
                "final_position": {
                    "x": final_position.x,
                    "y": final_position.y,
                },
            }
        if result.get("episode_ended") is True:
            events = result.get("events", [])
            reason = (
                events[-1].get("reason")
                if isinstance(events, list)
                and events
                and isinstance(events[-1], dict)
                else "episode_ended"
            )
            return {
                "passed": False,
                "start_node": start_node.id,
                "destination_node": destination_node.id,
                "route_node_ids": route_node_ids,
                "steps": steps,
                "distance_to_destination": distance,
                "final_position": {
                    "x": final_position.x,
                    "y": final_position.y,
                },
                "reason": reason,
            }
        if completed_steps == 0:
            raise CPUBridgeProtocolError(
                "Route-check simulation made no physics-step progress."
            )

    distance = math.hypot(
        final_position.x - destination_node.position.x,
        final_position.y - destination_node.position.y,
    )
    return {
        "passed": False,
        "start_node": start_node.id,
        "destination_node": destination_node.id,
        "route_node_ids": route_node_ids,
        "steps": steps,
        "distance_to_destination": distance,
        "final_position": {"x": final_position.x, "y": final_position.y},
        "reason": "step_limit_exceeded",
    }


def _reachable_destinations(
    graph: dict[str, Any],
    start_node: NavigationNode,
) -> list[NavigationNode]:
    nodes = {
        node["id"]: NavigationNode(
            node["id"], Point(node["position"]["x"], node["position"]["y"])
        )
        for node in graph["nodes"]
    }
    adjacency: dict[int, set[int]] = defaultdict(set)
    for edge in graph["edges"]:
        source, target = edge["from"], edge["to"]
        adjacency[source].add(target)
        if edge.get("bidirectional", False):
            adjacency[target].add(source)
    reachable = {start_node.id}
    pending = deque([start_node.id])
    while pending:
        source = pending.popleft()
        for target in adjacency[source] - reachable:
            reachable.add(target)
            pending.append(target)
    destinations = [nodes[node_id] for node_id in reachable if node_id != start_node.id]
    if not destinations:
        return []

    direct_probe_targets = {
        edge["to"]
        for edge in graph["edges"]
        if edge["from"] == start_node.id
        and edge["action"] != "WALK"
        and math.hypot(
            nodes[edge["to"]].position.x - start_node.position.x,
            nodes[edge["to"]].position.y - start_node.position.y,
        )
        > ROUTE_ARRIVAL_RADIUS
    }

    def destination_key(node: NavigationNode) -> tuple[int, float, int]:
        distance = math.hypot(
            node.position.x - start_node.position.x,
            node.position.y - start_node.position.y,
        )
        return (
            0 if node.id in direct_probe_targets else 1,
            distance,
            node.id,
        )

    return sorted(destinations, key=destination_key)


def _route_has_non_walk_edge(
    graph: dict[str, Any], route_node_ids: list[int]
) -> bool:
    edge_actions = {
        (edge["from"], edge["to"]): edge["action"] for edge in graph["edges"]
    }
    for source, target in zip(route_node_ids, route_node_ids[1:]):
        action = edge_actions.get((source, target))
        if action is None:
            reverse_edge = next(
                (
                    edge
                    for edge in graph["edges"]
                    if edge["from"] == target
                    and edge["to"] == source
                    and edge.get("bidirectional", False)
                ),
                None,
            )
            action = reverse_edge["action"] if reverse_edge is not None else None
        if action is not None and action != "WALK":
            return True
    return False


def _route_node_ids(
    result: dict[str, Any], start_node: int, destination_node: int
) -> list[int]:
    raw_node_ids = result.get("route_node_ids")
    if not isinstance(raw_node_ids, list):
        raise CPUBridgeProtocolError("Godot route result must contain node ids.")
    node_ids: list[int] = []
    for node_id in raw_node_ids:
        if isinstance(node_id, bool) or not isinstance(node_id, int):
            raise CPUBridgeProtocolError("Godot route node ids must be integers.")
        node_ids.append(node_id)
    if (
        not node_ids
        or node_ids[0] != start_node
        or node_ids[-1] != destination_node
    ):
        raise CPUBridgeProtocolError(
            "Godot returned a route with unexpected start or destination nodes."
        )
    return node_ids


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, indent=2, sort_keys=True, allow_nan=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(0o644)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
