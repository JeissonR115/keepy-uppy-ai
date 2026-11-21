# Spec Delta

## Purpose

Defines how the Python controlled CPU predicts balloon motion through arena wall rebounds, intercepts during its own turn, and maintains a reachable but no-contact position during the opponent's turn.

## ADDED Requirements

### Requirement: Respond on both turn phases
The policy SHALL produce an action for the controlled bot on every decision observation, using `bot_player` and `current_turn` to distinguish its own turn from the opponent's turn.

#### Scenario: Controlled bot has the expected touch
- **WHEN** an observation identifies the controlled bot as `current_turn`
- **THEN** the policy selects an action intended to reach a safe interception point for the balloon

#### Scenario: Opponent has the expected touch
- **WHEN** an observation identifies the other player as `current_turn`
- **THEN** the policy still returns a positioning action for the controlled bot without requesting a balloon touch

#### Scenario: No turn is assigned
- **WHEN** `current_turn` is empty or does not identify either player
- **THEN** the policy returns a non-contact ready action and reports that its phase is undetermined

### Requirement: Predict wall-rebounded balloon paths
The policy SHALL use the active level's exported playable bounds and the observed balloon position and velocity to predict future balloon positions, reflecting horizontal travel at arena side walls.

#### Scenario: Balloon reaches one side wall
- **WHEN** a predicted horizontal path reaches a playable side boundary within the prediction horizon
- **THEN** subsequent predicted positions reflect the horizontal direction and remain within the arena bounds

#### Scenario: Balloon reaches multiple side walls
- **WHEN** the prediction horizon spans more than one side-wall collision
- **THEN** the predicted path includes each rebound in chronological order

#### Scenario: Geometry is unavailable or inconsistent
- **WHEN** valid playable bounds cannot be obtained for the active level
- **THEN** the policy reports a prediction error and returns a safe fallback action instead of assuming arena dimensions

### Requirement: Intercept the balloon during the bot's turn
During its own turn, the policy SHALL target a predicted balloon position that is reachable by the controlled player and suitable for one intentional contact.

#### Scenario: Reachable rebound interception
- **WHEN** the predicted trajectory contains a reachable contact point after a wall rebound
- **THEN** the policy targets that point rather than pursuing the balloon's current position

#### Scenario: No predicted contact is reachable
- **WHEN** no candidate contact point is reachable within the prediction horizon
- **THEN** the policy moves toward the closest viable recovery position and reports that no interception was found

### Requirement: Maintain a safe defensive distance during the opponent's turn
During the opponent's turn, the policy SHALL position the controlled player near the predicted defensive point while keeping separation greater than the balloon-player contact distance plus a configurable safety margin.

#### Scenario: Defensive point is reachable without contact
- **WHEN** the bot can reach the defensive point outside the minimum safe separation
- **THEN** the policy moves toward that point and does not request jump, dash, or grab actions that would initiate balloon contact

#### Scenario: Balloon is approaching the bot too closely
- **WHEN** predicted motion would bring the balloon inside the minimum safe separation
- **THEN** the policy moves away while remaining within the playable area and reports an evasive defensive action

#### Scenario: Bot is already inside the minimum safe separation
- **WHEN** the current player-balloon separation is below the configured minimum
- **THEN** the policy prioritizes moving away and avoids further contact actions

### Requirement: Enforce a configurable contact-distance band
The policy SHALL use configurable minimum and preferred player-balloon distances so it can remain close enough to reach an interception without entering the accidental-contact zone.

#### Scenario: Player is farther than the preferred range
- **WHEN** the player is outside the preferred distance and approaching a viable intercept
- **THEN** the policy closes distance toward the target while respecting the minimum safe separation

#### Scenario: Player is inside the minimum distance
- **WHEN** the player is closer than the minimum safe separation
- **THEN** the policy selects an action that increases separation before any intentional touch action

### Requirement: Explain policy decisions
For each action, the episode runner SHALL make the policy phase, selected target or prediction status, player-balloon distance, and resulting action available in its run output.

#### Scenario: Inspect an interception decision
- **WHEN** the policy selects a predicted contact point
- **THEN** the run output identifies the own-turn phase, target point, and action

#### Scenario: Inspect a defensive decision
- **WHEN** the policy positions or evades during the opponent's turn
- **THEN** the run output identifies the opponent-turn phase, safe-distance status, and action

### Requirement: Use adaptive policy by default in episode runs
The Python episode runner SHALL use the adaptive balloon policy by default and SHALL allow users to select neutral actions for baseline runs.

#### Scenario: Run with default options
- **WHEN** the user starts an episode without selecting a policy mode
- **THEN** each bridge decision is handled by the adaptive balloon policy

#### Scenario: Select neutral baseline mode
- **WHEN** the user explicitly selects neutral policy mode
- **THEN** the runner replies with neutral actions and does not apply adaptive movement decisions
