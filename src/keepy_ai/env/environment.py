from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping, Protocol

from keepy_ai.bridge.errors import CPUBridgeProtocolError
from keepy_ai.bridge.models import (
    BridgeMessage,
    CPUIntent,
    CPUObservation,
    CommandResultMessage,
    EpisodeEvent,
    EpisodeEventMessage,
    ObservationMessage,
    Vector2,
)
from keepy_ai.godot.launcher import GodotSimulation
from keepy_ai.graph.geometry import LevelGeometry

_LEVELS = {"primary-flat", "hazard-arena", "classic", "sky-towers"}
_ACTION_FIELDS = {
    "horizontal",
    "jump",
    "dash",
    "dash_direction",
    "down",
    "grab",
}


class _BridgeClient(Protocol):
    def reset(self, seed: int, level: str) -> int: ...

    def get_level_geometry(self, level: str | None = None) -> int: ...

    def step(self, n: int = 1) -> int: ...

    def send_action(self, sequence: int, action: CPUIntent) -> None: ...

    def receive(self) -> BridgeMessage: ...

    def close_session(self) -> int: ...

    def close(self) -> None: ...


class CPUTrainingEnv:
    """Episode API over the bridge; action effects begin on the next physics tick."""

    def __init__(
        self,
        client: _BridgeClient | None = None,
        *,
        simulation: GodotSimulation | None = None,
        owns_client: bool = False,
    ) -> None:
        if client is not None and simulation is not None:
            raise ValueError("Provide either a bridge client or a Godot simulation, not both.")
        if client is None and simulation is None:
            raise ValueError("A bridge client or a Godot simulation is required.")
        if simulation is not None and simulation.client is not None:
            client = simulation.client
        self._client = client
        self._simulation = simulation
        self._owns_simulation = simulation is not None
        self._owns_client = owns_client
        self._closed = False
        self._done = True
        self._seed: int | None = None
        self._level: str | None = None

    def __enter__(self) -> CPUTrainingEnv:
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def reset(self, seed: int, level: str) -> tuple[CPUObservation, dict[str, Any]]:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer.")
        if not isinstance(level, str) or level not in _LEVELS:
            raise ValueError(f"unsupported level: {level!r}")

        self._done = True
        self._seed = None
        self._level = None
        sequence = self._bridge().reset(seed=seed, level=level)
        while True:
            message = self._bridge().receive()
            if isinstance(message, CommandResultMessage):
                if message.sequence != sequence:
                    raise CPUBridgeProtocolError(
                        "Reset result sequence does not match the request."
                    )
                observation = CPUObservation.from_payload(
                    message.result.get("observation")
                )
                break
            if isinstance(message, ObservationMessage):
                raise CPUBridgeProtocolError(
                    "Reset unexpectedly requested an action before its result."
                )
            if isinstance(message, EpisodeEventMessage):
                raise CPUBridgeProtocolError(
                    "Reset unexpectedly emitted an episode event."
                )

        self._seed = seed
        self._level = level
        self._done = False
        return observation, {"seed": seed, "level": level}

    def step(
        self,
        action: CPUIntent | Mapping[str, Any] | None = None,
        *,
        action_selector: Callable[
            [CPUObservation], tuple[CPUIntent | Mapping[str, Any], Mapping[str, Any]]
        ]
        | None = None,
    ) -> tuple[CPUObservation, float, bool, bool, dict[str, Any]]:
        if self._closed:
            raise RuntimeError("The environment is closed.")
        if self._done or self._level is None:
            raise RuntimeError("Reset the environment before stepping it.")
        if action_selector is not None and action is not None:
            raise ValueError("Provide either action or action_selector, not both.")
        if action_selector is None and action is None:
            raise ValueError("An action or action_selector is required.")
        intent = _coerce_action(action) if action_selector is None else None

        command_sequence = self._bridge().step(1)
        action_sequence: int | None = None
        policy_decision: Mapping[str, Any] | None = None
        asynchronous_events: list[EpisodeEvent] = []
        while True:
            message = self._bridge().receive()
            if isinstance(message, ObservationMessage):
                if action_sequence is not None:
                    raise CPUBridgeProtocolError(
                        "A one-tick step emitted more than one action observation."
                    )
                if action_selector is not None:
                    selected_action, policy_decision = action_selector(message.observation)
                    if not isinstance(policy_decision, Mapping):
                        raise ValueError("action_selector decision record must be a mapping.")
                    intent = _coerce_action(selected_action)
                if intent is None:
                    raise RuntimeError("No action was selected for the bridge observation.")
                self._bridge().send_action(message.sequence, intent)
                action_sequence = message.sequence
            elif isinstance(message, EpisodeEventMessage):
                asynchronous_events.append(message.event)
            elif isinstance(message, CommandResultMessage):
                if message.sequence != command_sequence:
                    raise CPUBridgeProtocolError(
                        "Step result sequence does not match the request."
                    )
                result = message.result
                observation = CPUObservation.from_payload(result.get("observation"))
                ended = result.get("episode_ended")
                if not isinstance(ended, bool):
                    raise CPUBridgeProtocolError(
                        "Step result episode_ended must be a boolean."
                    )
                result_events = _parse_events(result.get("events", []))
                events = result_events or asynchronous_events
                if action_sequence is None and not ended:
                    raise CPUBridgeProtocolError(
                        "Step completed without requesting an action observation."
                    )
                self._done = ended
                info: dict[str, Any] = {
                    "seed": self._seed,
                    "level": self._level,
                    "bridge_step_sequence": command_sequence,
                    "action_sequence": action_sequence,
                    "action_queued": action_sequence is not None,
                    "action_applied_to_returned_state": False,
                    "episode_ended": ended,
                    "events": events,
                }
                if policy_decision is not None:
                    info["policy_decision"] = dict(policy_decision)
                if ended:
                    terminal_event = _terminal_event(events)
                    info["episode_event"] = terminal_event
                    info["reason"] = (
                        terminal_event.reason if terminal_event is not None else None
                    )
                return observation, 0.0, ended, False, info

    def get_level_geometry(self, level: str | None = None) -> LevelGeometry:
        if self._closed or self._done or self._level is None:
            raise RuntimeError("Reset the environment before requesting level geometry.")
        requested_level = level or self._level
        if requested_level != self._level:
            raise ValueError("Geometry can only be requested for the active level.")
        sequence = self._bridge().get_level_geometry(requested_level)
        while True:
            message = self._bridge().receive()
            if isinstance(message, CommandResultMessage):
                if message.sequence != sequence:
                    raise CPUBridgeProtocolError(
                        "Geometry result sequence does not match the request."
                    )
                geometry = LevelGeometry.from_payload(message.result)
                if geometry.level != requested_level:
                    raise CPUBridgeProtocolError(
                        f"Geometry returned {geometry.level!r}, expected {requested_level!r}."
                    )
                return geometry
            if isinstance(message, ObservationMessage):
                raise CPUBridgeProtocolError(
                    "Geometry request unexpectedly requested a player action."
                )
            if isinstance(message, EpisodeEventMessage):
                raise CPUBridgeProtocolError(
                    "Geometry request unexpectedly emitted an episode event."
                )

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._owns_simulation and self._simulation is not None:
                self._simulation.close()
            elif self._owns_client and self._client is not None:
                client = self._client
                try:
                    sequence = client.close_session()
                    while True:
                        message = client.receive()
                        if (
                            isinstance(message, CommandResultMessage)
                            and message.sequence == sequence
                        ):
                            break
                finally:
                    client.close()
        finally:
            self._closed = True
            self._client = None

    def _bridge(self) -> _BridgeClient:
        if self._closed:
            raise RuntimeError("The environment is closed.")
        if self._client is None:
            if self._simulation is None:
                raise RuntimeError("The environment has no active bridge client.")
            self._client = self._simulation.start()
        return self._client


