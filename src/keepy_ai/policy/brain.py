from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from keepy_ai.bridge.models import CPUIntent, CPUObservation, PlayerObservation, Vector2
from keepy_ai.graph.geometry import LevelGeometry, Point
from keepy_ai.policy.config import PolicyConfig
from keepy_ai.policy.trajectory import TrajectorySample, predict_trajectory


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    action: CPUIntent
    phase: str
    prediction_status: str
    target: Point | None
    predicted_time: float | None
    player_balloon_distance: float
    minimum_safe_distance: float
    safe_distance: bool
    reason: str | None = None
    configuration: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "prediction_status": self.prediction_status,
            "target": self.target.to_payload() if self.target is not None else None,
            "predicted_time": self.predicted_time,
            "player_balloon_distance": self.player_balloon_distance,
            "minimum_safe_distance": self.minimum_safe_distance,
            "safe_distance": self.safe_distance,
            "action": self.action.to_payload(),
            "reason": self.reason,
            "configuration": self.configuration,
        }


def decide(
    observation: CPUObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
) -> PolicyDecision:
    player_id = observation.bot_player
    if player_id not in observation.players:
        return _fallback(observation, "unknown", "invalid_bot_player", config=config)
    player = observation.players[player_id]
    dx = player.position.x - observation.balloon.position.x
    dy = player.position.y - observation.balloon.position.y
    distance = math.hypot(dx, dy)
    phase = "own_turn" if observation.current_turn == player_id else "opponent_turn"
    if observation.current_turn not in observation.players:
        phase = "undetermined"
    try:
        if geometry.level != observation.level:
            raise ValueError("geometry_level_mismatch")
        path = predict_trajectory(observation.balloon, geometry, config)
    except ValueError as error:
        return _fallback(observation, phase, str(error), distance, config)

    if phase == "undetermined":
        return PolicyDecision(
            CPUIntent(), phase, "not_used", None, None, distance,
            config.minimum_safe_distance, distance >= config.minimum_safe_distance,
            "current_turn is empty or unknown",
            asdict(config),
        )
    if phase == "own_turn":
        return _decide_own_turn(observation, player, geometry, config, path, distance)
    return _decide_opponent_turn(observation, player, geometry, config, path, distance)


def _decide_own_turn(
    observation: CPUObservation,
    player: PlayerObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
    path: tuple[TrajectorySample, ...],
    distance: float,
) -> PolicyDecision:
    if observation.balloon.waiting_for_first_touch:
        target = Point(observation.balloon.position.x, observation.balloon.position.y)
        action = CPUIntent(horizontal=_horizontal(target.x - player.position.x))
        return PolicyDecision(
            action, "own_turn", "waiting_for_first_touch", target, 0.0, distance,
            config.minimum_safe_distance, distance >= config.minimum_safe_distance,
            configuration=asdict(config),
        )
    target_sample = _first_reachable_intercept(player, geometry, config, path)
    if target_sample is None:
        nearest = min(
            path,
            key=lambda sample: math.hypot(
                sample.position.x - player.position.x,
                sample.position.y - player.position.y,
            ),
        )
        target = Point(
            _clamp(nearest.position.x, geometry.bounds.position.x, geometry.bounds.right),
            player.position.y,
        )
        return PolicyDecision(
            CPUIntent(horizontal=_horizontal(target.x - player.position.x)),
            "own_turn", "no_reachable_intercept", target, nearest.time, distance,
            config.minimum_safe_distance, distance >= config.minimum_safe_distance,
            "No reachable balloon sample was found in the prediction horizon.",
            asdict(config),
        )

    target = target_sample.position
    delta_x = target.x - player.position.x
    horizontal = _horizontal(delta_x)
    target_distance = math.hypot(delta_x, target.y - player.position.y)
    jump = target.y < player.position.y - 10 and abs(delta_x) <= 26
    dash = (
        target_distance >= 56
        and player.dash_available
        and player.dash_cooldown <= 0
    )
    direction = Vector2(delta_x, target.y - player.position.y)
    if direction.x or direction.y:
        norm = math.hypot(direction.x, direction.y)
        direction = Vector2(direction.x / norm, direction.y / norm)
    action = CPUIntent(horizontal=horizontal, jump=jump, dash=dash, dash_direction=direction)
    return PolicyDecision(
        action, "own_turn", "intercept_found", target, target_sample.time, distance,
        config.minimum_safe_distance, distance >= config.minimum_safe_distance,
        configuration=asdict(config),
    )


