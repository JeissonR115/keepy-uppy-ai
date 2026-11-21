from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping

DEFAULT_PREFERRED_DISTANCE = 48.0


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    """Tunable physics approximation and player-balloon spacing in world pixels."""

    gravity: float = 137.2
    air_resistance: float = 0.055
    horizontal_damping: float = 0.08
    rebound_strength: float = 0.28
    max_horizontal_speed: float = 220.0
    max_rise_speed: float = 220.0
    max_fall_speed: float = 90.0
    physics_hz: float = 60.0
    balloon_radius: float = 9.0
    player_contact_radius: float = 16.0
    player_collision_radius: float = 3.0
    safety_margin: float = 8.0
    preferred_distance: float | None = None
    opponent_push_slowdown: float = 2.5
    prediction_horizon: float = 3.0
    max_prediction_steps: int = 360
    player_horizontal_speed: float = 130.0
    player_jump_speed: float = 250.0

    def __post_init__(self) -> None:
        numeric_positive = (
            "max_horizontal_speed",
            "max_rise_speed",
            "max_fall_speed",
            "physics_hz",
            "balloon_radius",
            "player_contact_radius",
            "player_collision_radius",
            "prediction_horizon",
            "player_horizontal_speed",
            "player_jump_speed",
        )
        for name in numeric_positive:
            value = getattr(self, name)
            if not _finite_number(value) or value <= 0:
                raise ValueError(f"policy.{name} must be finite and positive.")
        numeric_nonnegative = (
            "gravity",
            "air_resistance",
            "horizontal_damping",
            "safety_margin",
        )
        for name in numeric_nonnegative:
            value = getattr(self, name)
            if not _finite_number(value) or value < 0:
                raise ValueError(f"policy.{name} must be finite and non-negative.")
        if not _finite_number(self.rebound_strength) or not 0 <= self.rebound_strength <= 1:
            raise ValueError("policy.rebound_strength must be between 0 and 1.")
        if self.preferred_distance is not None and not _finite_number(
            self.preferred_distance
        ):
            raise ValueError("policy.preferred_distance must be finite.")
        if (
            self.preferred_distance is not None
            and self.preferred_distance < self.minimum_safe_distance
        ):
            raise ValueError(
                "policy.preferred_distance must be at least the minimum safe distance "
                f"({self.minimum_safe_distance:.2f})."
            )
        if (
            not _finite_number(self.opponent_push_slowdown)
            or self.opponent_push_slowdown < 1
        ):
            raise ValueError(
                "policy.opponent_push_slowdown must be finite and at least 1."
            )
        if (
            isinstance(self.max_prediction_steps, bool)
            or not isinstance(self.max_prediction_steps, int)
            or self.max_prediction_steps <= 0
        ):
            raise ValueError("policy.max_prediction_steps must be a positive integer.")

    @property
    def minimum_safe_distance(self) -> float:
        return self.player_contact_radius + self.player_collision_radius + self.safety_margin

    def resolve_preferred_distance(
        self, movement_constants: Mapping[str, float]
    ) -> tuple[float, str]:
        if self.preferred_distance is not None:
            return self.preferred_distance, "override"

        dash_speed = movement_constants.get("DASH_SPEED")
        dash_time = movement_constants.get("DASH_TIME")
        if (
            _finite_number(dash_speed)
            and _finite_number(dash_time)
            and dash_speed > 0
            and dash_time > 0
        ):
            return max(dash_speed * dash_time, self.minimum_safe_distance), "dash_range"

        return max(DEFAULT_PREFERRED_DISTANCE, self.minimum_safe_distance), "fallback"

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> PolicyConfig:
        allowed = {field.name for field in fields(cls)}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Unknown policy setting(s): " + ", ".join(sorted(unknown)))
        return cls(**values)


def load_policy_config(
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> PolicyConfig:
    values: dict[str, Any] = {}
    if config_path is not None and config_path.is_file():
        with config_path.open("rb") as stream:
            data = tomllib.load(stream)
        section = data.get("policy", {})
        if not isinstance(section, dict):
            raise ValueError("[policy] in keepy-ai.toml must be a table.")
        values.update(section)
    values.update({key: value for key, value in (overrides or {}).items() if value is not None})
    return PolicyConfig.from_mapping(values)


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )
