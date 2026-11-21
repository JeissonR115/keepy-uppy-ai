# Proposal

## Why

The live dashboard currently launches a headless Godot simulation and sends neutral actions. It cannot attach to the interactive match already running on the configured bridge, so it cannot show the policy decisions, route nodes, or waypoints used by the connected Python client.

## What Changes

- Replace the Live page's simulation-owned mode with an attach mode for an existing Godot bridge.
- Add a host and port configuration for the live attachment, defaulting to `127.0.0.1:8766` for the normal Godot live match.
- Make the dashboard read-only: it SHALL receive observations and policy telemetry, SHALL not reset, step, or close the match, and SHALL not send gameplay actions.
- Show live player and balloon positions, turn, action, target, route status, graph node IDs, and route waypoint.
- Extend the bridge protocol in the paired Godot repository to support a policy/observer session alongside the existing policy controller so the controller and dashboard can share live observations.
- Preserve the offline Levels, Metrics, and Episodes pages and preserve existing headless `run-episode` behavior.

## Capabilities

### New Capabilities

- `live-bridge-observation`: Attach to an existing live match and consume read-only observations and policy decisions from the bridge without owning or controlling the match.

### Modified Capabilities

- `visualization-dashboard`: The existing Live page requirement changes from "start/connect a configurable headless simulation" to "attach to an interactive live bridge or report that no live session is available."

## Impact

- Python dashboard: bridge client attachment, live telemetry parsing, periodic UI rendering, and route/action display.
- Python live client: publish the decision record produced by `decide` to observers instead of keeping route and action data process-local.
- Godot bridge: add a read-only observer role and multiplex or broadcast live observations and telemetry without disturbing the policy controller or accepting extra gameplay actions.
- Tests and documentation: cover direct port attachment, observer disconnection, malformed telemetry, duplicate clients, and unchanged offline pages.
