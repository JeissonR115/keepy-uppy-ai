from __future__ import annotations

import math
import os
import socket
import subprocess
import threading
import time
import tomllib
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from keepy_ai.bridge.client import CPUBridgeClient
from keepy_ai.bridge.errors import (
    CPUBridgeConnectionError,
    CPUBridgeError,
    CPUBridgeProtocolError,
    CPUBridgeTimeoutError,
)

_LEVELS = {"primary-flat", "hazard-arena", "classic", "sky-towers"}
_MODES = {"cpu-vs-cpu", "cpu-vs-scripted"}
_SCENE = "res://src/scenes/simulation/cpu_simulation.tscn"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class GodotLaunchError(RuntimeError):
    """Godot could not be started or shut down cleanly."""


@dataclass(frozen=True, slots=True)
class GodotConfig:
    godot_bin: str
    project_path: Path
    port: int | None
    level: str
    speed: float
    seed: int
    mode: str
    startup_timeout: float = 10.0
    shutdown_timeout: float = 3.0
    startup_retries: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.godot_bin, str) or not self.godot_bin.strip():
            raise ValueError("godot_bin must be a non-empty executable name or path.")
        if not isinstance(self.project_path, Path):
            raise ValueError("project_path must be a pathlib.Path.")
        if self.port is not None and (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("port must be an integer between 1 and 65535.")
        if not isinstance(self.level, str) or self.level not in _LEVELS:
            raise ValueError(f"unsupported level: {self.level!r}")
        if (
            isinstance(self.speed, bool)
            or not isinstance(self.speed, (int, float))
            or not math.isfinite(self.speed)
            or self.speed <= 0
        ):
            raise ValueError("speed must be a finite positive number.")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer.")
        if not isinstance(self.mode, str) or self.mode not in _MODES:
            raise ValueError(f"unsupported mode: {self.mode!r}")
        for name, value in (
            ("startup_timeout", self.startup_timeout),
            ("shutdown_timeout", self.shutdown_timeout),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number.")
        if (
            isinstance(self.startup_retries, bool)
            or not isinstance(self.startup_retries, int)
            or self.startup_retries <= 0
        ):
            raise ValueError("startup_retries must be a positive integer.")

    @classmethod
    def resolve(
        cls,
        cli: Mapping[str, Any] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        config_path: Path | None = None,
    ) -> GodotConfig:
        cli_values = cli or {}
        environment = os.environ if environ is None else environ
        path = config_path or Path.cwd() / "keepy-ai.toml"
        file_values: Mapping[str, Any] = {}
        if path.is_file():
            try:
                document = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as error:
                raise ValueError(f"Could not read Godot configuration at {path}.") from error
            section = document.get("godot", {})
            if not isinstance(section, dict):
                raise ValueError("The [godot] configuration section must be a TOML table.")
            file_values = section

        def choose(
            name: str,
            environment_name: str,
            file_name: str,
            default: Any,
        ) -> tuple[Any, str]:
            for source, values, key in (
                ("command line", cli_values, name),
                ("environment", environment, environment_name),
                ("TOML", file_values, file_name),
            ):
                value = values.get(key)
                if value is not None:
                    return value, source
            return default, "default"

        binary, _ = choose("godot_bin", "GODOT_BIN", "bin", "godot")
        raw_project, project_source = choose(
            "project_path",
            "GODOT_PROJECT_PATH",
            "project_path",
            _PROJECT_ROOT.parent / "keepy-uppy",
        )
        project_path = Path(raw_project).expanduser()
        if not project_path.is_absolute():
            base = path.parent if project_source == "TOML" else Path.cwd()
            if project_source == "default":
                base = _PROJECT_ROOT
            project_path = base / project_path

        raw_port, _ = choose("port", "GODOT_PORT", "port", None)
        raw_level, _ = choose("level", "GODOT_LEVEL", "level", "classic")
        raw_speed, _ = choose("speed", "GODOT_SPEED", "speed", 1.0)
        raw_seed, _ = choose("seed", "GODOT_SEED", "seed", 1)
        raw_mode, _ = choose("mode", "GODOT_MODE", "mode", "cpu-vs-cpu")
        return cls(
            godot_bin=str(binary),
            project_path=project_path.resolve(),
            port=None if raw_port is None else _parse_integer(raw_port, "port"),
            level=str(raw_level),
            speed=_parse_float(raw_speed, "speed"),
            seed=_parse_integer(raw_seed, "seed"),
            mode=str(raw_mode),
        )


def _parse_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as error:
            raise ValueError(f"{name} must be an integer.") from error
    raise ValueError(f"{name} must be an integer.")


def _parse_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{name} must be numeric.")
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric.") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite.")
    return parsed


def _available_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class GodotSimulation:
    def __init__(self, config: GodotConfig) -> None:
        self.config = config
        self.port: int | None = None
        self.client: CPUBridgeClient | None = None
        self.process: subprocess.Popen[str] | None = None
        self.forced_shutdown = False
        self._output: deque[str] = deque(maxlen=500)
        self._output_thread: threading.Thread | None = None

    def __enter__(self) -> GodotSimulation:
        self.start()
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def start(self) -> CPUBridgeClient:
        if self.process is not None:
            raise GodotLaunchError("This Godot simulation has already been started.")
        project_file = self.config.project_path / "project.godot"
        if not project_file.is_file():
            raise GodotLaunchError(
                f"Godot project file was not found: {project_file}"
            )

        last_error: str = "Godot did not provide a bridge hello before timeout."
        for _attempt in range(self.config.startup_retries):
            port = self.config.port or _available_loopback_port()
            self.port = port
            command = [
                self.config.godot_bin,
                "--headless",
                "--path",
                str(self.config.project_path),
                _SCENE,
                "--",
                f"--port={port}",
                f"--level={self.config.level}",
                f"--speed={self.config.speed:g}",
                f"--seed={self.config.seed}",
                f"--mode={self.config.mode}",
            ]
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError as error:
                raise GodotLaunchError(
                    f"Could not start Godot executable {self.config.godot_bin!r}: {error}"
                ) from error
            self.process = process
            self._start_output_reader(process)

            deadline = time.monotonic() + self.config.startup_timeout
            while time.monotonic() < deadline:
                return_code = process.poll()
                if return_code is not None:
                    last_error = f"Godot exited during startup with status {return_code}."
                    break
                remaining = deadline - time.monotonic()
                try:
                    self.client = CPUBridgeClient(
                        port=port, timeout=min(0.25, max(0.01, remaining))
                    )
                    self.client.set_timeout(10.0)
                    return self.client
                except (CPUBridgeConnectionError, CPUBridgeTimeoutError) as error:
                    last_error = str(error)
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                except CPUBridgeProtocolError as error:
                    last_error = f"Godot sent an invalid bridge hello: {error}"
                    self._stop_child(force=True)
                    self.process = None
                    raise GodotLaunchError(self._diagnostic(last_error)) from error

            self._stop_child(force=True)
            self.process = None

        raise GodotLaunchError(self._diagnostic(last_error))

    def close(self) -> None:
        process = self.process
        if process is None:
            if self.client is not None:
                self.client.close()
                self.client = None
            return

        if self.client is not None:
            try:
                self.client.close_session()
            except CPUBridgeError:
                self.forced_shutdown = True
        try:
            process.wait(timeout=self.config.shutdown_timeout)
        except subprocess.TimeoutExpired:
            self.forced_shutdown = True
            process.terminate()
            try:
                process.wait(timeout=self.config.shutdown_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        finally:
            if self.client is not None:
                self.client.close()
                self.client = None
            self._join_output_reader()
            self.process = None

    def _start_output_reader(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return

        def read_output() -> None:
            for line in process.stdout:
                self._output.append(line.rstrip())

        self._output_thread = threading.Thread(target=read_output, daemon=True)
        self._output_thread.start()

    def _stop_child(self, *, force: bool) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            if force:
                process.terminate()
            try:
                process.wait(timeout=self.config.shutdown_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self._join_output_reader()

    def _join_output_reader(self) -> None:
        if self._output_thread is not None:
            self._output_thread.join(timeout=1)
            self._output_thread = None

    def _diagnostic(self, message: str) -> str:
        output = "\n".join(self._output)
        if output:
            return f"{message}\nGodot output:\n{output}"
        return message
