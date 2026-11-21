from keepy_ai.bridge.models import CPUIntent, CPUObservation
from keepy_ai.graph.geometry import LevelGeometry, Point
from keepy_ai.graph.navigation import NavigationGraph
from keepy_ai.policy.brain import decide
from keepy_ai.policy.config import PolicyConfig
import json
import pytest
import pytest


def _geometry(
    *,
    width: float = 320.0,
    max_run: float = 130.0,
    dash_constants: bool = True,
    collision_geometry: bool = True,
) -> LevelGeometry:
    movement_constants = {
        "MAX_RUN": max_run,
        "GRAVITY": 1100.0,
        "JUMP_SPEED": -250.0,
    }
    if dash_constants:
        movement_constants.update({"DASH_SPEED": 300.0, "DASH_TIME": 0.2})
    return LevelGeometry.from_payload(
        {
            "schema_version": 1,
            "level": "classic",
            "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": width, "y": 180}},
            "safe_bounds": {"position": {"x": 8, "y": 8}, "size": {"x": width - 16, "y": 164}},
            "spawns": {"player_1": {"x": 60, "y": 150}, "player_2": {"x": width - 60, "y": 150}},
            "collisions": (
                [
                    {
                        "source": "fixture-floor",
                        "collision_layer": 1,
                        "one_way": False,
                        "shape": {
                            "type": "rectangle",
                            "size": {"x": width, "y": 10},
                        },
                        "transform": {
                            "origin": {"x": width / 2, "y": 175},
                            "x_axis": {"x": 1, "y": 0},
                            "y_axis": {"x": 0, "y": 1},
                        },
                    },
                ]
                if collision_geometry
                else []
            ),
            "platforms": [],
            "movement_constants": movement_constants,
        }
    )


def _observation(
    *,
    bot_x: float = 50,
    bot_y: float = 40,
    balloon_x: float = 70,
    balloon_y: float = 30,
    balloon_vx: float = 0,
    turn: str = "player_2",
    opponent_x: float = 60,
    opponent_y: float = 150,
    opponent_vx: float = 0,
    opponent_vy: float = 0,
    bot_on_floor: bool = True,
    waiting_for_first_touch: bool = False,
) -> CPUObservation:
    player = {
        "position": {"x": opponent_x, "y": opponent_y},
        "velocity": {"x": opponent_vx, "y": opponent_vy},
        "on_floor": True,
        "wall_contact": 0.0,
        "dash_cooldown": 0.0,
        "dash_available": True,
        "stamina": 110.0,
    }
    bot = {
        **player,
        "position": {"x": bot_x, "y": bot_y},
        "on_floor": bot_on_floor,
    }
    return CPUObservation.from_payload(
        {
            "tick": 1,
            "bot_player": "player_2",
            "players": {"player_1": player, "player_2": bot},
            "balloon": {
                "position": {"x": balloon_x, "y": balloon_y},
                "velocity": {"x": balloon_vx, "y": 0.0},
                "waiting_for_first_touch": waiting_for_first_touch,
            },
            "current_turn": turn,
            "score": {"points": {"player_1": 0, "player_2": 0}, "sets": {"player_1": 0, "player_2": 0}},
            "level": "classic",
        }
    )


def _config(**overrides) -> PolicyConfig:
    values = {"gravity": 0, "air_resistance": 0, "horizontal_damping": 0, "prediction_horizon": 2.0}
    values.update(overrides)
    return PolicyConfig(**values)


def _navigation_graph(level: str = "classic") -> NavigationGraph:
    return NavigationGraph.from_payload(
        {
            "schema_version": 1,
            "level": level,
            "nodes": [
                {"id": 1, "position": {"x": 50, "y": 40}},
                {"id": 2, "position": {"x": 80, "y": 40}},
            ],
            "edges": [
                {
                    "from": 1,
                    "to": 2,
                    "action": "WALK",
                    "cost": 1.0,
                    "bidirectional": True,
                }
            ],
        }
    )


def _opponent_obstacle_graph(detour_cost: float = 1.2) -> NavigationGraph:
    return NavigationGraph.from_payload(
        {
            "schema_version": 1,
            "level": "classic",
            "nodes": [
                {"id": 1, "position": {"x": 50, "y": 40}},
                {"id": 2, "position": {"x": 70, "y": 40}},
                {"id": 3, "position": {"x": 90, "y": 40}},
                {"id": 4, "position": {"x": 50, "y": 60}},
                {"id": 5, "position": {"x": 70, "y": 60}},
                {"id": 6, "position": {"x": 90, "y": 60}},
            ],
            "edges": [
                {"from": 1, "to": 2, "action": "WALK", "cost": 1.0},
                {"from": 2, "to": 3, "action": "WALK", "cost": 1.0},
                {"from": 1, "to": 4, "action": "JUMP", "cost": detour_cost},
                {"from": 4, "to": 5, "action": "WALK", "cost": detour_cost},
                {"from": 5, "to": 6, "action": "WALK", "cost": detour_cost},
                {"from": 6, "to": 3, "action": "DROP", "cost": detour_cost},
            ],
        }
    )


