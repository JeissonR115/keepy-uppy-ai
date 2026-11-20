from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from keepy_ai.dashboard.data import (
    DashboardDataError,
    discover_levels,
    load_episode_jsonl,
    load_geometry,
    load_graph,
    load_report,
    report_metrics,
    spatial_view,
)


def _geometry() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "level": "classic",
        "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": 320, "y": 180}},
        "safe_bounds": {
            "position": {"x": 8, "y": 8},
            "size": {"x": 304, "y": 164},
        },
        "spawns": {"player_1": {"x": 72, "y": 152}, "player_2": {"x": 248, "y": 152}},
        "collisions": [
            {
                "source": "floor",
                "collision_layer": 1,
                "one_way": False,
                "shape": {"type": "rectangle", "size": {"x": 320, "y": 16}},
                "transform": {
                    "origin": {"x": 160, "y": 168},
                    "x_axis": {"x": 1, "y": 0},
                    "y_axis": {"x": 0, "y": 1},
                },
            }
        ],
        "platforms": [],
        "movement_constants": {
            "GRAVITY": 1100,
            "JUMP_SPEED": -250,
            "VAR_JUMP_TIME": 0.2,
            "MAX_RUN": 130,
            "DASH_SPEED": 300,
            "DASH_TIME": 0.2,
        },
    }


def _graph() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "level": "classic",
        "nodes": [
            {"id": 1, "position": {"x": 10, "y": 20}},
            {"id": 2, "position": {"x": 30, "y": 20}},
        ],
        "edges": [
            {"from": 1, "to": 2, "action": "WALK", "cost": 1, "bidirectional": True}
        ],
    }


def _report() -> dict[str, Any]:
    return {
        "level": "classic",
        "node_count": 2,
        "edge_counts": {"WALK": 1},
        "discarded_candidates": [],
        "unreachable_node_ids": [],
        "route_check": {"passed": True, "steps": 3},
    }


def _episode(seed: int) -> dict[str, Any]:
    return {
        "seed": seed,
        "level": "classic",
        "steps": 3,
        "terminated": True,
        "truncated": False,
        "terminal_reason": "spikes",
        "episode_event": "point",
        "faults": 1,
        "points": {"player_1": 1, "player_2": 0},
        "sets": {"player_1": 0, "player_2": 0},
    }


def _write(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_discover_and_load_level_artifacts_and_transform(tmp_path: Path) -> None:
    _write(tmp_path / "graphs" / "classic.json", _graph())
    _write(tmp_path / "reports" / "classic.json", _report())
    _write(tmp_path / "geometry" / "classic.json", _geometry())

    discovered = discover_levels(tmp_path)
    graph = load_graph(discovered["classic"]["graph"])
    report = load_report(discovered["classic"]["report"])
    geometry = load_geometry(discovered["classic"]["geometry"])
    view = spatial_view(graph, geometry, report)

    assert set(discovered["classic"]) == {"graph", "report", "geometry"}
    assert view["edges"][0]["x"] == [10, 30]
    assert view["collisions"][0]["source"] == "floor"
    assert report_metrics(report)["route_passed"] is True


def test_discover_reports_partial_artifacts_and_loaders_identify_missing_file(
    tmp_path: Path,
) -> None:
    graph_path = _write(tmp_path / "graphs" / "classic.json", _graph())

    discovered = discover_levels(tmp_path)

    assert discovered["classic"] == {
        "graph": graph_path,
        "report": None,
        "geometry": None,
    }
    with pytest.raises(DashboardDataError, match="cannot read file"):
        load_report(tmp_path / "reports" / "classic.json")


def test_loaders_reject_invalid_json_and_unsupported_schema(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(DashboardDataError, match=r"invalid.json:1: invalid JSON"):
        load_graph(invalid)

    wrong_schema = _graph()
    wrong_schema["schema_version"] = 2
    path = _write(tmp_path / "wrong.json", wrong_schema)
    with pytest.raises(DashboardDataError, match="unsupported graph schema"):
        load_graph(path)

    invalid_geometry = _geometry()
    invalid_geometry["schema_version"] = 2
    with pytest.raises(DashboardDataError, match="invalid geometry"):
        load_geometry(_write(tmp_path / "geometry.json", invalid_geometry))


def test_episode_jsonl_returns_valid_records_and_identifies_bad_lines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "episodes.jsonl"
    path.write_text(
        json.dumps(_episode(1)) + "\nnot json\n{}\n" + json.dumps(_episode(2)),
        encoding="utf-8",
    )

    records, errors = load_episode_jsonl(path)

    assert [record["seed"] for record in records] == [1, 2]
    assert len(errors) == 2
    assert ":2:" in errors[0] and "invalid JSON" in errors[0]
    assert ":3:" in errors[1] and "missing fields" in errors[1]

