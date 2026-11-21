from __future__ import annotations

import math
from dataclasses import dataclass

from keepy_ai.bridge.models import BalloonObservation
from keepy_ai.graph.geometry import LevelGeometry, Point
from keepy_ai.policy.config import PolicyConfig

BALLOON_COLLISION_MASK = 0b011
_COLLISION_EPSILON = 1e-8
_CONTACT_SEPARATION = 1e-4
_MAX_COLLISIONS_PER_STEP = 4


@dataclass(frozen=True, slots=True)
class TrajectorySample:
    time: float
    position: Point
    velocity: Point
    wall_bounced: bool = False
    collision_bounced: bool = False


@dataclass(frozen=True, slots=True)
class _PreparedCollision:
    points: tuple[Point, ...]
    edges: tuple[tuple[Point, Point, float, Point], ...]
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class _CollisionContact:
    fraction: float
    normal: Point


def predict_trajectory(
    balloon: BalloonObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
) -> tuple[TrajectorySample, ...]:
    """Approximate the balloon path through exported arena collision geometry."""
    if not isinstance(geometry, LevelGeometry):
        raise ValueError("Level geometry is required for trajectory prediction.")
    bounds = geometry.bounds
    values = (
        bounds.position.x,
        bounds.position.y,
        bounds.size.x,
        bounds.size.y,
        balloon.position.x,
        balloon.position.y,
        balloon.velocity.x,
        balloon.velocity.y,
    )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Trajectory positions and bounds must be finite.")
    if bounds.size.x <= config.balloon_radius * 2 or bounds.size.y <= 0:
        raise ValueError("Arena bounds are too small for the configured balloon radius.")

    collisions = _prepare_collisions(geometry)
    left = bounds.position.x + config.balloon_radius
    right = bounds.right - config.balloon_radius
    if left >= right:
        raise ValueError("Playable side-wall bounds are inconsistent.")

    if balloon.waiting_for_first_touch:
        return (
            TrajectorySample(
                0.0,
                Point(
                    min(max(balloon.position.x, left), right),
                    balloon.position.y,
                ),
                Point(0.0, 0.0),
            ),
        )

    dt = 1.0 / config.physics_hz
    steps = min(
        math.ceil(config.prediction_horizon * config.physics_hz),
        config.max_prediction_steps,
    )
    x = min(max(balloon.position.x, left), right)
    y = balloon.position.y
    vx = balloon.velocity.x
    vy = balloon.velocity.y
    elapsed = 0.0
    samples = [TrajectorySample(0.0, Point(x, y), Point(vx, vy))]
    for _ in range(steps):
        step = min(dt, config.prediction_horizon - elapsed)
        if step <= 0:
            break
        retention = 1.0 + config.air_resistance * step
        vx /= retention * (1.0 + config.horizontal_damping * step)
        vy /= retention
        vx = min(max(vx, -config.max_horizontal_speed), config.max_horizontal_speed)
        vy = min(max(vy, -config.max_rise_speed), config.max_fall_speed)
        vy = min(max(vy + config.gravity * step, -config.max_rise_speed), config.max_fall_speed)
        x, y, vx, vy, collision_bounced = _move_with_collisions(
            Point(x, y), vx, vy, step, collisions, config
        )
        wall_bounced = False
        if x < left:
            x = left + (left - x)
            vx = abs(vx) * config.rebound_strength
            wall_bounced = True
        elif x > right:
            x = right - (x - right)
            vx = -abs(vx) * config.rebound_strength
            wall_bounced = True
        x = min(max(x, left), right)
        elapsed += step
        samples.append(
            TrajectorySample(
                elapsed,
                Point(x, y),
                Point(vx, vy),
                wall_bounced,
                collision_bounced,
            )
        )
        if y >= bounds.bottom - config.balloon_radius:
            break
    return tuple(samples)


def _prepare_collisions(geometry: LevelGeometry) -> tuple[_PreparedCollision, ...]:
    exported = [
        collision
        for collision in (*geometry.collisions, *geometry.platforms)
        if collision.collision_layer & BALLOON_COLLISION_MASK
    ]
    if not exported:
        raise ValueError("Balloon collision geometry is unavailable.")

    prepared = []
    for collision in exported:
        if collision.one_way:
            raise ValueError(
                f"One-way balloon collision geometry is unsupported: {collision.source}."
            )
        points = collision.points
        if len(points) < 2:
            raise ValueError(
                f"Balloon collision geometry is invalid: {collision.source}."
            )
        edges = []
        pairs = (
            tuple(zip(points, points[1:]))
            if len(points) == 2
            else tuple(zip(points, (*points[1:], points[0])))
        )
        for start, end in pairs:
            dx = end.x - start.x
            dy = end.y - start.y
            length_squared = dx * dx + dy * dy
            if length_squared <= _COLLISION_EPSILON:
                continue
            length = math.sqrt(length_squared)
            edges.append(
                (
                    start,
                    end,
                    length_squared,
                    Point(-dy / length, dx / length),
                )
            )
        if not edges:
            raise ValueError(
                f"Balloon collision geometry is degenerate: {collision.source}."
            )
        prepared.append(
            _PreparedCollision(
                points,
                tuple(edges),
                (
                    min(point.x for point in points),
                    min(point.y for point in points),
                    max(point.x for point in points),
                    max(point.y for point in points),
                ),
            )
        )
    return tuple(prepared)