def _opening_touch_graph() -> NavigationGraph:
    return NavigationGraph.from_payload(
        {
            "schema_version": 1,
            "level": "classic",
            "nodes": [
                {"id": 1, "position": {"x": 248, "y": 144}},
                {"id": 2, "position": {"x": 240, "y": 104}},
            ],
            "edges": [
                {"from": 1, "to": 2, "action": "DASH", "cost": 0.9},
            ],
        }
    )


def test_own_turn_targets_earliest_reachable_path_sample() -> None:
    decision = decide(
        _observation(bot_x=50, bot_y=40, balloon_x=70, balloon_y=30, balloon_vx=20),
        _geometry(),
        _config(),
    )

    assert decision.phase == "own_turn"
    assert decision.prediction_status == "intercept_found"
    assert decision.target is not None
    assert decision.target.x == pytest.approx(70.3333333333)
    assert decision.predicted_time > 0


@pytest.mark.parametrize(
    ("bot_on_floor", "expected_jump"),
    [(True, True), (False, False)],
)
def test_waiting_for_first_touch_jumps_toward_balloon_above_player(
    bot_on_floor: bool, expected_jump: bool
) -> None:
    decision = decide(
        _observation(
            bot_x=50,
            bot_y=150,
            balloon_x=70,
            balloon_y=114,
            waiting_for_first_touch=True,
            bot_on_floor=bot_on_floor,
        ),
        _geometry(),
        _config(),
    )

    assert decision.prediction_status == "waiting_for_first_touch"
    assert decision.action.horizontal == 1
    assert decision.action.jump is expected_jump


def test_waiting_for_first_touch_uses_graph_dash_to_reach_balloon() -> None:
    decision = decide(
        _observation(
            bot_x=248,
            bot_y=144,
            balloon_x=248,
            balloon_y=114,
            waiting_for_first_touch=True,
        ),
        _geometry(),
        _config(),
        graph=_opening_touch_graph(),
    )

    assert decision.route_status == "graph_route"
    assert decision.route_node_ids == (1, 2)
    assert decision.route_waypoint == Point(240, 104)
    assert decision.action.dash
    assert decision.action.dash_direction.x < 0
    assert decision.action.dash_direction.y < 0


def test_policy_uses_reachable_graph_route_to_intercept() -> None:
    decision = decide(
        _observation(bot_x=50, bot_y=40, balloon_x=70, balloon_y=30, balloon_vx=20),
        _geometry(),
        _config(),
        graph=_navigation_graph(),
    )

    assert decision.route_status == "graph_route"
    assert decision.route_node_ids == (1, 2)
    assert decision.route_waypoint is not None
    assert decision.route_waypoint.x == 80
    assert decision.action.horizontal == 1


def test_policy_skips_intercepts_without_a_nearby_reachable_graph_node() -> None:
    graph = NavigationGraph.from_payload(
        {
            "schema_version": 1,
            "level": "classic",
            "nodes": [
                {"id": 1, "position": {"x": 50, "y": 40}},
                {"id": 2, "position": {"x": 120, "y": 40}},
            ],
            "edges": [
                {
                    "from": 1,
                    "to": 2,
                    "action": "WALK",
                    "cost": 1.0,
                    "bidirectional": True,
                }
            ],
        }
    )

    decision = decide(
        _observation(bot_x=50, bot_y=40, balloon_x=70, balloon_y=30, balloon_vx=20),
        _geometry(),
        _config(),
        graph=graph,
    )

    assert decision.route_status == "graph_route"
    assert decision.target is not None
    assert decision.target.x > 70.3333333333


@pytest.mark.parametrize(
    ("opponent_y", "detour_cost", "expected_route"),
    [
        (40, 1.2, (1, 4, 5, 6, 3)),
        (100, 1.2, (1, 2, 3)),
        (40, 3.0, (1, 2, 3)),
    ],
)
def test_opponent_occupancy_cost_selects_detour_or_push_through(
    opponent_y: float, detour_cost: float, expected_route: tuple[int, ...]
) -> None:
    decision = decide(
        _observation(
            bot_x=50,
            bot_y=40,
            balloon_x=90,
            balloon_y=40,
            opponent_x=70,
            opponent_y=opponent_y,
        ),
        _geometry(),
        _config(),
        graph=_opponent_obstacle_graph(detour_cost),
    )

    assert decision.route_node_ids == expected_route
    assert decision.route_status == "graph_route"


def test_route_is_deterministic_and_recomputed_for_opponent_motion() -> None:
    geometry = _geometry()
    graph = _opponent_obstacle_graph()
    approaching = _observation(
        bot_x=50,
        bot_y=40,
        balloon_x=90,
        balloon_y=40,
        opponent_x=70,
        opponent_y=100,
        opponent_vy=-390,
    )
    first = decide(approaching, geometry, _config(), graph=graph)
    repeated = decide(approaching, geometry, _config(), graph=graph)
    moved_away = decide(
        _observation(
            bot_x=50,
            bot_y=40,
            balloon_x=90,
            balloon_y=40,
            opponent_x=70,
            opponent_y=100,
        ),
        geometry,
        _config(),
        graph=graph,
    )

    assert first.route_node_ids == (1, 4, 5, 6, 3)
    assert repeated.to_payload() == first.to_payload()
    assert moved_away.route_node_ids == (1, 2, 3)
    assert first.to_payload()["route_status"] == "graph_route"


