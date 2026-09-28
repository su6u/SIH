"""Create the editable art-detail version of FC-01 in Blender 4.2.

Uses the saved SDF import as its base. Presentation detail is kept separately
from the Gazebo collision model. All artwork and shaders are generated locally.
"""

from pathlib import Path
import json
import math
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "simulation/previews"
BASE = OUT / "kinesis-fulfillment.blend"
DEST = OUT / "kinesis-fulfillment-detailed.blend"
CONTRACT = (
    ROOT / "simulation/ros2_ws/src/kinesis_gazebo/config/fulfillment_contract.json"
)


def collection(name):
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def relocate(obj, col):
    for previous in list(obj.users_collection):
        previous.objects.unlink(obj)
    col.objects.link(obj)
    return obj


def shader(name, color, rough=0.4, metal=0, coat=0, transmission=0, glow=0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, 1)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    for key, value in {
        "Base Color": (*color, 1),
        "Roughness": rough,
        "Metallic": metal,
        "Coat Weight": coat,
        "Coat Roughness": 0.16,
        "Transmission Weight": transmission,
        "IOR": 1.46,
        "Emission Color": (*color, 1),
        "Emission Strength": glow,
    }.items():
        bsdf.inputs[key].default_value = value
    return mat


def grain(mat, scale, strength, distance, colors=None):
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 3
    coords = nodes.new("ShaderNodeTexCoord")
    links.new(coords.outputs["Object"], noise.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    bsdf = nodes.get("Principled BSDF")
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if colors:
        ramp = nodes.new("ShaderNodeValToRGB")
        for point, color in zip(ramp.color_ramp.elements, colors):
            point.color = (*color, 1)
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])


def finish(obj, name, mat, col, bevel=0):
    obj.name = name
    obj.data.materials.append(mat)
    if bevel:
        modifier = obj.modifiers.new("Machined edge radii", "BEVEL")
        modifier.width, modifier.segments = bevel, 8
        modifier = obj.modifiers.new("Weighted surface normals", "WEIGHTED_NORMAL")
        modifier.keep_sharp = True
    return relocate(obj, col)


def box(name, pos, size, mat, col, bevel=0.006):
    bpy.ops.mesh.primitive_cube_add(size=1, location=pos)
    obj = bpy.context.object
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(obj, name, mat, col, bevel)


def cylinder(name, pos, radius, depth, mat, col, axis=(0, 0, 1), vertices=64):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth, location=pos
    )
    obj = bpy.context.object
    obj.rotation_euler = Vector(axis).to_track_quat("Z", "Y").to_euler()
    for polygon in obj.data.polygons:
        polygon.use_smooth = len(polygon.vertices) == 4
    return finish(obj, name, mat, col, 0.0015)


def curve(name, points, radius, mat, col):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.bevel_depth, data.bevel_resolution = radius, 3
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, xyz in zip(spline.points, points):
        point.co = (*xyz, 1)
    obj = bpy.data.objects.new(name, data)
    col.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def text(name, body, pos, size, mat, col, rotation=(math.pi / 2, 0, 0)):
    data = bpy.data.curves.new(name, "FONT")
    data.body, data.size, data.align_x, data.align_y = body, size, "CENTER", "CENTER"
    data.extrude = 0.0003
    obj = bpy.data.objects.new(name, data)
    obj.location, obj.rotation_euler = pos, rotation
    col.objects.link(obj)
    data.materials.append(mat)
    return obj


