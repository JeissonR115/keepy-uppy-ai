# Keepy Uppy AI

Python tools for controlling and testing the Keepy Uppy Godot simulation through its TCP/JSON bridge. This repository is independent of the game; it does not import Godot code.

## Setup

Requirements: Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync
uv run python --version
```

The Git repository and OpenSpec root are initialized here. Use `uv sync` to create the project environment and install its development tools.

## Godot bridge

The default Godot project path is `../keepy-uppy`. The version-1 protocol contract lives in [`../keepy-uppy/docs/cpu-ai-bridge.md`](../keepy-uppy/docs/cpu-ai-bridge.md); it is the source of truth for message formats and behavior.

`CPUBridgeClient` provides typed helpers for reset, step, speed, geometry,
movement probes, graph loading, route selection, and the protocol `close`
command. Helpers return command sequence numbers; `receive()` returns typed
observation, event, or command-result messages. `close_session()` sends the
protocol command, while `close()` releases the local socket. Keep the Godot
contract authoritative if the client and contract differ.

Configuration precedence is command-line options, environment variables, `keepy-ai.toml`, then defaults:

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `GODOT_BIN` | Godot executable | `godot` from `PATH` |
| `GODOT_PROJECT_PATH` | Godot project directory | `../keepy-uppy` |
| `GODOT_PORT` | Bridge port | Available loopback port |
| `GODOT_LEVEL` | Arena id | `classic` |
| `GODOT_SPEED` | Simulation speed | `1` |
| `GODOT_SEED` | Episode seed | `1` |
| `GODOT_MODE` | Simulation mode | `cpu-vs-cpu` |

The optional TOML file uses the same setting names in a `[godot]` table:

```toml
[godot]
bin = "godot"
project_path = "../keepy-uppy"
level = "classic"
speed = 1
seed = 1
mode = "cpu-vs-cpu"
```

Omit `port` to let the launcher select an available loopback port.

The launcher is available as `GodotSimulation` and can be configured directly
from the same sources:

```python
from keepy_ai.godot.launcher import GodotConfig, GodotSimulation

config = GodotConfig.resolve()
with GodotSimulation(config) as simulation:
    client = simulation.client
```

The simulation starts the headless scene, waits for the protocol hello, and
selects a free loopback port unless one is configured. Startup retries are
bounded; shutdown sends the protocol `close` command and terminates Godot if
graceful exit exceeds the configured timeout.

## Development

```sh
uv run pytest
```

Real-Godot integration tests are optional and require `GODOT_BIN` and
`GODOT_PROJECT_PATH`. Generate the four graphs first to enable the graph-route
and seeded-replay test:

```sh
uv run generate-graph --all-levels
GODOT_BIN=/path/to/godot GODOT_PROJECT_PATH=../keepy-uppy \
  uv run pytest -m godot_integration
```

See [the training environment guide](docs/training-environment.md) for reset,
step, event, and one-tick action-latency semantics.

## Live Godot match

`run-live` is the Python client for an interactive match bridge. It requests
geometry for the selected level and answers sequenced observations, but it does
not start Godot or create the match bridge. The paired Godot launcher/bridge
integration is not implemented yet, so the normal one-player-versus-bot match
cannot start or use this client yet.

After that Godot integration is implemented, its launcher should start the
client with separate arguments similar to:

```sh
uv run --project /path/to/keepy-uppy-ai run-live \
  --host 127.0.0.1 --port 8765 --timeout 10 --level classic
```

Do not run this command by itself unless a Godot live bridge is already
listening on that address and port. To exercise the Python policy now, use
`run-episode`; it launches a headless Godot simulation and is not an
interactive match:

```sh
uv run run-episode --level classic --seed 42 --episode-count 1
```

`--host`, `--port`, and `--timeout` default to `127.0.0.1`, `8765`, and
10 seconds; `--level` is required. `--config` selects a policy TOML file, and
`--graph-dir` selects the navigation graph directory (default: `graphs/`).
`--policy-preferred-distance` and `--policy-safety-margin` override the
corresponding policy settings, and `--policy-opponent-push-slowdown` controls
the route cost of pushing through an opponent. In contrast, `run-episode`
launches and owns a headless Godot simulation and retains its reset/step
workflow.

Run seeded episodes with the neutral-intent baseline (no trained policy):

```sh
uv run run-episode --level classic --seed 42 --speed 2 --episode-count 3
```

Each completed episode is printed as one JSON line. Omitted simulation options
continue to resolve from environment variables, `keepy-ai.toml`, and defaults.

Generate and exercise a graph for one level, or all four current levels:

```sh
uv run generate-graph --level classic --seed 42
uv run generate-graph --all-levels --seed 42 --speed 2
```

The command writes validated schema-version-one graphs to `graphs/<level>.json`.
Each JSON report on stdout includes probe rejections and the bounded physical
route-check result. Graph generation runs real Godot movement probes and may
take several minutes for larger levels.

See [OpenSpec conventions](docs/openspec-conventions.md) for change-planning practices.

Install and start the optional local visualization panel with
`uv sync --extra viz` and `uv run keepy-dashboard`. See the
[dashboard guide](docs/dashboard.md) for its pages, artifact formats, and
screenshots.
