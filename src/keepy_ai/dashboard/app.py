from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from keepy_ai.bridge.models import (
    CPUIntent,
    CPUObservation,
    CommandResultMessage,
    EpisodeEventMessage,
    ObservationMessage,
)
from keepy_ai.dashboard.data import (
    DashboardDataError,
    discover_episodes,
    discover_levels,
    load_episode_jsonl,
    load_geometry,
    load_graph,
    load_report,
    report_metrics,
    spatial_view,
)
from keepy_ai.godot.launcher import GodotConfig, GodotLaunchError, GodotSimulation


def main() -> None:
    st.set_page_config(page_title="Keepy Uppy AI", layout="wide")
    for key in (
        "live_simulation",
        "live_client",
        "live_observation",
        "live_route",
        "live_root",
        "live_done",
    ):
        st.session_state.setdefault(key, None)
    st.title("Keepy Uppy AI · Inspector")
    project_root = Path(
        st.sidebar.text_input("Carpeta de artefactos", value=str(Path.cwd()))
    ).expanduser()
    page = st.sidebar.radio(
        "Vista", ("Niveles", "Métricas", "Episodios", "En vivo")
    )
    if page == "Niveles":
        show_levels(project_root)
    elif page == "Métricas":
        show_metrics(project_root)
    elif page == "Episodios":
        show_episodes(project_root)
    else:
        show_live(project_root)
    if page != "En vivo":
        _stop_live()


def show_levels(root: Path) -> None:
    st.header("Niveles")
    levels = discover_levels(root)
    if not levels:
        st.info(f"No hay grafos, reportes o geometría en {root}.")
        return
    level = st.selectbox("Nivel", sorted(levels))
    paths = levels[level]
    missing = [name for name, path in paths.items() if path is None]
    if missing:
        st.warning("Faltan artefactos: " + ", ".join(missing))
        st.caption("Genéralos desde la raíz del proyecto con el comando:")
        st.code(f"uv run generate-graph --level {level}", language="bash")
        return
    try:
        graph = load_graph(paths["graph"])
        geometry = load_geometry(paths["geometry"])
        report = load_report(paths["report"])
        for kind, payload in (("grafo", graph), ("geometría", geometry), ("reporte", report)):
            if payload.get("level") != level:
                raise DashboardDataError(
                    f"El archivo de {kind} seleccionado declara el nivel "
                    f"{payload.get('level')!r}, se esperaba {level!r}."
                )
        view = spatial_view(graph, geometry, report)
    except DashboardDataError as error:
        st.error(str(error))
        return

    actions = sorted({edge["action"] for edge in view["edges"]})
    selected_actions = st.multiselect("Acciones", actions, default=actions)
    figure = _level_figure(view, set(selected_actions))
    st.plotly_chart(figure, use_container_width=True)
    left, right = st.columns(2)
    with left:
        st.caption(f"Nodos: {len(view['nodes'])} · Aristas: {len(view['edges'])}")
        st.dataframe(view["nodes"], use_container_width=True)
    with right:
        st.caption(
            f"Descartes: {len(view['discarded_candidates'])} · "
            f"Inalcanzables: {len(view['unreachable_node_ids'])}"
        )
        rejected = [
            {
                "from": item.get("from"),
                "to": item.get("to"),
                "action": item.get("action"),
                "reason": item.get("reason"),
            }
            for item in view["discarded_candidates"]
        ]
        st.dataframe(rejected, use_container_width=True)


