from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from keepy_ai.bridge.client import CPUBridgeClient, PROTOCOL_VERSION
from keepy_ai.bridge.errors import (
    CPUBridgeConnectionError,
    CPUBridgeProtocolError,
    CPUBridgeServerError,
    CPUBridgeTimeoutError,
)
from keepy_ai.bridge.models import (
    CPUIntent,
    CommandResultMessage,
    EpisodeEventMessage,
    ObservationMessage,
    Vector2,
)

_SESSION_ID = "test-session"


def _send(connection: socket.socket, message: dict[str, Any]) -> None:
    connection.sendall(json.dumps(message).encode("utf-8") + b"\n")


def _hello() -> dict[str, Any]:
    return {
        "type": "hello",
        "protocol_version": PROTOCOL_VERSION,
        "session_id": _SESSION_ID,
    }


def _observation() -> dict[str, Any]:
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
        "tick": 12,
        "bot_player": "player_2",
        "players": {"player_1": player, "player_2": player},
        "balloon": {
            "position": {"x": 40, "y": 50},
            "velocity": {"x": 1, "y": -2},
            "waiting_for_first_touch": False,
        },
        "current_turn": "player_1",
        "score": {
            "points": {"player_1": 1, "player_2": 0},
            "sets": {"player_1": 0, "player_2": 0},
        },
        "level": "classic",
    }


@contextmanager
def _fake_server(
    handler: Callable[[socket.socket, Any], None],
    *,
    hello: dict[str, Any] | None = None,
) -> Iterator[int]:
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    port = listener.getsockname()[1]
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                reader = connection.makefile("rb")
                try:
                    _send(connection, hello or _hello())
                    handler(connection, reader)
                finally:
                    reader.close()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        listener.close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("Fake bridge server did not stop.")
        if errors:
            raise errors[0]


def _read_client_message(reader: Any) -> dict[str, Any]:
    message = json.loads(reader.readline())
    assert isinstance(message, dict)
    return message


def test_command_sequence_and_session_envelope() -> None:
    def handler(connection: socket.socket, reader: Any) -> None:
        for expected_sequence, expected_command in ((1, "reset"), (2, "step")):
            command = _read_client_message(reader)
            assert command == {
                "type": "command",
                "protocol_version": 1,
                "session_id": _SESSION_ID,
                "sequence": expected_sequence,
                "command": expected_command,
                "payload": {},
            }
            _send(
                connection,
                {
                    "type": "command_result",
                    "protocol_version": 1,
                    "session_id": _SESSION_ID,
                    "sequence": expected_sequence,
                    "ok": True,
                    "result": {"accepted": True},
                },
            )

    with _fake_server(handler) as port:
        with CPUBridgeClient(port=port) as client:
            assert client.session_id == _SESSION_ID
            first = client.send_command("reset")
            result = client.receive()
            assert first == 1
            assert result == CommandResultMessage(1, {"accepted": True})

            second = client.send_command("step")
            result = client.receive()
            assert second == 2
            assert result == CommandResultMessage(2, {"accepted": True})


