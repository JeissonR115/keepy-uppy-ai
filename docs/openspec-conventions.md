# OpenSpec conventions

This repository is the source of truth for the Python AI project. Keep its change artifacts under `openspec/changes/` and its maintained capabilities under `openspec/specs/`.

- Use the configured `spec-driven` workflow. Proposals name durable capabilities; create one spec per new capability.
- Write specs as observable behavior contracts, with normative requirements and testable WHEN/THEN scenarios.
- Keep design decisions and alternatives in `design.md`; keep implementation and verification steps in checked tasks in `tasks.md`.
- Implement only within this repository. When work also needs a Godot change, create or apply a change in the Godot repository's own OpenSpec root.
- Treat [`../keepy-uppy/docs/cpu-ai-bridge.md`](../../keepy-uppy/docs/cpu-ai-bridge.md) as the sole protocol contract. Do not copy its schema into a second source of truth or assume protocol changes.
- Keep runtime dependencies minimal and do not duplicate Godot movement constants; obtain them from the bridge.
- Validate a completed change with `openspec validate <change> --type change --strict`.
