from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

from keepy_ai.bridge.errors import CPUBridgeProtocolError


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CPUBridgeProtocolError(f"{name} must be a JSON object.")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CPUBridgeProtocolError(f"{name} must be numeric.")
    if not math.isfinite(value):
        raise CPUBridgeProtocolError(f"{name} must be finite.")
    return float(value)


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CPUBridgeProtocolError(f"{name} must be an integer.")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CPUBridgeProtocolError(f"{name} must be a non-empty string.")
    return value


@dataclass(frozen=True, slots=True, order=True)
class Point:
    x: float
    y: float

    @classmethod
    def from_payload(cls, value: Any, name: str) -> Point:
        payload = _object(value, name)
        return cls(
            _number(payload.get("x"), f"{name}.x"),
            _number(payload.get("y"), f"{name}.y"),
        )

    def to_payload(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True, slots=True)
class Rectangle:
    position: Point
    size: Point

    @classmethod
    def from_payload(cls, value: Any, name: str) -> Rectangle:
        payload = _object(value, name)
        position = Point.from_payload(payload.get("position"), f"{name}.position")
        size = Point.from_payload(payload.get("size"), f"{name}.size")
        if size.x <= 0 or size.y <= 0:
            raise CPUBridgeProtocolError(f"{name}.size must be positive.")
        return cls(position, size)

    @property
    def right(self) -> float:
        return self.position.x + self.size.x

    @property
    def bottom(self) -> float:
        return self.position.y + self.size.y

    def contains(self, point: Point, *, tolerance: float = 0.0) -> bool:
        return (
            self.position.x - tolerance <= point.x <= self.right + tolerance
            and self.position.y - tolerance <= point.y <= self.bottom + tolerance
        )


@dataclass(frozen=True, slots=True)
class GeometryCollision:
    source: str
    collision_layer: int
    one_way: bool
    points: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class SupportSegment:
    start_x: float
    end_x: float
    y: float
    one_way: bool


@dataclass(frozen=True, slots=True)
class NavigationNode:
    id: int
    position: Point

    def to_payload(self) -> dict[str, Any]:
        return {"id": self.id, "position": self.position.to_payload()}


@dataclass(frozen=True, slots=True)
class LevelGeometry:
    level: str
    bounds: Rectangle
    safe_bounds: Rectangle
    spawns: dict[str, Point]
    collisions: tuple[GeometryCollision, ...]
    platforms: tuple[GeometryCollision, ...]
    movement_constants: dict[str, float]

    @classmethod
    def from_payload(cls, value: Any) -> LevelGeometry:
        payload = _object(value, "geometry")
        if _integer(payload.get("schema_version"), "geometry.schema_version") != 1:
            raise CPUBridgeProtocolError("Unsupported level geometry schema version.")
        spawns_payload = _object(payload.get("spawns"), "geometry.spawns")
        constants_payload = _object(
            payload.get("movement_constants"), "geometry.movement_constants"
        )
        collisions_payload = payload.get("collisions")
        platforms_payload = payload.get("platforms")
        if not isinstance(collisions_payload, list) or not isinstance(
            platforms_payload, list
        ):
            raise CPUBridgeProtocolError(
                "geometry.collisions and geometry.platforms must be arrays."
            )
        return cls(
            level=_string(payload.get("level"), "geometry.level"),
            bounds=Rectangle.from_payload(payload.get("bounds"), "geometry.bounds"),
            safe_bounds=Rectangle.from_payload(
                payload.get("safe_bounds"), "geometry.safe_bounds"
            ),
            spawns={
                player: Point.from_payload(
                    spawns_payload.get(player), f"geometry.spawns.{player}"
                )
                for player in ("player_1", "player_2")
            },
            collisions=tuple(
                _parse_collision(item, f"geometry.collisions[{index}]")
                for index, item in enumerate(collisions_payload)
            ),
            platforms=tuple(
                _parse_collision(item, f"geometry.platforms[{index}]")
                for index, item in enumerate(platforms_payload)
            ),
            movement_constants=_parse_movement_constants(constants_payload),
        )


