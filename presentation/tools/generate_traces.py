#!/usr/bin/env python3
"""Generate browser traces exclusively from the authoritative simulator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator" / "src"))

from kinesis.domain import Cell  # noqa: E402
from kinesis.fleet import FleetSimulation, SimulationConfig  # noqa: E402
from kinesis.operations import ConflictZone  # noqa: E402
from kinesis.physics import MotionConfig  # noqa: E402
from kinesis.runtime import replicated_auction_for  # noqa: E402
from kinesis.scenario import Scenario, load_scenario  # noqa: E402
from kinesis.trace import TraceMetadata, build_presentation_trace  # noqa: E402


SCENARIOS = ROOT / "simulator/scenarios"
LAYOUT_PATH = ROOT / "simulation/layouts/fulfillment.json"
OUTPUT = ROOT / "presentation/public/data"

NAMES = ("Mochi", "Pixel", "Boba", "Taro", "Bean", "Nori", "Pip", "Miso", "Kiki", "Tofu", "Yuzu", "Pocky")
COLORS = ("#70e1d1", "#ffb37b", "#8bc6ff", "#d7a6ff", "#ffe27a", "#81dc9b", "#ff91ad", "#78a7ff", "#ffa8df", "#9ee8ff", "#ffcb74", "#b9eb8a")

# Each case is one short, self-contained story on the shared warehouse map:
# every order it announces is also delivered before the timeline ends, and the
# horizon is sized to that story so the run never stops mid-shift. Durations are
# deliberately kept under a minute of playback at 0.8s per tick.
TICK_SECONDS = 0.8
HORIZONS = {"peer-network": 65, "conflict-resolution": 64, "task-rerouting": 50}


def _metadata(trace_id: str, kind: str, title: str, subtitle: str) -> TraceMetadata:
    return TraceMetadata(trace_id, title, subtitle, kind, tick_seconds=TICK_SECONDS)


def _variants() -> tuple[tuple[Scenario, TraceMetadata], ...]:
    """One authored scenario per case, each proving the claim its title makes.

    The three cases used to share a single 16-order workload, which meant the
    conflict case recorded `rejected_plan_conflicts = 0` while claiming to show
    a resolved conflict. Each case now has its own scenario file sized so the
    phenomenon actually occurs and every order is delivered inside the horizon.
    """
    return (
        (
            load_scenario(SCENARIOS / "story-allocation.json"),
            _metadata(
                "peer-network",
                "communication",
                "Who takes the order?",
                "Six orders, no dispatcher: peers bid and the cheapest peer wins each one",
            ),
        ),
        (
            load_scenario(SCENARIOS / "story-conflict.json"),
            _metadata(
                "conflict-resolution",
                "conflict",
                "Two robots, one gap",
                "Five peers squeeze through a single-cell aisle; the overlapping plan is refused",
            ),
        ),
        (
            load_scenario(SCENARIOS / "story-reroute.json"),
            _metadata(
                "task-rerouting",
                "reroute",
                "The aisle just closed",
                "A blocked gap invalidates live routes; the work returns to auction and still lands",
            ),
        ),
    )


def _run(scenario: Scenario, metadata: TraceMetadata, layout: dict) -> dict:
    zones = scenario.conflict_zones or (
        ConflictZone("crossing-pack", frozenset({Cell(20, 18)}), 3),
        ConflictZone("crossing-outbound", frozenset({Cell(50, 14)}), 3),
        ConflictZone("crossing-rack", frozenset({Cell(36, 26)}), 3),
    )
    horizon = HORIZONS[metadata.trace_id]
    result = FleetSimulation(
        scenario.warehouse_map,
        scenario.robots,
        config=SimulationConfig(
            max_ticks=horizon,
            clearance_cells=1.4 / 1.5,
            planning_horizon_ticks=180,
            motion=MotionConfig(
                cell_size_m=float(layout["grid"]["resolution"]),
                tick_seconds=5.0,
            ),
        ),
        auction=replicated_auction_for(scenario),
        conflict_zones=zones,
    ).run(scenario.tasks, scenario.interventions)
    if result.metrics.executed_grid_vertex_conflicts:
        raise RuntimeError(f"{metadata.trace_id}: executed vertex conflict")
    if result.metrics.executed_grid_reverse_edge_conflicts:
        raise RuntimeError(f"{metadata.trace_id}: executed reverse-edge conflict")
    robot_ids = [robot.robot_id for robot in scenario.robots]
    if len(robot_ids) > len(NAMES):
        raise RuntimeError(f"{metadata.trace_id}: more robots than authored names")
    return build_presentation_trace(
        scenario,
        result,
        metadata,
        origin=tuple(float(value) for value in layout["grid"]["origin"]),
        resolution=float(layout["grid"]["resolution"]),
        duration=horizon,
        interventions=scenario.interventions,
        names=dict(zip(robot_ids, NAMES[: len(robot_ids)], strict=True)),
        colors=dict(zip(robot_ids, COLORS[: len(robot_ids)], strict=True)),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument("--scenario", help="generate only one trace id")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="rebuild the manifest from already generated trace files",
    )
    args = parser.parse_args()
    if args.manifest_only:
        _write_manifest()
        print("rebuilt manifest from authoritative traces")
        return 0
    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    variants = _variants()
    if args.scenario:
        variants = tuple(
            item for item in variants if item[1].trace_id == args.scenario
        )
        if not variants:
            parser.error(f"unknown scenario: {args.scenario}")
    traces = [_run(scenario, metadata, layout) for scenario, metadata in variants]
    if not args.check:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for trace in traces:
            (OUTPUT / f"{trace['id']}.json").write_text(
                json.dumps(trace, separators=(",", ":")), encoding="utf-8"
            )
        if args.scenario is None:
            _write_manifest()
    print(
        f"validated {len(traces)} authoritative scenarios: "
        + ", ".join(f"{t['id']} ({len(t['robots'])} robots, {t['duration']} ticks)" for t in traces)
    )
    return 0


def _write_manifest() -> None:
    scenario_ids = ("peer-network", "conflict-resolution", "task-rerouting")
    traces = [
        json.loads((OUTPUT / f"{trace_id}.json").read_text(encoding="utf-8"))
        for trace_id in scenario_ids
    ]
    manifest = {
        "schemaVersion": "2.0",
        "default": "peer-network",
        "scenarios": [
            {
                "id": trace["id"],
                "title": trace["title"],
                "subtitle": trace["subtitle"],
                "file": f"/data/{trace['id']}.json",
                "summary": trace["summary"],
            }
            for trace in traces
        ],
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
