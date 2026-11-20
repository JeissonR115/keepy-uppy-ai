from __future__ import annotations

from typing import Any

import pytest

from keepy_ai.bridge.errors import CPUBridgeProtocolError
from keepy_ai.graph.geometry import (
    LevelGeometry,
    Point,
    generate_support_nodes,
    support_segments,
)


def _rectangle_collision(
    source: str, size: tuple[float, float], origin: tuple[float, float]
) -> dict[str, Any]:
    return {
        "source": source,
        "collision_layer": 1,
        "one_way": False,
        "shape": {
            "type": "rectangle",
            "size": {"x": size[0], "y": size[1]},
        },
        "transform": {
            "origin": {"x": origin[0], "y": origin[1]},
            "x_axis": {"x": 1, "y": 0},
            "y_axis": {"x": 0, "y": 1},
        },
    }


def _geometry_payload(
    *,
    width: float = 100,
    height: float = 100,
    floor_y: float = 80,
    spawns: tuple[float, float] = (12, 88),
) -> dict[str, Any]:
    floor = _rectangle_collision("floor", (width, 16), (width / 2, floor_y))
    wall = _rectangle_collision("wall", (8, 32), (40, floor_y - 24))
    return {
        "schema_version": 1,
        "level": "fixture",
        "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": width, "y": height}},
        "safe_bounds": {
            "position": {"x": 0, "y": 0},
            "size": {"x": width, "y": height},
        },
        "spawns": {
            "player_1": {"x": spawns[0], "y": floor_y - 16},
            "player_2": {"x": spawns[1], "y": floor_y - 16},
        },
        "collisions": [floor, wall],
        "platforms": [
            {
                "source": "one-way-platform",
                "cell_position": {"x": width / 2, "y": floor_y - 40},
                "cell_transform": {
                    "alternative": 0,
                    "flip_h": False,
                    "flip_v": False,
                    "transpose": False,
                },
                "points": [
                    {"x": -20, "y": -4},
                    {"x": 20, "y": -4},
                    {"x": 20, "y": 4},
                    {"x": -20, "y": 4},
                ],
                "collision_layer": 4,
                "one_way": True,
            }
        ],
        "movement_constants": {"GRAVITY": 1100, "JUMP_SPEED": -250},
    }


def test_geometry_parser_and_support_nodes_use_surfaces_spawns_and_wall_bases() -> None:
    geometry = LevelGeometry.from_payload(_geometry_payload())
    segments = support_segments(geometry)
    nodes = generate_support_nodes(geometry)
    positions = {node.position for node in nodes}

    assert geometry.movement_constants == {"GRAVITY": 1100, "JUMP_SPEED": -250}
    assert _support_y(segments, 72) == (0, 100, False)
    assert _support_y(segments, 40) == (36, 44, False)
    assert _support_y(segments, 36) == (30, 70, True)
    assert Point(12, 64) in positions
    assert Point(88, 64) in positions
    assert Point(8, 64) in positions
    assert Point(92, 64) in positions
    assert Point(28, 64) in positions
    assert Point(52, 64) in positions
    assert Point(38, 28) in positions
    assert Point(62, 28) in positions
    assert [node.id for node in nodes] == list(range(1, len(nodes) + 1))


def _support_y(
    segments: list[Any], target_y: float
) -> tuple[float, float, bool]:
    segment = next(segment for segment in segments if segment.y == target_y)
    return segment.start_x, segment.end_x, segment.one_way


def test_geometry_respects_affine_transforms_and_level_dimensions() -> None:
    payload = _geometry_payload(width=200, height=120, floor_y=100, spawns=(40, 160))
    payload["collisions"][0]["transform"]["x_axis"] = {"x": 2, "y": 0}
    geometry = LevelGeometry.from_payload(payload)

    nodes = generate_support_nodes(geometry)

    assert all(0 <= node.position.x <= 200 for node in nodes)
    assert all(0 <= node.position.y <= 120 for node in nodes)
    assert any(node.position == Point(40, 84) for node in nodes)
    assert any(node.position == Point(160, 84) for node in nodes)


def test_geometry_rejects_unsupported_schema_and_invalid_spawns() -> None:
    payload = _geometry_payload()
    payload["schema_version"] = 2
    with pytest.raises(CPUBridgeProtocolError, match="schema version"):
        LevelGeometry.from_payload(payload)

    payload = _geometry_payload()
    payload["spawns"]["player_2"] = {"x": 88, "y": 90}
    geometry = LevelGeometry.from_payload(payload)
    with pytest.raises(CPUBridgeProtocolError, match="clearance"):
        generate_support_nodes(geometry)

