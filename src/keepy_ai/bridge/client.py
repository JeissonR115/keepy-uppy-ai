from __future__ import annotations

import json
import math
import socket
from typing import Any, Literal

from keepy_ai.bridge.errors import (
    CPUBridgeError,
    CPUBridgeConnectionError,
    CPUBridgeProtocolError,
    CPUBridgeServerError,
    CPUBridgeTimeoutError,
)
from keepy_ai.bridge.models import (
    BridgeMessage,
    CommandResultMessage,
    CPUIntent,
    CPUObservation,
    EpisodeEvent,
    EpisodeEventMessage,
    ObservationMessage,
    Vector2,
)

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_048_576
COMMANDS = frozenset(
    {
        "reset",
        "step",
        "set_speed",
        "get_level_geometry",
        "probe_movement",
        "load_nav_graph",
        "set_nav_route",
        "close",
    }
)


class CPUBridgeClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        timeout: float = 10.0,
    ) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a finite positive number.")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number.")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535.")

        try:
            self._socket = socket.create_connection((host, port), timeout=float(timeout))
        except socket.timeout as error:
            raise CPUBridgeTimeoutError("Timed out connecting to the bridge.") from error
        except OSError as error:
            raise CPUBridgeConnectionError(
                f"Could not connect to the bridge at {host}:{port}."
            ) from error

        self._socket.settimeout(float(timeout))
        self._timeout = float(timeout)
        self._reader = self._socket.makefile("rb")
        self._session_id = ""
        self._next_command_sequence = 1
        self._inflight_command_sequence: int | None = None
        self._outstanding_observations: set[int] = set()
        self._closed = False

        try:
            hello = self._read_json_line()
            self._validate_protocol_version(hello)
            if hello.get("type") != "hello":
                raise CPUBridgeProtocolError("The first server message must be hello.")
            session_id = hello.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise CPUBridgeProtocolError(
                    "The hello message must include a non-empty session_id."
                )
            self._session_id = session_id
        except CPUBridgeError:
            self.close()
            raise

    def __enter__(self) -> CPUBridgeClient:
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def timeout(self) -> float:
        return self._timeout

    def set_timeout(self, timeout: float) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a finite positive number.")
        if self._closed:
            raise CPUBridgeConnectionError("The bridge client is closed.")
        self._socket.settimeout(float(timeout))
        self._timeout = float(timeout)

    def reset(self, seed: int, level: str) -> int:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer.")
        self._validate_level(level)
        return self.send_command("reset", {"seed": seed, "level": level})

    def step(self, n: int = 1) -> int:
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise ValueError("n must be a positive integer.")
        return self.send_command("step", {"n": n})

    def set_speed(self, speed: float) -> int:
        if (
            isinstance(speed, bool)
            or not isinstance(speed, (int, float))
            or not math.isfinite(speed)
            or speed <= 0
        ):
            raise ValueError("speed must be a finite positive number.")
        return self.send_command("set_speed", {"speed": float(speed)})

    def get_level_geometry(self, level: str | None = None) -> int:
        payload: dict[str, Any] = {}
        if level is not None:
            self._validate_level(level)
            payload["level"] = level
        return self.send_command("get_level_geometry", payload)

    def probe_movement(
        self,
        movement: Literal["jump", "dash"],
        start_position: Vector2,
        *,
        level: str | None = None,
        horizontal: float | None = None,
        direction: Vector2 | None = None,
    ) -> int:
        if movement not in ("jump", "dash"):
            raise ValueError("movement must be 'jump' or 'dash'.")
        if not isinstance(start_position, Vector2):
            raise ValueError("start_position must be a Vector2.")
        payload: dict[str, Any] = {
            "movement": movement,
            "start_position": start_position.to_payload("start_position"),
        }
        if level is not None:
            self._validate_level(level)
            payload["level"] = level

        if movement == "jump":
            if direction is not None:
                raise ValueError("direction is only valid for a dash probe.")
            if (
                isinstance(horizontal, bool)
                or not isinstance(horizontal, (int, float))
                or not math.isfinite(horizontal)
                or not -1 <= horizontal <= 1
            ):
                raise ValueError("jump horizontal must be finite and between -1 and 1.")
            payload["horizontal"] = float(horizontal)
        else:
            if horizontal is not None:
                raise ValueError("horizontal is only valid for a jump probe.")
            if not isinstance(direction, Vector2):
                raise ValueError("dash probes require a Vector2 direction.")
            direction_payload = direction.to_payload("direction")
            if direction_payload["x"] == 0 and direction_payload["y"] == 0:
                raise ValueError("dash direction must be non-zero.")
            payload["direction"] = direction_payload

        return self.send_command("probe_movement", payload)

    def load_nav_graph(self, graph: dict[str, Any]) -> int:
        if not isinstance(graph, dict):
            raise ValueError("graph must be a JSON object.")
        return self.send_command("load_nav_graph", {"graph": graph})

    def set_nav_route(
        self, level: str, start_node: int, destination_node: int
    ) -> int:
        self._validate_level(level)
        for name, node_id in (
            ("start_node", start_node),
            ("destination_node", destination_node),
        ):
            if isinstance(node_id, bool) or not isinstance(node_id, int):
                raise ValueError(f"{name} must be an integer.")
        return self.send_command(
            "set_nav_route",
            {
                "level": level,
                "start_node": start_node,
                "destination_node": destination_node,
            },
        )

    def close_session(self) -> int:
        """Request protocol-level shutdown; call close() to release the socket."""
        return self.send_command("close")

    def send_command(
        self, command: str, payload: dict[str, Any] | None = None
    ) -> int:
        if self._closed:
            raise CPUBridgeConnectionError("The bridge client is closed.")
        if command not in COMMANDS:
            raise ValueError(f"unsupported command: {command}")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object.")
        if self._inflight_command_sequence is not None:
            raise CPUBridgeProtocolError(
                "A command is already in flight; receive its result before sending another."
            )

        sequence = self._next_command_sequence
        message = {
            "type": "command",
            "protocol_version": PROTOCOL_VERSION,
            "session_id": self._session_id,
            "sequence": sequence,
            "command": command,
            "payload": payload or {},
        }
        self._send_json_line(message)
        self._next_command_sequence += 1
        self._inflight_command_sequence = sequence
        return sequence

    def send_action(self, sequence: int, action: CPUIntent) -> None:
        if self._closed:
            raise CPUBridgeConnectionError("The bridge client is closed.")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
            raise ValueError("sequence must be a positive integer.")
        if sequence not in self._outstanding_observations:
            raise CPUBridgeProtocolError(
                "Action sequence does not match an outstanding observation."
            )
        if not isinstance(action, CPUIntent):
            raise ValueError("action must be a CPUIntent.")
        payload = action.to_payload()
        self._send_json_line(
            {
                "type": "action",
                "protocol_version": PROTOCOL_VERSION,
                "session_id": self._session_id,
                "sequence": sequence,
                "action": payload,
            }
        )
        self._outstanding_observations.remove(sequence)

    def receive(self) -> BridgeMessage:
        if self._closed:
            raise CPUBridgeConnectionError("The bridge client is closed.")
        message = self._read_json_line()
        self._validate_protocol_version(message)
        if message.get("session_id") != self._session_id:
            raise CPUBridgeProtocolError("Server message belongs to a different session.")

        message_type = message.get("type")
        if message_type == "error":
            code = message.get("code")
            detail = message.get("message")
            if not isinstance(code, str) or not isinstance(detail, str):
                raise CPUBridgeProtocolError("Server error is missing code or message.")
            sequence = message.get("sequence")
            if sequence is not None and (
                isinstance(sequence, bool) or not isinstance(sequence, int)
            ):
                raise CPUBridgeProtocolError("Server error sequence must be an integer.")
            raise CPUBridgeServerError(code, detail, sequence)
        if message_type == "observation":
            sequence = self._positive_sequence(message.get("sequence"))
            if sequence in self._outstanding_observations:
                raise CPUBridgeProtocolError(
                    f"Observation sequence {sequence} is already outstanding."
                )
            observation = CPUObservation.from_payload(message.get("observation"))
            self._outstanding_observations.add(sequence)
            return ObservationMessage(sequence, observation)
        if message_type == "episode_event":
            return EpisodeEventMessage(EpisodeEvent.from_payload(message.get("event")))
        if message_type == "command_result":
            sequence = self._positive_sequence(message.get("sequence"))
            if sequence != self._inflight_command_sequence:
                raise CPUBridgeProtocolError(
                    "Command result sequence does not match the in-flight command."
                )
            if message.get("ok") is not True:
                raise CPUBridgeProtocolError(
                    "Successful command result must have ok=true."
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise CPUBridgeProtocolError("Command result must contain a JSON object.")
            self._inflight_command_sequence = None
            return CommandResultMessage(sequence, result)
        raise CPUBridgeProtocolError(f"Unsupported server message type: {message_type!r}.")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._reader.close()
        finally:
            self._socket.close()

    def _read_json_line(self) -> dict[str, Any]:
        try:
            line = self._reader.readline(MAX_MESSAGE_BYTES + 2)
        except socket.timeout as error:
            raise CPUBridgeTimeoutError("Timed out waiting for a bridge message.") from error
        except OSError as error:
            raise CPUBridgeConnectionError("Could not read from the bridge.") from error
        if not line:
            raise CPUBridgeConnectionError("The bridge closed the connection.")
        if len(line) > MAX_MESSAGE_BYTES + 1:
            raise CPUBridgeProtocolError("Server message exceeds the 1 MiB line limit.")
        if not line.endswith(b"\n"):
            raise CPUBridgeProtocolError("Server message is not newline-terminated.")
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CPUBridgeProtocolError("Server sent invalid UTF-8 JSON.") from error
        if not isinstance(value, dict):
            raise CPUBridgeProtocolError("Server message must be a JSON object.")
        return value

    def _send_json_line(self, message: dict[str, Any]) -> None:
        try:
            encoded = json.dumps(
                message, separators=(",", ":"), allow_nan=False
            ).encode("utf-8") + b"\n"
        except (TypeError, ValueError) as error:
            raise ValueError("Message is not valid finite JSON.") from error
        if len(encoded) - 1 > MAX_MESSAGE_BYTES:
            raise ValueError("Message exceeds the 1 MiB line limit.")
        try:
            self._socket.sendall(encoded)
        except socket.timeout as error:
            raise CPUBridgeTimeoutError("Timed out sending a bridge message.") from error
        except OSError as error:
            raise CPUBridgeConnectionError("Could not send to the bridge.") from error

    @staticmethod
    def _validate_protocol_version(message: dict[str, Any]) -> None:
        version = message.get("protocol_version")
        if type(version) is not int or version != PROTOCOL_VERSION:
            raise CPUBridgeProtocolError(
                f"Unsupported protocol version: {version!r}; expected {PROTOCOL_VERSION}."
            )

    @staticmethod
    def _positive_sequence(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise CPUBridgeProtocolError("sequence must be a positive integer.")
        return value

    @staticmethod
    def _validate_level(level: str) -> None:
        if not isinstance(level, str) or not level.strip():
            raise ValueError("level must be a non-empty string.")
