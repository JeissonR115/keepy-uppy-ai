# Spec Delta

## Purpose

Allows the Python policy to control a live Godot match over the existing local bridge. The client answers game observations without taking ownership of match setup or simulation stepping.

## ADDED Requirements

### Requirement: Attach to a live match
The Python live client SHALL connect to a configured Godot bridge session and SHALL not launch, reset, or step the simulation.

#### Scenario: Connect from the game launcher
- **WHEN** Godot starts the Python live client with a valid loopback address and port
- **THEN** the client completes the protocol handshake and waits for live match messages

#### Scenario: Preserve episode runner behavior
- **WHEN** a caller uses the existing `run-episode` command
- **THEN** the client continues to launch and control the headless simulation as before

### Requirement: Obtain geometry for the active level
Before making a route-dependent decision, the live client SHALL request level geometry from the connected game and SHALL use geometry matching the observed level.

#### Scenario: Load active arena geometry
- **WHEN** the bridge returns geometry for the current match level
- **THEN** the client makes that geometry available to the policy for its decisions

#### Scenario: Geometry does not match the match
- **WHEN** the returned geometry level differs from the observed level or the request fails
- **THEN** the client reports an explicit bridge or protocol error and does not use mismatched geometry

### Requirement: Answer each live observation
For each valid observation, the Python live client SHALL send one action using the same session and observation sequence.

#### Scenario: Return a matching action
- **WHEN** the client receives an observation for the controlled bot
- **THEN** it computes a policy decision and sends all required action fields with that observation's sequence

#### Scenario: Turn changes
- **WHEN** an observation reports a different expected balloon toucher
- **THEN** the policy receives the updated turn and decides from the current state

### Requirement: Report live-client failures explicitly
The live client SHALL report connection, protocol, geometry, and policy failures and SHALL close its resources when the session ends.

#### Scenario: Bridge disconnects
- **WHEN** the game closes the bridge or the connection is interrupted
- **THEN** the client exits with a diagnostic and releases its socket

#### Scenario: Invalid observation or action
- **WHEN** an observation cannot be parsed or the selected action is invalid
- **THEN** the client reports the error and does not send a partial action
