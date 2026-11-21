# Design

## Context

The current bridge server accepts one TCP client and rejects a second connection while that client is active. The interactive match also has a separate `run-live` policy client, while the dashboard Live page owns a headless `GodotSimulation`, issues `reset`/`step`, and sends neutral intents. Directly adding a dashboard connection to port 8766 would therefore replace or compete with the policy client.

## Goals / Non-Goals

**Goals:**

- Attach the dashboard to an existing interactive match on a configurable loopback host and port.
- Keep match ownership with Godot and keep policy execution with `run-live`.
- Display current observations and the latest policy decision, including route nodes and waypoint.
- Preserve the dashboard's offline pages and the existing headless runner.

**Non-Goals:**

- Replace or act as the policy controller.
- Send reset, step, close, or gameplay action commands from the dashboard.
- Guarantee delivery of decisions for every tick over a lossy or disconnected connection.
- Change learned-policy behavior or routing algorithms.

## Decisions

### Add an observer connection role

The bridge SHALL distinguish controller and observer sessions. The existing Python live client remains the controller. The dashboard connects as an observer and receives broadcast observations and policy decision records.

Godot SHALL continue accepting only one controller and SHALL retain a bounded set of observer connections. Observer actions and simulation-control commands SHALL be rejected or ignored. The observer role SHALL not disconnect or replace the controller.

An observer is an alternative to the second connection if the existing TCP server cannot be extended safely: the live client could expose the observation/decision stream on a local dashboard port. Observer-role is preferred because it gives the dashboard and policy one shared match session.

### Broadcast validated observations

For every valid controller observation, Godot SHALL publish an observer copy with the existing session and observation sequence. The observer uses the same typed observation model as the policy client and applies level/schema validation before rendering.

The observer does not request or advance simulation ticks. Its refresh rate is network delivery, with UI state retained when no new observation arrives.

### Publish policy decisions with observation sequence

`run-live` SHALL attach each `PolicyDecision.to_payload()` record to the sequence of the observation that produced it and publish it to observer connections. The dashboard SHALL use sequence matching to pair decisions to observations and SHALL mark unmatched or stale decisions explicitly.

The policy decision already exposes `action`, `target`, `route_status`, `route_node_ids`, and `route_waypoint`; no policy duplicate or re-calculation is needed for the live view.

### Configure the dashboard attach target

The Live page SHALL read a host and port from environment or dashboard configuration, defaulting to `127.0.0.1` and `8766`. It SHALL show connection status, retry errors, and a disconnected state. It SHALL not check `GODOT_BIN` or launch Godot while attach mode is active.

If no attach target is available, the page SHALL report a missing or unavailable bridge and SHALL keep offline pages usable.

### Render bounded live state

The dashboard SHALL retain only the latest observation and decision plus a bounded recent history for route/turn context. Invalid observations, mismatched sessions, malformed telemetry, and stale decisions SHALL not replace the last validated state silently.

The route plot SHALL overlay graph nodes and edges with the latest `route_node_ids` and highlight `route_waypoint`. The action panel SHALL show exact action fields and route/prediction status.

## Risks / Trade-offs

- [The current bridge accepts only one client] → Implement explicit controller/observer roles or use a separate local telemetry stream; do not let the dashboard displace the policy.
- [Observer delivery can lag or arrive out of sequence] → Validate session and sequence, retain last-good state, and mark stale telemetry.
- [Decision publication changes the live protocol] → Version and validate the observer message shape; keep headless and live-controller messages backward compatible.
- [Multiple dashboard tabs create competing observers] → Bound observer connections and expose an explicit disconnected state.
- [The interactive match closes or changes level] → Validate level changes and clear stale route/decision state.

## Migration Plan

1. Keep the existing Live page behavior available only until observer support is implemented.
2. Add and test read-only observer sessions in the paired Godot bridge.
3. Add policy-decision publication to `run-live`.
4. Switch the dashboard Live page from `GodotSimulation` ownership to bridge attachment.
5. Test the interactive match, disconnects, malformed data, and repeated dashboard connections.
6. Roll back by restoring the previous Live-page launcher mode; no episode or graph migration is required.
