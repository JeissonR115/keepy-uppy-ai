# Training environment

`CPUTrainingEnv` wraps the version-1 Godot bridge without adding a Gymnasium
dependency. It returns typed `CPUObservation` instances and uses the
Gymnasium-shaped `step()` tuple:

```python
observation, reward, terminated, truncated, info = env.step(action)
```

`reward` is always `0.0` as a provisional placeholder, and `truncated` is
always `False`. These values do not define a training objective.

## One-tick action latency

The bridge asks for an action during a physics tick and consumes the reply on
the following tick. `step(action)` advances one bridge step, replies to the
observation emitted during that step, and returns the state after the
just-completed tick. Therefore the submitted action is queued and has not
affected the returned observation. This is intentionally not Gymnasium
transition alignment.

After reset there is no action observation outstanding. The first call to
`step()` still advances one tick to obtain an observation, replies to it, and
reports `action_queued=True` and `action_applied_to_returned_state=False` in
`info`. Later calls have the same one-tick latency.

`info` includes the requested seed and level, bridge command and observation
sequences, whether an action was queued, all episode events, and (when
terminal) the event and its reason. A `downward_fault_replay` is retained in
`events` but does not set `terminated`; the bridge's `episode_ended` value
controls termination.

Actions may be `CPUIntent` objects or mappings with exactly the six bridge
fields: `horizontal`, `jump`, `dash`, `dash_direction`, `down`, and `grab`.
Invalid actions are rejected before the bridge advances.

The environment accepts either an injected bridge client or a
`GodotSimulation`. A supplied simulation is owned and closed by the
environment. An injected client is external by default; pass `owns_client=True`
to have the environment send the bridge close command and release that socket.

