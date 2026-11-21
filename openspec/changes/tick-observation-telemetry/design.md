# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. `CPUObservation` is already the typed representation of Godot state and is returned by the environment for each step. Episode summaries and live-session state currently follow separate paths, so recording should be a small shared persistence layer with adapters at those two call sites. Godot's observation `tick` is its physics frame count and is the time axis used by the trace charts.

## Goals / Non-Goals

**Goals:**

- Keep a single JSON serialization format for observations captured by CLI and dashboard.
- Make recordings independently readable and tolerant of a partially written final sample.
- Keep file discovery and plotting usable when Godot is not running.

**Non-Goals:**

- Change Godot's bridge protocol or control policy.
- Persist every internal calculation or action decision; the trace records observed game state.
- Convert physics ticks into wall-clock duration or add a database service.

## Decisions

### Store one versioned JSONL file per recording

Write traces under a `telemetry/` directory as `<run_id>.jsonl`. A run id combines a UTC timestamp and random UUID component, and the file is opened exclusively so a collision cannot overwrite an earlier trace. Each line contains a schema version, run id, source, level, seed, UTC capture timestamp, and the observation payload. Use the Godot physics tick inside the observation as the canonical sample index. JSONL keeps completed samples readable if the process exits between ticks and avoids rewriting a growing trace.

An episode batch creates one file per episode; a dashboard session creates one file for that session. Keep this directory separate from `episodes/`, whose JSONL records are terminal summaries.

### Reuse the typed observation as the serialization boundary

Add a canonical `CPUObservation.to_payload()` counterpart to `from_payload()` and have the recorder serialize that representation. This keeps telemetry aligned with the bridge model and avoids a second hand-maintained list of physics fields. The outer telemetry envelope carries recording metadata and a schema version; the existing Godot payload shape remains unchanged.

### Record reset state and completed step results

When enabled, the episode adapter writes the observation returned by reset, then each observation returned by a completed step, including the terminal one. The dashboard adapter follows the same rule for live sessions. It records the returned state regardless of whether Godot requested an action from the Python process; some live modes advance under a Godot-side controller. The recorder flushes after each complete line and is closed through the existing episode/session cleanup path.

### Make recording opt-in at both entry points

Expose a CLI flag and output-directory option for episode runs. On the live dashboard, show a recording checkbox before a session starts and store the resulting trace under the dashboard artifact root. This avoids unbounded default data growth and keeps all paths explicit. With recording off, do not instantiate the recorder or create telemetry files.

### Keep reading and plotting in the dashboard data layer

Add a loader that discovers trace files, validates each line against the supported schema and observation model, and returns valid records plus file/line diagnostics. A malformed line should not hide valid lines elsewhere in the trace. Build charts from the loaded records, plotting X/Y positions and velocities separately against physics tick for the selected player or balloon. Use the dashboard's existing chart library so this feature adds no runtime dependency.

## Risks / Trade-offs

- [Long episodes can produce large files] → Recording is opt-in, split per run, and flushed incrementally.
- [A crash may leave a truncated final line] → The loader reports its file and line while keeping prior complete samples available.
- [Godot may skip tick values or observation requests] → Plot the tick values actually present; capture each returned completed observation rather than inferring missing states.
- [Observation fields may evolve] → Version each telemetry record and reject unsupported versions with a line-level diagnostic.

## Migration Plan

No migration is needed. Existing episode summaries remain in their current format and location. New traces use a separate `telemetry/` directory; rollback consists of disabling recording or removing the new dashboard page and recorder code, without modifying existing artifacts.
