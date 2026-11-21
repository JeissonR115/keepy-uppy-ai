import math

import pytest

from keepy_ai.policy.config import PolicyConfig, load_policy_config


def test_default_contact_band_has_separation_and_reachability() -> None:
    config = PolicyConfig()
    assert config.minimum_safe_distance == 27.0
    assert config.preferred_distance is None
    assert config.resolve_preferred_distance(
        {"DASH_SPEED": 300.0, "DASH_TIME": 0.2}
    ) == (60.0, "dash_range")


def test_missing_dash_constants_use_safe_documented_fallback() -> None:
    config = PolicyConfig()

    assert config.resolve_preferred_distance({}) == (48.0, "fallback")


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"rebound_strength": -0.1}, "between 0 and 1"),
        ({"rebound_strength": 1.1}, "between 0 and 1"),
        ({"physics_hz": 0}, "finite and positive"),
        ({"gravity": math.inf}, "finite and non-negative"),
        ({"preferred_distance": 20.0}, "minimum safe distance"),
        ({"opponent_push_slowdown": 0.9}, "at least 1"),
        ({"opponent_push_slowdown": math.inf}, "at least 1"),
        ({"max_prediction_steps": True}, "positive integer"),
    ],
)
def test_rejects_invalid_policy_configuration(values: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PolicyConfig(**values)


def test_loads_toml_then_cli_overrides(tmp_path) -> None:
    config_file = tmp_path / "keepy-ai.toml"
    config_file.write_text(
        "[policy]\npreferred_distance = 52.0\nrebound_strength = 0.4\n",
        encoding="utf-8",
    )

    toml_config = load_policy_config(config_file)
    config = load_policy_config(config_file, {"preferred_distance": 60.0})

    assert toml_config.preferred_distance == 52.0
    assert config.preferred_distance == 60.0
    assert config.rebound_strength == 0.4


def test_configured_preferred_distance_overrides_dash_range() -> None:
    config = PolicyConfig(preferred_distance=72.0)

    assert config.resolve_preferred_distance(
        {"DASH_SPEED": 300.0, "DASH_TIME": 0.2}
    ) == (72.0, "override")


def test_rejects_unknown_setting(tmp_path) -> None:
    config_file = tmp_path / "keepy-ai.toml"
    config_file.write_text("[policy]\nunknown = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown policy setting"):
        load_policy_config(config_file)
