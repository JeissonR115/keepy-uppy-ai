# Design

## Context

See [proposal.md](proposal.md) for motivation and [specs/balloon-play-policy/spec.md](specs/balloon-play-policy/spec.md) for behavior. The Python package currently has typed observations, a geometry parser with level bounds and movement constants, and an episode loop that sends the same supplied intent in response to each remote decision. It has no reusable action policy. In the Godot bridge, the remote brain requests actions while active in both turn phases, and the observation identifies both the controlled bot and the expected toucher.

## Goals / Non-Goals

**Goals:**

- Turn every bridge observation into a deterministic action plus a structured explanation.
- Keep trajectory prediction and tactical choices independently testable without a running Godot process.
- Allow distance and balloon-model parameters to be tuned without changing source code.

**Non-Goals:**

- Train a learned policy or introduce a reward function.
- Replace Godot's local fallback brain or change the bridge protocol.
- Model every platform, hazard, spin, or collision impulse in the balloon simulation; this version focuses on side-wall rebounds and observed motion.

## Decisions

### Separate trajectory prediction from turn policy

Add a pure predictor that samples the balloon's future state at a fixed physics step, using observed position/velocity, exported level bounds, and a small validated physics-parameter object. On horizontal side contact it clamps the center to the playable boundary and reverses horizontal velocity with the configured rebound coefficient; each later sample can therefore include additional wall bounces. Use the exported bounds rather than hard-coded arena dimensions so all current levels share the same model.

The bridge currently exports player movement constants but not all balloon physics values or player contact radii. Keep those extra model values in a documented Python policy configuration with defaults matching the current Godot arena, and allow TOML/CLI overrides. Include the selected configuration in policy reports. This avoids silently treating an approximate model as exact and avoids a protocol change; extending the bridge to export those values can be considered separately.

### Produce a structured decision for both turn phases

Implement the policy as a pure operation over `CPUObservation`, `LevelGeometry`, and policy configuration, returning a `CPUIntent` and a decision record. Select the controlled player from `bot_player`, then compare it with `current_turn`. On the bot's turn, sample candidate contact heights along the predicted path and choose the earliest reachable candidate that satisfies bounds and movement constraints. On the opponent's turn, target a defensive point near the predicted trajectory while remaining outside a minimum separation based on configured contact radii plus a safety margin. If the projected path violates that separation, prefer an evasive horizontal action. Do not request jump, dash, or grab during defensive positioning. If the turn is unknown or prediction is unusable, return a neutral or safe horizontal fallback with an explicit reason.

The preferred distance and minimum safe distance are separate settings: the minimum prevents unintended contact, while the preferred range keeps the bot close enough to respond. Clamp targets to playable bounds and never solve a too-close state by moving through the balloon.

### Invoke the policy at the bridge observation boundary

Allow `CPUTrainingEnv.step` to receive an optional action-selector callback. The environment invokes it for the actual `ObservationMessage` before sending the matching action sequence, then includes its decision record in `info`. Existing callers that pass a fixed intent retain their current behavior. `run-episode` defaults to the adaptive policy, loads and caches the selected level geometry once after reset, and supplies the policy callback on every step, including when `current_turn` belongs to the opponent. An explicit neutral mode remains available for baseline runs.

### Keep per-tick explanations separate from episode summaries

Represent every policy result as JSON-serializable data (phase, prediction status, target, predicted time, player-balloon distance, safety margin, selected action, and fallback reason). Keep the existing one-line terminal summary stable. Add an opt-in decision-log JSONL path for per-observation records so ordinary runs do not flood standard output and existing episode-summary consumers do not break.

### Validate geometry and tune safety values explicitly

Reject non-finite or inverted bounds and invalid distance/physics settings before starting a policy episode. Derive the physical no-contact floor from configured balloon/player contact radii plus safety margin, then apply the configured preferred distance above that floor. Avoid burying the user's safe-spacing choice in action code; expose both values in CLI/TOML configuration and in the decision log.

## Risks / Trade-offs

- [Balloon physics can drift from the mirrored defaults] → Keep coefficients configurable, include them in reports, and test representative traces from every current level; the policy remains an approximation until the bridge exports authoritative balloon constants.
- [A predicted intercept may be unreachable because of obstacles or stale movement constants] → Check movement reachability conservatively, fall back to the closest safe recovery point, and report the reason.
- [Remote action requests have a short response deadline] → Keep prediction bounded by a maximum sample count and avoid launching probes or expensive searches inside the per-observation callback.
- [A near target can still trigger contact because observations and actions are one tick apart] → Include the configured contact margin and use predicted closest approach, not just current distance, when choosing defensive movement.

## Migration Plan

No data migration is needed. Episode behavior changes to adaptive by default as requested; users can select neutral mode to reproduce fixed-neutral baseline runs. Existing episode summary JSONL remains unchanged. Rollback is selecting neutral mode or removing the new policy integration, without modifying saved episodes or Godot data.
