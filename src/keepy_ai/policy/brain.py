from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from keepy_ai.bridge.models import CPUIntent, CPUObservation, PlayerObservation, Vector2
from keepy_ai.graph.geometry import LevelGeometry, Point
from keepy_ai.graph.navigation import NavigationGraph, RoutePlan, find_route
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
    preferred_distance: float | None = None
    preferred_distance_source: str | None = None
    route_status: str = "not_used"
    route_node_ids: tuple[int, ...] = ()
    route_waypoint: Point | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "prediction_status": self.prediction_status,
            "target": self.target.to_payload() if self.target is not None else None,
            "predicted_time": self.predicted_time,
            "player_balloon_distance": self.player_balloon_distance,
            "minimum_safe_distance": self.minimum_safe_distance,
            "safe_distance": self.safe_distance,
            "preferred_distance": self.preferred_distance,
            "preferred_distance_source": self.preferred_distance_source,
            "route_status": self.route_status,
            "route_node_ids": list(self.route_node_ids),
            "route_waypoint": (
                self.route_waypoint.to_payload()
                if self.route_waypoint is not None
                else None
            ),
            "action": self.action.to_payload(),
            "reason": self.reason,
            "configuration": self.configuration,
        }


def decide(
    observation: CPUObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
    graph: NavigationGraph | None = None,
    graph_error: str | None = None,
) -> PolicyDecision:
    if graph is not None and graph.level != geometry.level:
        graph_error = (
            f"Navigation graph level {graph.level!r} does not match "
            f"geometry level {geometry.level!r}."
        )
        graph = None
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

    route_penalties = (
        _opponent_route_penalties(observation, geometry, graph, config)
        if graph is not None
        else {}
    )
    if phase == "undetermined":
        return PolicyDecision(
            CPUIntent(), phase, "not_used", None, None, distance,
            config.minimum_safe_distance, distance >= config.minimum_safe_distance,
            "current_turn is empty or unknown",
            asdict(config),
        )
    if phase == "own_turn":
        return _decide_own_turn(
            observation,
            player,
            geometry,
            config,
            path,
            distance,
            graph,
            graph_error,
            route_penalties,
        )
    return _decide_opponent_turn(
        observation,
        player,
        geometry,
        config,
        path,
        distance,
        graph,
        graph_error,
        route_penalties,
    )


def _decide_own_turn(
    observation: CPUObservation,
    player: PlayerObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
    path: tuple[TrajectorySample, ...],
    distance: float,
    graph: NavigationGraph | None,
    graph_error: str | None,
    route_penalties: dict[int, float],
) -> PolicyDecision:
    if observation.balloon.waiting_for_first_touch:
        target = Point(observation.balloon.position.x, observation.balloon.position.y)
        action = CPUIntent(horizontal=_horizontal(target.x - player.position.x))
        return PolicyDecision(
            action, "own_turn", "waiting_for_first_touch", target, 0.0, distance,
            config.minimum_safe_distance, distance >= config.minimum_safe_distance,
            configuration=asdict(config),
        )
    candidates = _reachable_intercepts(player, geometry, config, path)
    target_sample = candidates[0] if candidates else None
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

    route: RoutePlan | None = None
    if graph is not None:
        routed_candidates = [
            (
                sample,
                find_route(
                    graph,
                    player.position,
                    sample.position,
                    edge_penalties=route_penalties,
                ),
            )
            for sample in candidates
        ]
        reachable_routes = [
            (sample, candidate_route)
            for sample, candidate_route in routed_candidates
            if candidate_route is not None
        ]
        if reachable_routes:
            target_sample, route = min(
                reachable_routes,
                key=lambda item: (
                    item[1].cost,
                    item[0].time,
                    item[1].node_ids,
                ),
            )
    target = target_sample.position
    route_status, route_reason = _route_status(graph, route, graph_error)
    movement_target = route.waypoint if route is not None else target
    action = _action_toward(
        player,
        movement_target,
        route.first_traversal.action if route is not None and route.first_traversal else None,
    )
    return PolicyDecision(
        action, "own_turn", "intercept_found", target, target_sample.time, distance,
        config.minimum_safe_distance, distance >= config.minimum_safe_distance,
        route_reason,
        asdict(config),
        route_status=route_status,
        route_node_ids=route.node_ids if route is not None else (),
        route_waypoint=route.waypoint if route is not None else None,
    )