def sticker(name, center, radius, style, col, mats):
    """Original raised vinyl motif on a surface facing -Y."""
    x, y, z = center
    items = [
        cylinder(name + " vinyl", center, radius, 0.0014, mats["cream"], col, (0, 1, 0))
    ]
    if style == "heart":
        points = []
        for i in range(65):
            t = 2 * math.pi * i / 64
            points.append(
                (
                    x + radius * 0.046 * 16 * math.sin(t) ** 3,
                    y - 0.0016,
                    z
                    + radius
                    * 0.046
                    * (
                        13 * math.cos(t)
                        - 5 * math.cos(2 * t)
                        - 2 * math.cos(3 * t)
                        - math.cos(4 * t)
                    ),
                )
            )
        items.append(curve(name + " heart", points, radius * 0.065, mats["pink"], col))
    elif style == "star":
        points = [
            (
                x
                + (radius * 0.65 if i % 2 == 0 else radius * 0.29)
                * math.sin(i * math.pi / 5),
                y - 0.0016,
                z
                + (radius * 0.65 if i % 2 == 0 else radius * 0.29)
                * math.cos(i * math.pi / 5),
            )
            for i in range(11)
        ]
        items.append(curve(name + " star", points, radius * 0.065, mats["orange"], col))
    else:
        for side in (-1, 1):
            items.append(
                cylinder(
                    name + " eye",
                    (x + side * radius * 0.26, y - 0.002, z + radius * 0.20),
                    radius * 0.08,
                    0.001,
                    mats["ink"],
                    col,
                    (0, 1, 0),
                    24,
                )
            )
        items.append(
            curve(
                name + " smile",
                [
                    (
                        x + radius * 0.39 * math.cos(t),
                        y - 0.002,
                        z - radius * 0.02 + radius * 0.39 * math.sin(t),
                    )
                    for t in [math.pi + i * math.pi / 20 for i in range(21)]
                ],
                radius * 0.055,
                mats["ink"],
                col,
            )
        )
    return items


