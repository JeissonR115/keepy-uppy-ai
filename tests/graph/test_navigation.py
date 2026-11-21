from __future__ import annotations

import json

import pytest

from keepy_ai.graph.geometry import Point
from keepy_ai.graph.navigation import (
    NavigationGraph,
    NavigationGraphError,
    find_route,
    load_navigation_graph,
)


def _graph_payload(level: str = "classic") -> dict:
    return {
        "schema_version": 1,
        "level": level,
        "nodes": [
            {"id": 1, "position": {"x": 0, "y": 0}},
            {"id": 2, "position": {"x": 20, "y": 0}},
            {"id": 3, "position": {"x": 40, "y": 0}},
            {"id": 4, "position": {"x": 100, "y": 0}},
        ],
        "edges": [
            {"from": 1, "to": 2, "action": "WALK", "cost": 1.0, "bidirectional": True},
            {"from": 2, "to": 3, "action": "DASH", "cost": 0.9},
        ],
    }


def test_loads_valid_schema_graph_for_the_active_level(tmp_path) -> None:
    path = tmp_path / "classic.json"
    path.write_text(json.dumps(_graph_payload()), encoding="utf-8")

    graph = load_navigation_graph(path, "classic")
    route = find_route(graph, Point(0, 0), Point(40, 0))

    assert route is not None
    assert route.node_ids == (1, 2, 3)
    assert route.cost == pytest.approx(1.9)
    assert route.first_traversal is not None
    assert route.first_traversal.action == "WALK"
    assert route.waypoint == Point(20, 0)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda graph: graph.update(schema_version=2), "unsupported graph schema"),
        (lambda graph: graph.update(level="sky-towers"), "does not match active level"),
        (
            lambda graph: graph["edges"][0].update(to=99),
            "references an unknown node",
        ),
        (
            lambda graph: graph["nodes"][0]["position"].update(x=float("nan")),
            "must be finite",
        ),
    ],
)
def test_rejects_invalid_or_mismatched_graphs(tmp_path, mutate, message) -> None:
    payload = _graph_payload()
    mutate(payload)
    path = tmp_path / "classic.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(NavigationGraphError, match=message):
        load_navigation_graph(path, "classic")


def test_missing_graph_and_unreachable_target_use_recovery_path(tmp_path) -> None:
    path = tmp_path / "missing.json"
    with pytest.raises(NavigationGraphError, match="cannot read graph"):
        load_navigation_graph(path, "classic")

    graph = NavigationGraph.from_payload(_graph_payload())
    route = find_route(graph, Point(100, 0), Point(0, 0))

    assert route is None

