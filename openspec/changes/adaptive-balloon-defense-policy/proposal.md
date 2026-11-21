# Proposal

## Why

The Python project can exchange actions and generate navigation graphs, but its episode runner does not yet make purposeful play decisions. A reusable policy should predict where the balloon will travel after wall rebounds, intercept it on the bot's turn, and stay ready at a safe distance on the opponent's turn so the balloon remains reachable without accidental extra contact.

## What Changes

- Add an observation-driven CPU policy for both the bot's own turn and the opponent's turn, using the bridge's `bot_player`, `current_turn`, player state, balloon state, and level geometry.
- Predict balloon paths with horizontal wall reflections derived from the active arena bounds, then select reachable interception targets instead of aiming only at the balloon's current position.
- On the opponent's turn, keep the bot near the predicted defensive position while respecting a minimum no-contact distance; avoid initiating an extra balloon touch while preparing to respond.
- Make the adaptive policy the default for Python episode runs, while retaining an explicit neutral/manual mode for baseline runs.
- Report the policy's selected phase, predicted intercept, target distance, and action in episode telemetry/log output so decisions can be inspected.

## Capabilities

### New Capabilities

- `balloon-play-policy`: Turn-aware interception and defensive positioning for a remote CPU, including wall-bounce prediction and safe balloon-contact spacing.

### Modified Capabilities

None. No main specs exist in `openspec/specs/`; the existing bridge and training-environment requirements live in the separate `python-ai-project` change and do not need requirement changes for this new optional policy.

## Impact

- Adds reusable policy and trajectory-prediction modules under `src/keepy_ai/`, using typed bridge observations and level geometry.
- Updates `run-episode` to select and invoke the policy for each observation, including observations during the opponent's turn.
- Adds deterministic policy tests and episode integration coverage; documents configuration, assumptions, and decision traces.
- Does not require a Godot protocol change or mandatory third-party runtime dependency.
