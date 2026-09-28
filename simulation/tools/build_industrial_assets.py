"""Blender 4.2 asset authoring; run with blender --background --python FILE.

Original geometry, meters, Z up. Export evaluated beveled triangles and normals
per material so Gazebo and gzweb need no external MTL/texture resolution.
"""

from pathlib import Path
from collections import defaultdict
import json
import math
import xml.etree.ElementTree as ET

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "simulation/ros2_ws/src/kinesis_gazebo/models"
COLORS = {
    "blue": (0.055, 0.20, 0.37, 1),
    "orange": (0.98, 0.33, 0.045, 1),
    "steel": (0.44, 0.49, 0.54, 1),
    "dark": (0.045, 0.06, 0.077, 1),
    "wood": (0.48, 0.29, 0.12, 1),
    "cardboard": (0.65, 0.44, 0.24, 1),
    "tape": (0.82, 0.65, 0.40, 1),
    "label": (0.92, 0.92, 0.87, 1),
    "yellow": (0.98, 0.64, 0.025, 1),
    "green": (0.07, 0.64, 0.37, 1),
    "glass": (0.035, 0.31, 0.39, 1),
}


def finish(obj, color, bevel=0):
    obj["paint"] = color
    if bevel:
        modifier = obj.modifiers.new("Manufactured edge radius", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
    return obj


def box(pos, size, color, bevel=0.008):
    bpy.ops.mesh.primitive_cube_add(size=1, location=pos)
    obj = bpy.context.object
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(obj, color, bevel)


def cylinder(pos, radius, depth, color, axis=None):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32, radius=radius, depth=depth, location=pos
    )
    obj = bpy.context.object
    if axis:
        obj.rotation_euler = Vector(axis).to_track_quat("Z", "Y").to_euler()
    for face in obj.data.polygons:
        face.use_smooth = len(face.vertices) == 4
    return finish(obj, color, 0.004)


def beam(a, b, width, color):
    delta = Vector(b) - Vector(a)
    obj = box((Vector(a) + Vector(b)) / 2, (width, width, delta.length), color, 0.002)
    obj.rotation_euler = delta.to_track_quat("Z", "Y").to_euler()


def lettering(text, pos, size=0.16, color="label", rotation=(math.pi / 2, 0, 0)):
    bpy.ops.object.text_add(location=pos, rotation=rotation)
    obj = bpy.context.object
    obj.data.body = text
    obj.data.size = size
    obj.data.extrude = 0.001
    obj.data.align_x = "CENTER"
    bpy.ops.object.convert(target="MESH")
    finish(bpy.context.object, color)


def pallet(x, y, z):
    for xx in (-0.43, 0, 0.43):
        for yy in (-0.36, 0, 0.36):
            box((x + xx, y + yy, z + 0.075), (0.16, 0.17, 0.12), "wood", 0.006)
    for yy in (-0.36, 0, 0.36):
        box((x, y + yy, z + 0.02), (1.14, 0.16, 0.04), "wood", 0.004)
    for xx in (-0.48, -0.24, 0, 0.24, 0.48):
        box((x + xx, y, z + 0.155), (0.17, 0.96, 0.04), "wood", 0.004)


def carton(x, y, z, sx=0.47, sy=0.43, sz=0.45):
    box((x, y, z + sz / 2), (sx, sy, sz), "cardboard", 0.014)
    box((x, y, z + sz + 0.002), (0.055, sy, 0.004), "tape", 0.001)
    box((x, y - sy / 2 - 0.003, z + sz * 0.62), (0.17, 0.005, 0.105), "label", 0.001)
    for i in range(7):
        box(
            (x - 0.065 + i * 0.02, y - sy / 2 - 0.007, z + sz * 0.62),
            (0.006, 0.003, 0.065),
            "dark",
            0,
        )


def rack():
    for x in (-4.1, -2.05, 0, 2.05, 4.1):
        for y in (-1.16, 1.16):
            box((x, y, 3.2), (0.12, 0.12, 6.4), "blue")
            box((x, y, 0.065), (0.26, 0.26, 0.13), "orange", 0.02)
            for z in (0.22, 1.4, 2.9, 4.4, 5.9):
                cylinder((x, y - 0.066, z), 0.025, 0.016, "steel", (0, 1, 0))
        for z in (0.3, 1.8, 3.3, 4.8):
            beam((x, -1.16, z), (x, 1.16, z + 1.4), 0.035, "steel")
            beam((x, 1.16, z), (x, -1.16, z + 1.4), 0.035, "steel")
    for level, z in enumerate((0.35, 1.85, 3.35, 4.85)):
        for y in (-1.16, 1.16):
            box((0, y, z), (8.3, 0.13, 0.17), "orange")
        for bay, x in enumerate((-3.075, -1.025, 1.025, 3.075)):
            for k in range(6):
                box(
                    (x - 0.85 + k * 0.34, 0, z + 0.02),
                    (0.045, 2.23, 0.04),
                    "steel",
                    0.002,
                )
            for side, y in enumerate((-0.59, 0.59)):
                if (bay + level + side) % 5 == 0:
                    continue
                pallet(x, y, z + 0.08)
                for j in range(2):
                    for k in range(2):
                        carton(
                            x - 0.25 + j * 0.5,
                            y - 0.23 + k * 0.46,
                            z + 0.26,
                            sz=0.48 + 0.12 * ((bay + level) % 3),
                        )
            box((x, -1.239, z), (0.42, 0.012, 0.14), "label", 0.003)
            lettering(f"{level+1:02}-{bay+1:02}", (x, -1.249, z - 0.055), 0.095, "dark")
    for x in (-4.1, 4.1):
        for y in (-1.16, 1.16):
            box((x, y, 0.28), (0.27, 0.28, 0.56), "yellow", 0.025)


