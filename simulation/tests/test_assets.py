from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


REPOSITORY = Path(__file__).parents[2]
SCENARIO = REPOSITORY / "simulator" / "scenarios" / "warehouse-12.json"
GAZEBO = REPOSITORY / "simulation" / "ros2_ws" / "src" / "kinesis_gazebo"
WORLD = GAZEBO / "worlds" / "warehouse_12.sdf"
AMR = GAZEBO / "models" / "kinesis_amr" / "model.sdf"
AMR_MESH = GAZEBO / "models" / "kinesis_amr" / "meshes" / "amr_shell.obj"
RACK = GAZEBO / "models" / "kinesis_rack" / "model.sdf"


class AssetContractTest(unittest.TestCase):
    def test_all_xml_assets_are_well_formed(self) -> None:
        xml_files = tuple((REPOSITORY / "simulation" / "ros2_ws" / "src").rglob("*.xml"))
        sdf_files = tuple((REPOSITORY / "simulation" / "ros2_ws" / "src").rglob("*.sdf"))
        launch_files = tuple(
            (REPOSITORY / "simulation" / "ros2_ws" / "src").rglob("*.gzlaunch")
        )
        self.assertGreater(len(xml_files) + len(sdf_files) + len(launch_files), 0)
        for path in xml_files + sdf_files + launch_files:
            with self.subTest(path=path):
                ET.parse(path)

    def test_websocket_is_localhost_only_and_connection_limited(self) -> None:
        compose = (REPOSITORY / "simulation" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        websocket = ET.parse(GAZEBO / "config" / "websocket.gzlaunch").getroot()
        plugin = websocket.find("./plugin")
        self.assertIsNotNone(plugin)
        self.assertEqual(plugin.findtext("port"), "9002")
        self.assertEqual(plugin.findtext("max_connections"), "4")
        self.assertIn('"127.0.0.1:9002:9002"', compose)

    def test_world_spawns_match_scenario_robots(self) -> None:
        scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
        root = ET.parse(WORLD).getroot()
        includes = root.findall("./world/include")
        robot_includes = {
            item.findtext("name"): item
            for item in includes
            if (item.findtext("name") or "").startswith("robot_")
        }
        self.assertEqual(set(robot_includes), {robot["id"] for robot in scenario["robots"]})
        for robot in scenario["robots"]:
            pose = [float(value) for value in robot_includes[robot["id"]].findtext("pose").split()]
            expected_x = -15.0 + robot["cell"][0] * 1.5
            expected_y = -9.0 + robot["cell"][1] * 1.5
            self.assertAlmostEqual(pose[0], expected_x)
            self.assertAlmostEqual(pose[1], expected_y)

    def test_world_contains_all_rack_obstacles(self) -> None:
        scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
        root = ET.parse(WORLD).getroot()
        racks = [
            item
            for item in root.findall("./world/include")
            if (item.findtext("name") or "").startswith("rack_")
        ]
        self.assertEqual(len(racks), len(scenario["map"]["blocked_rectangles"]))

    def test_bridge_declares_command_and_odometry_for_every_robot(self) -> None:
        bridge = (GAZEBO / "config" / "bridge.yaml").read_text(encoding="utf-8")
        for index in range(1, 13):
            name = f"robot_{index:02d}"
            self.assertIn(f"/{name}/cmd_vel", bridge)
            self.assertIn(f"/{name}/odometry", bridge)

    def test_amr_separates_detailed_visuals_from_collision_geometry(self) -> None:
        root = ET.parse(AMR).getroot()
        collision_box = root.find("./model/link/collision/geometry/box/size")
        mesh_uri = root.findtext("./model/link/visual/geometry/mesh/uri")
        self.assertIsNotNone(collision_box)
        self.assertEqual(mesh_uri, "model://kinesis_amr/meshes/amr_shell.obj")
        self.assertTrue(AMR_MESH.is_file())
        vertex_count = sum(
            line.startswith("v ")
            for line in AMR_MESH.read_text(encoding="utf-8").splitlines()
        )
        self.assertGreaterEqual(vertex_count, 200)

    def test_amr_physical_contract_matches_the_motion_model(self) -> None:
        root = ET.parse(AMR).getroot()
        self.assertEqual(float(root.findtext("./model/link/inertial/mass")), 150.0)
        plugin = root.find("./model/plugin[@name='gz::sim::systems::DiffDrive']")
        self.assertIsNotNone(plugin)
        self.assertEqual(float(plugin.findtext("wheel_radius")), 0.10)
        self.assertEqual(float(plugin.findtext("wheel_separation")), 0.55)

    def test_rack_has_industrial_visual_detail_and_simple_collision(self) -> None:
        root = ET.parse(RACK).getroot()
        self.assertIsNotNone(root.find("./model/link/collision/geometry/box/size"))
        visual_names = {
            visual.get("name") for visual in root.findall("./model/link/visual")
        }
        self.assertGreaterEqual(len(visual_names), 35)
        for required in ("post_nw", "beam_n_4", "deck_4", "pallet_a", "guard_se"):
            self.assertIn(required, visual_names)

    def test_world_contains_industrial_architecture_and_high_bay_lighting(self) -> None:
        root = ET.parse(WORLD).getroot()
        light_names = {light.get("name") for light in root.findall("./world/light")}
        self.assertGreaterEqual(len(light_names), 7)
        details = root.find("./world/model[@name='warehouse_details']/link")
        self.assertIsNotNone(details)
        visual_names = {visual.get("name") for visual in details.findall("./visual")}
        for required in ("pedestrian_lane", "crosswalk_1", "dock_door_1", "fixture_ne"):
            self.assertIn(required, visual_names)


if __name__ == "__main__":
    unittest.main()
