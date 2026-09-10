#!/usr/bin/env python3
"""Generate browser traces exclusively from the authoritative simulator."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator" / "src"))

from kinesis.domain import Cell  # noqa: E402
from kinesis.fleet import FleetSimulation, SimulationConfig  # noqa: E402
from kinesis.operations import ConflictZone, Intervention, InterventionKind  # noqa: E402
from kinesis.physics import MotionConfig  # noqa: E402
from kinesis.runtime import replicated_auction_for  # noqa: E402
from kinesis.scenario import Scenario, load_scenario  # noqa: E402
from kinesis.trace import TraceMetadata, build_presentation_trace  # noqa: E402


SCENARIO_PATH = ROOT / "simulator/scenarios/fulfillment-large-12.json"
LAYOUT_PATH = ROOT / "simulation/layouts/fulfillment.json"
OUTPUT = ROOT / "presentation/public/data"

NAMES = ("Mochi", "Pixel", "Boba", "Taro", "Bean", "Nori", "Pip", "Miso", "Kiki", "Tofu", "Yuzu", "Pocky")
COLORS = ("#70e1d1", "#ffb37b", "#8bc6ff", "#d7a6ff", "#ffe27a", "#81dc9b", "#ff91ad", "#78a7ff", "#ffa8df", "#9ee8ff", "#ffcb74", "#b9eb8a")
HORIZON = 150


def _metadata(trace_id: str, kind: str, title: str, subtitle: str) -> TraceMetadata:
    return TraceMetadata(trace_id, title, subtitle, kind, tick_seconds=0.42)


def _variants(base: Scenario) -> tuple[tuple[Scenario, TraceMetadata], ...]:
    base = replace(base, tasks=base.tasks[:16])
    blocked = Intervention(
        "blocked-aisle-001", 35, InterventionKind.BLOCK_CELLS,
        cells=(Cell(29, 18),),
    )
    return (
        (
            base,
            _metadata(
                "peer-network",
                "communication",
                "Decentralized communication",
                "Signed position-and-intent messages move directly-to-peer with no central server",
            ),
        ),
        (
            base,
            _metadata(
                "conflict-resolution",
                "conflict",
                "Dynamic conflict resolution",
                "A rejected collision path becomes a reserved, conflict-free crossing",
            ),
        ),
        (
            replace(base, interventions=(blocked,)),
            _metadata(
                "task-rerouting",
                "reroute",
                "Task allocation & rerouting",
                "A blocked aisle invalidates routes and returns work to peer auction",
            ),
        ),
    )


def _run(scenario: Scenario, metadata: TraceMetadata, layout: dict) -> dict:
    zones = scenario.conflict_zones or (
        ConflictZone("crossing-pack", frozenset({Cell(20, 18)}), 3),
        ConflictZone("crossing-outbound", frozenset({Cell(50, 14)}), 3),
        ConflictZone("crossing-rack", frozenset({Cell(36, 26)}), 3),
    )
    result = FleetSimulation(
        scenario.warehouse_map,
        scenario.robots,
        config=SimulationConfig(
            max_ticks=HORIZON,
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
    return build_presentation_trace(
        scenario,
        result,
        metadata,
        origin=tuple(float(value) for value in layout["grid"]["origin"]),
        resolution=float(layout["grid"]["resolution"]),
        duration=HORIZON,
        interventions=scenario.interventions,
        names=dict(zip(robot_ids, NAMES, strict=True)),
        colors=dict(zip(robot_ids, COLORS, strict=True)),
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
    base = load_scenario(SCENARIO_PATH)
    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    variants = _variants(base)
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
        f"validated {len(traces)} authoritative scenarios, "
        f"{len(traces[0]['robots'])} robots, {HORIZON + 1} frames each"
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
