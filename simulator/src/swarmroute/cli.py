from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from enum import Enum
from typing import Any

from .bench import measure_decision_latency
from .comparison import compare_policies
from .demo import run_consensus_demo, run_demo
from .experiment import FleetExperiment
from .fleet import FleetSimulation, SimulationConfig
from .physics import MotionConfig
from .runtime import replicated_auction_for
from .scenario import load_scenario
from .trials import run_trials


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarmroute-sim")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser(
        "demo", help="run the deterministic vertical-slice scenario"
    )
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument("--compact", action="store_true")
    run = subparsers.add_parser(
        "run", help="run an experiment from a versioned JSON scenario"
    )
    run.add_argument("scenario")
    run.add_argument("--compact", action="store_true")
    run.add_argument("--include-events", action="store_true")
    simulate = subparsers.add_parser(
        "simulate", help="execute a scenario tick by tick with runtime safety checks"
    )
    simulate.add_argument("scenario")
    simulate.add_argument("--max-ticks", type=int, default=240)
    simulate.add_argument("--tick-seconds", type=float, default=5.0)
    simulate.add_argument("--include-events", action="store_true")
    simulate.add_argument("--include-plans", action="store_true")
    simulate.add_argument(
        "--auction",
        choices=["emulated-replicated", "central", "replicated"],
        default="emulated-replicated",
        help=(
            "auction used by the single-process simulator; 'replicated' is a "
            "deprecated alias for 'emulated-replicated'"
        ),
    )
    simulate.add_argument("--compact", action="store_true")
    compare = subparsers.add_parser(
        "compare", help="compare space-time and stop-and-wait policies"
    )
    compare.add_argument("scenario")
    compare.add_argument("--max-ticks", type=int, default=240)
    compare.add_argument("--tick-seconds", type=float, default=5.0)
    compare.add_argument("--bootstrap-samples", type=int, default=10_000)
    compare.add_argument("--compact", action="store_true")

    trials = subparsers.add_parser(
        "trials",
        help="run every policy over randomised layouts of one scenario's workload",
    )
    trials.add_argument("scenario")
    trials.add_argument("--trials", type=int, default=30)
    trials.add_argument("--max-ticks", type=int, default=240)
    trials.add_argument("--tick-seconds", type=float, default=5.0)
    trials.add_argument("--seed", type=int, default=20260904)
    trials.add_argument("--bootstrap-samples", type=int, default=2_000)
    trials.add_argument("--compact", action="store_true")

    latency = subparsers.add_parser(
        "latency", help="measure per-decision planning latency on this machine"
    )
    latency.add_argument("scenario")
    latency.add_argument("--repetitions", type=int, default=30)
    latency.add_argument("--max-ticks", type=int, default=240)
    latency.add_argument("--compact", action="store_true")
    consensus = subparsers.add_parser(
        "consensus-demo", help="run replicated single-task bid gossip"
    )
    consensus.add_argument("--partition", action="store_true")
    consensus.add_argument("--compact", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        result = run_demo(args.seed)
        print(
            json.dumps(
                result,
                default=_json_default,
                allow_nan=False,
                indent=None if args.compact else 2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "run":
        scenario = load_scenario(args.scenario)
        result = FleetExperiment(scenario.warehouse_map, scenario.robots).run(
            scenario.tasks
        )
        payload = {
            "schema_version": "1.0",
            "scenario": scenario.name,
            "seed": scenario.seed,
            "map_version": scenario.warehouse_map.version,
            "metrics": asdict(result.metrics),
            "outcomes": [asdict(outcome) for outcome in result.outcomes],
            "robots": [asdict(robot) for robot in result.robots],
        }
        if args.include_events:
            payload["events"] = [asdict(event) for event in result.events.events]
        print(
            json.dumps(
                payload,
                default=_json_default,
                allow_nan=False,
                indent=None if args.compact else 2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "consensus-demo":
        print(
            json.dumps(
                run_consensus_demo(partition=args.partition),
                default=_json_default,
                allow_nan=False,
                indent=None if args.compact else 2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "simulate":
        scenario = load_scenario(args.scenario)
        auction_kind = (
            "emulated-replicated" if args.auction == "replicated" else args.auction
        )
        auction = (
            replicated_auction_for(scenario)
            if auction_kind == "emulated-replicated"
            else None
        )
        result = FleetSimulation(
            scenario.warehouse_map,
            scenario.robots,
            config=SimulationConfig(
                max_ticks=args.max_ticks,
                planning_horizon_ticks=max(120, args.max_ticks),
                motion=MotionConfig(tick_seconds=args.tick_seconds),
            ),
            auction=auction,
            conflict_zones=scenario.conflict_zones,
        ).run(scenario.tasks, scenario.interventions)
        assignments = []
        for assignment in result.assignments:
            item = {
                "task_id": assignment.task_id,
                "robot_id": assignment.robot_id,
                "auction_epoch": assignment.auction_epoch,
                "assigned_tick": assignment.assigned_tick,
                "pickup_tick": assignment.pickup_tick,
                "dropoff_tick": assignment.dropoff_tick,
                "finish_tick": assignment.finish_tick,
                "score": assignment.score,
            }
            if args.include_plans:
                item["plan"] = [asdict(step) for step in assignment.plan.steps]
            assignments.append(item)
        payload = {
            "schema_version": "1.0",
            "scenario": scenario.name,
            "seed": scenario.seed,
            "map_version": scenario.warehouse_map.version,
            "auction": auction_kind,
            "metrics": asdict(result.metrics),
            "outcomes": [asdict(outcome) for outcome in result.outcomes],
            "assignments": assignments,
            "robots": [asdict(robot) for robot in result.robots],
        }
        if args.include_events:
            payload["events"] = [asdict(event) for event in result.events.events]
        print(
            json.dumps(
                payload,
                default=_json_default,
                allow_nan=False,
                indent=None if args.compact else 2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "compare":
        scenario = load_scenario(args.scenario)
        comparison = compare_policies(
            scenario,
            SimulationConfig(
                max_ticks=args.max_ticks,
                planning_horizon_ticks=max(120, args.max_ticks),
                motion=MotionConfig(tick_seconds=args.tick_seconds),
            ),
            bootstrap_samples=args.bootstrap_samples,
        )
        payload = {
            "schema_version": "1.1",
            "scenario": scenario.name,
            "seed": scenario.seed,
            "policies": {
                name: asdict(run.metrics) for name, run in comparison.runs.items()
            },
            "space_time": asdict(comparison.space_time.metrics),
            "stop_and_wait": asdict(comparison.stop_and_wait.metrics),
            "deltas": [asdict(item) for item in comparison.deltas],
            "completion_rate_difference_percentage_points": (
                comparison.completion_rate_difference_percentage_points
            ),
            "throughput_relative_change_percent": (
                comparison.throughput_relative_change_percent
            ),
            "paired_completed_task_flow_ticks": (
                asdict(comparison.paired_completed_task_flow_ticks)
                if comparison.paired_completed_task_flow_ticks is not None
                else None
            ),
        }
        if comparison.rolling_horizon is not None:
            payload["rolling_horizon"] = asdict(comparison.rolling_horizon.metrics)
        print(
            json.dumps(
                payload,
                default=_json_default,
                allow_nan=False,
                indent=None if args.compact else 2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "trials":
        scenario = load_scenario(args.scenario)
        report = run_trials(
            scenario,
            SimulationConfig(
                max_ticks=args.max_ticks,
                planning_horizon_ticks=max(120, args.max_ticks),
                motion=MotionConfig(tick_seconds=args.tick_seconds),
            ),
            trials=args.trials,
            seed=args.seed,
            bootstrap_samples=args.bootstrap_samples,
        )
        payload = {
            "schema_version": "1.0",
            "scenario": report.scenario,
            "trials": report.trials,
            "seed": report.seed,
            "pairs": [asdict(item) for item in report.pairs],
            "completed_tasks": {
                name: asdict(item) for name, item in report.completed_tasks.items()
            },
            "makespan_ticks": {
                name: asdict(item) for name, item in report.makespan_ticks.items()
            },
            "executed_conflicts": dict(report.executed_conflicts),
        }
        print(
            json.dumps(
                payload,
                default=_json_default,
                allow_nan=False,
                indent=None if args.compact else 2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "latency":
        scenario = load_scenario(args.scenario)
        report = measure_decision_latency(
            scenario,
            SimulationConfig(
                max_ticks=args.max_ticks,
                planning_horizon_ticks=max(120, args.max_ticks),
                schedule_seed=scenario.seed,
            ),
            repetitions=args.repetitions,
        )
        print(
            json.dumps(
                asdict(report),
                default=_json_default,
                allow_nan=False,
                indent=None if args.compact else 2,
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