def _level_figure(view: dict[str, Any], selected_actions: set[str]) -> go.Figure:
    figure = go.Figure()
    for collision in view["collisions"]:
        x = collision["x"] + [collision["x"][0]]
        y = collision["y"] + [collision["y"][0]]
        figure.add_trace(
            go.Scatter(
                x=x,
                y=y,
                fill="toself",
                fillcolor="rgba(120, 130, 150, 0.28)",
                line={"color": "#79839a"},
                name=collision["source"],
                hovertemplate=f"{collision['source']}<extra></extra>",
            )
        )
    colors = {"WALK": "#5aa9e6", "JUMP": "#70c1b3", "DASH": "#f4a261", "DROP": "#c77dff"}
    for edge in view["edges"]:
        if edge["action"] not in selected_actions:
            continue
        figure.add_trace(
            go.Scatter(
                x=edge["x"],
                y=edge["y"],
                mode="lines",
                line={"color": colors.get(edge["action"], "#888"), "width": 2},
                name=edge["action"],
                legendgroup=edge["action"],
                showlegend=False,
                hovertemplate=(
                    f"{edge['action']} · costo {edge['cost']}<br>"
                    f"{edge['from']} → {edge['to']}<extra></extra>"
                ),
            )
        )
    figure.add_trace(
        go.Scatter(
            x=[node["position"]["x"] for node in view["nodes"]],
            y=[node["position"]["y"] for node in view["nodes"]],
            mode="markers+text",
            text=[str(node["id"]) for node in view["nodes"]],
            textposition="top center",
            marker={
                "size": 9,
                "color": [
                    "#ef476f"
                    if node["id"] in view["unreachable_node_ids"]
                    else "#f2f4f8"
                    for node in view["nodes"]
                ],
            },
            name="Nodos",
            hovertemplate="Nodo %{text}<extra></extra>",
        )
    )
    rejected = [
        marker for marker in view["rejected_markers"]
        if marker["x"] is not None and marker["y"] is not None
    ]
    if rejected:
        figure.add_trace(
            go.Scatter(
                x=[marker["x"] for marker in rejected],
                y=[marker["y"] for marker in rejected],
                mode="markers",
                marker={"symbol": "x", "size": 12, "color": "#ff334f"},
                customdata=[
                    [marker["from"], marker["to"], marker["action"], marker["reason"]]
                    for marker in rejected
                ],
                name="Sondeos descartados",
                hovertemplate=(
                    "Descartado %{customdata[2]} · %{customdata[0]} → "
                    "%{customdata[1]}<br>%{customdata[3]}<extra></extra>"
                ),
            )
        )
    figure.update_layout(
        height=650,
        xaxis_title="X",
        yaxis_title="Y",
        yaxis={"autorange": "reversed", "scaleanchor": "x", "scaleratio": 1},
        legend_title="Elemento",
        hovermode="closest",
    )
    return figure


def show_metrics(root: Path) -> None:
    st.header("Métricas")
    levels = discover_levels(root)
    rows: list[dict[str, Any]] = []
    for level, paths in levels.items():
        if paths["report"] is None:
            continue
        try:
            rows.append(report_metrics(load_report(paths["report"])))
        except DashboardDataError as error:
            st.error(str(error))
    if not rows:
        st.info("No hay reportes válidos para comparar.")
        return
    st.dataframe(rows, use_container_width=True)
    figure = go.Figure()
    actions = sorted({action for row in rows for action in row["edge_counts"]})
    for action in actions:
        figure.add_bar(
            name=action,
            x=[row["level"] for row in rows],
            y=[row["edge_counts"].get(action, 0) for row in rows],
            hovertemplate=f"%{{x}} · {action}: %{{y}}<extra></extra>",
        )
    figure.update_layout(barmode="group", xaxis_title="Nivel", yaxis_title="Aristas")
    st.plotly_chart(figure, use_container_width=True)


def show_episodes(root: Path) -> None:
    st.header("Episodios")
    files = discover_episodes(root)
    if not files:
        st.info(f"No hay historiales JSONL en {root / 'episodes'}.")
        return
    selected = st.selectbox("Archivo", sorted(files, reverse=True))
    try:
        records, errors = load_episode_jsonl(files[selected])
    except DashboardDataError as error:
        st.error(str(error))
        return
    for error in errors:
        st.error(error)
    if not records:
        st.info("El archivo no contiene resúmenes válidos.")
        return
    episode_levels = sorted({record["level"] for record in records})
    selected_levels = st.multiselect(
        "Niveles", episode_levels, default=episode_levels
    )
    records = [record for record in records if record["level"] in selected_levels]
    if not records:
        st.info("No hay episodios para los niveles seleccionados.")
        return
    st.dataframe(records, use_container_width=True)
    figure = go.Figure()
    figure.add_trace(go.Histogram(x=[record["steps"] for record in records], name="Duración"))
    figure.update_layout(xaxis_title="Pasos por episodio", yaxis_title="Episodios")
    st.plotly_chart(figure, use_container_width=True)
    st.metric("Faltas", sum(record["faults"] for record in records))


