from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from keepy_ai.bridge.client import CPUBridgeClient
from keepy_ai.bridge.errors import CPUBridgeError, CPUBridgeProtocolError
from keepy_ai.bridge.models import (
    CommandResultMessage,
    EpisodeEventMessage,
    ObservationMessage,
)
from keepy_ai.graph.geometry import LevelGeometry
from keepy_ai.graph.navigation import (
    NavigationGraph,
    NavigationGraphError,
    load_navigation_graph,
)
from keepy_ai.policy.brain import decide
from keepy_ai.policy.config import PolicyConfig, load_policy_config


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


def _nonnegative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    return parsed


def _port(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run-live",
        description="Connect the Python policy to an interactive Godot match.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=_port, default=8765)
    parser.add_argument("--timeout", type=_positive_float, default=10.0)
    parser.add_argument("--level", required=True)
    parser.add_argument(
        "--config", type=Path, default=Path.cwd() / "keepy-ai.toml"
    )
    parser.add_argument(
        "--graph-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "graphs",
    )
    parser.add_argument("--policy-safety-margin", type=_nonnegative_float)
    parser.add_argument("--policy-preferred-distance", type=_positive_float)
    parser.add_argument("--policy-opponent-push-slowdown", type=_positive_float)
    return parser


def run_live_client(
    client: CPUBridgeClient,
    *,
    level: str,
    policy_config: PolicyConfig,
    graph: NavigationGraph | None = None,
    graph_error: str | None = None,
) -> None:
    geometry_sequence = client.get_level_geometry(level)
    geometry: LevelGeometry | None = None
    while True:
        message = client.receive()
        if isinstance(message, EpisodeEventMessage):
            continue
        if isinstance(message, CommandResultMessage):
            if geometry is not None or message.sequence != geometry_sequence:
                raise CPUBridgeProtocolError(
                    "Received an unexpected command result in the live session."
                )
            geometry = LevelGeometry.from_payload(message.result)
            if geometry.level != level:
                raise CPUBridgeProtocolError(
                    f"Geometry returned {geometry.level!r}, expected {level!r}."
                )
            continue
        if not isinstance(message, ObservationMessage):
            raise CPUBridgeProtocolError(
                f"Unsupported live bridge message: {type(message).__name__}."
            )
        if geometry is None:
            raise CPUBridgeProtocolError(
                "The live bridge requested an action before returning level geometry."
            )
        if message.observation.level != geometry.level:
            raise CPUBridgeProtocolError(
                f"Observation level {message.observation.level!r} does not match "
                f"loaded geometry {geometry.level!r}."
            )
        decision = decide(
            message.observation,
            geometry,
            policy_config,
            graph=graph,
            graph_error=graph_error,
        )
        if decision.prediction_status == "invalid_geometry":
            raise CPUBridgeProtocolError(
                f"Policy cannot use the active level geometry: {decision.reason}."
            )
        client.send_action(message.sequence, decision.action)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        policy_config = load_policy_config(
            args.config,
            {
                "safety_margin": args.policy_safety_margin,
                "preferred_distance": args.policy_preferred_distance,
                "opponent_push_slowdown": args.policy_opponent_push_slowdown,
            },
        )
        try:
            graph = load_navigation_graph(
                args.graph_dir / f"{args.level}.json", args.level
            )
            graph_error = None
        except NavigationGraphError as error:
            graph = None
            graph_error = str(error)
            print(
                f"run-live: {error}; using direct movement.",
                file=sys.stderr,
            )
        with CPUBridgeClient(
            host=args.host,
            port=args.port,
            timeout=args.timeout,
        ) as client:
            run_live_client(
                client,
                level=args.level,
                policy_config=policy_config,
                graph=graph,
                graph_error=graph_error,
            )
    except (CPUBridgeError, OSError, ValueError) as error:
        print(f"run-live: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