def pod():
    box((0, 0, 0.17), (1.30, 1.3, 0.25), "dark", 0.05)
    for x in (-0.62, 0.62):
        for y in (-0.62, 0.62):
            box((x, y, 1.6), (0.055, 0.055, 2.85), "yellow")
    for z in (0.38, 0.91, 1.44, 1.97, 2.5, 2.99):
        box((0, 0, z), (1.3, 1.3, 0.045), "yellow")
    box((0, 0, 1.65), (0.025, 1.28, 2.55), "yellow")
    box((0, 0, 1.65), (1.28, 0.025, 2.55), "yellow")
    for x in (-0.32, 0.32):
        for y in (-0.34, 0.34):
            for z in (0.41, 1.47, 2.53):
                carton(x, y, z, 0.45, 0.47, 0.34)


def conveyor():
    for y in (-0.65, 0.65):
        box((0, y, 0.8), (6, 0.10, 0.24), "steel")
        box((0, y, 1.04), (6, 0.035, 0.14), "orange")
        for x in (-2.6, 0, 2.6):
            box((x, y, 0.39), (0.10, 0.10, 0.78), "blue")
            box((x, y, 0.045), (0.26, 0.22, 0.09), "dark")
    for i in range(36):
        cylinder((-2.9 + i * 0.165, 0, 0.84), 0.062, 1.18, "steel", (0, 1, 0))
    for x in (-1.8, 0.2, 2.2):
        carton(x, 0, 0.91, 0.58, 0.48, 0.45)
    box((0, 0.89, 0.57), (0.48, 0.36, 0.34), "blue", 0.04)


def bench():
    for x in (-0.85, 0.85):
        for y in (-0.45, 0.45):
            box((x, y, 0.48), (0.07, 0.07, 0.96), "steel")
    box((0, 0, 0.96), (2.05, 1.05, 0.085), "wood", 0.02)
    box((-0.65, 0.3, 1.23), (0.06, 0.06, 0.5), "steel")
    box((-0.65, 0.24, 1.49), (0.5, 0.08, 0.34), "dark", 0.025)
    box((-0.65, 0.19, 1.49), (0.44, 0.01, 0.27), "glass", 0.006)
    box((0.65, 0.2, 1.15), (0.39, 0.39, 0.28), "dark", 0.025)
    carton(0, -0.13, 1.01, 0.51, 0.44, 0.38)
    box((0, 0.49, 1.9), (2.05, 0.06, 0.15), "blue")
    lettering("PACK / SCAN", (0, 0.45, 1.85), 0.11)


def cage():
    box((0, 0, 0.18), (1.4, 1.2, 0.10), "steel")
    for x in (-0.62, 0.62):
        for y in (-0.52, 0.52):
            cylinder((x, y, 0.09), 0.085, 0.06, "dark", (0, 1, 0))
            box((x, y, 1.0), (0.035, 0.035, 1.7), "steel", 0.003)
    for z in (0.25, 0.52, 0.79, 1.06, 1.33, 1.6, 1.85):
        for x in (-0.62, 0.62):
            box((x, 0, z), (0.015, 1.08, 0.015), "steel", 0)
        box((0, 0.52, z), (1.25, 0.015, 0.015), "steel", 0)
    for x in (-0.45, -0.22, 0, 0.22, 0.45):
        box((x, 0.52, 1.02), (0.012, 0.012, 1.6), "steel", 0)
    for z in (0.25, 0.72):
        for x in (-0.3, 0.3):
            carton(x, 0, z, 0.5, 0.8, 0.43)


def charger():
    box((0, 0, 0.58), (0.64, 0.33, 1.16), "dark", 0.055)
    box((0, -0.178, 0.65), (0.48, 0.015, 0.64), "blue", 0.012)
    box((0, -0.193, 0.84), (0.23, 0.02, 0.11), "green", 0.008)
    for x in (-0.17, 0.17):
        box((x, -0.23, 0.17), (0.1, 0.14, 0.08), "steel")
    lettering("CHARGE", (0, -0.20, 0.43), 0.075)