def show_live(_root: Path) -> None:
    st.header("En vivo")
    try:
        config = GodotConfig.resolve()
    except ValueError as error:
        st.error(f"Configuración de Godot no válida: {error}")
        return
    if not _is_executable(config.godot_bin) or not config.project_path.is_dir():
        st.info(
            "Vista en vivo no disponible: configura GODOT_BIN ejecutable y "
            "GODOT_PROJECT_PATH. Las páginas offline siguen disponibles."
        )
        return
    st.caption(
        f"{config.level} · semilla {config.seed} · velocidad {config.speed:g}× · "
        f"modo {config.mode}"
    )
    if st.session_state.get("live_simulation") is None:
        if st.button("Iniciar simulación", type="primary"):
            try:
                _start_live(config, _root)
                st.rerun()
            except (GodotLaunchError, DashboardDataError, RuntimeError, ValueError) as error:
                _stop_live()
                st.error(f"No se pudo iniciar la sesión: {error}")
        return
    if st.button("Detener simulación"):
        _stop_live()
        st.rerun()
    _render_live_tick()


def _start_live(config: GodotConfig, root: Path) -> None:
    simulation = GodotSimulation(config)
    st.session_state.live_simulation = simulation
    client = simulation.start()
    st.session_state.live_client = client
    reset_sequence = client.reset(seed=config.seed, level=config.level)
    reset_result = _receive_live_result(client, reset_sequence)
    observation = CPUObservation.from_payload(reset_result.get("observation"))
    route: list[int] = []
    paths = discover_levels(root).get(config.level, {})
    if paths.get("graph") is not None:
        graph = load_graph(paths["graph"])
        if graph["level"] != config.level:
            raise DashboardDataError(
                f"El grafo disponible declara el nivel {graph['level']!r}."
            )
        client = simulation.client
        if client is None:
            raise GodotLaunchError("Godot inició sin cliente del puente.")
        sequence = client.load_nav_graph(graph)
        loaded = _receive_live_result(client, sequence)
        if loaded.get("loaded") is not True:
            raise GodotLaunchError("Godot no confirmó la carga del grafo.")
        nodes = graph["nodes"]
        start_node = min(
            nodes,
            key=lambda node: _distance(
                node["position"], observation.players["player_2"].position
            ),
        )
        destination = None
        if paths.get("report") is not None:
            report = load_report(paths["report"])
            destination = report.get("route_check", {}).get("destination_node")
        node_ids = {node["id"] for node in nodes}
        if destination not in node_ids or destination == start_node["id"]:
            destination = next(
                (node["id"] for node in nodes if node["id"] != start_node["id"]),
                None,
            )
        if destination is not None:
            sequence = client.set_nav_route(
                config.level, start_node["id"], destination
            )
            result = _receive_live_result(client, sequence)
            raw_route = result.get("route_node_ids", [])
            if isinstance(raw_route, list) and all(
                isinstance(node_id, int) and not isinstance(node_id, bool)
                for node_id in raw_route
            ):
                route = raw_route
    st.session_state.live_client = client
    st.session_state.live_observation = observation
    st.session_state.live_route = route
    st.session_state.live_root = root
    st.session_state.live_done = False


def _receive_live_result(client: Any, sequence: int) -> dict[str, Any]:
    while True:
        message = client.receive()
        if isinstance(message, (EpisodeEventMessage, ObservationMessage)):
            continue
        if not isinstance(message, CommandResultMessage) or message.sequence != sequence:
            raise GodotLaunchError("El puente respondió fuera de secuencia.")
        return message.result


