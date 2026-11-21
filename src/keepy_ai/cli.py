from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo

from keepy_ai.bridge.errors import CPUBridgeError
from keepy_ai.bridge.models import CPUIntent
from keepy_ai.env.environment import CPUTrainingEnv
from keepy_ai.godot.launcher import GodotConfig, GodotLaunchError, GodotSimulation
from keepy_ai.graph.navigation import (
    NavigationGraph,
    NavigationGraphError,
    load_navigation_graph,
)
from keepy_ai.graph.workflow import CURRENT_LEVELS, generate_graphs
from keepy_ai.policy.brain import decide
from keepy_ai.policy.config import PolicyConfig, load_policy_config


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run-episode",
        description="Run seeded Keepy Uppy episodes through the Godot bridge.",
    )
    parser.add_argument("--godot-bin")
    parser.add_argument("--project-path", type=Path)
    parser.add_argument("--config", type=Path, default=Path.cwd() / "keepy-ai.toml")
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--graph-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "graphs",
        help="directory containing navigation graphs (default: graphs/)",
    )
    parser.add_argument("--level")
    parser.add_argument("--speed", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--episode-count",
        "--episodes",
        dest="episode_count",
        type=_positive_integer,
        default=1,
        help="number of sequential episodes to run",
    )
    parser.add_argument("--mode", choices=("cpu-vs-cpu", "cpu-vs-scripted"))
    parser.add_argument(
        "--policy",
        choices=("adaptive", "neutral"),
        default="adaptive",
        help="action policy (default: adaptive; neutral is a fixed-action baseline)",
    )
    parser.add_argument(
        "--policy-log",
        type=Path,
        help="optional JSONL file for per-observation policy decisions",
    )
    parser.add_argument("--policy-safety-margin", type=float)
    parser.add_argument("--policy-preferred-distance", type=float)
    parser.add_argument("--policy-opponent-push-slowdown", type=float)
    parser.add_argument(
        "--save-episodes",
        action="store_true",
        help="append episode summaries to a dated JSONL file",
    )
    parser.add_argument(
        "--episodes-dir",
        type=Path,
        default=Path.cwd() / "episodes",
        help="directory for dated episode JSONL files (default: episodes/)",
    )
    return parser


def run_episode_batch(
    env: CPUTrainingEnv,
    *,
    episode_count: int,
    seed: int,
    level: str,
    output: TextIO,
    episode_output: TextIO | None = None,
    policy_mode: str = "adaptive",
    policy_config: PolicyConfig | None = None,
    policy_output: TextIO | None = None,
    graph: NavigationGraph | None = None,
    graph_error: str | None = None,
) -> list[dict[str, Any]]:
    if isinstance(episode_count, bool) or not isinstance(episode_count, int) or episode_count <= 0:
        raise ValueError("episode_count must be a positive integer.")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer.")
    if policy_mode not in {"adaptive", "neutral"}:
        raise ValueError("policy_mode must be 'adaptive' or 'neutral'.")
    selected_policy_config = policy_config or PolicyConfig()

    summaries: list[dict[str, Any]] = []
    geometry = None
    for episode_index in range(episode_count):
        episode_seed = seed + episode_index
        env.reset(seed=episode_seed, level=level)
        if policy_mode == "adaptive" and geometry is None:
            geometry = env.get_level_geometry(level)
        steps = 0
        fault_count = 0
        while True:
            decision_log: list[dict[str, Any]] = []
            if policy_mode == "adaptive":
                if geometry is None:
                    raise RuntimeError("Adaptive policy requires level geometry.")

                def select_action(current_observation):
                    decision = decide(
                        current_observation,
                        geometry,
                        selected_policy_config,
                        graph=graph,
                        graph_error=graph_error,
                    )
                    record = {
                        "episode": episode_index,
                        "seed": episode_seed,
                        "level": level,
                        "tick": current_observation.tick,
                        **decision.to_payload(),
                    }
                    decision_log.append(record)
                    return decision.action, record

                result = env.step(action_selector=select_action)
            else:
                result = env.step(CPUIntent())
            observation, _reward, terminated, truncated, info = result
            if policy_output is not None:
                for record in decision_log:
                    policy_output.write(json.dumps(record, sort_keys=True) + "\n")
                    policy_output.flush()
            steps += 1
            fault_count += sum(
                event.type == "fault" for event in info.get("events", [])
            )
            if not terminated and not truncated:
                continue
            terminal_event = info.get("episode_event")
            summary = {
                "seed": episode_seed,
                "level": level,
                "steps": steps,
                "terminated": terminated,
                "truncated": truncated,
                "terminal_reason": info.get("reason"),
                "episode_event": (
                    terminal_event.type if terminal_event is not None else None
                ),
                "faults": fault_count,
                "points": observation.score.points,
                "sets": observation.score.sets,
            }
            line = json.dumps(summary, sort_keys=True) + "\n"
            output.write(line)
            output.flush()
            if episode_output is not None:
                episode_output.write(line)
                episode_output.flush()
            summaries.append(summary)
            break
    return summaries


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cli_values = {
        "godot_bin": args.godot_bin,
        "project_path": args.project_path,
        "port": args.port,
        "level": args.level,
        "speed": args.speed,
        "seed": args.seed,
        "mode": args.mode,
    }
    try:
        config = GodotConfig.resolve(cli_values, config_path=args.config)
        policy_config = load_policy_config(
            args.config,
            {
                "safety_margin": args.policy_safety_margin,
                "preferred_distance": args.policy_preferred_distance,
                "opponent_push_slowdown": args.policy_opponent_push_slowdown,
            },
        )
        graph = None
        graph_error = None
        if args.policy == "adaptive":
            try:
                graph = load_navigation_graph(
                    args.graph_dir / f"{config.level}.json", config.level
                )
            except NavigationGraphError as error:
                graph_error = str(error)
                print(
                    f"run-episode: {error}; using direct movement.",
                    file=sys.stderr,
                )
        date = datetime.now(ZoneInfo("America/Bogota")).date().isoformat()
        episode_file = (
            args.episodes_dir / f"{date}.jsonl" if args.save_episodes else None
        )
        if episode_file is not None:
            episode_file.parent.mkdir(parents=True, exist_ok=True)
        output_context = (
            episode_file.open("a", encoding="utf-8")
            if episode_file is not None
            else nullcontext(None)
        )
        if args.policy_log is not None:
            args.policy_log.parent.mkdir(parents=True, exist_ok=True)
        policy_output_context = (
            args.policy_log.open("a", encoding="utf-8")
            if args.policy_log is not None
            else nullcontext(None)
        )
        with output_context as episode_output, policy_output_context as policy_output, CPUTrainingEnv(
            simulation=GodotSimulation(config)
        ) as env:
            run_episode_batch(
                env,
                episode_count=args.episode_count,
                seed=config.seed,
                level=config.level,
                output=sys.stdout,
                episode_output=episode_output,
                policy_mode=args.policy,
                policy_config=policy_config,
                policy_output=policy_output,
                graph=graph,
                graph_error=graph_error,
            )
    except (CPUBridgeError, GodotLaunchError, ValueError) as error:
        print(f"run-episode: {error}", file=sys.stderr)
        return 1
    return 0