def pallet_jack():
    for y in (-0.28, 0.28):
        box((0.42, y, 0.12), (1.6, 0.17, 0.12), "yellow", 0.025)
        cylinder((1.02, y, 0.07), 0.06, 0.13, "dark", (0, 1, 0))
    box((-0.37, 0, 0.24), (0.38, 0.8, 0.30), "yellow", 0.05)
    cylinder((-0.44, 0, 0.11), 0.10, 0.18, "dark", (0, 1, 0))
    beam((-0.44, 0, 0.25), (-0.75, 0, 1.18), 0.055, "dark")
    box((-0.75, 0, 1.18), (0.09, 0.58, 0.07), "dark", 0.025)


def save_model(name, collision, build):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    build()
    target = MODELS / name
    mesh_dir = target / "meshes"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            groups[obj["paint"]].append(obj)
    root = ET.Element("sdf", version="1.10")
    model = ET.SubElement(root, "model", name=name)
    ET.SubElement(model, "static").text = "true"
    link = ET.SubElement(model, "link", name="body")
    co = ET.SubElement(link, "collision", name="envelope")
    ET.SubElement(co, "pose").text = f"0 0 {collision[2]/2} 0 0 0"
    ET.SubElement(ET.SubElement(ET.SubElement(co, "geometry"), "box"), "size").text = (
        " ".join(map(str, collision))
    )
    triangles = 0
    deps = bpy.context.evaluated_depsgraph_get()
    for paint, objects in groups.items():
        rows = ["# Kinesis original Blender geometry; meters, Z up"]
        offset = 1
        for obj in objects:
            evaluated = obj.evaluated_get(deps)
            mesh = evaluated.to_mesh()
            mesh.calc_loop_triangles()
            matrix = obj.matrix_world
            normal_matrix = matrix.to_3x3().inverted().transposed()
            # Split vertices at every corner to preserve exported corner normals.
            for tri in mesh.loop_triangles:
                for loop_id in tri.loops:
                    loop = mesh.loops[loop_id]
                    p = matrix @ mesh.vertices[loop.vertex_index].co
                    n = (
                        normal_matrix @ mesh.corner_normals[loop_id].vector
                    ).normalized()
                    rows.append(f"v {p.x:.6f} {p.y:.6f} {p.z:.6f}")
                    rows.append(f"vn {n.x:.6f} {n.y:.6f} {n.z:.6f}")
                rows.append(
                    "f " + " ".join(f"{i}//{i}" for i in range(offset, offset + 3))
                )
                offset += 3
                triangles += 1
            evaluated.to_mesh_clear()
        (mesh_dir / f"{paint}.obj").write_text("\n".join(rows) + "\n")
        visual = ET.SubElement(link, "visual", name=paint)
        ET.SubElement(
            ET.SubElement(ET.SubElement(visual, "geometry"), "mesh"), "uri"
        ).text = f"model://{name}/meshes/{paint}.obj"
        material = ET.SubElement(visual, "material")
        color = COLORS[paint]
        ET.SubElement(material, "diffuse").text = " ".join(map(str, color))
        ET.SubElement(material, "ambient").text = " ".join(
            map(str, (*[v * 0.7 for v in color[:3]], 1))
        )
        ET.SubElement(material, "specular").text = (
            "0.4 0.4 0.4 1" if paint in ("steel", "glass") else "0.1 0.1 0.1 1"
        )
    ET.indent(root)
    ET.ElementTree(root).write(
        target / "model.sdf", encoding="utf-8", xml_declaration=True
    )
    config = ET.Element("model")
    ET.SubElement(config, "name").text = name
    ET.SubElement(config, "version").text = "1.0.0"
    ET.SubElement(config, "sdf", version="1.10").text = "model.sdf"
    ET.SubElement(config, "description").text = (
        "Original detailed visual mesh with conservative primitive collision envelope."
    )
    ET.ElementTree(config).write(
        target / "model.config", encoding="utf-8", xml_declaration=True
    )
    return {"triangles": triangles, "materials": len(groups), "collision": collision}


if __name__ == "__main__":
    catalog = {}
    for name, size, build in (
        ("fulfillment_rack", (8.45, 2.6, 6.45), rack),
        ("inventory_pod", (1.4, 1.4, 3.05), pod),
        ("roller_conveyor", (6.1, 1.95, 1.2), conveyor),
        ("packing_bench", (2.2, 1.3, 2.05), bench),
        ("roll_cage", (1.5, 1.3, 1.9), cage),
        ("charge_dock", (0.7, 0.6, 1.2), charger),
        ("pallet_jack", (2.9, 0.85, 1.25), pallet_jack),
    ):
        catalog[name] = save_model(name, size, build)
        print(name, catalog[name], flush=True)
    (MODELS / "industrial_catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n"
    )
