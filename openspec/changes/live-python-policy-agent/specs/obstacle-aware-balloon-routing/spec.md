# Spec Delta

## Purpose

Selects reachable balloon positions using the active arena's real movement and collision data. It keeps the controlled player dash-ready while considering tile rebounds and the moving opponent's effect on route cost.

## ADDED Requirements

### Requirement: Keep a configurable dash-ready distance
The policy SHALL use a preferred balloon distance derived from the active level's dash travel and SHALL keep that distance separate from its minimum no-contact threshold.

#### Scenario: Use active dash movement constants
- **WHEN** no preferred distance override is set and valid `DASH_SPEED` and `DASH_TIME` values are available
- **THEN** the preferred distance is derived from their product and is not hard-coded for one arena

#### Scenario: Configure preferred distance
- **WHEN** a preferred distance override is supplied through policy configuration
- **THEN** the policy uses the override while still enforcing its minimum safe separation

#### Scenario: Dash constants are unavailable
- **WHEN** valid dash movement constants are missing from the active geometry
- **THEN** the policy reports that it cannot derive the default and uses an explicitly configured or documented fallback value

### Requirement: Predict balloon motion through tile collisions
The trajectory predictor SHALL use exported collision geometry that interacts with the balloon to predict rebounds within the bounded prediction horizon.

#### Scenario: Balloon contacts a tile or platform
- **WHEN** a predicted balloon path reaches a solid tile or platform surface
- **THEN** the subsequent positions and velocity reflect the contact using the exported surface geometry

#### Scenario: Balloon contacts an arena boundary
- **WHEN** the predicted path reaches an arena wall
- **THEN** the trajectory includes the rebound and remains inside the playable bounds

#### Scenario: Geometry is missing or invalid
- **WHEN** required collision geometry is unavailable or invalid
- **THEN** the policy reports an explicit prediction status and does not treat an unverified path as a valid intercept

### Requirement: Choose a reachable route around or through the opponent
The policy SHALL treat the opponent as a moving obstacle and select between pushing through and routing around based on estimated travel cost.

#### Scenario: Push-through has the lower travel cost
- **WHEN** current observations indicate a push-through is faster despite its movement slowdown
- **THEN** the policy selects that route and accounts for the slowdown

#### Scenario: Detour has the lower travel cost
- **WHEN** current observations indicate that a detour is faster or safer than a push-through
- **THEN** the policy selects a reachable route around the opponent

#### Scenario: Opponent changes position
- **WHEN** a later observation shows the opponent moved from the position used for the previous decision
- **THEN** the policy recalculates the relative route costs using the new position

### Requirement: Reconsider routes as the balloon rebounds
The policy SHALL select an interception or ready position from the predicted collision-aware trajectory rather than pursuing only the balloon's current position.

#### Scenario: A rebound creates a reachable interception
- **WHEN** a predicted tile or wall rebound produces a reachable interception point
- **THEN** the policy targets that point and identifies the predicted route status

#### Scenario: No interception is reachable
- **WHEN** no predicted contact point is reachable within the horizon
- **THEN** the policy moves toward a reachable recovery position and reports that no interception was found
