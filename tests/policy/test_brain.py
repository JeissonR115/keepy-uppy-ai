from keepy_ai.bridge.models import CPUObservation
from keepy_ai.graph.geometry import LevelGeometry
from keepy_ai.policy.brain import decide
from keepy_ai.policy.config import PolicyConfig
import json
import pytest
import pytest


def _geometry(*, width: float = 320.0, max_run: float = 130.0) -> LevelGeometry:
    return LevelGeometry.from_payload(
        {
            "schema_version": 1,
            "level": "classic",
            "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": width, "y": 180}},
            "safe_bounds": {"position": {"x": 8, "y": 8}, "size": {"x": width - 16, "y": 164}},
            "spawns": {"player_1": {"x": 60, "y": 150}, "player_2": {"x": width - 60, "y": 150}},
            "collisions": [],
            "platforms": [],
            "movement_constants": {"MAX_RUN": max_run, "GRAVITY": 1100.0, "JUMP_SPEED": -250.0},
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
) -> CPUObservation:
    player = {
        "position": {"x": 60.0, "y": 150.0},
        "velocity": {"x": 0.0, "y": 0.0},
        "on_floor": True,
        "wall_contact": 0.0,
        "dash_cooldown": 0.0,
        "dash_available": True,
        "stamina": 110.0,
    }
    bot = {**player, "position": {"x": bot_x, "y": bot_y}}
    return CPUObservation.from_payload(
        {
            "tick": 1,
            "bot_player": "player_2",
            "players": {"player_1": player, "player_2": bot},
            "balloon": {
                "position": {"x": balloon_x, "y": balloon_y},
                "velocity": {"x": balloon_vx, "y": 0.0},
                "waiting_for_first_touch": False,
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
    assert decision.safe_distance
    assert decision.action.horizontal == expected_horizontal
    assert not decision.action.jump
    assert not decision.action.dash
    assert not decision.action.grab


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
