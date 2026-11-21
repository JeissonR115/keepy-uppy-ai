# Tasks

## 1. Observation serialization and recorder

- [ ] 1.1 Add canonical `CPUObservation.to_payload()` serialization and a versioned JSONL telemetry recorder with unique per-run files; verify round-trip field coverage, one-line-per-sample output, and collision-safe run IDs with unit tests.
- [ ] 1.2 Add the telemetry loader and validation result types for supported versions, required fields, and per-file/per-line errors; verify malformed lines do not hide valid samples with unit tests.

## 2. Episode recording

- [ ] 2.1 Add opt-in telemetry and output-directory options to `run-episode`, recording reset plus each completed step observation per episode; verify enabled and disabled behavior, including terminal samples, with CLI/environment tests.
- [ ] 2.2 Document the episode recording command, output layout, JSONL envelope, and relationship to episode summaries; verify the documented CLI options match `--help`.

## 3. Live dashboard recording

- [ ] 3.1 Add a pre-session recording control and wire recorder creation, reset/tick capture, and cleanup into the live dashboard lifecycle; verify opt-in behavior and session shutdown/error handling with dashboard tests.
- [ ] 3.2 Document how to enable live recording and where dashboard traces are stored; verify the documented steps match the dashboard controls and artifact path.

## 4. Offline trajectory inspection

- [ ] 4.1 Add telemetry trace discovery and metadata display to the dashboard, including line-level diagnostics while retaining valid samples; verify valid, mixed-validity, and empty-directory states with data-layer tests.
- [ ] 4.2 Add trace and entity selection with position and velocity charts plotted against Godot physics tick; verify plotted series and selectors for both players and the balloon with dashboard tests.
- [ ] 4.3 Document how to open the offline trajectory page and interpret its axes; verify it works from saved telemetry without requiring a running Godot process.

## 5. Integration verification

- [ ] 5.1 Run the relevant project test suite and OpenSpec validation; verify CLI recording, live recording, trace loading, and dashboard charts work together without changing existing episode summary behavior.
