import pytest

from keepy_ai.bridge.models import BalloonObservation, Vector2
from keepy_ai.graph.geometry import LevelGeometry
from keepy_ai.policy.config import PolicyConfig
from keepy_ai.policy.trajectory import predict_trajectory


def _rectangle(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    layer: int = 1,
    one_way: bool = False,
) -> dict:
    return {
        "source": "fixture",
        "collision_layer": layer,
        "one_way": one_way,
        "shape": {"type": "rectangle", "size": {"x": width, "y": height}},
        "transform": {
            "origin": {"x": x + width / 2, "y": y + height / 2},
            "x_axis": {"x": 1, "y": 0},
            "y_axis": {"x": 0, "y": 1},
        },
    }


def _geometry(
    level: str = "fixture",
    width: float = 100.0,
    *,
    collisions: list[dict] | None = None,
    platforms: list[dict] | None = None,
) -> LevelGeometry:
    return LevelGeometry.from_payload(
        {
            "schema_version": 1,
            "level": level,
            "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": width, "y": 100}},
            "safe_bounds": {"position": {"x": 1, "y": 1}, "size": {"x": width - 2, "y": 98}},
            "spawns": {"player_1": {"x": 20, "y": 80}, "player_2": {"x": width - 20, "y": 80}},
            "collisions": (
                [_rectangle(0, 95, width, 5)] if collisions is None else collisions
            ),
            "platforms": platforms or [],
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


def test_predicts_rebound_from_tile_using_balloon_swept_radius() -> None:
    geometry = _geometry(
        collisions=[
            _rectangle(30, 50, 40, 2),
            _rectangle(0, 95, 100, 5),
        ]
    )
    samples = predict_trajectory(
        _balloon(x=50, y=30, vx=0, vy=100),
        geometry,
        _config(prediction_horizon=0.5),
    )

    bounced = next(sample for sample in samples if sample.collision_bounced)

    assert 30 < bounced.position.y < 41
    assert bounced.velocity.y < 0


def test_swept_circle_handles_tile_corner_contact() -> None:
    geometry = _geometry(
        collisions=[
            _rectangle(30, 50, 40, 2),
            _rectangle(0, 95, 100, 5),
        ]
    )
    samples = predict_trajectory(
        _balloon(x=25, y=45, vx=50, vy=50),
        geometry,
        _config(prediction_horizon=0.1),
    )

    bounced = next(sample for sample in samples if sample.collision_bounced)

    assert bounced.velocity.x < 0
    assert bounced.velocity.y < 0


def test_predicts_multiple_tile_contacts_in_a_vertical_corridor() -> None:
    geometry = _geometry(
        collisions=[
            _rectangle(0, 20, 100, 2),
            _rectangle(0, 78, 100, 2),
            _rectangle(0, 95, 100, 5),
        ]
    )
    samples = predict_trajectory(
        _balloon(x=50, y=50, vx=0, vy=90),
        geometry,
        _config(prediction_horizon=3.0),
    )

    assert sum(sample.collision_bounced for sample in samples) >= 2
    assert all(28.9 <= sample.position.y <= 69.1 for sample in samples)


def test_ignores_one_way_platforms_outside_the_balloon_collision_mask() -> None:
    geometry = _geometry(
        platforms=[_rectangle(20, 50, 60, 2, layer=4, one_way=True)]
    )
    samples = predict_trajectory(
        _balloon(x=50, y=30, vx=0, vy=20),
        geometry,
        _config(prediction_horizon=0.7),
    )

    assert samples[-1].position.y > 41
    assert not any(sample.collision_bounced for sample in samples)


def test_rejects_missing_or_degenerate_balloon_collision_geometry() -> None:
    balloon = _balloon()
    config = _config()
    missing = _geometry(collisions=[])
    degenerate = LevelGeometry.from_payload(
        {
            "schema_version": 1,
            "level": "fixture",
            "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": 100, "y": 100}},
            "safe_bounds": {
                "position": {"x": 1, "y": 1},
                "size": {"x": 98, "y": 98},
            },
            "spawns": {"player_1": {"x": 20, "y": 80}, "player_2": {"x": 80, "y": 80}},
            "collisions": [
                {
                    "source": "degenerate",
                    "collision_layer": 1,
                    "one_way": False,
                    "shape": {
                        "type": "polygon",
                        "points": [{"x": 10, "y": 10}, {"x": 10, "y": 10}],
                    },
                    "transform": {
                        "origin": {"x": 0, "y": 0},
                        "x_axis": {"x": 1, "y": 0},
                        "y_axis": {"x": 0, "y": 1},
                    },
                }
            ],
            "platforms": [],
            "movement_constants": {},
        }
    )

    with pytest.raises(ValueError, match="unavailable"):
        predict_trajectory(balloon, missing, config)
    with pytest.raises(ValueError, match="degenerate"):
        predict_trajectory(balloon, degenerate, config)


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
