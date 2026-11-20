from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from keepy_ai.bridge.errors import CPUBridgeServerError
from keepy_ai.bridge.models import (
    CPUObservation,
    CommandResultMessage,
    EpisodeEvent,
    EpisodeEventMessage,
    ObservationMessage,
)
from keepy_ai.env.environment import CPUTrainingEnv


def _observation_payload(tick: int, level: str = "classic") -> dict[str, Any]:
    player = {
        "position": {"x": 20 + tick, "y": 30},
        "velocity": {"x": 0, "y": 0},
        "on_floor": True,
        "wall_contact": 0,
        "dash_cooldown": 0,
        "dash_available": True,
        "stamina": 110,
    }
    return {
        "tick": tick,
        "bot_player": "player_2",
        "players": {"player_1": player, "player_2": player},
        "balloon": {
            "position": {"x": 40, "y": 50},
            "velocity": {"x": 1, "y": -2},
            "waiting_for_first_touch": False,
        },
        "current_turn": "player_1",
        "score": {
            "points": {"player_1": 0, "player_2": 0},
            "sets": {"player_1": 0, "player_2": 0},
        },
        "level": level,
    }


def _observation(tick: int, level: str = "classic") -> CPUObservation:
    return CPUObservation.from_payload(_observation_payload(tick, level))


def _event(
    event_type: str, reason: str | None = None
) -> EpisodeEvent:
    return EpisodeEvent.from_payload(
        {
            "type": event_type,
            "reason": reason,
            "player": "player_2",
            "winner": "player_1" if event_type != "downward_fault_replay" else "",
            "score": {
                "points": {"player_1": 1, "player_2": 0},
                "sets": {"player_1": 0, "player_2": 0},
            },
        }
    )


@dataclass
class _StepScenario:
    observation_sequence: int | None
    observation: CPUObservation
    result: dict[str, Any]
    events: list[EpisodeEvent]


class _FakeClient:
    def __init__(self, scenarios: list[_StepScenario]) -> None:
        self.scenarios = scenarios
        self.messages: list[Any] = []
        self.command_sequence = 0
        self.sent_actions: list[tuple[int, Any]] = []
        self.reset_arguments: tuple[int, str] | None = None
        self.step_calls = 0
        self.closed = False
        self.reset_error: Exception | None = None

    def reset(self, seed: int, level: str) -> int:
        self.reset_arguments = (seed, level)
        if self.reset_error is not None:
            raise self.reset_error
        self.command_sequence += 1
        self.messages.append(
            CommandResultMessage(
                self.command_sequence,
                {"observation": _observation_payload(0, level)},
            )
        )
        return self.command_sequence

    def step(self, n: int = 1) -> int:
        assert n == 1
        self.step_calls += 1
        self.command_sequence += 1
        scenario = self.scenarios.pop(0)
        if scenario.observation_sequence is not None:
            self.messages.append(
                ObservationMessage(
                    scenario.observation_sequence, scenario.observation
                )
            )
        self.messages.extend(EpisodeEventMessage(event) for event in scenario.events)
        self.messages.append(
            CommandResultMessage(self.command_sequence, scenario.result)
        )
        return self.command_sequence

    def send_action(self, sequence: int, action: Any) -> None:
        self.sent_actions.append((sequence, action))

    def receive(self) -> Any:
        return self.messages.pop(0)

    def close_session(self) -> int:
        self.command_sequence += 1
        self.messages.append(CommandResultMessage(self.command_sequence, {}))
        return self.command_sequence

    def close(self) -> None:
        self.closed = True


def _scenario(
    observation_sequence: int | None,
    *,
    tick: int,
    ended: bool = False,
    events: list[EpisodeEvent] | None = None,
    result_events: list[EpisodeEvent] | None = None,
) -> _StepScenario:
    step_events = events or []
    result_payload = {
        "episode_ended": ended,
        "observation": _observation_payload(tick),
        "events": [_event_payload(event) for event in (result_events or [])],
    }
    return _StepScenario(observation_sequence, _observation(tick), result_payload, step_events)


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


