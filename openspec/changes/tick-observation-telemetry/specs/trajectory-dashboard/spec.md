# Spec Delta

## Purpose

Lets users inspect saved Godot motion traces after a run, comparing actual player and balloon positions and velocities against the simulation tick.

## ADDED Requirements

### Requirement: Discover and validate telemetry traces
The dashboard SHALL discover telemetry JSONL files, validate their supported schema and required observation fields, and identify malformed records by file and line without discarding valid records from the same trace.

#### Scenario: Load a valid trace
- **WHEN** the user selects a telemetry file containing valid samples
- **THEN** the dashboard exposes its run metadata and tick-ordered observations for plotting

#### Scenario: Report malformed trace lines
- **WHEN** one or more lines have invalid JSON, unsupported schema versions, or missing required values
- **THEN** the dashboard identifies each invalid line and continues to show valid samples from that file

### Requirement: Plot motion against simulation time
The dashboard SHALL plot the selected entity's horizontal and vertical position and velocity components against Godot physics tick.

#### Scenario: Inspect a player's motion
- **WHEN** the user selects a trace and either player
- **THEN** the dashboard displays that player's X and Y positions and X and Y velocities over the recorded ticks

#### Scenario: Inspect the balloon's motion
- **WHEN** the user selects the balloon
- **THEN** the dashboard displays the balloon's X and Y positions and X and Y velocities over the recorded ticks

### Requirement: Select traces and entities
The dashboard SHALL let the user select a recording and an entity, and SHALL identify the selected run's level, seed, and source alongside its charts.

#### Scenario: Compare separate recording sessions
- **WHEN** multiple telemetry files are available
- **THEN** the user can choose a run and distinguish its charts by run id, source, level, and seed

#### Scenario: No telemetry is available
- **WHEN** no valid telemetry files are found
- **THEN** the page explains that recording must be enabled during a run and remains usable without Godot