def _reachable_intercepts(
    player: PlayerObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
    path: tuple[TrajectorySample, ...],
) -> list[TrajectorySample]:
    constants = geometry.movement_constants
    horizontal_speed = constants.get("MAX_RUN", config.player_horizontal_speed)
    gravity = constants.get("GRAVITY", 980.0)
    jump_speed = abs(constants.get("JUMP_SPEED", -config.player_jump_speed))
    jump_height = jump_speed * jump_speed / (2 * max(gravity, 1.0))
    contact = config.player_contact_radius + config.player_collision_radius
    min_y = player.position.y - jump_height - contact
    max_y = player.position.y + contact
    candidates = []
    for sample in path[1:]:
        if not min_y <= sample.position.y <= max_y:
            continue
        horizontal_distance = abs(sample.position.x - player.position.x)
        if horizontal_distance <= horizontal_speed * sample.time + contact:
            candidates.append(sample)
    return candidates


def _decide_opponent_turn(
    observation: CPUObservation,
    player: PlayerObservation,
    geometry: LevelGeometry,
    config: PolicyConfig,
    path: tuple[TrajectorySample, ...],
    distance: float,
    graph: NavigationGraph | None,
    graph_error: str | None,
    route_penalties: dict[int, float],
) -> PolicyDecision:
    preferred_distance, preferred_distance_source = config.resolve_preferred_distance(
        geometry.movement_constants
    )
    closest = min(
        path,
        key=lambda sample: math.hypot(
            sample.position.x - player.position.x,
            sample.position.y - player.position.y,
        ),
    )
    side = _safe_side(player.position.x, closest.position.x, geometry, config)
    target_x = _clamp(
        closest.position.x + side * preferred_distance,
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
                closest.position.x - preferred_distance,
            )
            if closest.position.x - left < config.minimum_safe_distance:
                target_x = left
        elif player.position.x > closest.position.x:
            target_x = min(
                right,
                closest.position.x + preferred_distance,
            )
            if right - closest.position.x < config.minimum_safe_distance:
                target_x = right
        else:
            left_clearance = closest.position.x - left
            right_clearance = right - closest.position.x
            target_x = left if left_clearance >= right_clearance else right
    target = Point(target_x, player.position.y)
    route = (
        find_route(
            graph,
            player.position,
            target,
            edge_penalties=route_penalties,
        )
        if graph is not None
        else None
    )
    route_status, route_reason = _route_status(graph, route, graph_error)
    movement_target = route.waypoint if route is not None else target
    action = _action_toward(
        player,
        movement_target,
        route.first_traversal.action if route is not None and route.first_traversal else None,
        allow_direct_dash=False,
    )
    return PolicyDecision(
        action,
        "opponent_turn",
        "evasive" if evasive else "defensive_position",
        target,
        closest.time,
        distance,
        config.minimum_safe_distance,
        projected_distance >= config.minimum_safe_distance,
        (
            "Predicted closest approach is inside the safe distance."
            if evasive
            else (
                "Dash constants unavailable; used the documented fallback distance."
                if preferred_distance_source == "fallback"
                else route_reason
            )
        ),
        asdict(config),
        preferred_distance,
        preferred_distance_source,
        route_status,
        route.node_ids if route is not None else (),
        route.waypoint if route is not None else None,
    )


def _route_status(
    graph: NavigationGraph | None,
    route: RoutePlan | None,
    graph_error: str | None,
) -> tuple[str, str | None]:
    if graph is None:
        return (
            "graph_unavailable" if graph_error else "direct_fallback",
            graph_error or "Navigation graph not provided; using direct movement.",
        )
    if route is None:
        return "no_graph_route", "No reachable graph route matched the target."
    return "graph_route", None


