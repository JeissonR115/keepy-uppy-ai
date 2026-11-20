# Navigation graph geometry

The generator parses geometry returned by the bridge and preserves the
exported movement constants; it does not maintain Python copies of movement
physics values.

Current level exports describe solid rectangle collisions and tile polygons.
The parser transforms local rectangle vertices through each exported affine
transform, and transforms tile points using their center and flip/transpose
flags. Collision entries with `collision_layer=0` are ignored as non-solid
hazard/area shapes. Polygonal collision layers and one-way platform polygons
contribute horizontal top surfaces; adjacent tile edges at the same height
are merged deterministically.

Navigation nodes represent the player's center, not the floor contact point.
The body clearance is inferred per level from each player spawn and its nearest
support surface below; the same derived clearance is used to inset edge nodes
and to place nodes beside wall bases. Spawn points are also retained as graph
nodes. Bounds and safe bounds filter generated support nodes. If a spawn has no
support beneath it, generation fails explicitly rather than guessing a player
size.

V1 supports transformed rectangles, polygonal tile geometry, and segment
descriptors. An unsupported walkable collision shape is an explicit protocol
error. Nodes are sorted by world-space position and assigned stable positive
integer ids.

## Edges and probe validation

Schema-version-one exports contain the `schema_version`, `level`, `nodes`, and
`edges` fields accepted by the Godot bridge. Consecutive nodes on the same
support surface receive bidirectional `WALK` edges. `DROP` edges are directed
from an edge or one-way platform to a lower support when the vertical path is
not blocked by solid geometry.

`JUMP` and `DASH` candidates are bounded using the current level's
`movement_constants` (including `MAX_RUN`, `JUMP_SPEED`, `GRAVITY`,
`VAR_JUMP_TIME`, `DASH_SPEED`, and `DASH_TIME`). A candidate is retained only
when Godot reports that the action started, the player landed, and the landing
is within 8 world-space pixels of the target node. Rejected probes remain in
the report with their complete outcome and rejection reason. V1 emits no
`WALL_JUMP` edges because the bridge probe does not validate that action.
To keep probe runs bounded while preserving directional choices, at most the
nearest candidate per action and source-node quadrant is probed.

Positive edge costs are route preferences (`WALK=1.0`, `DROP=1.1`,
`JUMP=1.2`, `DASH=0.9`), not movement constants or training rewards. The
generation report contains node count, accepted edge counts by action,
discarded probe candidates, and node ids unreachable from both player-spawn
roots.

## CLI and route smoke check

Run `uv run generate-graph --level classic --seed 42` for one level, or add
`--all-levels` to process all four current levels. The command accepts the
same Godot configuration options as `run-episode`, plus `--graph-dir` and
`--route-step-limit` (default 1800 physics steps). Each level is reset with a
deterministic seed, its geometry is exported, and its movement candidates are
probed by Godot. After Godot accepts the generated graph, it is atomically
written as `graphs/<level>.json`.

The route smoke check starts at the graph node nearest player 2's reset
position, prefers a reachable route using a probe-validated non-WALK edge,
asks Godot for the selected route, and advances the simulation in bounded
batches. When no such edge is reachable, it falls back to the nearest distinct
reachable node. Arrival uses Godot's 8-pixel radius with a 0.01-pixel allowance
for floating-point physics values. The JSON report printed for each
level includes per-action edge counts, every rejected probe and its outcome,
unreachable node ids, the selected route node ids, step count, and distance to
the destination. A route that ends early or exceeds the step limit is reported
as failed, and the CLI exits non-zero.

