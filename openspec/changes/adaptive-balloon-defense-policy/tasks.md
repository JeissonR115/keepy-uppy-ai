# Tasks

## 1. Wall-bounce trajectory model

- [x] 1.1 Add validated policy physics and distance configuration, sourced from documented defaults with CLI/TOML overrides; verify invalid coefficients and spacing values are rejected with focused tests, and document the parameters.
- [x] 1.2 Implement bounded balloon trajectory sampling with horizontal wall rebounds from `LevelGeometry`; verify one and multiple rebounds stay within the playable bounds and compare representative traces across all four levels with deterministic tests.

## 2. Turn-aware action policy

- [x] 2.1 Implement own-turn interception selection over predicted contact points with conservative player reachability and recovery fallback; verify pre-wall and post-wall interception choices and unreachable-path fallback with deterministic tests.
- [x] 2.2 Implement opponent-turn ready positioning, preferred distance, minimum no-contact distance, and evasive movement without jump/dash/grab; verify the policy moves closer when outside range and away when below safe spacing across both horizontal directions.
- [x] 2.3 Add a JSON-serializable decision record for both turn phases and document policy behavior and model limitations; verify records include phase, target/prediction status, spacing, and final action.

## 3. Episode integration

- [x] 3.1 Add an optional action-selector callback at the bridge observation boundary and include its decision record in step info; verify one action is chosen for each matching observation sequence and fixed-action callers retain existing behavior.
- [x] 3.2 Integrate adaptive policy as the `run-episode` default, load active level geometry once per episode, preserve explicit neutral baseline mode, and add opt-in per-decision JSONL logging; verify CLI defaults/help and fake-bridge runs in both policy modes, and document commands and log format.

## 4. End-to-end verification

- [ ] 4.1 Exercise multi-seed episodes on all four levels with the adaptive policy and inspect own-turn, opponent-turn, and wall-rebound decisions; verify the policy-log output is parseable, episode summaries remain compatible, and report any real-Godot model drift that requires tuning.
