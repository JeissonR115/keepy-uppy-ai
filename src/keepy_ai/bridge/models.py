from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, TypeAlias

from keepy_ai.bridge.errors import CPUBridgeProtocolError


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CPUBridgeProtocolError(f"{name} must be a JSON object.")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise CPUBridgeProtocolError(f"{name} must be a string.")
    return value


def _integer(value: Any, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CPUBridgeProtocolError(f"{name} must be an integer.")
    if positive and value <= 0:
        raise CPUBridgeProtocolError(f"{name} must be positive.")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CPUBridgeProtocolError(f"{name} must be numeric.")
    if not math.isfinite(value):
        raise CPUBridgeProtocolError(f"{name} must be finite.")
    return float(value)


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise CPUBridgeProtocolError(f"{name} must be boolean.")
    return value


@dataclass(frozen=True, slots=True)
class Vector2:
    x: float
    y: float

    @classmethod
    def from_payload(cls, value: Any, name: str) -> Vector2:
        payload = _object(value, name)
        if set(payload) != {"x", "y"}:
            raise CPUBridgeProtocolError(f"{name} must contain exactly x and y.")
        return cls(
            x=_number(payload["x"], f"{name}.x"),
            y=_number(payload["y"], f"{name}.y"),
        )

    def to_payload(self, name: str = "vector") -> dict[str, float]:
        for field_name, value in (("x", self.x), ("y", self.y)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name}.{field_name} must be finite numeric input.")
        return {
            "x": float(self.x),
            "y": float(self.y),
        }


@dataclass(frozen=True, slots=True)
class PlayerObservation:
    position: Vector2
    velocity: Vector2
    on_floor: bool
    wall_contact: float
    dash_cooldown: float
    dash_available: bool
    stamina: float

    @classmethod
    def from_payload(cls, value: Any, name: str) -> PlayerObservation:
        payload = _object(value, name)
        required = {
            "position",
            "velocity",
            "on_floor",
            "wall_contact",
            "dash_cooldown",
            "dash_available",
            "stamina",
        }
        missing = required - payload.keys()
        if missing:
            raise CPUBridgeProtocolError(
                f"{name} is missing fields: {', '.join(sorted(missing))}."
            )
        return cls(
            position=Vector2.from_payload(payload["position"], f"{name}.position"),
            velocity=Vector2.from_payload(payload["velocity"], f"{name}.velocity"),
            on_floor=_boolean(payload["on_floor"], f"{name}.on_floor"),
            wall_contact=_number(payload["wall_contact"], f"{name}.wall_contact"),
            dash_cooldown=_number(payload["dash_cooldown"], f"{name}.dash_cooldown"),
            dash_available=_boolean(payload["dash_available"], f"{name}.dash_available"),
            stamina=_number(payload["stamina"], f"{name}.stamina"),
        )


@dataclass(frozen=True, slots=True)
class BalloonObservation:
    position: Vector2
    velocity: Vector2
    waiting_for_first_touch: bool

    @classmethod
    def from_payload(cls, value: Any) -> BalloonObservation:
        payload = _object(value, "observation.balloon")
        return cls(
            position=Vector2.from_payload(payload.get("position"), "balloon.position"),
            velocity=Vector2.from_payload(payload.get("velocity"), "balloon.velocity"),
            waiting_for_first_touch=_boolean(
                payload.get("waiting_for_first_touch"),
                "balloon.waiting_for_first_touch",
            ),
        )


@dataclass(frozen=True, slots=True)
class ScoreSnapshot:
    points: dict[str, int]
    sets: dict[str, int]

    @classmethod
    def from_payload(cls, value: Any) -> ScoreSnapshot:
        payload = _object(value, "score")
        points = _object(payload.get("points"), "score.points")
        sets = _object(payload.get("sets"), "score.sets")
        return cls(
            points={
                player: _integer(points.get(player), f"score.points.{player}")
                for player in ("player_1", "player_2")
            },
            sets={
                player: _integer(sets.get(player), f"score.sets.{player}")
                for player in ("player_1", "player_2")
            },
        )


@dataclass(frozen=True, slots=True)
class CPUObservation:
    tick: int
    bot_player: str
    players: dict[str, PlayerObservation]
    balloon: BalloonObservation
    current_turn: str
    score: ScoreSnapshot
    level: str

    @classmethod
    def from_payload(cls, value: Any) -> CPUObservation:
        payload = _object(value, "observation")
        players = _object(payload.get("players"), "observation.players")
        return cls(
            tick=_integer(payload.get("tick"), "observation.tick"),
            bot_player=_string(payload.get("bot_player"), "observation.bot_player"),
            players={
                player: PlayerObservation.from_payload(
                    players.get(player), f"observation.players.{player}"
                )
                for player in ("player_1", "player_2")
            },
            balloon=BalloonObservation.from_payload(payload.get("balloon")),
            current_turn=_string(payload.get("current_turn"), "observation.current_turn"),
            score=ScoreSnapshot.from_payload(payload.get("score")),
            level=_string(payload.get("level"), "observation.level"),
        )


@dataclass(frozen=True, slots=True)
class MovementProbeResult:
    level: str
    movement: str
    start_position: Vector2
    action_started: bool
    landed: bool
    landing_position: Vector2 | None
    final_position: Vector2
    physics_frames_elapsed: int
    physics_delta: float
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "movement": self.movement,
            "start_position": self.start_position.to_payload("probe.start_position"),
            "action_started": self.action_started,
            "landed": self.landed,
            "landing_position": (
                None
                if self.landing_position is None
                else self.landing_position.to_payload("probe.landing_position")
            ),
            "final_position": self.final_position.to_payload("probe.final_position"),
            "physics_frames_elapsed": self.physics_frames_elapsed,
            "physics_delta": self.physics_delta,
            "reason": self.reason,
        }

    @classmethod
    def from_payload(cls, value: Any) -> MovementProbeResult:
        payload = _object(value, "probe result")
        movement = _string(payload.get("movement"), "probe result.movement")
        if movement not in {"jump", "dash"}:
            raise CPUBridgeProtocolError(
                f"Unsupported probe movement: {movement!r}."
            )
        landing = payload.get("landing_position")
        physics_frames_elapsed = _integer(
            payload.get("physics_frames_elapsed"),
            "probe result.physics_frames_elapsed",
        )
        physics_delta = _number(
            payload.get("physics_delta"), "probe result.physics_delta"
        )
        if physics_frames_elapsed < 0:
            raise CPUBridgeProtocolError(
                "probe result.physics_frames_elapsed must not be negative."
            )
        if physics_delta <= 0:
            raise CPUBridgeProtocolError("probe result.physics_delta must be positive.")
        return cls(
            level=_string(payload.get("level"), "probe result.level"),
            movement=movement,
            start_position=Vector2.from_payload(
                payload.get("start_position"), "probe result.start_position"
            ),
            action_started=_boolean(
                payload.get("action_started"), "probe result.action_started"
            ),
            landed=_boolean(payload.get("landed"), "probe result.landed"),
            landing_position=(
                None
                if landing is None
                else Vector2.from_payload(landing, "probe result.landing_position")
            ),
            final_position=Vector2.from_payload(
                payload.get("final_position"), "probe result.final_position"
            ),
            physics_frames_elapsed=physics_frames_elapsed,
            physics_delta=physics_delta,
            reason=_string(payload.get("reason"), "probe result.reason"),
        )


