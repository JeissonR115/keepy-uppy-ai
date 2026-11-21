from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from keepy_ai.bridge.client import PROTOCOL_VERSION
from keepy_ai.live import build_parser, main


@contextmanager
def _fake_bridge(
    handler: Callable[[socket.socket, Any, list[dict[str, Any]]], None] | None = None,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    received: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                reader = connection.makefile("rb")
                try:
                    connection.sendall(
                        json.dumps(
                            {
                                "type": "hello",
                                "protocol_version": PROTOCOL_VERSION,
                                "session_id": "fake-live-session",
                            }
                        ).encode()
                        + b"\n"
                    )
                    if handler is None:
                        received.append(json.loads(reader.readline()))
                    else:
                        handler(connection, reader, received)
                finally:
                    reader.close()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], received
    finally:
        listener.close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("Fake bridge server did not stop.")
        if errors:
            raise errors[0]


def _geometry_payload(
    level: str = "classic", *, collision_geometry: bool = True
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "level": level,
        "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": 320, "y": 180}},
        "safe_bounds": {
            "position": {"x": 8, "y": 8},
            "size": {"x": 304, "y": 164},
        },
        "spawns": {
            "player_1": {"x": 60, "y": 150},
            "player_2": {"x": 260, "y": 150},
        },
        "collisions": (
            [
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
                },
            ]
            if collision_geometry
            else []
        ),
        "platforms": [],
        "movement_constants": {
            "MAX_RUN": 130,
            "GRAVITY": 0,
            "JUMP_SPEED": -250,
        },
    }


def _observation_payload(
    *, turn: str, tick: int, bot_x: float, balloon_x: float
) -> dict[str, Any]:
    player = {
        "position": {"x": 60, "y": 40},
        "velocity": {"x": 0, "y": 0},
        "on_floor": True,
        "wall_contact": 0,
        "dash_cooldown": 0,
        "dash_available": True,
        "stamina": 110,
    }
    bot = {**player, "position": {"x": bot_x, "y": 40}}
    return {
        "tick": tick,
        "bot_player": "player_2",
        "players": {"player_1": player, "player_2": bot},
        "balloon": {
            "position": {"x": balloon_x, "y": 40},
            "velocity": {"x": 0, "y": 0},
            "waiting_for_first_touch": False,
        },
        "current_turn": turn,
        "score": {
            "points": {"player_1": 0, "player_2": 0},
            "sets": {"player_1": 0, "player_2": 0},
        },
        "level": "classic",
    }


def _read_message(reader: Any) -> dict[str, Any]:
    message = json.loads(reader.readline())
    assert isinstance(message, dict)
    return message


def _send(connection: socket.socket, message: dict[str, Any]) -> None:
    connection.sendall(json.dumps(message).encode() + b"\n")


def test_live_cli_connects_and_recovers_when_graph_is_missing(capsys, tmp_path) -> None:
    with _fake_bridge() as (port, received):
        result = main(
            [
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--timeout",
                "1",
                "--level",
                "classic",
                "--graph-dir",
                str(tmp_path),
            ]
        )

    assert result == 1
    assert received[0]["command"] == "get_level_geometry"
    assert received[0]["payload"] == {"level": "classic"}
    error_output = capsys.readouterr().err
    assert "cannot read graph" in error_output
    assert "using direct movement" in error_output
    assert "run-live:" in error_output