def _parse_movement_constants(value: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for name, number in value.items():
        if not isinstance(name, str) or not name:
            raise CPUBridgeProtocolError(
                "geometry.movement_constants keys must be non-empty strings."
            )
        result[name] = _number(number, f"geometry.movement_constants.{name}")
    return result


def _parse_collision(value: Any, name: str) -> GeometryCollision:
    payload = _object(value, name)
    collision_layer = _integer(payload.get("collision_layer"), f"{name}.collision_layer")
    if collision_layer < 0:
        raise CPUBridgeProtocolError(f"{name}.collision_layer must not be negative.")
    one_way = payload.get("one_way")
    if not isinstance(one_way, bool):
        raise CPUBridgeProtocolError(f"{name}.one_way must be boolean.")
    source = _string(payload.get("source"), f"{name}.source")
    if collision_layer == 0:
        return GeometryCollision(source, collision_layer, one_way, ())

    if isinstance(payload.get("points"), list) and "cell_position" in payload:
        center = Point.from_payload(payload.get("cell_position"), f"{name}.cell_position")
        transform = _object(payload.get("cell_transform"), f"{name}.cell_transform")
        points = tuple(
            _tile_point(
                center,
                Point.from_payload(point, f"{name}.points[{index}]"),
                transform,
            )
            for index, point in enumerate(payload["points"])
        )
    else:
        shape = _object(payload.get("shape"), f"{name}.shape")
        local_points = _shape_points(shape, f"{name}.shape")
        transform = _object(payload.get("transform"), f"{name}.transform")
        origin = Point.from_payload(transform.get("origin"), f"{name}.transform.origin")
        x_axis = Point.from_payload(transform.get("x_axis"), f"{name}.transform.x_axis")
        y_axis = Point.from_payload(transform.get("y_axis"), f"{name}.transform.y_axis")
        points = tuple(
            Point(
                origin.x + x_axis.x * point.x + y_axis.x * point.y,
                origin.y + x_axis.y * point.x + y_axis.y * point.y,
            )
            for point in local_points
        )
    if len(points) < 2:
        raise CPUBridgeProtocolError(f"{name} does not describe a polygonal collision.")
    return GeometryCollision(source, collision_layer, one_way, points)


def _shape_points(shape: dict[str, Any], name: str) -> tuple[Point, ...]:
    shape_type = _string(shape.get("type"), f"{name}.type")
    if shape_type == "rectangle":
        size = Point.from_payload(shape.get("size"), f"{name}.size")
        if size.x <= 0 or size.y <= 0:
            raise CPUBridgeProtocolError(f"{name}.size must be positive.")
        half_width = size.x / 2
        half_height = size.y / 2
        return (
            Point(-half_width, -half_height),
            Point(half_width, -half_height),
            Point(half_width, half_height),
            Point(-half_width, half_height),
        )
    if shape_type in {"polygon", "convex_polygon", "concave_polygon"}:
        raw_points = shape.get("points")
        if not isinstance(raw_points, list):
            raise CPUBridgeProtocolError(f"{name}.points must be an array.")
        return tuple(
            Point.from_payload(point, f"{name}.points[{index}]")
            for index, point in enumerate(raw_points)
        )
    if shape_type == "segment":
        return (
            Point.from_payload(shape.get("a"), f"{name}.a"),
            Point.from_payload(shape.get("b"), f"{name}.b"),
        )
    raise CPUBridgeProtocolError(
        f"Unsupported walkable collision shape type: {shape_type!r}."
    )


def _tile_point(center: Point, point: Point, transform: dict[str, Any]) -> Point:
    x = point.x
    y = point.y
    for flag in ("transpose", "flip_h", "flip_v"):
        if not isinstance(transform.get(flag), bool):
            raise CPUBridgeProtocolError(f"cell_transform.{flag} must be boolean.")
    if transform["transpose"]:
        x, y = y, x
    if transform["flip_h"]:
        x = -x
    if transform["flip_v"]:
        y = -y
    return Point(center.x + x, center.y + y)


def support_segments(geometry: LevelGeometry) -> list[SupportSegment]:
    result: list[SupportSegment] = []
    for collision in (*geometry.collisions, *geometry.platforms):
        if collision.collision_layer == 0 or len(collision.points) < 2:
            continue
        horizontal_edges: list[tuple[float, float, float]] = []
        for start, end in zip(
            collision.points, (*collision.points[1:], collision.points[0])
        ):
            if abs(start.y - end.y) <= 0.25:
                horizontal_edges.append(
                    (min(start.x, end.x), max(start.x, end.x), (start.y + end.y) / 2)
                )
        if not horizontal_edges:
            continue
        top_y = min(edge[2] for edge in horizontal_edges)
        result.extend(
            SupportSegment(start_x, end_x, y, collision.one_way)
            for start_x, end_x, y in horizontal_edges
            if abs(y - top_y) <= 0.25 and end_x - start_x > 0.25
        )
    return _merge_segments(result)


def generate_support_nodes(geometry: LevelGeometry) -> list[NavigationNode]:
    segments = support_segments(geometry)
    clearance = infer_player_clearance(geometry.spawns, segments)
    min_x = geometry.safe_bounds.position.x + clearance
    max_x = geometry.safe_bounds.right - clearance
    min_y = geometry.safe_bounds.position.y
    max_y = geometry.safe_bounds.bottom

    positions: list[Point] = []
    for segment in segments:
        start_x = max(min_x, segment.start_x + clearance)
        end_x = min(max_x, segment.end_x - clearance)
        if end_x < start_x:
            continue
        candidate_y = segment.y - clearance
        if not min_y <= candidate_y <= max_y:
            continue
        if end_x - start_x <= clearance:
            x_positions = [(start_x + end_x) / 2]
        else:
            x_positions = [start_x, end_x]
        positions.extend(Point(x, candidate_y) for x in x_positions)

    positions.extend(
        spawn
        for spawn in geometry.spawns.values()
        if geometry.safe_bounds.contains(spawn)
    )
    positions.extend(_wall_base_positions(geometry, segments, clearance))
    unique_positions = _unique_positions(positions)
    return [
        NavigationNode(index, point)
        for index, point in enumerate(
            sorted(unique_positions, key=lambda point: (point.x, point.y)), start=1
        )
    ]


def infer_player_clearance(
    spawns: dict[str, Point], segments: list[SupportSegment]
) -> float:
    offsets: list[float] = []
    for player, spawn in sorted(spawns.items()):
        below_spawn = [
            segment.y - spawn.y
            for segment in segments
            if segment.start_x - 0.5 <= spawn.x <= segment.end_x + 0.5
            and segment.y > spawn.y + 0.5
        ]
        if not below_spawn:
            raise CPUBridgeProtocolError(
                f"Could not infer player clearance from {player}'s spawn."
            )
        offsets.append(min(below_spawn))
    clearance = statistics.median(offsets)
    if not math.isfinite(clearance) or clearance <= 0:
        raise CPUBridgeProtocolError("Inferred player clearance must be positive.")
    return clearance


def _wall_base_positions(
    geometry: LevelGeometry,
    segments: list[SupportSegment],
    clearance: float,
) -> list[Point]:
    positions: list[Point] = []
    for collision in geometry.collisions:
        if collision.collision_layer == 0 or collision.one_way:
            continue
        polygon_center_x = sum(point.x for point in collision.points) / len(
            collision.points
        )
        for start, end in zip(
            collision.points, (*collision.points[1:], collision.points[0])
        ):
            if abs(start.x - end.x) > 0.25:
                continue
            wall_x = (start.x + end.x) / 2
            wall_bottom = max(start.y, end.y)
            outside_direction = -1 if wall_x < polygon_center_x else 1
            for segment in segments:
                if segment.y < wall_bottom - 0.5 or segment.y - wall_bottom > clearance * 2:
                    continue
                y = segment.y - clearance
                x = wall_x + outside_direction * clearance
                if (
                    segment.start_x + clearance <= x <= segment.end_x - clearance
                    and geometry.safe_bounds.contains(Point(x, y))
                ):
                    positions.append(Point(x, y))
    return positions


def _merge_segments(segments: list[SupportSegment]) -> list[SupportSegment]:
    merged: list[SupportSegment] = []
    ordered = sorted(
        segments,
        key=lambda segment: (segment.one_way, segment.y, segment.start_x, segment.end_x),
    )
    for segment in ordered:
        if (
            merged
            and merged[-1].one_way == segment.one_way
            and abs(merged[-1].y - segment.y) <= 0.25
            and segment.start_x <= merged[-1].end_x + 0.5
        ):
            previous = merged[-1]
            merged[-1] = SupportSegment(
                previous.start_x,
                max(previous.end_x, segment.end_x),
                min(previous.y, segment.y),
                previous.one_way,
            )
        else:
            merged.append(segment)
    return merged


def _unique_positions(positions: list[Point], tolerance: float = 0.5) -> list[Point]:
    unique: list[Point] = []
    for point in sorted(positions, key=lambda item: (item.x, item.y)):
        if not any(
            abs(existing.x - point.x) <= tolerance
            and abs(existing.y - point.y) <= tolerance
            for existing in unique
        ):
            unique.append(point)
    return unique
