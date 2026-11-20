from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from keepy_ai.bridge.models import CPUIntent, CPUObservation, CommandResultMessage
from keepy_ai.env.environment import CPUTrainingEnv
from keepy_ai.godot.launcher import GodotConfig, GodotSimulation
from keepy_ai.graph.geometry import NavigationNode, Point
from keepy_ai.graph.workflow import (
    CURRENT_LEVELS,
    _command_result,
    _exercise_route,
)


@pytest.mark.godot_integration
def test_real_godot_starts_resets_and_closes() -> None:
    godot_bin = os.environ.get("GODOT_BIN")
    project_path = os.environ.get("GODOT_PROJECT_PATH")
    if not godot_bin or not project_path:
        pytest.skip("Set GODOT_BIN and GODOT_PROJECT_PATH to run this integration test.")

    config = GodotConfig.resolve(
        {
            "godot_bin": godot_bin,
            "project_path": project_path,
            "level": "classic",
            "speed": 1,
            "seed": 123,
            "mode": "cpu-vs-cpu",
        },
        environ={},
        config_path=Path(project_path) / "missing-keepy-ai.toml",
    )
    with GodotSimulation(config) as simulation:
        assert simulation.client is not None
        sequence = simulation.client.reset(seed=123, level="classic")
        while True:
            message = simulation.client.receive()
            if (
                isinstance(message, CommandResultMessage)
                and message.sequence == sequence
            ):
                assert message.result["observation"]["level"] == "classic"
                break
    assert simulation.process is None
    assert simulation.client is None


@pytest.mark.godot_integration
def test_real_godot_graphs_routes_and_seeded_replay() -> None:
    godot_bin = os.environ.get("GODOT_BIN")
    project_path = os.environ.get("GODOT_PROJECT_PATH")
    if not godot_bin or not project_path:
        pytest.skip("Set GODOT_BIN and GODOT_PROJECT_PATH to run this integration test.")

    config = GodotConfig.resolve(
        {
            "godot_bin": godot_bin,
            "project_path": project_path,
            "level": "classic",
            "speed": 8,
            "seed": 123,
            "mode": "cpu-vs-cpu",
        },
        environ={},
        config_path=Path(project_path) / "missing-keepy-ai.toml",
    )
    project_root = Path(__file__).resolve().parents[2]
    graph_directory = project_root / "graphs"
    graph_paths = {
        level: graph_directory / f"{level}.json" for level in CURRENT_LEVELS
    }
    if not all(path.is_file() for path in graph_paths.values()):
        pytest.skip("Run `uv run generate-graph --all-levels` before this test.")

    simulation = GodotSimulation(config)
    with simulation:
        client = simulation.client
        assert client is not None
        route_results = []
        for level_index, level in enumerate(CURRENT_LEVELS):
            reset_result = _command_result(
                client, client.reset(123 + level_index, level)
            )
            observation = CPUObservation.from_payload(
                reset_result.get("observation")
            )
            graph = json.loads(graph_paths[level].read_text(encoding="utf-8"))
            _command_result(client, client.load_nav_graph(graph))
            nodes = [
                NavigationNode(
                    node["id"],
                    Point(node["position"]["x"], node["position"]["y"]),
                )
                for node in graph["nodes"]
            ]
            route_results.append(
                _exercise_route(client, level, nodes, graph, observation, 900)
            )
        assert all(result["passed"] for result in route_results)

        with CPUTrainingEnv(client, owns_client=False) as env:
            first_run = _run_seeded_rollouts(env)
            replay = _run_seeded_rollouts(env)
        assert first_run == replay
    assert simulation.process is None
    assert simulation.client is None


def _run_seeded_rollouts(env: CPUTrainingEnv) -> list[dict[str, object]]:
    results = []
    for seed in (500, 501):
        observation, _info = env.reset(seed=seed, level="classic")
        terminal_reason = None
        terminal_event = None
        terminated = False
        steps = 0
        for steps in range(1, 121):
            observation, _reward, terminated, _truncated, info = env.step(CPUIntent())
            if terminated:
                terminal_reason = info.get("reason")
                event = info.get("episode_event")
                terminal_event = event.type if event is not None else None
                break
        results.append(
            {
                "seed": seed,
                "level": "classic",
                "steps": steps,
                "terminated": terminated,
                "truncated": not terminated,
                "terminal_reason": terminal_reason,
                "terminal_event": terminal_event,
                "points": observation.score.points,
                "sets": observation.score.sets,
                "player_2": {
                    "x": observation.players["player_2"].position.x,
                    "y": observation.players["player_2"].position.y,
                },
                "balloon": {
                    "x": observation.balloon.position.x,
                    "y": observation.balloon.position.y,
                },
            }
        )
    return results
