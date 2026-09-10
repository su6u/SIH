"""Render review images from the actual SDF/OBJ assets, not substitute geometry.

Run Blender 4.2 with --background --factory-startup --python this_file.
This is an offline geometry review, not a Gazebo execution trace.
"""

from pathlib import Path
import math
import sys
import xml.etree.ElementTree as ET

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
GAZEBO = ROOT / "simulation/ros2_ws/src/kinesis_gazebo"
OUTPUT = ROOT / "simulation/previews"
MESHES = {}
MATERIALS = {}


def pose(element):
    values = list(map(float, element.findtext("pose", "0 0 0 0 0 0").split()))
    return (
        Matrix.Translation(Vector(values[:3]))
        @ Euler(values[3:], "XYZ").to_matrix().to_4x4()
    )


def material(visual):
    color = tuple(map(float, visual.findtext("material/diffuse", ".5 .5 .5 1").split()))
    alpha = 1 - float(visual.findtext("transparency", "0"))
    key = (color, alpha)
    if key not in MATERIALS:
        mat = bpy.data.materials.new("SDF material")
        mat.diffuse_color = (*color[:3], alpha)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.48
        if alpha < 1:
            bsdf.inputs["Alpha"].default_value = alpha
            bsdf.inputs["Roughness"].default_value = 0.14
        MATERIALS[key] = mat
    return MATERIALS[key]


def visual_object(visual, transform):
    geometry = visual.find("geometry")
    mesh_uri = geometry.findtext("mesh/uri")
    if mesh_uri:
        path = GAZEBO / "models" / mesh_uri.removeprefix("model://")
        if mesh_uri not in MESHES:
            bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
            obj = bpy.context.object
            MESHES[mesh_uri] = obj.data
        else:
            obj = bpy.data.objects.new(visual.get("name"), MESHES[mesh_uri])
            bpy.context.collection.objects.link(obj)
    elif geometry.find("box") is not None:
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.object
        obj.scale = tuple(map(float, geometry.findtext("box/size").split()))
    elif geometry.find("cylinder") is not None:
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=32,
            radius=float(geometry.findtext("cylinder/radius")),
            depth=float(geometry.findtext("cylinder/length")),
        )
        obj = bpy.context.object
    elif geometry.find("sphere") is not None:
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=24, ring_count=12, radius=float(geometry.findtext("sphere/radius"))
        )
        obj = bpy.context.object
    else:
        raise ValueError(ET.tostring(geometry))
    scale = obj.scale.copy()
    obj.matrix_world = transform @ pose(visual)
    obj.scale = scale
    obj.name = visual.get("name")
    if not obj.data.materials:
        obj.data.materials.append(material(visual))
    return obj


def load_model(model, transform):
    frames = {"__model__": Matrix.Identity(4)}
    for link in model.findall("link"):
        relative = link.find("pose")
        parent = (
            relative.get("relative_to", "__model__")
            if relative is not None
            else "__model__"
        )
        frames[link.get("name")] = frames[parent] @ pose(link)
        for visual in link.findall("visual"):
            visual_object(visual, transform @ frames[link.get("name")])


def render():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    world = ET.parse(GAZEBO / "worlds/warehouse_fulfillment.sdf").find("world")
    for model in world.findall("model"):
        load_model(model, pose(model))
    for include in world.findall("include"):
        path = (
            GAZEBO
            / "models"
            / include.findtext("uri").removeprefix("model://")
            / "model.sdf"
        )
        load_model(ET.parse(path).find("model"), pose(include))
    bpy.ops.object.light_add(type="SUN", rotation=(0.45, -0.35, -0.4))
    bpy.context.object.data.energy = 2.3
    bpy.context.object.data.angle = 0.15
    scene.world.color = (0.28, 0.32, 0.38)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 20
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1100
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "AgX"
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    scene.camera = camera
    OUTPUT.mkdir(exist_ok=True)
    if "--save-only" in sys.argv:
        camera.location = (118, -108, 117)
        camera.rotation_euler = (
            Vector((23, 19, 1)) - camera.location
        ).to_track_quat("-Z", "Y").to_euler()
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = 119
        bpy.ops.wm.save_as_mainfile(
            filepath=str(OUTPUT / "kinesis-fulfillment.blend")
        )
        return
    for name, position, target, scale in (
        ("fulfillment-overview", (118, -108, 117), (23, 19, 1), 119),
        ("fulfillment-rack-detail", (-1, -13, 8), (-7, 0, 2.5), 16),
    ):
        camera.location = position
        camera.rotation_euler = (
            (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
        )
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = scale
        scene.render.filepath = str(OUTPUT / f"{name}.png")
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    render()