def test_live_client_uses_geometry_and_answers_each_sequenced_turn(
    capsys, tmp_path
) -> None:
    actions: list[dict[str, Any]] = []

    def handle(
        connection: socket.socket, reader: Any, received: list[dict[str, Any]]
    ) -> None:
        geometry_request = _read_message(reader)
        received.append(geometry_request)
        _send(
            connection,
            {
                "type": "command_result",
                "protocol_version": PROTOCOL_VERSION,
                "session_id": "fake-live-session",
                "sequence": geometry_request["sequence"],
                "ok": True,
                "result": _geometry_payload(),
            },
        )
        for sequence, turn, bot_x, balloon_x in (
            (17, "player_1", 50, 140),
            (18, "player_2", 200, 140),
        ):
            _send(
                connection,
                {
                    "type": "observation",
                    "protocol_version": PROTOCOL_VERSION,
                    "session_id": "fake-live-session",
                    "sequence": sequence,
                    "observation": _observation_payload(
                        turn=turn,
                        tick=sequence,
                        bot_x=bot_x,
                        balloon_x=balloon_x,
                    ),
                },
            )
            actions.append(_read_message(reader))

    with _fake_bridge(handle) as (port, received):
        result = main(
            [
                "--port",
                str(port),
                "--timeout",
                "1",
                "--level",
                "classic",
                "--graph-dir",
                str(tmp_path),
            ]
        )

    assert result == 1
    assert received[0]["command"] == "get_level_geometry"
    assert [action["sequence"] for action in actions] == [17, 18]
    assert actions[0]["action"]["horizontal"] == 1.0
    assert actions[1]["action"]["horizontal"] == -1.0
    assert "run-live:" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("geometry", "observation", "message"),
    [
        (_geometry_payload("sky-towers"), None, "expected 'classic'"),
        ({}, None, "geometry.schema_version"),
        (
            _geometry_payload(),
            {},
            "observation.players must be a JSON object",
        ),
    ],
)
def test_live_client_rejects_mismatched_or_malformed_data(
    geometry: dict[str, Any], observation: dict[str, Any] | None, message: str, capsys
) -> None:
    def handle(
        connection: socket.socket, reader: Any, _received: list[dict[str, Any]]
    ) -> None:
        request = _read_message(reader)
        _send(
            connection,
            {
                "type": "command_result",
                "protocol_version": PROTOCOL_VERSION,
                "session_id": "fake-live-session",
                "sequence": request["sequence"],
                "ok": True,
                "result": geometry,
            },
        )
        if observation is not None:
            _send(
                connection,
                {
                    "type": "observation",
                    "protocol_version": PROTOCOL_VERSION,
                    "session_id": "fake-live-session",
                    "sequence": 21,
                    "observation": observation,
                },
            )

    with _fake_bridge(handle) as (port, _received):
        result = main(
            ["--port", str(port), "--timeout", "1", "--level", "classic"]
        )

    assert result == 1
    assert message in capsys.readouterr().err


def test_live_client_does_not_send_action_without_collision_geometry(capsys) -> None:
    received: list[dict[str, Any]] = []

    def handle(
        connection: socket.socket, reader: Any, messages: list[dict[str, Any]]
    ) -> None:
        request = _read_message(reader)
        messages.append(request)
        _send(
            connection,
            {
                "type": "command_result",
                "protocol_version": PROTOCOL_VERSION,
                "session_id": "fake-live-session",
                "sequence": request["sequence"],
                "ok": True,
                "result": _geometry_payload(collision_geometry=False),
            },
        )
        _send(
            connection,
            {
                "type": "observation",
                "protocol_version": PROTOCOL_VERSION,
                "session_id": "fake-live-session",
                "sequence": 22,
                "observation": _observation_payload(
                    turn="player_1", tick=22, bot_x=50, balloon_x=140
                ),
            },
        )
        action = reader.readline()
        if action:
            received.append(json.loads(action))

    with _fake_bridge(handle) as (port, _messages):
        result = main(
            ["--port", str(port), "--timeout", "1", "--level", "classic"]
        )

    assert result == 1
    assert received == []
    assert "collision geometry is unavailable" in capsys.readouterr().err


def test_live_cli_parses_game_launcher_arguments() -> None:
    args = build_parser().parse_args(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--timeout",
            "4",
            "--level",
            "classic",
            "--policy-opponent-push-slowdown",
            "3",
        ]
    )

    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.timeout == 4
    assert args.level == "classic"
    assert args.policy_opponent_push_slowdown == 3


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_live_cli_rejects_invalid_timeouts(value: str) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--level", "classic", "--timeout", value])