def test_unavailable_or_mismatched_graph_uses_reported_direct_recovery() -> None:
    decision = decide(
        _observation(bot_x=50, bot_y=40, balloon_x=180, balloon_y=40, turn="player_1"),
        _geometry(),
        _config(),
        graph=_navigation_graph("sky-towers"),
    )

    assert decision.route_status == "graph_unavailable"
    assert "does not match" in decision.reason


def test_own_turn_can_select_interception_after_wall_bounce() -> None:
    decision = decide(
        _observation(bot_x=200, bot_y=40, balloon_x=280, balloon_y=30, balloon_vx=100),
        _geometry(),
        _config(),
    )

    assert decision.prediction_status == "intercept_found"
    assert decision.target is not None
    assert decision.predicted_time > 0.45
    assert decision.target.x < 311


def test_own_turn_falls_back_when_no_intercept_is_reachable() -> None:
    decision = decide(
        _observation(bot_x=20, bot_y=40, balloon_x=250, balloon_y=30),
        _geometry(max_run=1.0),
        _config(),
    )

    assert decision.prediction_status == "no_reachable_intercept"
    assert decision.action.horizontal == 1.0
    assert decision.reason


@pytest.mark.parametrize(
    ("bot_x", "balloon_x", "expected_horizontal"),
    [(50, 180, 1.0), (270, 140, -1.0)],
)
def test_opponent_turn_moves_toward_preferred_safe_position(
    bot_x: float, balloon_x: float, expected_horizontal: float
) -> None:
    decision = decide(
        _observation(bot_x=bot_x, bot_y=40, balloon_x=balloon_x, balloon_y=40, turn="player_1"),
        _geometry(),
        _config(),
    )

    assert decision.phase == "opponent_turn"
    assert decision.prediction_status == "defensive_position"
    assert decision.preferred_distance == 60.0
    assert decision.preferred_distance_source == "dash_range"
    assert decision.safe_distance
    assert decision.action.horizontal == expected_horizontal
    assert not decision.action.jump
    assert not decision.action.dash
    assert not decision.action.grab


def test_missing_dash_constants_are_reported_with_safe_fallback() -> None:
    decision = decide(
        _observation(bot_x=50, bot_y=40, balloon_x=180, balloon_y=40, turn="player_1"),
        _geometry(dash_constants=False),
        _config(),
    )

    assert decision.preferred_distance == 48.0
    assert decision.preferred_distance_source == "fallback"
    assert "fallback distance" in decision.reason


def test_missing_collision_geometry_returns_explicit_safe_recovery() -> None:
    decision = decide(
        _observation(bot_x=50, bot_y=40, balloon_x=180, balloon_y=40, turn="player_1"),
        _geometry(collision_geometry=False),
        _config(),
    )

    assert decision.prediction_status == "invalid_geometry"
    assert decision.target is None
    assert decision.action == CPUIntent()
    assert decision.reason == "Balloon collision geometry is unavailable."


@pytest.mark.parametrize(
    ("bot_x", "balloon_x", "expected_horizontal"),
    [(100, 110, -1.0), (220, 210, 1.0)],
)
def test_opponent_turn_evades_when_balloon_is_inside_safe_distance(
    bot_x: float, balloon_x: float, expected_horizontal: float
) -> None:
    decision = decide(
        _observation(bot_x=bot_x, bot_y=40, balloon_x=balloon_x, balloon_y=40, turn="player_1"),
        _geometry(),
        _config(),
    )

    assert decision.prediction_status == "evasive"
    assert decision.action.horizontal == expected_horizontal
    assert not decision.action.jump
    assert not decision.action.dash
    assert not decision.action.grab


def test_evasion_stays_on_current_side_instead_of_crossing_through_balloon() -> None:
    decision = decide(
        _observation(bot_x=100, bot_y=40, balloon_x=110, balloon_y=40, turn="player_1"),
        _geometry(),
        _config(),
    )

    assert decision.prediction_status == "evasive"
    assert decision.action.horizontal == -1.0
    assert decision.target is not None
    assert decision.target.x < 100


def test_decision_record_is_json_serializable_and_includes_configuration() -> None:
    decision = decide(_observation(turn="player_1"), _geometry(), _config())

    payload = decision.to_payload()
    encoded = json.dumps(payload)

    assert payload["phase"] == "opponent_turn"
    assert payload["configuration"]["rebound_strength"] == 0.28
    assert "minimum_safe_distance" in payload
    assert json.loads(encoded)["action"]["grab"] is False


def test_undetermined_turn_returns_non_contact_ready_action() -> None:
    decision = decide(_observation(turn=""), _geometry(), _config())

    assert decision.phase == "undetermined"
    assert decision.prediction_status == "not_used"
    assert not decision.action.jump
    assert not decision.action.dash
    assert not decision.action.grab