def _first_reachable_intercept(
    player: PlayerObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
    path: tuple[TrajectorySample, ...],
) -> TrajectorySample | None:
    constants = geometry.movement_constants
    horizontal_speed = constants.get("MAX_RUN", config.player_horizontal_speed)
    gravity = constants.get("GRAVITY", 980.0)
    jump_speed = abs(constants.get("JUMP_SPEED", -config.player_jump_speed))
    jump_height = jump_speed * jump_speed / (2 * max(gravity, 1.0))
    contact = config.player_contact_radius + config.player_collision_radius
    min_y = player.position.y - jump_height - contact
    max_y = player.position.y + contact
    for sample in path[1:]:
        if not min_y <= sample.position.y <= max_y:
            continue
        horizontal_distance = abs(sample.position.x - player.position.x)
        if horizontal_distance <= horizontal_speed * sample.time + contact:
            return sample
    return None


def _decide_opponent_turn(
    observation: CPUObservation,
    player: PlayerObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
    path: tuple[TrajectorySample, ...],
    distance: float,
) -> PolicyDecision:
    closest = min(
        path,
        key=lambda sample: math.hypot(
            sample.position.x - player.position.x,
            sample.position.y - player.position.y,
        ),
    )
    side = _safe_side(player.position.x, closest.position.x, geometry, config)
    target_x = _clamp(
        closest.position.x + side * config.preferred_distance,
        geometry.bounds.position.x + config.player_collision_radius,
        geometry.bounds.right - config.player_collision_radius,
    )
    projected_distance = math.hypot(
        player.position.x - closest.position.x,
        player.position.y - closest.position.y,
    )
    evasive = projected_distance < config.minimum_safe_distance
    if evasive:
        left = geometry.bounds.position.x + config.player_collision_radius
        right = geometry.bounds.right - config.player_collision_radius
        if player.position.x < closest.position.x:
            target_x = max(
                left,
                closest.position.x - config.preferred_distance,
            )
            if closest.position.x - left < config.minimum_safe_distance:
                target_x = left
        elif player.position.x > closest.position.x:
            target_x = min(
                right,
                closest.position.x + config.preferred_distance,
            )
            if right - closest.position.x < config.minimum_safe_distance:
                target_x = right
        else:
            left_clearance = closest.position.x - left
            right_clearance = right - closest.position.x
            target_x = left if left_clearance >= right_clearance else right
    action = CPUIntent(horizontal=_horizontal(target_x - player.position.x))
    return PolicyDecision(
        action,
        "opponent_turn",
        "evasive" if evasive else "defensive_position",
        Point(target_x, player.position.y),
        closest.time,
        distance,
        config.minimum_safe_distance,
        projected_distance >= config.minimum_safe_distance,
        "Predicted closest approach is inside the safe distance." if evasive else None,
        asdict(config),
    )


def _safe_side(
    player_x: float,
    balloon_x: float,
    geometry: LevelGeometry,
    config: PolicyConfig,
) -> float:
    if player_x < balloon_x:
        return -1.0
    if player_x > balloon_x:
        return 1.0
    left_clearance = balloon_x - (geometry.bounds.position.x + config.player_collision_radius)
    right_clearance = geometry.bounds.right - config.player_collision_radius - balloon_x
    return -1.0 if left_clearance >= right_clearance else 1.0


def _fallback(
    observation: CPUObservation,
    phase: str,
    reason: str,
    distance: float = 0.0,
    config: PolicyConfig | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        CPUIntent(), phase, "invalid_geometry", None, None, distance,
        config.minimum_safe_distance if config is not None else 0.0,
        False,
        reason,
        asdict(config) if config is not None else None,
    )


def _horizontal(distance: float) -> float:
    return 0.0 if abs(distance) <= 10 else (1.0 if distance > 0 else -1.0)


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)