@dataclass(frozen=True, slots=True)
class CPUIntent:
    horizontal: float = 0.0
    jump: bool = False
    dash: bool = False
    dash_direction: Vector2 = Vector2(0.0, 0.0)
    down: bool = False
    grab: bool = False

    def to_payload(self) -> dict[str, Any]:
        if (
            isinstance(self.horizontal, bool)
            or not isinstance(self.horizontal, (int, float))
            or not math.isfinite(self.horizontal)
        ):
            raise ValueError("action.horizontal must be finite numeric input.")
        horizontal = float(self.horizontal)
        if not -1.0 <= horizontal <= 1.0:
            raise ValueError("action.horizontal must be between -1 and 1.")
        for field_name in ("jump", "dash", "down", "grab"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"action.{field_name} must be boolean.")
        if not isinstance(self.dash_direction, Vector2):
            raise ValueError("action.dash_direction must be a Vector2.")
        return {
            "horizontal": horizontal,
            "jump": self.jump,
            "dash": self.dash,
            "dash_direction": self.dash_direction.to_payload("action.dash_direction"),
            "down": self.down,
            "grab": self.grab,
        }


@dataclass(frozen=True, slots=True)
class EpisodeEvent:
    type: str
    reason: str | None
    player: str
    winner: str
    score: ScoreSnapshot

    @classmethod
    def from_payload(cls, value: Any) -> EpisodeEvent:
        payload = _object(value, "episode_event.event")
        event_type = _string(payload.get("type"), "episode_event.event.type")
        if event_type not in {
            "fault",
            "point",
            "downward_fault_replay",
            "set",
            "match",
        }:
            raise CPUBridgeProtocolError(
                f"Unsupported episode event type: {event_type}."
            )
        reason_value = payload.get("reason")
        reason = None if reason_value is None else _string(
            reason_value, "episode_event.event.reason"
        )
        return cls(
            type=event_type,
            reason=reason,
            player=_string(payload.get("player"), "episode_event.event.player"),
            winner=_string(payload.get("winner"), "episode_event.event.winner"),
            score=ScoreSnapshot.from_payload(payload.get("score")),
        )


@dataclass(frozen=True, slots=True)
class ObservationMessage:
    sequence: int
    observation: CPUObservation


@dataclass(frozen=True, slots=True)
class EpisodeEventMessage:
    event: EpisodeEvent


@dataclass(frozen=True, slots=True)
class CommandResultMessage:
    sequence: int
    result: dict[str, Any]


BridgeMessage: TypeAlias = (
    ObservationMessage | EpisodeEventMessage | CommandResultMessage
)
