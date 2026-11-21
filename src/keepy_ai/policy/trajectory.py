from __future__ import annotations

import math
from dataclasses import dataclass

from keepy_ai.bridge.models import BalloonObservation
from keepy_ai.graph.geometry import LevelGeometry, Point
from keepy_ai.policy.config import PolicyConfig


@dataclass(frozen=True, slots=True)
class TrajectorySample:
    time: float
    position: Point
    velocity: Point
    wall_bounced: bool = False


def predict_trajectory(
    balloon: BalloonObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
) -> tuple[TrajectorySample, ...]:
    """Approximate the balloon path with horizontal side-wall rebounds."""
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
        x += vx * step
        y += vy * step
        bounced = False
        if x < left:
            x = left + (left - x)
            vx = abs(vx) * config.rebound_strength
            bounced = True
        elif x > right:
            x = right - (x - right)
            vx = -abs(vx) * config.rebound_strength
            bounced = True
        # Correct any remaining overshoot if an unusually large time step spans
        # more than one wall. The following frame handles subsequent rebounds.
        x = min(max(x, left), right)
        elapsed += step
        samples.append(TrajectorySample(elapsed, Point(x, y), Point(vx, vy), bounced))
        if y >= bounds.bottom - config.balloon_radius:
            break
    return tuple(samples)
