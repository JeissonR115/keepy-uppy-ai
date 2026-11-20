from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from keepy_ai.bridge.models import CommandResultMessage, Vector2
from keepy_ai.graph.geometry import NavigationNode, Point
from keepy_ai.graph.workflow import _reachable_destinations, generate_graphs


def _geometry_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "level": "classic",
        "bounds": {"position": {"x": 0, "y": 0}, "size": {"x": 320, "y": 180}},
        "safe_bounds": {
            "position": {"x": 8, "y": 8},
            "size": {"x": 304, "y": 164},
        },
        "spawns": {
            "player_1": {"x": 72, "y": 152},
            "player_2": {"x": 248, "y": 152},
        },
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


def _observation_payload(position: Vector2) -> dict[str, Any]:
    player = {
        "position": {"x": position.x, "y": position.y},
        "velocity": {"x": 0, "y": 0},
        "on_floor": True,
        "wall_contact": 0,
        "dash_cooldown": 0,
        "dash_available": True,
        "stamina": 110,
    }
    return {
        "tick": 1,
        "bot_player": "player_2",
        "players": {"player_1": player, "player_2": player},
        "balloon": {
            "position": {"x": 160, "y": 90},
            "velocity": {"x": 0, "y": 0},
            "waiting_for_first_touch": True,
        },
        "current_turn": "",
        "score": {
            "points": {"player_1": 0, "player_2": 0},
            "sets": {"player_1": 0, "player_2": 0},
        },
        "level": "classic",
    }


class _FakeBridge:
    def __init__(self) -> None:
        self.messages: deque[CommandResultMessage] = deque()
        self.sequence = 0
        self.position = Vector2(248, 152)
        self.graph: dict[str, Any] | None = None
        self.destination_position: Vector2 | None = None

    def _result(self, result: dict[str, Any]) -> int:
        self.sequence += 1
        self.messages.append(CommandResultMessage(self.sequence, result))
        return self.sequence

    def reset(self, seed: int, level: str) -> int:
        assert seed == 17
        assert level == "classic"
        self.position = Vector2(248, 152)
        return self._result({"observation": _observation_payload(self.position)})

    def get_level_geometry(self, level: str) -> int:
        assert level == "classic"
        return self._result(_geometry_payload())

    def probe_movement(self, *_args: Any, **_kwargs: Any) -> int:
        raise AssertionError("A single flat floor should not need movement probes.")

    def load_nav_graph(self, graph: dict[str, Any]) -> int:
        self.graph = graph
        return self._result(
            {"loaded": True, "level": "classic", "node_count": len(graph["nodes"])}
        )

    def set_nav_route(self, level: str, start_node: int, destination_node: int) -> int:
        assert level == "classic"
        assert self.graph is not None
        assert any(node["id"] == start_node for node in self.graph["nodes"])
        destination = next(
            node for node in self.graph["nodes"] if node["id"] == destination_node
        )
        self.destination_position = Vector2(
            destination["position"]["x"], destination["position"]["y"]
        )
        return self._result(
            {
                "route_node_ids": [start_node, destination_node],
                "start_node": start_node,
                "destination_node": destination_node,
            }
        )

    def step(self, n: int) -> int:
        assert self.destination_position is not None
        self.position = self.destination_position
        return self._result(
            {
                "steps": min(n, 2),
                "episode_ended": False,
                "observation": _observation_payload(self.position),
            }
        )

    def receive(self) -> CommandResultMessage:
        return self.messages.popleft()


def test_generate_graph_loads_and_exercises_route_with_fake_bridge(
    tmp_path: Path,
) -> None:
    bridge = _FakeBridge()

    reports = generate_graphs(
        bridge,
        ("classic",),
        graph_directory=tmp_path,
        report_directory=tmp_path / "reports",
        geometry_directory=tmp_path / "geometry",
        seed=17,
        route_step_limit=20,
    )

    graph_path = tmp_path / "classic.json"
    geometry_path = tmp_path / "geometry" / "classic.json"
    report_path = tmp_path / "reports" / "classic.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    persisted_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert graph["schema_version"] == 1
    assert graph["level"] == "classic"
    assert bridge.graph == graph
    assert geometry == _geometry_payload()
    assert persisted_report == reports[0]
    assert reports[0]["route_check"]["passed"] is True
    assert reports[0]["route_check"]["steps"] == 2
    assert reports[0]["graph_path"] == str(graph_path)
    assert reports[0]["geometry_path"] == str(geometry_path)


def test_route_selection_prefers_probe_validated_motion() -> None:
    start = NavigationNode(1, Point(0, 0))
    graph = {
        "level": "fixture",
        "nodes": [
            {"id": 1, "position": {"x": 0, "y": 0}},
            {"id": 2, "position": {"x": 8, "y": 0}},
            {"id": 3, "position": {"x": 32, "y": 0}},
        ],
        "edges": [
            {
                "from": 1,
                "to": 2,
                "action": "WALK",
                "cost": 1,
                "bidirectional": True,
            },
            {"from": 1, "to": 3, "action": "DASH", "cost": 0.9},
        ],
    }

    destinations = _reachable_destinations(graph, start)

    assert [node.id for node in destinations] == [3, 2]
