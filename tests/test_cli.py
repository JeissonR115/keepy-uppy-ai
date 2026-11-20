from __future__ import annotations

import io
import json
from typing import Any

import pytest

from keepy_ai.cli import main, run_episode_batch
from keepy_ai.bridge.models import (
    CPUIntent,
    CPUObservation,
    CommandResultMessage,
    EpisodeEvent,
    EpisodeEventMessage,
    ObservationMessage,
)
from keepy_ai.env.environment import CPUTrainingEnv


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


def _terminal_event() -> EpisodeEvent:
    return EpisodeEvent.from_payload(
        {
            "type": "point",
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
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.command_sequence = 0
        self.action_sequence = 0
        self.actions: list[tuple[int, CPUIntent]] = []
        self.resets: list[tuple[int, str]] = []
        self.closed = False

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

    def step(self, n: int = 1) -> int:
        assert n == 1
        self.command_sequence += 1
        self.action_sequence += 1
        event = _terminal_event()
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
                        "events": [_event_payload(event)],
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
    assert all(action == CPUIntent() for _, action in bridge.actions)
    assert bridge.closed
    assert [summary["seed"] for summary in summaries] == [40, 41]
    lines = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [line["terminal_reason"] for line in lines] == ["spikes", "spikes"]
    assert all(line["level"] == "classic" for line in lines)
    assert all(line["episode_event"] == "point" for line in lines)


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
    ):
        assert option in help_text