def test_typed_helpers_send_contract_payloads_and_match_results() -> None:
    expected_commands = [
        ("reset", {"seed": 3, "level": "classic"}),
        ("step", {"n": 2}),
        ("set_speed", {"speed": 2.5}),
        ("get_level_geometry", {}),
        (
            "probe_movement",
            {
                "movement": "jump",
                "start_position": {"x": 1.0, "y": 2.0},
                "level": "classic",
                "horizontal": -0.5,
            },
        ),
        (
            "probe_movement",
            {
                "movement": "dash",
                "start_position": {"x": 3.0, "y": 4.0},
                "direction": {"x": 1.0, "y": -1.0},
            },
        ),
        (
            "load_nav_graph",
            {"graph": {"schema_version": 1, "level": "classic", "nodes": [], "edges": []}},
        ),
        (
            "set_nav_route",
            {"level": "classic", "start_node": 1, "destination_node": 2},
        ),
        ("close", {}),
    ]

    def handler(connection: socket.socket, reader: Any) -> None:
        for sequence, (expected_command, expected_payload) in enumerate(
            expected_commands, start=1
        ):
            command = _read_client_message(reader)
            assert command["sequence"] == sequence
            assert command["command"] == expected_command
            assert command["payload"] == expected_payload
            _send(
                connection,
                {
                    "type": "command_result",
                    "protocol_version": 1,
                    "session_id": _SESSION_ID,
                    "sequence": sequence,
                    "ok": True,
                    "result": {},
                },
            )

    with _fake_server(handler) as port:
        with CPUBridgeClient(port=port) as client:
            operations = [
                lambda: client.reset(3, "classic"),
                lambda: client.step(2),
                lambda: client.set_speed(2.5),
                lambda: client.get_level_geometry(),
                lambda: client.probe_movement(
                    "jump", Vector2(1, 2), level="classic", horizontal=-0.5
                ),
                lambda: client.probe_movement(
                    "dash", Vector2(3, 4), direction=Vector2(1, -1)
                ),
                lambda: client.load_nav_graph(
                    {"schema_version": 1, "level": "classic", "nodes": [], "edges": []}
                ),
                lambda: client.set_nav_route("classic", 1, 2),
                lambda: client.close_session(),
            ]
            for sequence, operation in enumerate(operations, start=1):
                assert operation() == sequence
                assert client.receive() == CommandResultMessage(sequence, {})


@pytest.mark.parametrize(
    "operation",
    [
        lambda client: client.reset(True, "classic"),
        lambda client: client.reset(1, ""),
        lambda client: client.step(0),
        lambda client: client.set_speed(float("inf")),
        lambda client: client.get_level_geometry(" "),
        lambda client: client.probe_movement("jump", Vector2(0, 0)),
        lambda client: client.probe_movement(
            "jump", Vector2(0, 0), horizontal=2
        ),
        lambda client: client.probe_movement(
            "dash", Vector2(0, 0), direction=Vector2(0, 0)
        ),
        lambda client: client.load_nav_graph([]),
        lambda client: client.set_nav_route("classic", True, 2),
    ],
)
def test_typed_helpers_reject_invalid_inputs_before_sending(operation: Any) -> None:
    with _fake_server(lambda _connection, _reader: None) as port:
        with CPUBridgeClient(port=port) as client:
            with pytest.raises(ValueError):
                operation(client)


def test_rejects_mismatched_command_result_sequence() -> None:
    def handler(connection: socket.socket, reader: Any) -> None:
        _read_client_message(reader)
        _send(
            connection,
            {
                "type": "command_result",
                "protocol_version": 1,
                "session_id": _SESSION_ID,
                "sequence": 2,
                "ok": True,
                "result": {},
            },
        )

    with _fake_server(handler) as port:
        with CPUBridgeClient(port=port) as client:
            client.step()
            with pytest.raises(CPUBridgeProtocolError, match="does not match"):
                client.receive()


@pytest.mark.parametrize(
    "hello",
    [
        {"type": "hello", "protocol_version": 2, "session_id": _SESSION_ID},
        {"type": "hello", "protocol_version": 1.0, "session_id": _SESSION_ID},
        {"type": "hello", "protocol_version": 1, "session_id": ""},
        {"type": "not-hello", "protocol_version": 1, "session_id": _SESSION_ID},
    ],
)
def test_rejects_invalid_handshake(hello: dict[str, Any]) -> None:
    with _fake_server(lambda _connection, _reader: None, hello=hello) as port:
        with pytest.raises(CPUBridgeProtocolError):
            CPUBridgeClient(port=port)


