from __future__ import annotations

import os
from pathlib import Path

import pytest

from keepy_ai.bridge.models import CPUIntent
from keepy_ai.env.environment import CPUTrainingEnv
from keepy_ai.godot.launcher import GodotConfig, GodotSimulation


@pytest.mark.godot_integration
def test_live_dashboard_environment_advances_and_closes_godot() -> None:
    godot_bin = os.environ.get("GODOT_BIN")
    project_path = os.environ.get("GODOT_PROJECT_PATH")
    if not godot_bin or not project_path:
        pytest.skip("Set GODOT_BIN and GODOT_PROJECT_PATH for a real live session.")
    config = GodotConfig.resolve(
        {
            "godot_bin": godot_bin,
            "project_path": project_path,
            "level": "classic",
            "seed": 31,
            "mode": "cpu-vs-cpu",
        },
        environ={},
        config_path=Path(project_path) / "missing-keepy-ai.toml",
    )
    simulation = GodotSimulation(config)
    env = CPUTrainingEnv(simulation=simulation)
    initial, _info = env.reset(seed=config.seed, level=config.level)
    observation, _reward, terminated, _truncated, info = env.step(CPUIntent())
    assert observation.tick >= initial.tick
    assert info["action_queued"] is True
    assert terminated is False
    env.close()
    assert simulation.process is None
    assert simulation.client is None

