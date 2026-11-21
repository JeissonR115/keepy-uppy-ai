from __future__ import annotations

import io
import json
from typing import Any

import pytest

import keepy_ai.cli as cli
from keepy_ai.cli import build_parser, main, run_episode_batch
from keepy_ai.bridge.models import (
    CPUIntent,
    CPUObservation,
    CommandResultMessage,
    EpisodeEvent,
    EpisodeEventMessage,
    ObservationMessage,
)
from keepy_ai.env.environment import CPUTrainingEnv
from keepy_ai.graph.navigation import NavigationGraph


def _observation_payload() -> dict[str, Any]:
    player = {
        "position": {"x": 20, "y": 30},
        "velocity": {"x": 0, "y": 0},
        "on_floor": True,
        "wall_contact": 0,
        "dash_cooldown": 0,
        "dash_available": True,
        "stamina": 110,
    }
    return {
        "tick": 1,
        "bot_player": "player_2",
        "players": {"player_1": player, "player_2": player},
        "balloon": {
            "position": {"x": 40, "y": 50},
            "velocity": {"x": 1, "y": -2},
            "waiting_for_first_touch": False,
        },
        "current_turn": "player_1",
        "score": {
            "points": {"player_1": 2, "player_2": 1},
            "sets": {"player_1": 1, "player_2": 0},
        },
        "level": "classic",
    }


def _geometry_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "level": "classic",
        "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": 320, "y": 180}},
        "safe_bounds": {"position": {"x": 8, "y": 8}, "size": {"x": 304, "y": 164}},
        "spawns": {"player_1": {"x": 72, "y": 144}, "player_2": {"x": 248, "y": 144}},
        "collisions": [
            {
                "source": "fixture-floor",
                "collision_layer": 1,
                "one_way": False,
                "shape": {"type": "rectangle", "size": {"x": 320, "y": 10}},
                "transform": {
                    "origin": {"x": 160, "y": 175},
                    "x_axis": {"x": 1, "y": 0},
                    "y_axis": {"x": 0, "y": 1},
                },
            }
        ],
        "platforms": [],
        "movement_constants": {"MAX_RUN": 130, "GRAVITY": 1100, "JUMP_SPEED": -250},
    }


def _terminal_event(event_type: str = "point") -> EpisodeEvent:
    return EpisodeEvent.from_payload(
        {
            "type": event_type,
            "reason": "spikes",
            "player": "player_2",
            "winner": "player_1",
            "score": {
                "points": {"player_1": 2, "player_2": 1},
                "sets": {"player_1": 1, "player_2": 0},
            },
        }
    )


def _event_payload(event: EpisodeEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "reason": event.reason,
        "player": event.player,
        "winner": event.winner,
        "score": {
            "points": event.score.points,
            "sets": event.score.sets,
        },
    }


class _FakeBridge:
    def __init__(self, faults_per_episode: int = 0) -> None:
        self.messages: list[Any] = []
        self.command_sequence = 0
        self.action_sequence = 0
        self.actions: list[tuple[int, CPUIntent]] = []
        self.resets: list[tuple[int, str]] = []
        self.closed = False
        self.faults_per_episode = faults_per_episode
        self.geometry_calls = 0

    def reset(self, seed: int, level: str) -> int:
        self.resets.append((seed, level))
        self.command_sequence += 1
        self.messages.append(
            CommandResultMessage(
                self.command_sequence,
                {"observation": _observation_payload()},
            )
        )
        return self.command_sequence

    def get_level_geometry(self, level: str | None = None) -> int:
        assert level == "classic"
        self.geometry_calls += 1
        self.command_sequence += 1
        self.messages.append(CommandResultMessage(self.command_sequence, _geometry_payload()))
        return self.command_sequence

    def step(self, n: int = 1) -> int:
        assert n == 1
        self.command_sequence += 1
        self.action_sequence += 1
        event = _terminal_event()
        events = [_event_payload(_terminal_event("fault")) for _ in range(self.faults_per_episode)]
        events.append(_event_payload(event))
        self.messages.extend(
            [
                ObservationMessage(
                    self.action_sequence,
                    CPUObservation.from_payload(_observation_payload()),
                ),
                EpisodeEventMessage(event),
                CommandResultMessage(
                    self.command_sequence,
                    {
                        "episode_ended": True,
                        "observation": _observation_payload(),
                        "events": events,
                    },
                ),
            ]
        )
        return self.command_sequence

    def send_action(self, sequence: int, action: CPUIntent) -> None:
        self.actions.append((sequence, action))

    def receive(self) -> Any:
        return self.messages.pop(0)

    def close_session(self) -> int:
        self.command_sequence += 1
        self.messages.append(CommandResultMessage(self.command_sequence, {}))
        return self.command_sequence

    def close(self) -> None:
        self.closed = True


