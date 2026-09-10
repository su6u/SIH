"""Generate physical world, planner map, and spawn contract from one layout.

All ground obstacles register a collision envelope. Planner cells are inflated
by the robot envelope; detailed static assets never silently become traversable.
"""

from pathlib import Path
import json
import math
import random
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
GAZEBO = ROOT / "simulation/ros2_ws/src/kinesis_gazebo"
LAYOUT = ROOT / "simulation/layouts/fulfillment.json"


def child(parent, tag, text=None, **attrs):
    result = ET.SubElement(parent, tag, attrs)
    if text is not None:
        result.text = str(text)
    return result


def numbers(values):
    return " ".join(f"{v:.5g}" for v in values)


def inside(x, y, polygon):
    result = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (
            b[1] - a[1]
        ) + a[0]:
            result = not result
    return result


def generate():
    layout = json.loads(LAYOUT.read_text())
    catalog = json.loads((GAZEBO / "models/industrial_catalog.json").read_text())
    randomizer = random.Random(layout["seed"])
    sdf = ET.Element("sdf", version="1.10")
    world = child(sdf, "world", name="kinesis_warehouse")
    physics = child(world, "physics", name="warehouse_physics", type="ignored")
    child(physics, "max_step_size", 0.002)
    child(physics, "real_time_factor", 1)
    for system in ("Physics", "UserCommands", "SceneBroadcaster", "Sensors"):
        filenames = {
            "Physics": "physics",
            "UserCommands": "user-commands",
            "SceneBroadcaster": "scene-broadcaster",
            "Sensors": "sensors",
        }
        plugin = child(
            world,
            "plugin",
            name="gz::sim::systems::" + system,
            filename="gz-sim-" + filenames[system] + "-system",
        )
        if system == "Sensors":
            child(plugin, "render_engine", "ogre2")
    child(world, "gravity", "0 0 -9.81")
    scene = child(world, "scene")
    child(scene, "ambient", ".55 .58 .63 1")
    child(scene, "background", ".055 .075 .10 1")
    child(scene, "shadows", "true")
    light = child(world, "light", type="directional", name="daylight")
    child(light, "direction", "-.4 .25 -1")
    child(light, "diffuse", ".8 .85 .95 1")
    child(light, "specular", ".2 .2 .2 1")
    child(light, "cast_shadows", "true")
    obstacles = []
    instances = []

    def model(name):
        item = child(world, "model", name=name)
        child(item, "static", "true")
        return child(item, "link", name="structure")

    architecture = model("warehouse_architecture")
    markings = model("floor_markings")

    def box(link, name, pos, size, color, collision=False, alpha=1, yaw=0):
        visual = child(link, "visual", name=name)
        child(visual, "pose", numbers((*pos, 0, 0, yaw)))
        child(child(child(visual, "geometry"), "box"), "size", numbers(size))
        material = child(visual, "material")
        child(material, "diffuse", numbers((*color, 1)))
        child(material, "ambient", numbers((*[v * 0.7 for v in color], 1)))
        child(material, "specular", ".35 .4 .45 1")
        if alpha < 1:
            child(visual, "transparency", 1 - alpha)
        if collision:
            co = child(link, "collision", name=name + "_collision")
            child(co, "pose", numbers((*pos, 0, 0, yaw)))
            child(child(child(co, "geometry"), "box"), "size", numbers(size))
            if pos[2] - size[2] / 2 < 0.8:
                sx = abs(math.cos(yaw)) * size[0] + abs(math.sin(yaw)) * size[1]
                sy = abs(math.sin(yaw)) * size[0] + abs(math.cos(yaw)) * size[1]
                obstacles.append(
                    [pos[0] - sx / 2, pos[1] - sy / 2, pos[0] + sx / 2, pos[1] + sy / 2]
                )
        return visual

    def asset(kind, name, x, y, yaw=0):
        include = child(world, "include")
        child(include, "uri", "model://" + kind)
        child(include, "name", name)
        child(include, "pose", numbers((x, y, 0, 0, 0, yaw)))
        sx, sy, sz = catalog[kind]["collision"]
        dx = abs(math.cos(yaw)) * sx / 2 + abs(math.sin(yaw)) * sy / 2
        dy = abs(math.sin(yaw)) * sx / 2 + abs(math.cos(yaw)) * sy / 2
        bounds = [x - dx, y - dy, x + dx, y + dy]
        obstacles.append(bounds)
        instances.append(
            {"kind": kind, "name": name, "pose": [x, y, yaw], "bounds": bounds}
        )

    for i, (x1, y1, x2, y2) in enumerate(layout["floor_sections"]):
        # Floor top at zero avoids spawning robots embedded in the floor.
        floor = model(f"warehouse_floor_{i}")
        box(
            floor,
            "slab",
            ((x1 + x2) / 2, (y1 + y2) / 2, -0.12),
            (x2 - x1, y2 - y1, 0.24),
            (0.32, 0.35, 0.38),
        )
        co = child(floor, "collision", name="slab_collision")
        child(co, "pose", numbers(((x1 + x2) / 2, (y1 + y2) / 2, -0.12, 0, 0, 0)))
        child(
            child(child(co, "geometry"), "box"),
            "size",
            numbers((x2 - x1, y2 - y1, 0.24)),
        )

    # Glass facade, dark mullions, concrete plinth and steel roof-edge girders.
    polygon = layout["footprint"]
    for i, (a, b) in enumerate(zip(polygon, polygon[1:] + polygon[:1])):
        length = math.dist(a, b)
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        box(
            architecture,
            f"plinth_{i}",
            (*mid, 0.18),
            (length, 0.20, 0.36),
            (0.18, 0.22, 0.27),
            True,
            yaw=angle,
        )
        box(
            architecture,
            f"glass_{i}",
            (*mid, 2.1),
            (length, 0.055, 3.6),
            (0.10, 0.47, 0.59),
            True,
            0.18,
            angle,
        )
        box(
            architecture,
            f"parapet_{i}",
            (*mid, 7.6),
            (length, 0.35, 0.55),
            (0.10, 0.16, 0.23),
            yaw=angle,
        )
        for j in range(math.ceil(length / 6) + 1):
            t = j / math.ceil(length / 6)
            x = a[0] + (b[0] - a[0]) * t
            y = a[1] + (b[1] - a[1]) * t
            box(
                architecture,
                f"column_{i}_{j}",
                (x, y, 3.8),
                (0.22, 0.22, 7.6),
                (0.13, 0.18, 0.23),
                True,
            )
            box(
                architecture,
                f"mullion_{i}_{j}",
                (x, y, 2.1),
                (0.10, 0.10, 3.6),
                (0.08, 0.12, 0.16),
            )

    for row, y in enumerate(layout["rack_y"]):
        for col, x in enumerate(layout["rack_x"]):
            asset("fulfillment_rack", f"rack_{row:02}_{col:02}", x, y)
            # End-of-aisle labels and rack exclusion boundary paint.
            for side in (-1, 1):
                box(
                    markings,
                    f"rack_line_{row}_{col}_{side}",
                    (x, y + side * 1.9, 0.014),
                    (9.1, 0.07, 0.012),
                    (0.95, 0.63, 0.025),
                )

    # Pick modules: compact yellow tote pods in the eastern workcell.
    for i, x in enumerate((61.5, 64.5, 67.5)):
        for j, y in enumerate((0, 3, 6)):
            asset("inventory_pod", f"pod_{i}_{j}", x, y)
    # Packing and induction stations feed two conveyor spines.
    for i, y in enumerate((12, 16.5, 21, 25.5)):
        asset("packing_bench", f"packing_{i}", 64.5, y, math.pi / 2)
    for i, y in enumerate((13.5, 19.5, 25.5)):
        asset("roller_conveyor", f"conveyor_{i}", 69, y, math.pi / 2)
    for i, x in enumerate((15, 21, 27, 33, 39, 45)):
        asset("roller_conveyor", f"sortation_{i}", x, -10.2)

    # Northern annex: maintenance equipment and twelve charging docks.
    for i in range(12):
        asset("charge_dock", f"charger_{i+1:02}", -15 + i * 2.1, 52.4)
        x = -15 + i * 2.1
        for side in (-1, 1):
            box(
                markings,
                f"charge_line_{i}_{side}",
                (x + side * 0.8, 50.9, 0.014),
                (0.04, 2.6, 0.012),
                (0.08, 0.74, 0.49),
            )
    for i in range(4):
        asset("roll_cage", f"receiving_cage_{i}", -15, 43.5 + i * 1.7)
    asset("pallet_jack", "service_jack", 7.5, 48)

    # Staged dispatch containers and occasional floor equipment.
    for i in range(6):
        asset("roll_cage", f"dispatch_cage_{i}", 48 + i * 3, -8.5)
    for i, (x, y) in enumerate(((-15, 6), (57, 18), (33, 30))):
        asset("pallet_jack", f"pallet_jack_{i}", x, y, math.pi / 2)
    # Fixed guards protect crossings; each is included in the planner obstacle map.
    for i, x in enumerate((-16, 10, 34, 58)):
        for j, y in enumerate((5, 17, 29)):
            box(
                architecture,
                f"guard_{i}_{j}",
                (x, y, 0.45),
                (0.2, 1.8, 0.9),
                (0.96, 0.58, 0.025),
                True,
            )
    # Segmented dock seals, shutter slats, warning bumpers on south elevation.
    for i, x in enumerate((-10, 2, 54, 65)):
        box(
            architecture,
            f"dock_{i}",
            (x, -11.86, 2.4),
            (3.5, 0.14, 4.2),
            (0.27, 0.31, 0.36),
        )
        for j in range(14):
            box(
                architecture,
                f"dock_slat_{i}_{j}",
                (x, -11.7, 0.5 + j * 0.28),
                (3.35, 0.06, 0.025),
                (0.48, 0.52, 0.55),
            )
        for dx in (-1.9, 1.9):
            box(
                architecture,
                f"dock_seal_{i}_{dx}",
                (x + dx, -11.64, 2.4),
                (0.28, 0.30, 4.65),
                (0.045, 0.065, 0.09),
            )
            box(
                architecture,
                f"dock_bumper_{i}_{dx}",
                (x + dx, -11.5, 0.6),
                (0.32, 0.35, 0.8),
                (0.96, 0.58, 0.025),
                True,
            )
        box(
            architecture,
            f"dock_lintel_{i}",
            (x, -11.64, 4.8),
            (4.1, 0.3, 0.25),
            (0.96, 0.58, 0.025),
        )

    # White concrete expansion joints, yellow transit arteries and pedestrian route.
    for i, x in enumerate(range(-15, 70, 6)):
        for j, y in enumerate(range(-9, 52, 6)):
            if inside(x, y, polygon):
                box(
                    markings,
                    f"joint_{i}_{j}",
                    (x, y, 0.004),
                    (5.94, 0.014, 0.006),
                    (0.23, 0.25, 0.27),
                )
    for i, y in enumerate((6, 18, 30)):
        for side in (-1, 1):
            box(
                markings,
                f"artery_{i}_{side}",
                (20, y + side * 2, 0.012),
                (74, 0.08, 0.014),
                (0.96, 0.66, 0.045),
            )
        for j, x in enumerate(range(-12, 59, 5)):
            box(
                markings,
                f"dash_{i}_{j}",
                (x, y, 0.012),
                (1.6, 0.08, 0.014),
                (0.85, 0.88, 0.89),
            )
    box(
        markings,
        "pedestrian_green",
        (-16, 20, 0.008),
        (1.0, 60, 0.01),
        (0.03, 0.32, 0.26),
    )
    for y in (6, 18, 30):
        for j in range(7):
            box(
                markings,
                f"crosswalk_{y}_{j}",
                (9, y - 1.8 + j * 0.6, 0.018),
                (2, 0.30, 0.014),
                (0.92, 0.92, 0.85),
            )
    # Hanging high-bay luminaire housings; only daylight casts shadows in browser.
    for x in (-9, 9, 27, 45, 63):
        for y in (-3, 9, 21, 33):
            if not inside(x, y, polygon):
                continue
            visual = box(
                architecture,
                f"highbay_{x}_{y}",
                (x, y, 7.2),
                (2.1, 0.55, 0.12),
                (0.9, 0.94, 1),
            )
            child(visual.find("material"), "emissive", ".7 .75 .85 1")
            for dx in (-0.8, 0.8):
                box(
                    architecture,
                    f"hanger_{x}_{y}_{dx}",
                    (x + dx, y, 7.6),
                    (0.025, 0.025, 0.8),
                    (0.15, 0.19, 0.23),
                )

    grid = layout["grid"]
    origin = grid["origin"]
    res = grid["resolution"]
    clearance = grid["clearance"]
    blocked = set()
    for iy in range(grid["height"]):
        for ix in range(grid["width"]):
            x, y = origin[0] + ix * res, origin[1] + iy * res
            if not all(
                inside(x + dx, y + dy, polygon)
                for dx in (-clearance, clearance)
                for dy in (-clearance, clearance)
            ) or any(
                x1 - clearance <= x <= x2 + clearance
                and y1 - clearance <= y <= y2 + clearance
                for x1, y1, x2, y2 in obstacles
            ):
                blocked.add((ix, iy))
    free = {
        (ix, iy) for ix in range(grid["width"]) for iy in range(grid["height"])
    } - blocked

    def nearest(x, y):
        return min(
            free,
            key=lambda c: (
                (origin[0] + c[0] * res - x) ** 2 + (origin[1] + c[1] * res - y) ** 2,
                c,
            ),
        )

    robots = []
    spawns = {}
    for i in range(layout["robot_count"]):
        cell = nearest(-15 + i * 4.5, -6)
        name = f"robot_{i+1:02}"
        robots.append({"id": name, "cell": list(cell), "battery_soc": 0.97})
        x, y = origin[0] + cell[0] * res, origin[1] + cell[1] * res
        spawns[name] = [x, y, 0]
        include = child(world, "include")
        child(include, "uri", "model://kinesis_amr")
        child(include, "name", name)
        child(include, "pose", numbers((x, y, 0.26, 0, 0, 0)))
    station_targets = [
        (-12, -6),
        (0, -6),
        (51, -4.5),
        (66, -4.5),
        (60, 12),
        (60, 21),
        (-9, 45),
        (3, 45),
        (-9, 6),
        (15, 18),
        (39, 30),
        (51, 30),
    ]
    stations = [nearest(x, y) for x, y in station_targets]
    for i, (ix, iy) in enumerate(stations):
        x, y = origin[0] + ix * res, origin[1] + iy * res
        box(
            markings,
            f"station_pad_{i}",
            (x, y, 0.01),
            (1.3, 1.3, 0.012),
            (0.035, 0.30, 0.42),
        )
    tasks = []
    for i in range(layout["task_count"]):
        a, b = randomizer.sample(stations, 2)
        tasks.append(
            {
                "id": f"fc_order_{i+1:03}",
                "pickup": list(a),
                "dropoff": list(b),
                "release_tick": i // 4 * 5,
                "deadline_tick": 340,
                "payload_kg": randomizer.choice((80, 140, 220, 320)),
                "service_ticks": 2,
            }
        )
    conflict_zones = [
        {
            "id": zone_id,
            "cells": [list(nearest(x, y))],
            "lease_ttl_ticks": 3,
        }
        for zone_id, x, y in (
            ("crossing-pack", 15, 18),
            ("crossing-outbound", 60, 12),
            ("crossing-rack", 39, 30),
        )
    ]
    scenario = {
        "schema_version": "1.0",
        "name": "fulfillment-large-12",
        "seed": layout["seed"],
        "map": {
            "width": grid["width"],
            "height": grid["height"],
            "version": "fc-stepped-v1",
            "blocked": [list(c) for c in sorted(blocked)],
            "blocked_rectangles": [],
        },
        "conflict_zones": conflict_zones,
        "robots": robots,
        "tasks": tasks,
    }
    contract = {
        "layout": layout,
        "spawns": spawns,
        "obstacles": obstacles,
        "instances": instances,
        "stations": [list(s) for s in stations],
    }
    ET.indent(sdf)
    ET.ElementTree(sdf).write(
        GAZEBO / "worlds/warehouse_fulfillment.sdf",
        encoding="utf-8",
        xml_declaration=True,
    )
    (GAZEBO / "config/fulfillment_contract.json").write_text(
        json.dumps(contract, indent=2) + "\n"
    )
    (ROOT / "simulator/scenarios/fulfillment-large-12.json").write_text(
        json.dumps(scenario, indent=2) + "\n"
    )
    print(
        f"Generated {len(instances)} equipment models, {len(obstacles)} collision envelopes, {len(free)} free cells, {len(robots)} robots, {len(tasks)} tasks"
    )


if __name__ == "__main__":
    generate()