def build_graph_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-graph",
        description="Generate, load, and physically exercise navigation graphs.",
    )
    parser.add_argument("--godot-bin")
    parser.add_argument("--project-path", type=Path)
    parser.add_argument("--config", type=Path, default=Path.cwd() / "keepy-ai.toml")
    parser.add_argument("--port", type=int)
    level_group = parser.add_mutually_exclusive_group()
    level_group.add_argument("--level")
    level_group.add_argument(
        "--all-levels",
        action="store_true",
        help="generate graphs for all four current levels",
    )
    parser.add_argument("--speed", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--graph-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "graphs",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        help="directory for complete JSON reports (default: sibling reports/)",
    )
    parser.add_argument(
        "--geometry-dir",
        type=Path,
        help="directory for exported geometry JSON (default: sibling geometry/)",
    )
    parser.add_argument(
        "--route-step-limit",
        type=_positive_integer,
        default=1800,
        help="maximum physics steps allowed for each route check",
    )
    parser.add_argument("--mode", choices=("cpu-vs-cpu", "cpu-vs-scripted"))
    return parser


def graph_main(argv: list[str] | None = None) -> int:
    args = build_graph_parser().parse_args(argv)
    cli_values = {
        "godot_bin": args.godot_bin,
        "project_path": args.project_path,
        "port": args.port,
        "level": args.level,
        "speed": args.speed,
        "seed": args.seed,
        "mode": args.mode,
    }
    try:
        config = GodotConfig.resolve(cli_values, config_path=args.config)
        levels = (
            CURRENT_LEVELS
            if args.all_levels
            else (args.level or config.level,)
        )
        with GodotSimulation(config) as simulation:
            if simulation.client is None:
                raise GodotLaunchError("Godot started without a bridge client.")
            reports = generate_graphs(
                simulation.client,
                levels,
                graph_directory=args.graph_dir,
                report_directory=args.report_dir,
                geometry_directory=args.geometry_dir,
                seed=config.seed,
                route_step_limit=args.route_step_limit,
            )
        for report in reports:
            print(json.dumps(report, sort_keys=True))
        return 0 if all(report["route_check"]["passed"] for report in reports) else 1
    except (CPUBridgeError, GodotLaunchError, OSError, ValueError) as error:
        print(f"generate-graph: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