def test_reset_and_first_step_queue_action_for_next_tick() -> None:
    client = _FakeClient([_scenario(17, tick=1)])
    env = CPUTrainingEnv(client)

    observation, reset_info = env.reset(seed=42, level="classic")
    assert observation.tick == 0
    assert reset_info == {"seed": 42, "level": "classic"}
    assert client.reset_arguments == (42, "classic")

    result = env.step(
        {
            "horizontal": -1,
            "jump": True,
            "dash": False,
            "dash_direction": {"x": 0, "y": 0},
            "down": True,
            "grab": False,
        }
    )
    next_observation, reward, terminated, truncated, info = result
    assert next_observation.tick == 1
    assert (reward, terminated, truncated) == (0.0, False, False)
    assert info["action_sequence"] == 17
    assert info["action_queued"] is True
    assert info["action_applied_to_returned_state"] is False
    assert client.sent_actions[0][0] == 17
    assert client.sent_actions[0][1].jump is True


def test_step_preserves_replay_and_terminal_events() -> None:
    replay = _event("downward_fault_replay", "downward_hit")
    terminal = _event("point", "spikes")
    client = _FakeClient(
        [
            _scenario(20, tick=1, events=[replay]),
            _scenario(
                21,
                tick=2,
                ended=True,
                events=[terminal],
                result_events=[terminal],
            ),
        ]
    )
    env = CPUTrainingEnv(client)
    env.reset(seed=8, level="classic")

    _, _, terminated, _, replay_info = env.step(
        {
            "horizontal": 0,
            "jump": False,
            "dash": False,
            "dash_direction": {"x": 0, "y": 0},
            "down": False,
            "grab": False,
        }
    )
    assert not terminated
    assert replay_info["events"] == [replay]
    assert replay_info["events"][0].type == "downward_fault_replay"

    _, _, terminated, truncated, terminal_info = env.step(
        {
            "horizontal": 0,
            "jump": False,
            "dash": False,
            "dash_direction": {"x": 0, "y": 0},
            "down": False,
            "grab": False,
        }
    )
    assert terminated
    assert not truncated
    assert terminal_info["episode_event"] == terminal
    assert terminal_info["reason"] == "spikes"
    with pytest.raises(RuntimeError, match="Reset"):
        env.step(
            {
                "horizontal": 0,
                "jump": False,
                "dash": False,
                "dash_direction": {"x": 0, "y": 0},
                "down": False,
                "grab": False,
            }
        )


def test_invalid_action_is_rejected_before_advancing_bridge() -> None:
    client = _FakeClient([_scenario(3, tick=1)])
    env = CPUTrainingEnv(client)
    env.reset(seed=1, level="classic")

    with pytest.raises(ValueError):
        env.step({"horizontal": 2})

    assert client.step_calls == 0
    assert client.sent_actions == []


def test_reset_surfaces_bridge_error_without_fabricating_observation() -> None:
    client = _FakeClient([])
    client.reset_error = CPUBridgeServerError("unknown_level", "Unsupported level.")
    env = CPUTrainingEnv(client)

    with pytest.raises(CPUBridgeServerError, match="unknown_level"):
        env.reset(seed=1, level="classic")

    with pytest.raises(RuntimeError, match="Reset"):
        env.step(
            {
                "horizontal": 0,
                "jump": False,
                "dash": False,
                "dash_direction": {"x": 0, "y": 0},
                "down": False,
                "grab": False,
            }
        )


def test_close_releases_an_owned_bridge_client() -> None:
    client = _FakeClient([])
    env = CPUTrainingEnv(client, owns_client=True)
    env.reset(seed=1, level="classic")

    env.close()

    assert client.closed
    with pytest.raises(RuntimeError, match="closed"):
        env.reset(seed=1, level="classic")
