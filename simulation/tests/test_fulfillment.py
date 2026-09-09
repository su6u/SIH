"""Physical scene/planner contracts for the expanded fulfillment environment."""

from collections import deque
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
GAZEBO = ROOT / "simulation/ros2_ws/src/swarmroute_gazebo"
WORLD = GAZEBO / "worlds/warehouse_fulfillment.sdf"
CONTRACT = GAZEBO / "config/fulfillment_contract.json"
SCENARIO = ROOT / "simulator/scenarios/fulfillment-large-12.json"


class FulfillmentContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text())
        cls.scenario = json.loads(SCENARIO.read_text())
        cls.world = ET.parse(WORLD).find("world")
        cls.grid = cls.contract["layout"]["grid"]
        cls.blocked = {tuple(c) for c in cls.scenario["map"]["blocked"]}
        cls.free = {
            (x, y) for x in range(cls.grid["width"]) for y in range(cls.grid["height"])
        } - cls.blocked

    def test_robot_spawns_use_shared_grid_transform(self):
        includes = {i.findtext("name"): i for i in self.world.findall("include")}
        for robot in self.scenario["robots"]:
            cell = robot["cell"]
            expected = [
                self.grid["origin"][i] + cell[i] * self.grid["resolution"]
                for i in (0, 1)
            ]
            pose = list(map(float, includes[robot["id"]].findtext("pose").split()))
            self.assertEqual(pose[:2], expected)
            self.assertEqual(self.contract["spawns"][robot["id"]][:2], expected)
            # Wheel bottom must start above floor, then settle through physics.
            self.assertGreater(pose[2] - 0.06 - 0.16, 0)

    def test_all_robot_and_task_cells_are_connected(self):
        start = tuple(self.scenario["robots"][0]["cell"])
        visited = {start}
        queue = deque([start])
        while queue:
            x, y = queue.popleft()
            for cell in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if cell in self.free and cell not in visited:
                    visited.add(cell)
                    queue.append(cell)
        targets = [r["cell"] for r in self.scenario["robots"]]
        targets += [
            t[key] for t in self.scenario["tasks"] for key in ("pickup", "dropoff")
        ]
        for target in targets:
            self.assertIn(tuple(target), visited)

    def test_free_cells_clear_every_physical_obstacle(self):
        clearance = self.grid["clearance"]
        for ix, iy in self.free:
            x, y = [
                self.grid["origin"][i] + (ix, iy)[i] * self.grid["resolution"]
                for i in (0, 1)
            ]
            for x1, y1, x2, y2 in self.contract["obstacles"]:
                self.assertFalse(
                    x1 - clearance <= x <= x2 + clearance
                    and y1 - clearance <= y <= y2 + clearance
                )

    def test_equipment_collisions_match_registered_envelopes(self):
        import math

        for item in self.contract["instances"]:
            model = ET.parse(GAZEBO / "models" / item["kind"] / "model.sdf")
            sx, sy, _ = map(
                float,
                model.findtext("./model/link/collision/geometry/box/size").split(),
            )
            x, y, yaw = item["pose"]
            dx = abs(math.cos(yaw)) * sx / 2 + abs(math.sin(yaw)) * sy / 2
            dy = abs(math.sin(yaw)) * sx / 2 + abs(math.cos(yaw)) * sy / 2
            for actual, expected in zip(
                item["bounds"], (x - dx, y - dy, x + dx, y + dy)
            ):
                self.assertAlmostEqual(actual, expected)

    def test_cutouts_are_not_traversable_and_glass_is_preserved(self):
        # East loading recess and north central cutout, not a rectangular floor.
        for x, y in ((66, 36), (30, 48)):
            cell = tuple(
                round((value - self.grid["origin"][i]) / self.grid["resolution"])
                for i, value in enumerate((x, y))
            )
            self.assertIn(cell, self.blocked)
        glass = self.world.findall("./model/link/visual[@name='glass_0']")
        self.assertEqual(len(glass), 1)
        self.assertAlmostEqual(float(glass[0].findtext("transparency")), 0.82)
        robot = ET.parse(GAZEBO / "models/swarmroute_amr/model.sdf")
        self.assertIsNotNone(robot.find(".//visual[@name='front_sensor_window']"))

    def test_all_external_meshes_resolve_locally(self):
        kinds = {i["kind"] for i in self.contract["instances"]} | {"swarmroute_amr"}
        for kind in kinds:
            model = ET.parse(GAZEBO / "models" / kind / "model.sdf")
            for uri in model.findall(".//mesh/uri"):
                self.assertTrue(uri.text.startswith("model://"))
                self.assertTrue(
                    (GAZEBO / "models" / uri.text.removeprefix("model://")).is_file()
                )

    def test_regeneration_is_deterministic(self):
        paths = (WORLD, CONTRACT, SCENARIO)
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        spec = importlib.util.spec_from_file_location(
            "fulfillment_generator", ROOT / "simulation/tools/generate_fulfillment.py"
        )
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        generator.generate()
        self.assertEqual(
            before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        )