def _move_with_collisions(
    position: Point,
    vx: float,
    vy: float,
    duration: float,
    collisions: tuple[_PreparedCollision, ...],
    config: PolicyConfig,
) -> tuple[float, float, float, float, bool]:
    current = position
    remaining = 1.0
    bounced = False
    for _ in range(_MAX_COLLISIONS_PER_STEP):
        destination = Point(
            current.x + vx * duration * remaining,
            current.y + vy * duration * remaining,
        )
        contact = _first_collision(
            current, destination, config.balloon_radius, collisions
        )
        if contact is None:
            current = destination
            break
        delta_x = destination.x - current.x
        delta_y = destination.y - current.y
        current = Point(
            current.x + delta_x * contact.fraction
            + contact.normal.x * _CONTACT_SEPARATION,
            current.y + delta_y * contact.fraction
            + contact.normal.y * _CONTACT_SEPARATION,
        )
        normal_speed = vx * contact.normal.x + vy * contact.normal.y
        if normal_speed >= -_COLLISION_EPSILON:
            break
        reflection = (1.0 + config.rebound_strength) * normal_speed
        vx -= reflection * contact.normal.x
        vy -= reflection * contact.normal.y
        remaining *= 1.0 - contact.fraction
        bounced = True
        if remaining <= _COLLISION_EPSILON:
            break
    return current.x, current.y, vx, vy, bounced


def _first_collision(
    start: Point,
    end: Point,
    radius: float,
    collisions: tuple[_PreparedCollision, ...],
) -> _CollisionContact | None:
    delta = Point(end.x - start.x, end.y - start.y)
    sweep_bounds = (
        min(start.x, end.x) - radius,
        min(start.y, end.y) - radius,
        max(start.x, end.x) + radius,
        max(start.y, end.y) + radius,
    )
    earliest: _CollisionContact | None = None
    for collision in collisions:
        min_x, min_y, max_x, max_y = collision.bounds
        if (
            sweep_bounds[2] < min_x
            or sweep_bounds[0] > max_x
            or sweep_bounds[3] < min_y
            or sweep_bounds[1] > max_y
        ):
            continue
        if _inside_polygon(start, collision.points):
            raise ValueError("Balloon starts inside exported collision geometry.")
        for edge_start, edge_end, edge_length_squared, edge_normal in collision.edges:
            signed_start = _dot(
                Point(start.x - edge_start.x, start.y - edge_start.y), edge_normal
            )
            signed_delta = _dot(delta, edge_normal)
            if abs(signed_start) <= _COLLISION_EPSILON:
                side = -1.0 if signed_delta > 0 else 1.0
            else:
                side = 1.0 if signed_start > 0 else -1.0
            distance = signed_start * side
            motion = signed_delta * side
            if motion >= -_COLLISION_EPSILON:
                continue
            fraction = 0.0 if distance <= radius else (radius - distance) / motion
            if not 0.0 <= fraction <= 1.0:
                continue
            center = Point(
                start.x + delta.x * fraction,
                start.y + delta.y * fraction,
            )
            edge_fraction = (
                (center.x - edge_start.x) * (edge_end.x - edge_start.x)
                + (center.y - edge_start.y) * (edge_end.y - edge_start.y)
            ) / edge_length_squared
            if not -_COLLISION_EPSILON <= edge_fraction <= 1 + _COLLISION_EPSILON:
                continue
            normal = Point(edge_normal.x * side, edge_normal.y * side)
            earliest = _earlier_contact(
                earliest, _CollisionContact(fraction, normal)
            )
        for vertex in collision.points:
            contact = _sweep_vertex(start, delta, vertex, radius)
            if contact is not None:
                earliest = _earlier_contact(earliest, contact)
    return earliest


def _sweep_vertex(
    start: Point, delta: Point, vertex: Point, radius: float
) -> _CollisionContact | None:
    offset = Point(start.x - vertex.x, start.y - vertex.y)
    a = _dot(delta, delta)
    if a <= _COLLISION_EPSILON:
        return None
    b = 2.0 * _dot(offset, delta)
    c = _dot(offset, offset) - radius * radius
    if c <= 0:
        normal_length = math.hypot(offset.x, offset.y)
        if normal_length <= _COLLISION_EPSILON:
            normal = Point(-delta.x / math.sqrt(a), -delta.y / math.sqrt(a))
        else:
            normal = Point(offset.x / normal_length, offset.y / normal_length)
        if _dot(delta, normal) >= -_COLLISION_EPSILON:
            return None
        return _CollisionContact(0.0, normal)
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0:
        return None
    fraction = (-b - math.sqrt(discriminant)) / (2.0 * a)
    if not 0.0 <= fraction <= 1.0:
        return None
    center = Point(
        start.x + delta.x * fraction,
        start.y + delta.y * fraction,
    )
    normal = Point(center.x - vertex.x, center.y - vertex.y)
    length = math.hypot(normal.x, normal.y)
    if length <= _COLLISION_EPSILON:
        return None
    normal = Point(normal.x / length, normal.y / length)
    if _dot(delta, normal) >= -_COLLISION_EPSILON:
        return None
    return _CollisionContact(fraction, normal)


def _earlier_contact(
    current: _CollisionContact | None, candidate: _CollisionContact
) -> _CollisionContact:
    if current is None or candidate.fraction < current.fraction:
        return candidate
    return current


def _inside_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    if len(polygon) < 3:
        return False
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if (current.y > point.y) != (previous.y > point.y):
            intersection_x = (
                (previous.x - current.x)
                * (point.y - current.y)
                / (previous.y - current.y)
                + current.x
            )
            if point.x < intersection_x:
                inside = not inside
        previous = current
    return inside


def _dot(left: Point, right: Point) -> float:
    return left.x * right.x + left.y * right.y