def robot(col, m):
    # Local axes match the AMR: +X forward, Y wheel axle, floor at Z=0.
    box(
        "BUDDY | cast aluminium lower chassis",
        (0, 0, 0.20),
        (0.92, 0.72, 0.25),
        m["metal"],
        col,
        0.08,
    )
    box(
        "BUDDY | mint enamel floating shell",
        (0, 0, 0.32),
        (0.94, 0.73, 0.20),
        m["mint"],
        col,
        0.085,
    )
    box(
        "BUDDY | rubber perimeter bumper",
        (0, 0, 0.18),
        (0.97, 0.76, 0.09),
        m["rubber"],
        col,
        0.037,
    )
    box(
        "BUDDY | top deck seam", (0, 0, 0.422), (0.73, 0.56, 0.018), m["ink"], col, 0.05
    )
    box(
        "BUDDY | satin service hatch",
        (0, 0, 0.435),
        (0.70, 0.53, 0.018),
        m["cream"],
        col,
        0.045,
    )
    box(
        "BUDDY | curved display surround",
        (0.476, 0, 0.325),
        (0.034, 0.49, 0.16),
        m["ink"],
        col,
        0.035,
    )
    visor = box(
        "BUDDY | optical glass face",
        (0.497, 0, 0.325),
        (0.008, 0.44, 0.132),
        m["visor"],
        col,
        0.025,
    )
    for side in (-1, 1):
        eye = box(
            "BUDDY | friendly cyan LED eye",
            (0.502, side * 0.105, 0.342),
            (0.004, 0.045, 0.052),
            m["led"],
            col,
            0.015,
        )
        box(
            "BUDDY | rosy cheek",
            (0.503, side * 0.165, 0.307),
            (0.003, 0.034, 0.012),
            m["pink"],
            col,
            0.006,
        )
        cylinder(
            "BUDDY | obstacle camera bezel",
            (0.482, side * 0.29, 0.24),
            0.029,
            0.016,
            m["metal"],
            col,
            (1, 0, 0),
        )
        cylinder(
            "BUDDY | obstacle camera glass",
            (0.493, side * 0.29, 0.24),
            0.022,
            0.005,
            m["visor"],
            col,
            (1, 0, 0),
        )
        cylinder(
            "BUDDY | lens blue coating",
            (0.496, side * 0.29, 0.24),
            0.010,
            0.003,
            m["lens"],
            col,
            (1, 0, 0),
        )
    curve(
        "BUDDY | LED smile",
        [
            (0.504, 0.055 * math.cos(t), 0.314 + 0.022 * math.sin(t))
            for t in [math.pi + i * math.pi / 24 for i in range(25)]
        ],
        0.0025,
        m["led"],
        col,
    )
    for side in (-1, 1):
        y = side * 0.397
        cylinder(
            "BUDDY | moulded tyre",
            (0, y, 0.165),
            0.165,
            0.075,
            m["rubber"],
            col,
            (0, 1, 0),
            96,
        )
        cylinder(
            "BUDDY | brushed wheel rim",
            (0, y + side * 0.040, 0.165),
            0.111,
            0.016,
            m["metal"],
            col,
            (0, 1, 0),
        )
        cylinder(
            "BUDDY | orange hubcap",
            (0, y + side * 0.052, 0.165),
            0.056,
            0.018,
            m["orange"],
            col,
            (0, 1, 0),
        )
        for i in range(32):
            t = i * math.tau / 32
            tread = box(
                "BUDDY | tyre siping",
                (0.161 * math.sin(t), y, 0.165 + 0.161 * math.cos(t)),
                (0.009, 0.073, 0.012),
                m["rubber_light"],
                col,
                0.002,
            )
            tread.rotation_euler[1] = t
        for i in range(6):
            t = i * math.tau / 6
            cylinder(
                "BUDDY | wheel lug",
                (0.077 * math.sin(t), y + side * 0.054, 0.165 + 0.077 * math.cos(t)),
                0.008,
                0.010,
                m["steel"],
                col,
                (0, 1, 0),
                6,
            )
        box(
            "BUDDY | status light diffuser",
            (0.22, side * 0.370, 0.36),
            (0.22, 0.012, 0.017),
            m["led"],
            col,
            0.006,
        )
        for i in range(9):
            box(
                "BUDDY | ventilation slot",
                (-0.31 + i * 0.026, side * 0.370, 0.275),
                (0.012, 0.006, 0.044),
                m["ink"],
                col,
                0.004,
            )
        for x in (-0.36, 0.36):
            cylinder(
                "BUDDY | captive Torx screw",
                (x, side * 0.29, 0.45),
                0.009,
                0.003,
                m["steel"],
                col,
                vertices=6,
            )
    cylinder("BUDDY | LiDAR pedestal", (-0.27, 0, 0.48), 0.092, 0.068, m["ink"], col)
    cylinder(
        "BUDDY | LiDAR optical band", (-0.27, 0, 0.529), 0.088, 0.038, m["visor"], col
    )
    cylinder("BUDDY | LiDAR cap", (-0.27, 0, 0.554), 0.092, 0.016, m["metal"], col)
    cylinder(
        "BUDDY | emergency stop yellow collar",
        (-0.28, -0.21, 0.465),
        0.035,
        0.026,
        m["orange"],
        col,
    )
    cylinder(
        "BUDDY | emergency stop mushroom",
        (-0.28, -0.21, 0.487),
        0.025,
        0.025,
        m["red"],
        col,
    )
    for x in (-0.35, 0.35):
        box(
            "BUDDY | service handle",
            (x, 0, 0.458),
            (0.027, 0.23, 0.023),
            m["metal"],
            col,
            0.01,
        )
    text(
        "BUDDY | identification",
        "BUDDY / AMR",
        (0.23, -0.371, 0.298),
        0.036,
        m["ink"],
        col,
    )
    sticker("BUDDY | kindness badge", (0.33, -0.374, 0.34), 0.023, "heart", col, m)
    box(
        "BUDDY | payload cushion",
        (0.095, 0, 0.461),
        (0.40, 0.42, 0.03),
        m["rubber"],
        col,
        0.016,
    )
    box(
        "Parcel | rounded corrugated carton",
        (0.095, 0, 0.64),
        (0.39, 0.39, 0.33),
        m["cardboard"],
        col,
        0.014,
    )
    box(
        "Parcel | paper tape across lid",
        (0.095, 0, 0.806),
        (0.053, 0.395, 0.002),
        m["tape"],
        col,
        0.001,
    )
    box(
        "Parcel | folded taped edge",
        (0.095, -0.196, 0.73),
        (0.053, 0.002, 0.15),
        m["tape"],
        col,
        0.001,
    )
    box(
        "Parcel | shipping label",
        (0.10, -0.198, 0.638),
        (0.19, 0.002, 0.10),
        m["cream"],
        col,
        0.004,
    )
    text(
        "Parcel | handle with care",
        "HANDLE WITH CARE",
        (0.10, -0.200, 0.66),
        0.012,
        m["ink"],
        col,
    )
    for i in range(24):
        box(
            "Parcel | barcode ink",
            (0.023 + i * 0.0064, -0.200, 0.628),
            (0.0015 if i % 3 else 0.003, 0.001, 0.027),
            m["ink"],
            col,
            0,
        )
    sticker("Parcel | smile seal", (-0.029, -0.201, 0.75), 0.035, "smile", col, m)
    sticker("Parcel | love seal", (0.225, -0.201, 0.72), 0.029, "heart", col, m)
    sticker("Parcel | star seal", (0.216, -0.201, 0.56), 0.027, "star", col, m)