def test_episode_batch_reports_seed_level_and_terminal_reason() -> None:
    bridge = _FakeBridge()
    output = io.StringIO()

    with CPUTrainingEnv(bridge, owns_client=True) as env:
        summaries = run_episode_batch(
            env, episode_count=2, seed=40, level="classic", output=output
        )

    assert bridge.resets == [(40, "classic"), (41, "classic")]
    assert len(bridge.actions) == 2
    assert all(action != CPUIntent() for _, action in bridge.actions)
    assert bridge.geometry_calls == 1
    assert bridge.closed
    assert [summary["seed"] for summary in summaries] == [40, 41]
    lines = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [line["terminal_reason"] for line in lines] == ["spikes", "spikes"]
    assert all(line["level"] == "classic" for line in lines)
    assert all(line["episode_event"] == "point" for line in lines)
    assert all(line["faults"] == 0 for line in lines)


def test_episode_batch_neutral_mode_keeps_fixed_neutral_actions() -> None:
    bridge = _FakeBridge()
    stdout = io.StringIO()

    with CPUTrainingEnv(bridge, owns_client=True) as env:
        run_episode_batch(
            env,
            episode_count=1,
            seed=7,
            level="classic",
            output=stdout,
            policy_mode="neutral",
        )

    assert bridge.geometry_calls == 0
    assert bridge.actions == [(1, CPUIntent())]


def test_episode_batch_logs_each_policy_decision_as_jsonl() -> None:
    bridge = _FakeBridge()
    stdout = io.StringIO()
    policy_log = io.StringIO()

    with CPUTrainingEnv(bridge, owns_client=True) as env:
        run_episode_batch(
            env,
            episode_count=1,
            seed=7,
            level="classic",
            output=stdout,
            policy_output=policy_log,
        )

    record = json.loads(policy_log.getvalue())
    assert record["phase"] == "opponent_turn"
    assert record["tick"] == 1
    assert record["action"]["horizontal"] != 0


def test_episode_batch_passes_navigation_graph_to_policy(monkeypatch) -> None:
    bridge = _FakeBridge()
    graph = NavigationGraph.from_payload(
        {
            "schema_version": 1,
            "level": "classic",
            "nodes": [{"id": 1, "position": {"x": 20, "y": 30}}],
            "edges": [],
        }
    )
    received_graphs = []
    actual_decide = cli.decide

    def decide_with_graph(observation, geometry, config, graph=None, graph_error=None):
        received_graphs.append(graph)
        return actual_decide(
            observation, geometry, config, graph=graph, graph_error=graph_error
        )

    monkeypatch.setattr(cli, "decide", decide_with_graph)
    with CPUTrainingEnv(bridge, owns_client=True) as env:
        run_episode_batch(
            env,
            episode_count=1,
            seed=7,
            level="classic",
            output=io.StringIO(),
            graph=graph,
        )

    assert received_graphs == [graph]


def test_episode_batch_appends_jsonl_and_counts_faults() -> None:
    bridge = _FakeBridge(faults_per_episode=2)
    stdout = io.StringIO()
    saved = io.StringIO()

    with CPUTrainingEnv(bridge, owns_client=True) as env:
        run_episode_batch(
            env,
            episode_count=1,
            seed=40,
            level="classic",
            output=stdout,
            episode_output=saved,
        )
        run_episode_batch(
            env,
            episode_count=1,
            seed=41,
            level="classic",
            output=stdout,
            episode_output=saved,
        )

    saved_lines = [json.loads(line) for line in saved.getvalue().splitlines()]
    stdout_lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(saved_lines) == len(stdout_lines) == 2
    assert [line["seed"] for line in saved_lines] == [40, 41]
    assert all(line["faults"] == 2 for line in saved_lines)
    assert saved.getvalue() == stdout.getvalue()


def test_run_episode_help_lists_documented_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    help_text = capsys.readouterr().out
    for option in (
        "--level",
        "--seed",
        "--speed",
        "--episode-count",
        "--godot-bin",
        "--project-path",
        "--policy",
        "--policy-log",
        "--policy-preferred-distance",
        "--policy-safety-margin",
        "--policy-opponent-push-slowdown",
        "--graph-dir",
    ):
        assert option in help_text


def test_run_episode_defaults_to_adaptive_policy() -> None:
    args = build_parser().parse_args([])

    assert args.policy == "adaptive"

