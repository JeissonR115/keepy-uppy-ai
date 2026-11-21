# Proposal

## Why

The live dashboard displays the latest Godot observation, while saved episode files contain only terminal summaries. This prevents users from comparing real player and balloon movement over the course of a simulation. Persisting per-tick observations and plotting them offline makes those physics traces inspectable and reproducible.

## What Changes

- Add opt-in JSONL recording of full typed observations from `run-episode` and the live dashboard, with one uniquely identified trace per episode or live session.
- Include the run id, source, level, seed, capture time, Godot physics tick, players, balloon, and score/context needed to interpret each sample.
- Add validated discovery and loading for telemetry files, including file and line details for malformed records.
- Add a dashboard page to select a run and plot player or balloon position and velocity components against the Godot physics tick.
- Keep existing terminal episode summaries and the live view behavior available when telemetry recording is disabled.

## Capabilities

### New Capabilities

- `simulation-telemetry`: Opt-in capture and local persistence of typed per-tick Godot observations from episode runs and live sessions.
- `trajectory-dashboard`: Discovery, validation, and visualization of saved telemetry traces by run, entity, and observation field.

### Modified Capabilities

None. The repository has no main specs under `openspec/specs/`; the existing dashboard requirements are currently defined only in a completed change delta.

## Impact

- Affects the observation serialization and episode loop in `src/keepy_ai/bridge/models.py` and `src/keepy_ai/cli.py`.
- Adds a reusable telemetry recorder/loader under `src/keepy_ai/dashboard/` and updates `src/keepy_ai/dashboard/app.py` with a trace page and optional live-session recording.
- Adds a local `telemetry/` output directory and documentation for JSONL format, recording commands, and trace charts.
- Does not change the Godot bridge protocol or make telemetry capture the default.
