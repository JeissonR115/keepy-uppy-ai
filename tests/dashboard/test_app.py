from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_dashboard_pages_render_sample_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("streamlit")
    pytest.importorskip("plotly")
    from streamlit.testing.v1 import AppTest

    graph = {
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
    geometry = {
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
        "movement_constants": {"GRAVITY": 1100, "JUMP_SPEED": -250},
    }
    report = {
        "level": "classic",
        "node_count": 2,
        "edge_counts": {"WALK": 1},
        "discarded_candidates": [],
        "unreachable_node_ids": [],
        "route_check": {"passed": True, "steps": 3},
    }
    episode = {
        "seed": 5,
        "level": "classic",
        "steps": 10,
        "terminated": True,
        "truncated": False,
        "terminal_reason": "spikes",
        "episode_event": "point",
        "faults": 1,
        "points": {"player_1": 1, "player_2": 0},
        "sets": {"player_1": 0, "player_2": 0},
    }
    for directory, payload in (
        ("graphs", graph),
        ("geometry", geometry),
        ("reports", report),
    ):
        folder = tmp_path / directory
        folder.mkdir()
        (folder / "classic.json").write_text(json.dumps(payload), encoding="utf-8")
    episodes = tmp_path / "episodes"
    episodes.mkdir()
    (episodes / "2026-11-20.jsonl").write_text(
        json.dumps(episode) + "\n", encoding="utf-8"
    )

    monkeypatch.setenv("GODOT_BIN", "missing-godot-for-dashboard-test")
    monkeypatch.setenv("GODOT_PROJECT_PATH", str(tmp_path / "missing-project"))
    app_path = Path(__file__).resolve().parents[2] / "src/keepy_ai/dashboard/app.py"
    app = AppTest.from_file(app_path).run()
    assert not app.exception
    app.sidebar.text_input[0].set_value(str(tmp_path))
    app.run()
    assert not app.exception

    for page in ("Métricas", "Episodios", "En vivo"):
        app.sidebar.radio[0].set_value(page)
        app.run()
        assert not app.exception
    assert app.session_state["live_client"] is None

