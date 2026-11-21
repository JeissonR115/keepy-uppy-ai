# Tasks

## 1. Bridge observer contract

- [ ] 1.1 Add a controller-versus-observer session role to the paired Godot bridge and verify observers cannot send actions or simulation-control commands.
- [ ] 1.2 Broadcast valid controller observations to every observer with session and observation sequence, and verify a controller remains active after observer connect/disconnect.
- [ ] 1.3 Add or coordinate policy-decision telemetry publication from `run-live`, paired to the observation sequence, and verify malformed decisions are rejected explicitly.

## 2. Dashboard attachment

- [ ] 2.1 Replace the Live page's headless simulation owner with configurable bridge host/port attachment, defaulting to `127.0.0.1:8766`, and verify it never starts, resets, steps, or closes Godot.
- [ ] 2.2 Implement typed live observation and policy-decision parsing, stale/mismatched-state handling, and explicit connection status, and verify tests cover success, disconnect, malformed data, and stale sequences.
- [ ] 2.3 Preserve the last validated live state for bounded UI updates and verify it is not replaced by malformed or cross-session telemetry.

## 3. Live visualization

- [ ] 3.1 Render player and balloon positions, velocities, turn, score, level, selected action, target/prediction, and route status, and verify the fields update from matched observations and decisions.
- [ ] 3.2 Overlay graph node IDs and route edges on the live level and highlight the current waypoint, and verify the route view matches the current graph and level.
- [ ] 3.3 Render clear pending, stale, disconnected, unavailable-bridge, and unsupported-action states, and verify the offline dashboard pages remain usable.

## 4. Documentation and integration verification

- [ ] 4.1 Document the live bridge host/port settings and the separation between controller and observer sessions, and verify documented commands/configuration match the implementation.
- [ ] 4.2 Run fake-bridge tests and a paired interactive Godot match to verify direct port attachment shows live actions/nodes/waypoint without displacing the Python policy controller or changing `run-episode`.
