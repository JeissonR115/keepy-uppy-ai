import pytest

from keepy_ai.bridge.models import BalloonObservation, Vector2
from keepy_ai.graph.geometry import LevelGeometry
from keepy_ai.policy.config import PolicyConfig
from keepy_ai.policy.trajectory import predict_trajectory


def _geometry(level: str = "fixture", width: float = 100.0) -> LevelGeometry:
    return LevelGeometry.from_payload(
        {
            "schema_version": 1,
            "level": level,
            "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": width, "y": 100}},
            "safe_bounds": {"position": {"x": 1, "y": 1}, "size": {"x": width - 2, "y": 98}},
            "spawns": {"player_1": {"x": 20, "y": 80}, "player_2": {"x": width - 20, "y": 80}},
            "collisions": [],
            "platforms": [],
            "movement_constants": {"MAX_RUN": 130.0, "JUMP_SPEED": -250.0},
        }
    )


def _balloon(x: float = 50, y: float = 30, vx: float = 90, vy: float = 0) -> BalloonObservation:
    return BalloonObservation(Vector2(x, y), Vector2(vx, vy), False)


def _config(**overrides) -> PolicyConfig:
    values = {
        "gravity": 0.0,
        "air_resistance": 0.0,
        "horizontal_damping": 0.0,
        "rebound_strength": 0.8,
        "physics_hz": 10.0,
        "prediction_horizon": 3.0,
        "max_prediction_steps": 30,
    }
    values.update(overrides)
    return PolicyConfig(**values)


def test_predicts_single_wall_rebound_with_velocity_reflection() -> None:
    samples = predict_trajectory(_balloon(), _geometry(), _config())

    bounced = next(sample for sample in samples if sample.wall_bounced)

    assert 80 < bounced.position.x < 91
    assert bounced.velocity.x < 0
    assert all(9 <= sample.position.x <= 91 for sample in samples)


def test_predicts_multiple_rebounds_in_order() -> None:
    config = _config(prediction_horizon=7.0, max_prediction_steps=70)
    samples = predict_trajectory(_balloon(), _geometry(), config)

    bounce_indices = [index for index, sample in enumerate(samples) if sample.wall_bounced]

    assert len(bounce_indices) >= 2
    assert samples[bounce_indices[0]].velocity.x < 0
    assert samples[bounce_indices[1]].velocity.x > 0
    assert all(9 <= sample.position.x <= 91 for sample in samples)


@pytest.mark.parametrize("level", ["primary-flat", "hazard-arena", "classic", "sky-towers"])
def test_uses_each_level_geometry(level: str) -> None:
    geometry = _geometry(level, width=320 if level == "classic" else 480)
    samples = predict_trajectory(_balloon(x=geometry.bounds.right / 2), geometry, _config())

    assert samples
    assert all(
        geometry.bounds.position.x + 9 <= sample.position.x <= geometry.bounds.right - 9
        for sample in samples
    )


def test_rejects_balloon_that_is_non_finite() -> None:
    geometry = _geometry()
    invalid_balloon = BalloonObservation(Vector2(float("nan"), 30), Vector2(0, 0), False)

    with pytest.raises(ValueError, match="finite"):
        predict_trajectory(invalid_balloon, geometry, _config())


def test_rejects_bounds_narrower_than_balloon_diameter() -> None:
    geometry = _geometry(width=18.0)

    with pytest.raises(ValueError, match="too small"):
        predict_trajectory(_balloon(), geometry, _config())


def test_waiting_balloon_does_not_get_a_predicted_gravity_drop() -> None:
    balloon = BalloonObservation(Vector2(50, 30), Vector2(0, 0), True)

    samples = predict_trajectory(
        balloon,
        _geometry(),
        _config(gravity=137.2),
    )

    assert len(samples) == 1
    assert samples[0].position.y == 30
