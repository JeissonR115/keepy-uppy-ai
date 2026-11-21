# Design

## Context

See [proposal.md](proposal.md) and the two capability specs for motivation and behavior. `CPUBridgeClient` already handles versioned sessions, sequenced actions, commands, and exported geometry. `run-episode` owns the current headless loop and launches Godot; the adaptive policy predicts side-wall rebounds but does not use navigation graphs or collision polygons.

The paired Godot change, `integrate-python-policy-into-game`, will own process startup, the interactive bridge server, and local-brain fallback. This Python change owns a live client and the policy it invokes; it must not start or step Godot.

## Goals / Non-Goals

**Goals:**

- Reuse the version-one bridge and policy code for both live matches and headless episodes.
- Make live geometry, observation sequencing, and action responses explicit and independently testable.
- Keep routing work bounded enough to run once per action request.

**Non-Goals:**

- Change Godot gameplay physics, scoring, or the TCP protocol version.
- Train a learned policy or guarantee exact collision prediction for every physics interaction.
- Modify the sibling Godot repository from this change.

## Decisions

### Separate live-client mode from episode ownership

Add a dedicated live command that connects through `CPUBridgeClient`, requests geometry for the active level, and then loops over observations and matching actions. Do not overload `run-episode` or alter its reset/step semantics: the live Godot process owns match state and physics. The live client handles a geometry command result and action observations on the same connection, preserving command and action sequence rules.

The game-side coordinator must make the active level's geometry available before enabling remote decisions. It can start the Python process while the match is paused, accept the geometry request, then enable `RemoteBrain`; this avoids burning the action timeout while Python initializes. The paired Godot change owns this readiness gate and uses its local fallback if it expires.

### Derive spacing from exported movement data

When no user override is set, calculate preferred spacing from the active level's `DASH_SPEED * DASH_TIME` movement constants. Current values imply approximately 60 world pixels, but the result is a ready-position preference, not a contact radius or guarantee that a dash can hit the balloon. Keep minimum no-contact distance derived independently from the player/balloon contact sizes and safety margin. An explicit TOML or CLI preferred-distance value takes precedence.

### Predict collisions from exported geometry

Extend bounded trajectory sampling to test the balloon's swept circle against the active level's exported collision polygons and platforms. For surfaces that affect the balloon, reflect velocity using the configured balloon rebound approximation and continue sampling; keep arena bounds as an additional constraint. Use a fixed maximum sample count and evaluate only valid finite geometry. This is preferable to a wall-only model or loading static geometry files that may not match the live arena.

The exported geometry does not encode every material-specific physics response. The predictor remains an approximation, reports when the geometry is unusable, and leaves actual movement and collision resolution to Godot.

### Reuse generated navigation graphs and add transient costs

Load the schema-versioned graph for the observed level and evaluate reachable graph routes to candidate interception or defensive positions. Recompute route costs for each new observation. Add a transient cost to edges that intersect the opponent's predicted occupied area: a push-through route receives a movement-slowdown penalty, while a detour retains its graph movement cost. Choose the lower estimated cost and keep the result bounded by the graph size and prediction horizon.

Direct movement remains a recovery fallback when a graph is missing or has no usable route; it is reported as a fallback rather than presented as a validated route.

### Keep the live client a replaceable policy consumer

The live command invokes the same `decide` operation and serializes its existing action shape. It does not duplicate policy decisions in the networking loop. Connection, geometry, and policy errors remain explicit so Godot can apply its local-brain fallback rather than Python silently fabricating successful decisions.

## Risks / Trade-offs

- [The live game may request an action before geometry is ready] → Coordinate readiness with the paired Godot change and enable the remote brain only after geometry loading or a bounded startup failure.
- [Exported polygons may not capture every bounce material or moving surface] → Use bounded approximate physics, identify invalid geometry, and compare selected live traces with Godot observations.
- [Opponent displacement varies with priority and dash state] → Use observed motion and a configurable slowdown penalty; reevaluate every observation instead of caching an obstacle route.
- [A graph may be missing, stale, or have no reachable candidate] → Validate its level/schema, report the condition, and use the explicit recovery fallback.
- [Per-observation route search could exceed the action timeout] → Bound prediction samples and graph work, and verify worst-case policy latency in tests.

## Migration Plan

1. Keep `run-episode` on its current headless launch path and introduce the live command separately.
2. Implement and test geometry loading, trajectory collisions, and route-cost selection without Godot.
3. Run the live client against a fake bridge, then against the paired interactive Godot bridge.
4. Configure the Godot game to launch this client; if startup or connection fails, retain its local CPU behavior.

No saved episode or graph migration is required. Rollback by disabling the Godot Python-client configuration; existing headless episodes and local CPU behavior remain available.
