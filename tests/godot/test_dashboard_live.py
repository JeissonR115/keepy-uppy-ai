from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from keepy_ai.bridge.models import CPUIntent
from keepy_ai.env.environment import CPUTrainingEnv
from keepy_ai.godot.launcher import GodotConfig, GodotSimulation
from keepy_ai.graph.workflow import _command_result


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


@pytest.mark.godot_integration
def test_live_dashboard_advances_when_godot_route_does_not_request_remote_action(
) -> None:
    pytest.importorskip("streamlit")
    from keepy_ai.dashboard.app import _advance_live_tick

    godot_bin = os.environ.get("GODOT_BIN")
    project_path = os.environ.get("GODOT_PROJECT_PATH")
    if not godot_bin or not project_path:
        pytest.skip("Set GODOT_BIN and GODOT_PROJECT_PATH for a real live session.")
    project_root = Path(__file__).resolve().parents[2]
    graph_path = project_root / "graphs/classic.json"
    report_path = project_root / "reports/classic.json"
    if not graph_path.is_file() or not report_path.is_file():
        pytest.skip("Generate the classic graph and report before this integration test.")

    config = GodotConfig.resolve(
        {
            "godot_bin": godot_bin,
            "project_path": project_path,
            "level": "classic",
            "seed": 1,
            "mode": "cpu-vs-cpu",
        },
        environ={},
        config_path=Path(project_path) / "missing-keepy-ai.toml",
    )
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    simulation = GodotSimulation(config)
    client = simulation.start()
    try:
        observation_result = _command_result(
            client, client.reset(config.seed, config.level)
        )
        observation = observation_result["observation"]
        _command_result(client, client.load_nav_graph(graph))
        start_node = min(
            graph["nodes"],
            key=lambda node: (
                (
                    node["position"]["x"]
                    - observation["players"]["player_2"]["position"]["x"]
                )
                ** 2
                + (
                    node["position"]["y"]
                    - observation["players"]["player_2"]["position"]["y"]
                )
                ** 2
            ),
        )
        destination = report["route_check"]["destination_node"]
        if destination == start_node["id"]:
            destination = next(
                node["id"]
                for node in graph["nodes"]
                if node["id"] != start_node["id"]
            )
        _command_result(
            client,
            client.set_nav_route(config.level, start_node["id"], destination),
        )

        _observation, action_queued, terminated, _result = _advance_live_tick(client)

        assert action_queued is False
        assert terminated is False
    finally:
        simulation.close()

