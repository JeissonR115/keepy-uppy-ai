# Proposal

## Why

The Godot game exposes a versioned TCP/JSON bridge, reproducible headless simulation, level geometry, physical movement probes, and per-level navigation graphs. The existing independent sibling repository needs its Python package, training interface, and graph-generation tooling so it can use those capabilities without importing or modifying game code.

## What Changes

- Complete the existing `keepy-uppy-ai` repository as a Python 3.11+ project managed by `uv`, with the requested package layout, tests, documentation, generated-graph directory, and conventions for its already initialized OpenSpec root.
- Add a typed bridge client and Godot headless process launcher. Use the existing `../keepy-uppy/docs/cpu-ai-bridge.md` contract for all commands, observations, actions, events, graph data, errors, and protocol versioning.
- Add a lightweight environment with `reset(seed, level)`, `step(action)`, and `close()` that exposes bridge observations and terminal-event reasons in a five-value Gymnasium-shaped result. It uses `reward=0.0` as an explicitly provisional placeholder, not a training signal. Because the unchanged bridge consumes an action response on the following physics tick, `step(action)` documents one-tick action-response latency and does not promise standard Gymnasium transition alignment; no algorithm or mandatory Gymnasium dependency is introduced.
- Add a geometry-driven graph generator for all four current levels. Generate WALK and DROP transitions from geometry rules and JUMP and DASH candidates validated with the real movement probe; export schema-version-1 JSON, load it in Godot, and check a reachable route.
- Report node counts, edge counts by action, rejected candidates, and nodes unreachable from either player spawn.
- Defer generation of WALL_JUMP edges in V1. The existing Godot probe only supports jump and dash; the Python generator will not label an unverified transition as WALL_JUMP. The graph format and bridge client remain compatible with WALL_JUMP edges supplied by other sources.
- Update the Godot repository's documentation only to point to this sibling AI project; do not change game code or the bridge protocol.

## Capabilities

### New Capabilities

- `python-godot-bridge`: Typed client and managed Godot headless process lifecycle using the documented TCP/JSON protocol.
- `python-training-environment`: Reset, step, close, observation, action, and terminal-event behavior for a minimal training environment.
- `navigation-graph-generation`: Per-level geometry analysis, movement-probe validation, schema-version-1 graph export, route smoke checks, and generation reports.

### Modified Capabilities

None. The existing Godot protocol and gameplay requirements remain unchanged.

## Impact

- Existing sibling repository `/media/disk/Dev/keepy-uppy-ai`; it retains its independent Git history and OpenSpec root and does not import game modules.
- Python 3.11+ standard library at runtime, `uv` for project and environment management; no mandatory Gymnasium or NumPy dependency.
- The Godot project is referenced through its filesystem path and the existing bridge. Its `docs/cpu-ai-bridge.md` receives a location reference, with no runtime changes.
- Optional end-to-end tests require `GODOT_BIN` and the path to the Godot project.
