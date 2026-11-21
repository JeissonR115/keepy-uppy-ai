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
action without initiating contact.

The balloon trajectory is an approximation. Godot's bridge currently exports
level bounds and player movement constants, but not every balloon physics value
or contact radius. Defaults below match the current game's settings and can be
adjusted in the `[policy]` table of `keepy-ai.toml` or with the CLI distance
options. Decisions can be written to JSONL with `--policy-log PATH`.

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
preferred_distance = 48.0
prediction_horizon = 3.0
max_prediction_steps = 360
player_horizontal_speed = 130.0
player_jump_speed = 250.0
```

The minimum safe distance is `player_contact_radius + player_collision_radius
+ safety_margin`. `preferred_distance` must be at least that large. The
approximate physics settings and distances are included in policy decision
records so a run can be reviewed and tuned. Each record identifies the policy
phase, target or prediction status, predicted time, player-balloon distance,
minimum safe distance, chosen action, and any fallback reason.

For example, run with explicit standoff values and save per-decision records:

```sh
uv run run-episode --level classic --seed 10 \
  --policy adaptive --policy-safety-margin 8 \
  --policy-preferred-distance 48 --policy-log reports/classic-policy.jsonl
```

Use `--policy neutral` to run the fixed neutral-action baseline.
