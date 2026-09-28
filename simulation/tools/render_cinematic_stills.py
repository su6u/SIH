"""Render quick cinematic stills from the completed detailed warehouse scene."""

from pathlib import Path
import math

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "simulation/previews/cinematic"


def point_camera(camera, target):
    camera.rotation_euler = (
        (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
    )


def make_camera(name, position, target, lens, focus, fstop):
    data = bpy.data.cameras.new(name)
    camera = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = position
    point_camera(camera, target)
    data.lens = lens
    data.sensor_width = 36
    data.clip_start = 0.08
    data.clip_end = 500
    focus_data = bpy.data.objects.new(name + " focus", None)
    focus_data.location = focus
    bpy.context.scene.collection.objects.link(focus_data)
    data.dof.use_dof = True
    data.dof.focus_object = focus_data
    data.dof.aperture_fstop = fstop
    data.dof.aperture_blades = 8
    return camera


def render():
    scene = bpy.context.scene
    OUTPUT.mkdir(parents=True, exist_ok=True)
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 788
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.filepath = str(OUTPUT)
    scene.view_settings.view_transform = "AgX"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass

    # Warm sunlight crossing the cool warehouse gives the glass and floor shape.
    sun_data = bpy.data.lights.new("Cinematic late-afternoon sun", "SUN")
    sun_data.energy = 2.2
    sun_data.angle = math.radians(5)
    sun_data.color = (1.0, 0.72, 0.48)
    sun = bpy.data.objects.new(sun_data.name, sun_data)
    sun.rotation_euler = (math.radians(38), 0, math.radians(-38))
    scene.collection.objects.link(sun)

    cameras = (
        (
            "01-inside-long-rack-aisle",
            (-15.8, 6.0, 1.18),
            (48.0, 6.0, 1.05),
            24,
            (16.0, 6.0, 1.0),
            5.6,
        ),
        (
            "02-inside-robots-at-work",
            (-17.0, -9.3, 1.28),
            (-8.0, -5.8, 0.45),
            42,
            (-12.0, -6.0, 0.45),
            3.5,
        ),
        (
            "03-inside-operations-overlook",
            (66.0, -7.0, 6.2),
            (25.0, 17.0, 1.6),
            30,
            (31.0, 14.0, 1.4),
            6.3,
        ),
    )
    for name, position, target, lens, focus, fstop in cameras:
        camera = make_camera(name, position, target, lens, focus, fstop)
        scene.camera = camera
        scene.render.filepath = str(OUTPUT / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print(f"Rendered {name}", flush=True)


if __name__ == "__main__":
    render()