@st.fragment(run_every=1.0)
def _render_live_tick() -> None:
    client = st.session_state.get("live_client")
    if client is None:
        st.info(
            "No hay una sesión en vivo activa. Inicia la simulación para conectar Godot."
        )
        return
    if st.session_state.get("live_done", False):
        st.warning(
            "La partida terminó. Detén y vuelve a iniciar la simulación para reiniciarla."
        )
        return
    try:
        observation, action_queued, terminated, info = _advance_live_tick(client)
        st.session_state.live_observation = observation
        if terminated:
            st.session_state.live_done = True
    except Exception as error:
        st.error(f"Se perdió la sesión de Godot: {error}")
        _stop_live()
        return

    observation = st.session_state.live_observation
    left, right, balloon = st.columns(3)
    for column, player_name in zip((left, right), ("player_1", "player_2")):
        player = observation.players[player_name]
        with column:
            st.metric(player_name, f"({player.position.x:.1f}, {player.position.y:.1f})")
            st.caption(
                f"velocidad ({player.velocity.x:.1f}, {player.velocity.y:.1f}) · "
                f"suelo {player.on_floor} · dash {player.dash_available} · "
                f"stamina {player.stamina:.0f}"
            )
    with balloon:
        st.metric(
            "Globo",
            f"({observation.balloon.position.x:.1f}, "
            f"{observation.balloon.position.y:.1f})",
        )
        st.caption(
            f"velocidad ({observation.balloon.velocity.x:.1f}, "
            f"{observation.balloon.velocity.y:.1f})"
        )
    control_source = (
        "intención neutral de Python (se aplica en el siguiente tick)"
        if action_queued
        else "controlador activo de Godot"
    )
    st.caption(
        f"Tick {observation.tick} · turno {observation.current_turn or '—'} · "
        f"puntos {observation.score.points} · control: {control_source}"
    )
    if terminated:
        st.warning(f"La partida terminó: {info.get('reason') or 'sin motivo indicado'}.")
    _render_live_route(st.session_state.live_root, observation.level)


def _advance_live_tick(
    client: Any,
) -> tuple[CPUObservation, bool, bool, dict[str, Any]]:
    sequence = client.step(1)
    action_queued = False
    while True:
        message = client.receive()
        if isinstance(message, ObservationMessage):
            client.send_action(message.sequence, CPUIntent())
            action_queued = True
            continue
        if isinstance(message, EpisodeEventMessage):
            continue
        if not isinstance(message, CommandResultMessage) or message.sequence != sequence:
            raise GodotLaunchError("El puente respondió fuera de secuencia durante el paso.")
        result = message.result
        observation = CPUObservation.from_payload(result.get("observation"))
        ended = result.get("episode_ended")
        if not isinstance(ended, bool):
            raise GodotLaunchError("Godot devolvió un indicador episode_ended inválido.")
        return observation, action_queued, ended, result


def _render_live_route(root: Path, level: str) -> None:
    route = st.session_state.get("live_route", [])
    paths = discover_levels(root).get(level, {})
    if not route or paths.get("graph") is None or paths.get("geometry") is None:
        st.info("No hay ruta activa disponible; carga el grafo y la geometría de este nivel.")
        return
    try:
        graph = load_graph(paths["graph"])
        geometry = load_geometry(paths["geometry"])
        report = (
            load_report(paths["report"])
            if paths.get("report") is not None
            else {
                "discarded_candidates": [],
                "unreachable_node_ids": [],
            }
        )
        view = spatial_view(graph, geometry, report)
    except DashboardDataError as error:
        st.error(str(error))
        return
    positions = {node["id"]: node["position"] for node in graph["nodes"]}
    route_nodes = [positions[node_id] for node_id in route if node_id in positions]
    figure = _level_figure(view, {edge["action"] for edge in view["edges"]})
    figure.add_trace(
        go.Scatter(
            x=[point["x"] for point in route_nodes],
            y=[point["y"] for point in route_nodes],
            mode="lines+markers",
            line={"color": "#f8d34f", "width": 5},
            marker={"size": 12, "color": "#f8d34f"},
            name="Ruta activa",
            hovertemplate="Ruta · (%{x}, %{y})<extra></extra>",
        )
    )
    st.plotly_chart(figure, use_container_width=True)
    st.caption(f"Ruta activa: {' → '.join(map(str, route))}")


def _stop_live() -> None:
    simulation = st.session_state.get("live_simulation")
    if simulation is not None:
        try:
            simulation.close()
        except Exception:
            pass
    for key in (
        "live_simulation",
        "live_client",
        "live_observation",
        "live_route",
        "live_root",
        "live_done",
    ):
        st.session_state.pop(key, None)


def _distance(position: dict[str, float], target: Any) -> float:
    return ((position["x"] - target.x) ** 2 + (position["y"] - target.y) ** 2) ** 0.5


def _is_executable(path: str) -> bool:
    candidate = Path(path)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate.is_file() and os.access(candidate, os.X_OK)
    from shutil import which

    return which(path) is not None


if __name__ == "__main__":
    main()
