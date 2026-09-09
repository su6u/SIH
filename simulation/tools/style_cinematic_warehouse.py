"""Apply a clear-glass, warm-concrete lighting look to the detailed Blender scene.

Run with Blender 4.2. Saves a separate editable file and two look-review images.
"""

from pathlib import Path
import math
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repair_presentation_details import repair

OUT = Path(__file__).resolve().parents[2] / "simulation/previews"


def clear_glass():
    material = bpy.data.materials["Low iron architectural glass / IOR 1.46"]
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    transmission = nodes.new("ShaderNodeBsdfTransparent")
    transmission.inputs[0].default_value = (0.96, 0.99, 0.985, 1)
    glass = nodes.new("ShaderNodeBsdfPrincipled")
    glass.inputs["Base Color"].default_value = (0.94, 0.985, 0.97, 1)
    glass.inputs["Transmission Weight"].default_value = 1
    glass.inputs["Roughness"].default_value = 0.025
    glass.inputs["IOR"].default_value = 1.45
    blend = nodes.new("ShaderNodeMixShader")
    blend.inputs[0].default_value = 0.32
    links.new(transmission.outputs[0], blend.inputs[1])
    links.new(glass.outputs[0], blend.inputs[2])
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(blend.outputs[0], output.inputs["Surface"])
    material.diffuse_color = (0.74, 0.88, 0.84, 0.18)
    material["Look"] = (
        "68% clear transmission / 32% refractive glass; subtle green tint"
    )


def warehouse_floor():
    material = bpy.data.materials["Polished aggregate concrete"]
    material.name = "Warehouse | warm greige sealed concrete"
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.42
    bsdf.inputs["Coat Weight"].default_value = 0.12
    bsdf.inputs["Coat Roughness"].default_value = 0.30
    material.diffuse_color = (0.26, 0.225, 0.18, 1)
    position = nodes.new("ShaderNodeNewGeometry")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.7
    noise.inputs["Detail"].default_value = 4
    links.new(position.outputs["Position"], noise.inputs["Vector"])
    colors = nodes.new("ShaderNodeValToRGB")
    colors.color_ramp.elements[0].color = (0.18, 0.155, 0.12, 1)
    colors.color_ramp.elements[1].color = (0.32, 0.285, 0.235, 1)
    links.new(noise.outputs["Fac"], colors.inputs[0])
    links.new(colors.outputs[0], bsdf.inputs["Base Color"])
    aggregate = nodes.new("ShaderNodeTexNoise")
    aggregate.inputs["Scale"].default_value = 140
    aggregate.inputs["Detail"].default_value = 2
    links.new(position.outputs["Position"], aggregate.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.18
    bump.inputs["Distance"].default_value = 0.001
    links.new(aggregate.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs[0], bsdf.inputs["Normal"])
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(bsdf.outputs[0], output.inputs["Surface"])


def light_scene(scene):
    for node in scene.world.node_tree.nodes:
        if node.type == "BACKGROUND":
            node.inputs["Strength"].default_value = 0.13
        if node.type == "TEX_SKY":
            node.sun_elevation = math.radians(19)
            node.sun_rotation = math.radians(120)
    for obj in scene.objects:
        if obj.type != "LIGHT":
            continue
        if obj.name.startswith("High bay"):
            obj.data.energy = 240
            obj.data.color = (1, 0.76, 0.49)
        elif obj.name == "Soft daylight bounce":
            obj.data.energy = 130
            obj.data.color = (0.67, 0.80, 1)
    # Broad window sources create a warm/cool separation and soft floor highlights.
    for name, pos, target, watts, color, size in (
        (
            "Window light | warm afternoon",
            (-17, -2, 5),
            (5, 8, 0),
            1800,
            (1, 0.77, 0.52),
            8,
        ),
        (
            "Window light | cool skylight",
            (25, 17, 7.6),
            (20, 13, 0),
            1200,
            (0.68, 0.82, 1),
            12,
        ),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.color, data.size = watts, color, size
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        obj.location = pos
        obj.rotation_euler = (
            (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
        )
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -0.5


def main():
    bpy.ops.wm.open_mainfile(
        filepath=str(OUT / "swarmroute-fulfillment-detailed.blend")
    )
    scene = bpy.context.scene
    clear_glass()
    warehouse_floor()
    light_scene(scene)
    # Smooth the curved robot surfaces while preserving broad machined panels.
    for obj in scene.objects:
        if obj.type == "MESH" and obj.name.startswith("BUDDY"):
            if any(mod.type == "BEVEL" for mod in obj.modifiers):
                for face in obj.data.polygons:
                    face.use_smooth = True
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 32
    scene.cycles.preview_samples = 12
    scene.cycles.use_denoising = True
    scene.cycles.use_preview_denoising = True
    scene.cycles.transparent_max_bounces = 16
    scene.camera = bpy.data.objects["01 Robot portrait"]
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.type = "RENDERED"
                area.spaces.active.region_3d.view_perspective = "CAMERA"
    scene["Glass visibility"] = (
        "Roof and facade use clear transmission with restrained reflections. Use rendered shading."
    )
    scene["Lighting look"] = (
        "Warm greige concrete, warm practical lights, cool fill, reduced exposure"
    )
    repair(scene)
    destination = OUT / "swarmroute-fulfillment-cinematic-fixed.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(destination))
    print(f"Saved {destination}", flush=True)
    if "--save-only" in sys.argv:
        return
    scene.cycles.samples = 20
    scene.render.resolution_x, scene.render.resolution_y = 1100, 720
    scene.render.resolution_percentage = 100
    for name, camera in (
        ("fixed-robot-clearance-labels", "01 Robot portrait"),
        ("fixed-glass-roof", "02 Glass roof overview"),
    ):
        scene.camera = bpy.data.objects[camera]
        scene.render.filepath = str(OUT / f"{name}.png")
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