def make_scene():
    bpy.ops.wm.open_mainfile(filepath=str(BASE))
    scene = bpy.context.scene
    layout = json.loads(CONTRACT.read_text())
    m = {
        "mint": shader(
            "Ceramic mint / automotive clear coat", (0.19, 0.58, 0.52), 0.24, 0.28, 0.55
        ),
        "cream": shader(
            "Warm ivory enamel / vinyl", (0.88, 0.85, 0.72), 0.38, 0.02, 0.2
        ),
        "metal": shader("Bead blasted aluminium", (0.35, 0.43, 0.49), 0.28, 0.82),
        "steel": shader("Machined stainless steel", (0.56, 0.61, 0.65), 0.2, 0.95),
        "rubber": shader("Carbon rubber", (0.016, 0.022, 0.027), 0.83),
        "rubber_light": shader("Tyre tread edges", (0.027, 0.036, 0.039), 0.9),
        "ink": shader("Graphite ABS", (0.015, 0.024, 0.032), 0.35),
        "orange": shader("Safety apricot", (0.96, 0.42, 0.075), 0.3, 0.12, 0.4),
        "red": shader("Emergency vermilion", (0.70, 0.025, 0.021), 0.28, 0.1, 0.3),
        "pink": shader("Strawberry vinyl", (0.97, 0.19, 0.32), 0.32, 0, 0.2),
        "led": shader("Soft aqua OLED", (0.20, 0.94, 0.82), 0.25, 0, 0, 0, 2),
        "lens": shader("Camera coating", (0.025, 0.13, 0.28), 0.08, 0.5, 0.8),
        "visor": shader("Optical smoked glass", (0.14, 0.28, 0.32), 0.08, 0, 0.5, 0.75),
        "glass": shader(
            "Low iron architectural glass / IOR 1.46",
            (0.88, 0.97, 0.98),
            0.055,
            0,
            0,
            1,
        ),
        "cardboard": shader("Corrugated kraft paper", (0.51, 0.31, 0.14), 0.88),
        "tape": shader("Recycled paper tape", (0.67, 0.46, 0.23), 0.61),
        "floor": shader(
            "Polished aggregate concrete", (0.31, 0.34, 0.35), 0.31, 0.02, 0.18
        ),
    }
    grain(m["floor"], 90, 0.22, 0.002, ((0.23, 0.26, 0.28), (0.38, 0.40, 0.40)))
    grain(m["cardboard"], 170, 0.3, 0.0005, ((0.39, 0.23, 0.10), (0.57, 0.37, 0.19)))
    grain(m["rubber"], 240, 0.35, 0.0004)
    grain(m["metal"], 180, 0.12, 0.00015)
    # Upgrade materials and move original scene into a named collection.
    existing = collection("01 | Imported warehouse and physical layout")
    robot_names = {
        v.get("name")
        for v in __import__("xml.etree.ElementTree", fromlist=["ElementTree"])
        .parse(
            ROOT
            / "simulation/ros2_ws/src/kinesis_gazebo/models/kinesis_amr/model.sdf"
        )
        .findall(".//visual")
    }
    for obj in list(scene.objects):
        if obj.type in {"LIGHT", "CAMERA"}:
            bpy.data.objects.remove(obj, do_unlink=True)
            continue
        relocate(obj, existing)
        name = obj.name.split(".")[0]
        if name in robot_names:
            obj.hide_render = True
            obj.hide_set(True)
        if name.startswith("glass_"):
            obj.data.materials.clear()
            obj.data.materials.append(m["glass"])
        if name == "slab":
            obj.data.materials.clear()
            obj.data.materials.append(m["floor"])
        if name in {"cardboard", "wood", "steel"}:
            target = {
                "cardboard": m["cardboard"],
                "wood": m["tape"],
                "steel": m["steel"],
            }[name]
            obj.data.materials.clear()
            obj.data.materials.append(target)
    roof = collection("02 | GLASS ROOF — toggle collection eye for cutaway")
    for index, (x1, y1, x2, y2) in enumerate(layout["layout"]["floor_sections"]):
        for x in range(x1, x2, 6):
            for y in range(y1, y2, 6):
                box(
                    "Roof | laminated glass panel",
                    (x + 3, y + 3, 7.94),
                    (5.90, 5.90, 0.035),
                    m["glass"],
                    roof,
                    0.006,
                )
                box(
                    "Roof | glazing pressure cap",
                    (x + 3, y, 7.98),
                    (6, 0.065, 0.055),
                    m["metal"],
                    roof,
                )
            box(
                "Roof | steel purlin",
                (x, (y1 + y2) / 2, 7.86),
                (0.12, y2 - y1, 0.18),
                m["metal"],
                roof,
            )
        box(
            "Roof | edge closure",
            (x2, (y1 + y2) / 2, 7.86),
            (0.12, y2 - y1, 0.18),
            m["metal"],
            roof,
        )
    fleet = collection("03 | BUDDY fleet — detailed robot assemblies")
    robot(fleet, m)
    prototype = list(fleet.objects)
    names = (
        "Mochi",
        "Pip",
        "Bean",
        "Miso",
        "Pebble",
        "Boba",
        "Nori",
        "Sunny",
        "Kiwi",
        "Tofu",
        "Coco",
        "Sprout",
    )
    for index, (identifier, spawn) in enumerate(layout["spawns"].items()):
        group = bpy.data.objects.new(f"{identifier} / {names[index]}", None)
        fleet.objects.link(group)
        objects = prototype if index == 0 else []
        if index:
            for source in prototype:
                obj = source.copy()
                obj.data = source.data
                fleet.objects.link(obj)
                objects.append(obj)
        for obj in objects:
            obj.parent = group
        # Copy children in local coordinates; parent transforms carry fleet placement.
        badge = text(
            identifier + " name badge",
            f"{index+1:02d}  /  {names[index].upper()}",
            (-0.1, -0.376, 0.345),
            0.022,
            m["cream"],
            fleet,
        )
        badge.parent = group
        group.location = (spawn[0], spawn[1], 0)
    props = collection("04 | Package stickers and warehouse character")
    templates = {
        style: sticker("Parcel sticker / " + style, (0, 0, 0), 0.075, style, props, m)
        for style in ("smile", "heart", "star")
    }
    # Repeated stickers share geometry. Labels face into the storage aisles.
    for index, item in enumerate(layout["instances"]):
        if item["kind"] != "fulfillment_rack":
            continue
        x, y, _ = item["pose"]
        for bay in (-3.075, -1.025, 1.025, 3.075):
            for level in (1.85, 3.35):
                style = ("smile", "heart", "star")[
                    (index + int(level * 10) + round(bay)) % 3
                ]
                for source in templates[style]:
                    obj = source.copy()
                    obj.data = source.data
                    obj.location += Vector((x + bay - 0.25, y - 1.04, level + 0.51))
                    props.objects.link(obj)
    for objects in templates.values():
        for obj in objects:
            bpy.data.objects.remove(obj, do_unlink=True)
    text(
        "Welcome floor message",
        "SMALL BOTS. BIG HEART.",
        (-1, -7.8, 0.022),
        0.58,
        m["cream"],
        props,
        (0, 0, 0),
    )
    for x, label in ((-9, "INBOUND"), (24, "SORT / PACK"), (56, "DISPATCH")):
        text(
            "Floor zone / " + label,
            label,
            (x, -9, 0.025),
            0.44,
            m["cream"],
            props,
            (0, 0, 0),
        )
    # Subtle physical slab seams and wheel scuffs, all above the floor by millimeters.
    for x in range(-12, 60, 6):
        box(
            "Floor | saw-cut expansion joint",
            (x, 12, 0.002),
            (0.012, 46, 0.003),
            m["rubber"],
            props,
            0,
        )
    for i in range(14):
        x = -12 + i * 4.7
        curve(
            "Floor | faint rubber turn mark",
            [
                (x + 0.44 * math.cos(t), -5 + 0.44 * math.sin(t), 0.004)
                for t in [i * 0.1 + j * 0.07 for j in range(15)]
            ],
            0.006,
            m["rubber_light"],
            props,
        )
    lighting = collection("05 | Daylight and practical fixtures")
    scene.world.use_nodes = True
    nodes = scene.world.node_tree.nodes
    links = scene.world.node_tree.links
    nodes.clear()
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(28)
    sky.sun_rotation = math.radians(135)
    sky.sun_size = math.radians(1.1)
    sky.altitude = 0.1
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = 0.35
    output = nodes.new("ShaderNodeOutputWorld")
    links.new(sky.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs[0], output.inputs[0])
    for x in (-9, 9, 27, 45, 63):
        for y in (-3, 9, 21):
            data = bpy.data.lights.new("High bay / 4500 K", "AREA")
            data.energy = 190
            data.shape = "RECTANGLE"
            data.size = 2.1
            data.size_y = 0.55
            data.color = (1, 0.86, 0.70)
            light = bpy.data.objects.new(data.name, data)
            light.location = (x, y, 7.1)
            lighting.objects.link(light)
    # A large soft source over the foreground improves legibility of small robot details.
    data = bpy.data.lights.new("Soft daylight bounce", "AREA")
    data.energy = 500
    data.shape = "DISK"
    data.size = 5
    light = bpy.data.objects.new(data.name, data)
    light.location = (-12, -8, 4)
    lighting.objects.link(light)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 48
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 10
    scene.cycles.transmission_bounces = 8
    scene.cycles.transparent_max_bounces = 8
    scene.view_settings.view_transform = "AgX"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1000
    scene.render.resolution_percentage = 100
    cameras = collection("06 | Presentation cameras")
    for name, location, target, ortho in (
        ("01 Robot portrait", (-12.9, -8.7, 1.8), (-14.95, -6, 0.39), 2.25),
        ("02 Glass roof overview", (117, -112, 119), (23, 19, 1), 122),
        ("03 Inside the warehouse", (-12, -8, 2), (-6, 2, 2), None),
    ):
        data = bpy.data.cameras.new(name)
        camera = bpy.data.objects.new(name, data)
        cameras.objects.link(camera)
        camera.location = location
        camera.rotation_euler = (
            (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
        )
        if ortho:
            data.type = "ORTHO"
            data.ortho_scale = ortho
        else:
            data.lens = 26
        data.clip_end = 400
    scene.camera = bpy.data.objects["01 Robot portrait"]
    # Open directly on the robot portrait; material colors are visible without rendering.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
                area.spaces.active.shading.color_type = "MATERIAL"
                area.spaces.active.clip_end = 500
    scene["Art pass scope"] = (
        "Detailed Blender presentation scene; Gazebo dynamics and SDF assets remain separate."
    )
    scene["Glass roof"] = (
        "Collection 02 is visible by default. Toggle its eye/render icon for cutaway views."
    )
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.wm.save_as_mainfile(filepath=str(DEST))
    print(f"Saved {DEST} with {len(scene.objects)} objects", flush=True)
    if "--save-only" not in sys.argv:
        for camera_name, filename in (
            ("01 Robot portrait", "detailed-robot"),
            ("02 Glass roof overview", "detailed-glass-roof"),
        ):
            scene.camera = bpy.data.objects[camera_name]
            scene.render.filepath = str(OUT / f"{filename}.png")
            bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    make_scene()