def _action_toward(
    player: PlayerObservation,
    target: Point,
    edge_action: str | None,
    *,
    allow_direct_dash: bool = True,
) -> CPUIntent:
    delta_x = target.x - player.position.x
    delta_y = target.y - player.position.y
    direction = Vector2(delta_x, delta_y)
    if direction.x or direction.y:
        norm = math.hypot(direction.x, direction.y)
        direction = Vector2(direction.x / norm, direction.y / norm)
    dash_requested = (
        edge_action == "DASH"
        if edge_action is not None
        else allow_direct_dash and math.hypot(delta_x, delta_y) >= 56
    )
    jump_requested = (
        edge_action == "JUMP"
        if edge_action is not None
        else target.y < player.position.y - 10 and abs(delta_x) <= 26
    )
    dash = dash_requested and player.dash_available and player.dash_cooldown <= 0
    jump = jump_requested and (player.on_floor if edge_action is not None else True)
    down = edge_action == "DROP"
    return CPUIntent(
        horizontal=_horizontal(delta_x),
        jump=jump,
        dash=dash,
        dash_direction=direction,
        down=down,
    )


def _opponent_route_penalties(
    observation: CPUObservation,
    geometry: LevelGeometry,
    graph: NavigationGraph,
    config: PolicyConfig,
) -> dict[int, float]:
    player = observation.players[observation.bot_player]
    opponent_id = next(
        player_id
        for player_id in observation.players
        if player_id != observation.bot_player
    )
    opponent = observation.players[opponent_id]
    player_speed = geometry.movement_constants.get(
        "MAX_RUN", config.player_horizontal_speed
    )
    if not math.isfinite(player_speed) or player_speed <= 0:
        player_speed = config.player_horizontal_speed
    occupied_radius = config.player_collision_radius * 2.0 + 2.0
    penalties: dict[int, float] = {}
    for edge_index, edge in enumerate(graph.edges):
        start = graph.nodes[edge.source].position
        end = graph.nodes[edge.target].position
        edge_length = math.hypot(end.x - start.x, end.y - start.y)
        eta_start = min(
            config.prediction_horizon,
            math.hypot(
                start.x - player.position.x,
                start.y - player.position.y,
            )
            / player_speed,
        )
        eta_end = min(
            config.prediction_horizon,
            eta_start + edge_length / player_speed,
        )
        opponent_start = _predicted_opponent_position(
            opponent, eta_start, geometry
        )
        opponent_end = _predicted_opponent_position(opponent, eta_end, geometry)
        if (
            _synchronized_segment_distance(
                start, end, opponent_start, opponent_end
            )
            <= occupied_radius
        ):
            penalties[edge_index] = edge.cost * (
                config.opponent_push_slowdown - 1.0
            )
    return penalties


def _predicted_opponent_position(
    opponent: PlayerObservation, elapsed: float, geometry: LevelGeometry
) -> Point:
    return Point(
        _clamp(
            opponent.position.x + opponent.velocity.x * elapsed,
            geometry.bounds.position.x,
            geometry.bounds.right,
        ),
        _clamp(
            opponent.position.y + opponent.velocity.y * elapsed,
            geometry.bounds.position.y,
            geometry.bounds.bottom,
        ),
    )


def _synchronized_segment_distance(
    player_start: Point,
    player_end: Point,
    opponent_start: Point,
    opponent_end: Point,
) -> float:
    relative_x = player_start.x - opponent_start.x
    relative_y = player_start.y - opponent_start.y
    relative_delta_x = (
        player_end.x - player_start.x - opponent_end.x + opponent_start.x
    )
    relative_delta_y = (
        player_end.y - player_start.y - opponent_end.y + opponent_start.y
    )
    relative_delta_length_squared = (
        relative_delta_x * relative_delta_x
        + relative_delta_y * relative_delta_y
    )
    if relative_delta_length_squared <= 1e-12:
        return math.hypot(relative_x, relative_y)
    fraction = min(
        max(
            -(
                relative_x * relative_delta_x
                + relative_y * relative_delta_y
            )
            / relative_delta_length_squared,
            0.0,
        ),
        1.0,
    )
    return math.hypot(
        relative_x + fraction * relative_delta_x,
        relative_y + fraction * relative_delta_y,
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
