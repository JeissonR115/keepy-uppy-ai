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
