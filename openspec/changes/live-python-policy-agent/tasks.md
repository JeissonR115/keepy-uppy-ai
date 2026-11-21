# Tasks

## 1. Live game client

- [x] 1.1 Add a separate live-client CLI entry point with host, port, and timeout configuration; verify it connects to a fake bridge without starting Godot.
- [x] 1.2 Request and validate active level geometry, then process each observation and send one action with the matching sequence; verify command results, observations, turn changes, malformed data, and disconnects with bridge tests.
- [x] 1.3 Document how the Godot launcher invokes the live client and how it differs from `run-episode`; verify the documented arguments match the CLI.

## 2. Dash-ready spacing

- [x] 2.1 Derive the unset preferred distance from exported `DASH_SPEED * DASH_TIME` while retaining the independent minimum safe distance; verify the current game values yield approximately 60 pixels.
- [x] 2.2 Preserve TOML and CLI preferred-distance overrides and document precedence; verify overrides and missing dash constants with focused configuration and policy tests.

## 3. Tile-aware balloon prediction

- [x] 3.1 Extend bounded trajectory prediction to account for the balloon's swept radius and exported collision polygons/platforms; verify tile and wall rebounds, multiple contacts, and playable-bound constraints with deterministic fixtures.
- [x] 3.2 Report unusable collision geometry instead of selecting an unverified intercept; verify invalid or missing geometry produces an explicit prediction status and safe recovery decision.

## 4. Opponent-aware route planning

- [x] 4.1 Load and validate the schema-versioned graph for the active level and calculate reachable candidate routes; verify invalid, missing, and mismatched graphs take the documented recovery path.
- [x] 4.2 Add transient route costs for predicted opponent occupancy, including a push-through slowdown penalty; verify the policy chooses push-through or detour according to the lower estimated cost.
- [x] 4.3 Recalculate routes after the opponent or balloon trajectory changes and expose the selected route status in policy output; verify deterministic decisions for repeated and changed observations.
- [x] 4.4 Document the route-cost and collision-model assumptions; verify examples and settings match the implementation.

## 5. Paired game integration

- [x] 5.1 Coordinate the live command arguments and geometry request with `integrate-python-policy-into-game`; verify the two changes agree on loopback address, port, client readiness, and active-level geometry.
- [x] 5.2 Run the live client against an interactive Godot match and verify the Python policy returns actions, responds to turn changes, and leaves headless `run-episode` behavior unchanged.
