# Proposal

## Why

The adaptive policy currently runs only inside Python-owned headless episodes, so the Godot game cannot launch it as its live CPU opponent. The policy also predicts side-wall rebounds only and does not compare routes around a moving opponent, which limits its usefulness in the actual arenas.

## What Changes

- Add a live bridge-client mode that connects to an already-running Godot match, requests the active level geometry, answers sequenced observations, and does not reset or step the game.
- Keep the existing headless `run-episode` workflow and its command semantics unchanged.
- Derive the default safe preferred spacing from the active level's dash speed and duration (about 60 world pixels with current values), while retaining a simple TOML/CLI override and a separate minimum no-contact distance.
- Predict balloon rebounds against the exported solid arena and tile collision geometry, not only the horizontal arena bounds.
- Treat the opponent as a moving route obstacle; compare the estimated cost of a slower push-through with a detour, then reconsider the choice on every updated observation.
- Coordinate the live-client command and launch arguments with Godot change `integrate-python-policy-into-game` in the sibling game repository.

## Capabilities

### New Capabilities

- `live-game-client`: Connect to an interactive Godot match and provide one policy action for each live observation without owning simulation control.
- `obstacle-aware-balloon-routing`: Select safe, reachable balloon positions using dash-range spacing, tile-aware trajectory prediction, and a moving opponent's route cost.

### Modified Capabilities

None. The Python repository has no main specs yet; the existing `balloon-play-policy` requirements are in a separate completed-planning change and are not rewritten here.

## Impact

- Python bridge client and CLI: add a live attach mode that can request current level geometry and answer actions without `reset`/`step`.
- Python policy: configurable dash-range spacing, collision-aware trajectory prediction, and dynamic opponent route evaluation.
- Tests and docs: cover live message flow, policy decisions, settings, and coordination with the Godot match launcher.
- Godot remains a separate repository; this change defines the Python-side client contract but does not edit game files.
