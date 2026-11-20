from __future__ import annotations

import json
from pathlib import Path

import pytest

from keepy_ai.bridge.client import CPUBridgeClient
from keepy_ai.godot.launcher import GodotConfig, GodotLaunchError, GodotSimulation


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "godot-project"
    project.mkdir()
    (project / "project.godot").write_text("", encoding="utf-8")
    return project


def _fake_godot(path: Path, *, ignore_close: bool = False) -> Path:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "import socket",
                "import sys",
                "import time",
                "args = sys.argv[1:]",
                "with open(os.environ['FAKE_GODOT_ARGS'], 'w', encoding='utf-8') as f:",
                "    json.dump(args, f)",
                "port = int(next(arg.split('=', 1)[1] for arg in args if arg.startswith('--port=')))",
                "server = socket.socket()",
                "server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)",
                "server.bind(('127.0.0.1', port))",
                "server.listen(1)",
                "print('fake Godot ready', flush=True)",
                "connection, _ = server.accept()",
                "with connection:",
                "    reader = connection.makefile('rb')",
                "    session = 'fake-session'",
                "    connection.sendall((json.dumps({'type': 'hello', 'protocol_version': 1, 'session_id': session}) + '\\n').encode())",
                "    while True:",
                "        message = json.loads(reader.readline())",
                "        if message.get('command') == 'close':",
                f"            if {ignore_close!r}:",
                "                time.sleep(30)",
                "                break",
                "            response = {'type': 'command_result', 'protocol_version': 1, 'session_id': session, 'sequence': message['sequence'], 'ok': True, 'result': {}}",
                "            connection.sendall((json.dumps(response) + '\\n').encode())",
                "            break",
                "    reader.close()",
                "server.close()",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_configuration_precedence_and_relative_toml_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "keepy-ai.toml"
    config_path.write_text(
        '[godot]\n'
        'bin = "toml-godot"\n'
        'project_path = "../project-from-toml"\n'
        'port = 9000\n'
        'level = "classic"\n'
        'speed = 1.5\n'
        'seed = 3\n'
        'mode = "cpu-vs-cpu"\n',
        encoding="utf-8",
    )

    config = GodotConfig.resolve(
        {"godot_bin": "cli-godot", "port": 7000, "speed": 2},
        environ={"GODOT_BIN": "env-godot", "GODOT_SEED": "42", "GODOT_LEVEL": "sky-towers"},
        config_path=config_path,
    )

    assert config.godot_bin == "cli-godot"
    assert config.port == 7000
    assert config.level == "sky-towers"
    assert config.speed == 2
    assert config.seed == 42
    assert config.project_path == (tmp_path / "../project-from-toml").resolve()


def test_launcher_starts_headless_and_closes_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    executable = _fake_godot(tmp_path / "fake-godot")
    args_file = tmp_path / "godot-args.json"
    monkeypatch.setenv("FAKE_GODOT_ARGS", str(args_file))
    config = GodotConfig(
        str(executable), project, None, "sky-towers", 2, 12, "cpu-vs-scripted",
        startup_timeout=2, shutdown_timeout=2,
    )
    simulation = GodotSimulation(config)

    client = simulation.start()
    assert isinstance(client, CPUBridgeClient)
    assert client.timeout == 10
    assert simulation.port is not None
    simulation.close()

    args = json.loads(args_file.read_text(encoding="utf-8"))
    assert args[:4] == [
        "--headless",
        "--path",
        str(project),
        "res://src/scenes/simulation/cpu_simulation.tscn",
    ]
    assert f"--port={simulation.port}" in args
    assert "--level=sky-towers" in args
    assert "--speed=2" in args
    assert "--seed=12" in args
    assert "--mode=cpu-vs-scripted" in args
    assert simulation.process is None
    assert simulation.client is None
    assert not simulation.forced_shutdown


def test_launcher_forces_shutdown_when_bridge_ignores_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    executable = _fake_godot(tmp_path / "fake-godot", ignore_close=True)
    monkeypatch.setenv("FAKE_GODOT_ARGS", str(tmp_path / "godot-args.json"))
    simulation = GodotSimulation(
        GodotConfig(
            str(executable), project, None, "classic", 1, 1, "cpu-vs-cpu",
            startup_timeout=2, shutdown_timeout=0.1,
        )
    )

    simulation.start()
    process = simulation.process
    simulation.close()

    assert process is not None
    assert process.poll() is not None
    assert simulation.forced_shutdown


def test_launcher_reports_child_failure_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    executable = tmp_path / "failing-godot"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "with open(os.environ['FAKE_GODOT_COUNT'], 'a', encoding='utf-8') as f:\n"
        "    f.write('attempt\\n')\n"
        "print('startup-boom', flush=True)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("FAKE_GODOT_ARGS", str(tmp_path / "godot-args.json"))
    count_file = tmp_path / "attempts.txt"
    monkeypatch.setenv("FAKE_GODOT_COUNT", str(count_file))
    simulation = GodotSimulation(
        GodotConfig(
            str(executable), project, None, "classic", 1, 1, "cpu-vs-cpu",
            startup_timeout=1, shutdown_timeout=1, startup_retries=3,
        )
    )

    with pytest.raises(GodotLaunchError, match="startup-boom"):
        simulation.start()
    assert simulation.process is None
    assert count_file.read_text(encoding="utf-8").splitlines() == [
        "attempt",
        "attempt",
        "attempt",
    ]
