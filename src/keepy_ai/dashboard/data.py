from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from keepy_ai.bridge.errors import CPUBridgeProtocolError
from keepy_ai.graph.geometry import LevelGeometry

ARTIFACT_DIRECTORIES = {
    "graph": "graphs",
    "report": "reports",
    "geometry": "geometry",
}
EPISODE_FIELDS = {
    "seed",
    "level",
    "steps",
    "terminated",
    "truncated",
    "terminal_reason",
    "episode_event",
    "faults",
    "points",
    "sets",
}


class DashboardDataError(ValueError):
    """An artifact is missing or does not match a supported data shape."""


def discover_levels(root: Path) -> dict[str, dict[str, Path | None]]:
    """Discover levels and artifact paths without requiring every file to exist."""
    discovered: dict[str, dict[str, Path | None]] = {}
    for kind, directory in ARTIFACT_DIRECTORIES.items():
        folder = root / directory
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            discovered.setdefault(path.stem, {name: None for name in ARTIFACT_DIRECTORIES})[
                kind
            ] = path
    return discovered


def discover_episodes(root: Path) -> dict[str, Path]:
    folder = root / "episodes"
    if not folder.is_dir():
        return {}
    return {path.stem: path for path in sorted(folder.glob("*.jsonl"))}


def load_graph(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if _integer(payload.get("schema_version"), "schema_version", path) != 1:
        raise DashboardDataError(f"{path}: unsupported graph schema_version.")
    _string(payload.get("level"), "level", path)
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise DashboardDataError(f"{path}: graph nodes and edges must be arrays.")
    node_ids: set[int] = set()
    for index, node in enumerate(nodes):
        name = f"nodes[{index}]"
        if not isinstance(node, dict):
            raise DashboardDataError(f"{path}: {name} must be an object.")
        node_id = _integer(node.get("id"), f"{name}.id", path)
        if node_id in node_ids:
            raise DashboardDataError(f"{path}: duplicate node id {node_id}.")
        node_ids.add(node_id)
        _point(node.get("position"), f"{name}.position", path)
    for index, edge in enumerate(edges):
        name = f"edges[{index}]"
        if not isinstance(edge, dict):
            raise DashboardDataError(f"{path}: {name} must be an object.")
        source = _integer(edge.get("from"), f"{name}.from", path)
        target = _integer(edge.get("to"), f"{name}.to", path)
        if source not in node_ids or target not in node_ids:
            raise DashboardDataError(f"{path}: {name} references an unknown node.")
        _string(edge.get("action"), f"{name}.action", path)
        cost = _number(edge.get("cost"), f"{name}.cost", path)
        if cost <= 0:
            raise DashboardDataError(f"{path}: {name}.cost must be positive.")
        if not isinstance(edge.get("bidirectional", False), bool):
            raise DashboardDataError(f"{path}: {name}.bidirectional must be boolean.")
    return payload


def load_report(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    _string(payload.get("level"), "level", path)
    _integer(payload.get("node_count"), "node_count", path)
    counts = payload.get("edge_counts")
    if not isinstance(counts, dict) or any(
        not isinstance(key, str)
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for key, value in counts.items()
    ):
        raise DashboardDataError(f"{path}: edge_counts must map actions to counts.")
    discarded = payload.get("discarded_candidates")
    unreachable = payload.get("unreachable_node_ids")
    if not isinstance(discarded, list) or not isinstance(unreachable, list):
        raise DashboardDataError(
            f"{path}: discarded_candidates and unreachable_node_ids must be arrays."
        )
    if not isinstance(payload.get("route_check"), dict):
        raise DashboardDataError(f"{path}: route_check must be an object.")
    return payload


def load_geometry(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    try:
        LevelGeometry.from_payload(payload)
    except (CPUBridgeProtocolError, TypeError, ValueError) as error:
        raise DashboardDataError(f"{path}: invalid geometry: {error}") from error
    return payload


def load_episode_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read valid episode summaries and report malformed lines individually."""
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        source = path.open("r", encoding="utf-8")
    except OSError as error:
        raise DashboardDataError(f"{path}: cannot open episode file: {error}") from error
    with source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                _validate_episode(record, path, line_number)
                records.append(record)
            except json.JSONDecodeError as error:
                errors.append(
                    f"{path}:{line_number}: invalid JSON: {error.msg}"
                )
            except DashboardDataError as error:
                errors.append(f"{path}:{line_number}: {error}")
    return records, errors


def spatial_view(
    graph: dict[str, Any], geometry_payload: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """Transform validated artifacts into simple rows suitable for plotting."""
    geometry = LevelGeometry.from_payload(geometry_payload)
    nodes_by_id = {node["id"]: node["position"] for node in graph["nodes"]}
    edges = [
        {
            "from": edge["from"],
            "to": edge["to"],
            "action": edge["action"],
            "cost": edge["cost"],
            "x": [nodes_by_id[edge["from"]]["x"], nodes_by_id[edge["to"]]["x"]],
            "y": [nodes_by_id[edge["from"]]["y"], nodes_by_id[edge["to"]]["y"]],
        }
        for edge in graph["edges"]
    ]
    collisions = [
        {
            "source": collision.source,
            "x": [point.x for point in collision.points],
            "y": [point.y for point in collision.points],
        }
        for collision in (*geometry.collisions, *geometry.platforms)
        if collision.points
    ]
    rejected = []
    for candidate in report["discarded_candidates"]:
        probe = candidate.get("probe", {})
        end = probe.get("landing_position") or probe.get("final_position") or {}
        rejected.append(
            {
                "from": candidate.get("from"),
                "to": candidate.get("to"),
                "action": candidate.get("action"),
                "reason": candidate.get("reason"),
                "x": end.get("x"),
                "y": end.get("y"),
            }
        )
    return {
        "level": graph["level"],
        "bounds": {
            "x": [geometry.bounds.position.x, geometry.bounds.right],
            "y": [geometry.bounds.position.y, geometry.bounds.bottom],
        },
        "collisions": collisions,
        "nodes": graph["nodes"],
        "edges": edges,
        "discarded_candidates": report["discarded_candidates"],
        "rejected_markers": rejected,
        "unreachable_node_ids": report["unreachable_node_ids"],
    }


def report_metrics(report: dict[str, Any]) -> dict[str, Any]:
    route_check = report["route_check"]
    return {
        "level": report["level"],
        "nodes": report["node_count"],
        "edges": sum(report["edge_counts"].values()),
        "edge_counts": report["edge_counts"],
        "discarded": len(report["discarded_candidates"]),
        "unreachable": len(report["unreachable_node_ids"]),
        "route_passed": route_check.get("passed", False),
        "route_steps": route_check.get("steps"),
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except OSError as error:
        raise DashboardDataError(f"{path}: cannot read file: {error}") from error
    except json.JSONDecodeError as error:
        raise DashboardDataError(f"{path}:{error.lineno}: invalid JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise DashboardDataError(f"{path}: top-level JSON value must be an object.")
    return payload


def _validate_episode(value: Any, path: Path, line_number: int) -> None:
    prefix = f"{path}:{line_number}"
    if not isinstance(value, dict):
        raise DashboardDataError(f"{prefix}: record must be an object.")
    missing = EPISODE_FIELDS - value.keys()
    if missing:
        raise DashboardDataError(
            f"{prefix}: missing fields: {', '.join(sorted(missing))}."
        )
    _integer(value["seed"], "seed", path, prefix)
    _string(value["level"], "level", path, prefix)
    for field in ("steps", "faults"):
        number = _integer(value[field], field, path, prefix)
        if number < 0:
            raise DashboardDataError(f"{prefix}: {field} must not be negative.")
    for field in ("terminated", "truncated"):
        if not isinstance(value[field], bool):
            raise DashboardDataError(f"{prefix}: {field} must be boolean.")
    for field in ("terminal_reason", "episode_event"):
        if value[field] is not None and not isinstance(value[field], str):
            raise DashboardDataError(f"{prefix}: {field} must be a string or null.")
    for field in ("points", "sets"):
        if not isinstance(value[field], dict):
            raise DashboardDataError(f"{prefix}: {field} must be an object.")


def _point(value: Any, name: str, path: Path) -> None:
    if not isinstance(value, dict):
        raise DashboardDataError(f"{path}: {name} must be an object.")
    _number(value.get("x"), f"{name}.x", path)
    _number(value.get("y"), f"{name}.y", path)


def _number(value: Any, name: str, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DashboardDataError(f"{path}: {name} must be a finite number.")
    return float(value)


def _integer(
    value: Any, name: str, path: Path, prefix: str | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        location = prefix or str(path)
        raise DashboardDataError(f"{location}: {name} must be an integer.")
    return value


def _string(
    value: Any, name: str, path: Path, prefix: str | None = None
) -> str:
    if not isinstance(value, str) or not value:
        location = prefix or str(path)
        raise DashboardDataError(f"{location}: {name} must be a non-empty string.")
    return value