def test_dispatches_observation_event_and_result_and_validates_actions() -> None:
    def handler(connection: socket.socket, reader: Any) -> None:
        command = _read_client_message(reader)
        assert command["sequence"] == 1
        _send(
            connection,
            {
                "type": "observation",
                "protocol_version": 1,
                "session_id": _SESSION_ID,
                "sequence": 7,
                "observation": _observation(),
            },
        )
        action = _read_client_message(reader)
        assert action == {
            "type": "action",
            "protocol_version": 1,
            "session_id": _SESSION_ID,
            "sequence": 7,
            "action": {
                "horizontal": -1.0,
                "jump": True,
                "dash": False,
                "dash_direction": {"x": 0.0, "y": 0.0},
                "down": True,
                "grab": False,
            },
        }
        _send(
            connection,
            {
                "type": "episode_event",
                "protocol_version": 1,
                "session_id": _SESSION_ID,
                "event": {
                    "type": "fault",
                    "reason": "spikes",
                    "player": "player_2",
                    "winner": "player_1",
                    "score": {
                        "points": {"player_1": 1, "player_2": 0},
                        "sets": {"player_1": 0, "player_2": 0},
                    },
                },
            },
        )
        _send(
            connection,
            {
                "type": "command_result",
                "protocol_version": 1,
                "session_id": _SESSION_ID,
                "sequence": 1,
                "ok": True,
                "result": {"episode_ended": True},
            },
        )

    with _fake_server(handler) as port:
        with CPUBridgeClient(port=port) as client:
            client.send_command("step", {"n": 1})
            with pytest.raises(CPUBridgeProtocolError):
                client.send_action(7, CPUIntent())

            message = client.receive()
            assert isinstance(message, ObservationMessage)
            assert message.sequence == 7
            assert message.observation.players["player_2"].position == Vector2(20, 30)
            with pytest.raises(ValueError):
                client.send_action(7, CPUIntent(horizontal=2))
            with pytest.raises(CPUBridgeProtocolError):
                client.send_action(8, CPUIntent())

            client.send_action(
                7,
                CPUIntent(
                    horizontal=-1,
                    jump=True,
                    down=True,
                    dash_direction=Vector2(0, 0),
                ),
            )
            event = client.receive()
            assert isinstance(event, EpisodeEventMessage)
            assert event.event.type == "fault"
            assert event.event.reason == "spikes"
            result = client.receive()
            assert result == CommandResultMessage(1, {"episode_ended": True})


def test_rejects_server_errors_with_code_and_message() -> None:
    def handler(connection: socket.socket, reader: Any) -> None:
        command = _read_client_message(reader)
        _send(
            connection,
            {
                "type": "error",
                "protocol_version": 1,
                "session_id": _SESSION_ID,
                "sequence": command["sequence"],
                "code": "invalid_payload",
                "message": "Bad reset request.",
            },
        )

    with _fake_server(handler) as port:
        with CPUBridgeClient(port=port) as client:
            client.send_command("reset")
            with pytest.raises(CPUBridgeServerError) as error:
                client.receive()
            assert error.value.code == "invalid_payload"
            assert error.value.message == "Bad reset request."
            assert error.value.sequence == 1


def test_reports_malformed_message_and_timeout() -> None:
    def malformed_handler(connection: socket.socket, _reader: Any) -> None:
        connection.sendall(b"{broken json}\n")

    with _fake_server(malformed_handler) as port:
        with CPUBridgeClient(port=port) as client:
            with pytest.raises(CPUBridgeProtocolError, match="invalid UTF-8 JSON"):
                client.receive()

    def timeout_handler(_connection: socket.socket, _reader: Any) -> None:
        time.sleep(0.25)

    with _fake_server(timeout_handler) as port:
        with CPUBridgeClient(port=port, timeout=0.05) as client:
            with pytest.raises(CPUBridgeTimeoutError):
                client.receive()


def test_reports_disconnect() -> None:
    with _fake_server(lambda _connection, _reader: None) as port:
        with CPUBridgeClient(port=port) as client:
            with pytest.raises(CPUBridgeConnectionError):
                client.receive()