def _coerce_action(action: CPUIntent | Mapping[str, Any]) -> CPUIntent:
    if isinstance(action, CPUIntent):
        intent = action
    elif isinstance(action, Mapping):
        if set(action) != _ACTION_FIELDS:
            raise ValueError(
                f"action must contain exactly: {', '.join(sorted(_ACTION_FIELDS))}."
            )
        direction = action["dash_direction"]
        if not isinstance(direction, Mapping) or set(direction) != {"x", "y"}:
            raise ValueError("action.dash_direction must contain numeric x and y.")
        intent = CPUIntent(
            horizontal=action["horizontal"],
            jump=action["jump"],
            dash=action["dash"],
            dash_direction=Vector2(direction["x"], direction["y"]),
            down=action["down"],
            grab=action["grab"],
        )
    else:
        raise ValueError("action must be a CPUIntent or mapping.")
    intent.to_payload()
    return intent


def _parse_events(value: Any) -> list[EpisodeEvent]:
    if not isinstance(value, list):
        raise CPUBridgeProtocolError("Step result events must be an array.")
    return [EpisodeEvent.from_payload(event) for event in value]


def _terminal_event(events: list[EpisodeEvent]) -> EpisodeEvent | None:
    return next(
        (
            event
            for event in reversed(events)
            if event.type in {"fault", "point", "set", "match"}
        ),
        None,
    )
