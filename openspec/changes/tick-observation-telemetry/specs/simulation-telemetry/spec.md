# Spec Delta

## Purpose

Captures real per-tick observations from Godot episodes and live dashboard sessions so movement can be inspected after a run. Recording is opt-in and stored locally as line-oriented JSON.

## ADDED Requirements

### Requirement: Record observations when telemetry is enabled
The project SHALL allow episode runs and live dashboard sessions to opt into recording each completed bridge-step observation.

#### Scenario: Record an episode trace
- **WHEN** `run-episode` is started with telemetry recording enabled
- **THEN** it records each returned observation through the terminal step of that episode

#### Scenario: Include the initial episode state
- **WHEN** an episode trace is opened
- **THEN** it begins with the observation returned by reset before the first physics step

#### Scenario: Record a live session trace
- **WHEN** the user enables telemetry before starting a live dashboard session
- **THEN** the session records the reset observation and each observation returned by Godot while that session is active

#### Scenario: Telemetry recording is disabled
- **WHEN** a run or live session starts without enabling telemetry
- **THEN** it does not create a telemetry file

### Requirement: Persist self-contained telemetry samples
Each telemetry JSONL record SHALL identify its recording, source, level, seed, capture time, Godot physics tick, and observation values for both players and the balloon, including position and velocity components.

#### Scenario: Inspect a stored observation
- **WHEN** a telemetry line is read independently of the running session
- **THEN** it identifies the run and contains the sampled tick, player positions and velocities, and balloon position and velocity

#### Scenario: Keep repeated runs distinguishable
- **WHEN** two recordings use the same level and seed
- **THEN** their records carry different run identifiers and are stored as separate traces

### Requirement: Preserve telemetry records during append and interruption
Telemetry output SHALL use one complete JSON object per line, keep separate runs distinguishable, and preserve completed records when later sampling or shutdown fails.

#### Scenario: Append valid samples
- **WHEN** multiple observations are recorded for one run
- **THEN** each sample is appended as a separate complete JSONL line in tick order

#### Scenario: Stop a recording after a failure
- **WHEN** a live session or episode ends unexpectedly
- **THEN** previously completed telemetry lines remain readable and the active Godot resources are closed
