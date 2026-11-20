from __future__ import annotations

import json
import math

from keepy_ai.bridge.models import MovementProbeResult
from keepy_ai.bridge.models import Vector2
from keepy_ai.graph.generator import (
    ACTION_COSTS,
    ProbeRequest,
    generate_navigation_graph,
)
from keepy_ai.graph.geometry import LevelGeometry, Point


def _fixture_geometry() -> LevelGeometry:
    rectangle = {
        "type": "rectangle",
        "size": {"x": 320, "y": 16},
    }
    return LevelGeometry.from_payload(
        {
            "schema_version": 1,
            "level": "fixture",
            "bounds": {
                "position": {"x": 0, "y": 0},
                "size": {"x": 320, "y": 180},
            },
            "safe_bounds": {
                "position": {"x": 8, "y": 8},
                "size": {"x": 304, "y": 164},
            },
            "spawns": {
                "player_1": {"x": 100, "y": 152},
                "player_2": {"x": 240, "y": 152},
            },
            "collisions": [
                {
                    "source": "floor",
                    "collision_layer": 1,
                    "one_way": False,
                    "shape": rectangle,
                    "transform": {
                        "origin": {"x": 160, "y": 168},
                        "x_axis": {"x": 1, "y": 0},
                        "y_axis": {"x": 0, "y": 1},
                    },
                }
            ],
            "platforms": [
                {
                    "source": "upper-platform",
                    "cell_position": {"x": 100, "y": 116},
                    "cell_transform": {
                        "alternative": 0,
                        "flip_h": False,
                        "flip_v": False,
                        "transpose": False,
                    },
                    "points": [
                        {"x": -10, "y": -4},
                        {"x": 10, "y": -4},
                        {"x": 10, "y": 4},
                        {"x": -10, "y": 4},
                    ],
                    "collision_layer": 4,
                    "one_way": True,
                }
            ],
            "movement_constants": {
                "GRAVITY": 1100,
                "JUMP_SPEED": -250,
                "VAR_JUMP_TIME": 0.2,
                "MAX_RUN": 130,
                "DASH_SPEED": 300,
                "DASH_TIME": 0.2,
            },
        }
    )


def _result(
    request: ProbeRequest, *, landed: bool, reason: str = ""
) -> MovementProbeResult:
    return MovementProbeResult(
        level="fixture",
        movement=request.movement,
        start_position=Vector2(
            request.start_position.x, request.start_position.y
        ),
        action_started=True,
        landed=landed,
        landing_position=(
            Vector2(request.target_position.x, request.target_position.y)
            if landed
            else None
        ),
        final_position=Vector2(
            request.target_position.x, request.target_position.y
        ),
        physics_frames_elapsed=10,
        physics_delta=1 / 60,
        reason=reason,
    )


def test_graph_edges_include_geometry_and_confirmed_probes() -> None:
    geometry = _fixture_geometry()
    probes: list[ProbeRequest] = []

    def probe(request: ProbeRequest) -> MovementProbeResult:
        probes.append(request)
        if (
            request.movement == "dash"
            and request.start_position == Point(100, 152)
            and request.target_position == Point(100, 104)
        ):
            return _result(request, landed=True)
        if (
            request.movement == "jump"
            and request.start_position == Point(16, 152)
            and request.target_position == Point(100, 104)
        ):
            return _result(request, landed=True)
        return _result(request, landed=False, reason="obstructed")

    report = generate_navigation_graph(geometry, probe)
    graph = report.graph_payload()
    edge_types = {edge.action for edge in report.edges}

    assert {"WALK", "DASH", "JUMP"} <= edge_types
    assert all(edge.action != "WALL_JUMP" for edge in report.edges)
    assert all(edge.cost > 0 for edge in report.edges)
    assert report.edge_counts["WALL_JUMP"] == 0
    assert report.discarded
    assert report.discarded[0].reason == "obstructed"
    assert report.discarded[0].probe.landed is False
    assert any(edge.action == "DROP" for edge in report.edges)
    assert len({(edge["from"], edge["to"]) for edge in graph["edges"]}) == len(
        graph["edges"]
    )
    assert graph["schema_version"] == 1
    assert graph["level"] == "fixture"
    assert json.dumps(graph, sort_keys=True) == json.dumps(
        report.graph_payload(), sort_keys=True
    )
    assert probes
    assert set(ACTION_COSTS) == {"WALK", "JUMP", "DASH", "DROP"}


def test_graph_generation_is_deterministic_and_reports_unreachable_nodes() -> None:
    geometry = _fixture_geometry()

    def reject(request: ProbeRequest) -> MovementProbeResult:
        return _result(request, landed=False, reason="not_landed")

    first = generate_navigation_graph(geometry, reject)
    second = generate_navigation_graph(geometry, reject)

    assert first.graph_payload() == second.graph_payload()
    assert first.report_payload() == second.report_payload()
    unreachable_positions = {
        node.position
        for node in first.nodes
        if node.id in first.unreachable_node_ids
    }
    assert Point(100, 104) in unreachable_positions
    assert all(
        math.isfinite(edge.cost) and edge.cost > 0 for edge in first.edges
    )


def test_probe_candidates_are_limited_per_direction() -> None:
    geometry = _fixture_geometry()
    candidates: dict[tuple[Point, str, int, int], list[float]] = {}

    def reject(request: ProbeRequest) -> MovementProbeResult:
        dx = request.target_position.x - request.start_position.x
        dy = request.target_position.y - request.start_position.y
        quadrant = (
            0 if abs(dx) < 0.5 else (1 if dx > 0 else -1),
            0 if abs(dy) < 0.5 else (1 if dy > 0 else -1),
        )
        key = (request.start_position, request.movement, *quadrant)
        candidates.setdefault(key, []).append(math.hypot(dx, dy))
        return _result(request, landed=False, reason="not_landed")

    generate_navigation_graph(geometry, reject)

    assert candidates
    assert all(len(distances) == 1 for distances in candidates.values())

