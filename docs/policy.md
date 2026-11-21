# Adaptive balloon policy

`run-episode` uses an adaptive CPU policy by default. Select `--policy neutral`
for a baseline that sends neutral actions. The policy reads the active level
geometry and the bridge observation on each decision.

On the bot's turn, it predicts a bounded path, including side-wall rebounds,
and moves toward the earliest contact point it estimates is reachable. If no
point is reachable, it moves toward the closest recovery position. While the
opponent has the expected touch, it moves to a defensive position near the
projected path, avoids jump/dash/grab, and backs away if the projected closest
approach is inside the minimum safe distance. An empty turn produces a ready
action without initiating contact. When a navigation graph is available,
routes are recalculated for each observation. The policy predicts the opponent's
linear movement over each edge's estimated travel time, adds a configurable
slowdown cost to edges whose predicted occupied area overlaps the route, and
selects the lower-cost detour or push-through route. The selected route status,
node IDs, and next waypoint are included in each decision record.

The balloon trajectory is an approximation. Godot's bridge currently exports
level bounds and player movement constants, but not every balloon physics value
or contact radius. Defaults below match the current game's settings and can be
adjusted in the `[policy]` table of `keepy-ai.toml` or with the CLI distance
options. When `preferred_distance` is omitted, the policy uses
`DASH_SPEED * DASH_TIME` from active-level geometry (60 world pixels with the
current game values). If either dash constant is unavailable, it reports and
uses the documented 48-pixel fallback, clamped to at least the minimum safe
distance. Decisions can be written to JSONL with `--policy-log PATH`.

```toml
[policy]
gravity = 137.2
air_resistance = 0.055
horizontal_damping = 0.08
rebound_strength = 0.28
max_horizontal_speed = 220.0
max_rise_speed = 220.0
max_fall_speed = 90.0
physics_hz = 60.0
balloon_radius = 9.0
player_contact_radius = 16.0
player_collision_radius = 3.0
safety_margin = 8.0
opponent_push_slowdown = 2.5
prediction_horizon = 3.0
max_prediction_steps = 360
player_horizontal_speed = 130.0
player_jump_speed = 250.0
```

The minimum safe distance is `player_contact_radius + player_collision_radius
+ safety_margin`. It is independent of the preferred distance. Set
`preferred_distance` in TOML to override the dash-derived value; the
`--policy-preferred-distance` CLI option takes precedence over TOML. An
override must be at least the minimum safe distance. The approximate physics
settings and effective spacing are included in policy decision records so a
run can be reviewed and tuned. Each record identifies the policy phase, target
or prediction status, predicted time, player-balloon distance, minimum safe
distance, chosen action, and any fallback reason.

Opponent-aware routing uses the graph's edge cost as its movement-cost estimate.
An overlapping edge is multiplied by `opponent_push_slowdown`; the default
`2.5` approximates the cost of pushing through an opponent. The slowdown is a
route-planning estimate, not a change to game physics, and must be at least
`1.0`. Set it in `[policy]` or override it with
`--policy-opponent-push-slowdown`.

The opponent model extrapolates its observed velocity linearly, clamped to
level bounds, during the estimated time to traverse an edge. Player and
opponent are approximated as a combined radius of twice
`player_collision_radius` plus 2 pixels. This model does not simulate the
opponent's own collision response or pushing priority. Balloon collision
prediction likewise uses exported solid geometry and one generic rebound
strength; it does not model material-specific trampolines, one-way surfaces,
or every Godot physics detail. These are bounded route and trajectory estimates,
not guarantees of in-game outcomes.

For example, run with explicit standoff values and save per-decision records:

```sh
uv run run-episode --level classic --seed 10 \
  --policy adaptive --policy-safety-margin 8 \
  --policy-preferred-distance 48 --policy-opponent-push-slowdown 2.5 \
  --policy-log reports/classic-policy.jsonl
```

Use `--policy neutral` to run the fixed neutral-action baseline.
