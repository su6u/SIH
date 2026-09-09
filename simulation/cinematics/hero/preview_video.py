"""Render a fast editorial playblast without modifying the final hero .blend.

The preview uses the saved scene, animation, camera markers and visibility keys,
but swaps Cycles for Workbench and renders only every second source frame.

blender --background --factory-startup --python-exit-code 1 \
  --python preview_video.py -- --open
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

import bpy


HERE = Path(__file__).resolve().parent


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--blend",
        type=Path,
        default=HERE / "output/swarmroute-hero-40s.blend",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=HERE / "output/preview/swarmroute-playblast.mp4",
    )
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument(
        "--engine",
        choices=("workbench", "eevee"),
        default="workbench",
        help="Workbench is fastest; Eevee is the macOS-headless fallback.",
    )
    parser.add_argument(
        "--keep-detail",
        action="store_true",
        help="Keep microgeometry. Usually too slow for a complete local playblast.",
    )
    parser.add_argument("--start", type=int, help="Optional source-frame start for a test clip.")
    parser.add_argument("--end", type=int, help="Optional source-frame end for a test clip.")
    parser.add_argument(
        "--fps",
        type=int,
        choices=(6, 10, 15, 30),
        default=15,
        help="Preview fps. 15 is the recommended fast review; 30 renders every frame.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the finished movie on macOS after Blender exits rendering.",
    )
    parser.add_argument(
        "--quit",
        action="store_true",
        help="Quit a foreground Blender instance after the movie is finished.",
    )
    parser.add_argument(
        "--viewport",
        action="store_true",
        help="Capture the camera through Blender's viewport playblast path.",
    )
    parser.add_argument(
        "--save-proxy",
        type=Path,
        help="Save the lightweight interactive .blend and exit without rendering.",
    )
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])


def workbench_engine(scene: bpy.types.Scene) -> str:
    # Blender 4.2 uses the NEXT identifier; newer versions may expose the
    # un-suffixed name. Assignment is the most reliable cross-version probe.
    for identifier in ("BLENDER_WORKBENCH_NEXT", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = identifier
            return identifier
        except TypeError:
            continue
    raise RuntimeError("This Blender build does not provide the Workbench renderer")


def material_viewport_colours() -> None:
    """Make Workbench approximate the authored Principled material palette."""
    for material in bpy.data.materials:
        if not material.use_nodes or not material.node_tree:
            continue
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is None:
            continue
        colour = principled.inputs.get("Base Color")
        if colour is not None:
            material.diffuse_color = colour.default_value


def proxy_material(name: str, colour: tuple[float, float, float, float]):
    material = bpy.data.materials.new("PLAYBLAST | " + name)
    material.diffuse_color = colour
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = colour
    principled.inputs["Roughness"].default_value = 0.72
    return material


def proxy_cube_mesh():
    mesh = bpy.data.meshes.new("PLAYBLAST | unit cube")
    mesh.from_pydata(
        [
            (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5),
            (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
            (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5),
            (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
        ],
        [],
        [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
         (1, 5, 6, 2), (2, 6, 7, 3), (4, 0, 3, 7)],
    )
    return mesh


def proxy_box(name, location, dimensions, material, collection, mesh, parent=None):
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    obj.scale = dimensions
    obj.data = mesh.copy()
    obj.data.materials.append(material)
    obj.parent = parent
    return obj


def build_coarse_proxy() -> None:
    """Create a tiny stand-in warehouse around the exact animated rig."""
    collection = bpy.data.collections.new("PLAYBLAST | coarse warehouse")
    bpy.context.scene.collection.children.link(collection)
    mesh = proxy_cube_mesh()
    floor = proxy_material("concrete", (0.24, 0.27, 0.28, 1))
    rack = proxy_material("rack steel", (0.10, 0.27, 0.37, 1))
    shelf = proxy_material("shelf orange", (0.84, 0.39, 0.08, 1))
    carton = proxy_material("carton", (0.55, 0.34, 0.16, 1))
    mint = proxy_material("robot mint", (0.22, 0.78, 0.69, 1))
    dark = proxy_material("robot dark", (0.035, 0.055, 0.062, 1))
    cyan = proxy_material("status", (0.2, 1.0, 0.86, 1))
    layout = json.loads((HERE.parents[1] / "layouts/fulfillment.json").read_text())

    for index, (x1, y1, x2, y2) in enumerate(layout["floor_sections"]):
        proxy_box(
            f"PLAYBLAST | floor {index}",
            ((x1 + x2) / 2, (y1 + y2) / 2, -0.08),
            (x2 - x1, y2 - y1, 0.16), floor, collection, mesh,
        )
    for row, y in enumerate(layout["rack_y"]):
        for column, x in enumerate(layout["rack_x"]):
            proxy_box(f"PLAYBLAST | rack {row}-{column}", (x, y, 2.1),
                      (7.2, 3.6, 4.2), rack, collection, mesh)
            for level in (0.55, 1.55, 2.55, 3.55):
                proxy_box(f"PLAYBLAST | shelf {row}-{column}-{level}",
                          (x, y, level), (7.35, 3.75, 0.10), shelf,
                          collection, mesh)
            proxy_box(f"PLAYBLAST | stock {row}-{column}", (x, y, 2.25),
                      (6.7, 3.1, 3.25), carton, collection, mesh)

    for index in range(1, 13):
        root = bpy.data.objects.get(f"robot_{index:02d} / " + (
            "Mochi", "Pip", "Bean", "Miso", "Pebble", "Boba",
            "Nori", "Sunny", "Kiwi", "Tofu", "Coco", "Sprout",
        )[index - 1])
        if root is None:
            continue
        proxy_box(f"PLAYBLAST | robot {index:02d} body", (0, 0, 0.28),
                  (0.94, 0.73, 0.34), mint, collection, mesh, root)
        proxy_box(f"PLAYBLAST | robot {index:02d} bumper", (0, 0, 0.13),
                  (1.00, 0.78, 0.10), dark, collection, mesh, root)
        proxy_box(f"PLAYBLAST | robot {index:02d} face", (0.49, 0, 0.30),
                  (0.025, 0.43, 0.15), dark, collection, mesh, root)
        proxy_box(f"PLAYBLAST | robot {index:02d} status", (0.18, 0, 0.47),
                  (0.18, 0.18, 0.06), cyan, collection, mesh, root)


def apply_proxy_scene() -> tuple[int, int]:
    """Remove render-costly microdetail from this unsaved, in-memory copy."""
    remove = set()
    collection_names = (
        "01 | Imported warehouse and physical layout",
        "02 | GLASS ROOF — toggle collection eye for cutaway",
        "03 | BUDDY fleet — detailed robot assemblies",
        "04 | Package stickers and warehouse character",
        "05 | Daylight and practical fixtures",
        "06 | Presentation cameras",
    )
    for name in collection_names:
        collection = bpy.data.collections.get(name)
        if collection:
            for obj in collection.all_objects:
                # These twelve animated roots are the authoritative choreography.
                if obj.type == "EMPTY" and obj.name.startswith("robot_"):
                    continue
                remove.add(obj)

    before = len(bpy.data.objects)
    for obj in remove:
        bpy.data.objects.remove(obj, do_unlink=True)
    build_coarse_proxy()
    return before, len(bpy.data.objects)


def configure(scene: bpy.types.Scene, args: argparse.Namespace) -> None:
    source_fps = round(scene.render.fps / scene.render.fps_base)
    if source_fps % args.fps:
        raise ValueError(f"Preview fps must divide the source fps ({source_fps})")

    if args.engine == "workbench":
        engine = workbench_engine(scene)
        material_viewport_colours()
        scene.display.shading.light = "STUDIO"
        scene.display.shading.studio_light = "rim.sl"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
        scene.display.shading.cavity_type = "BOTH"
        scene.display.shading.show_specular_highlight = True
        scene.display.shading.background_type = "WORLD"
    else:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
        engine = scene.render.engine

    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.use_compositing = False
    scene.render.use_motion_blur = False
    scene.render.fps = args.fps
    scene.render.fps_base = 1
    scene.frame_step = source_fps // args.fps
    if args.start is not None:
        scene.frame_start = args.start
    if args.end is not None:
        scene.frame_end = args.end
    if scene.frame_start < 1 or scene.frame_end < scene.frame_start:
        raise ValueError("Invalid preview frame range")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(args.output.resolve())
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.ffmpeg_preset = "REALTIME"
    scene.render.ffmpeg.audio_codec = "NONE"

    duration = (scene.frame_end - scene.frame_start + 1) / source_fps
    preview_frames = len(range(scene.frame_start, scene.frame_end + 1, scene.frame_step))
    print(
        "PLAYBLAST_CONFIG "
        f"engine={engine} resolution={args.width}x{args.height} "
        f"fps={args.fps} source_step={scene.frame_step} frames={preview_frames} "
        f"duration={duration:.2f}s output={args.output.resolve()}",
        flush=True,
    )


def main() -> None:
    args = arguments()
    blend = args.blend.resolve()
    if not blend.is_file():
        raise FileNotFoundError(blend)
    if args.width < 320 or args.height < 180:
        raise ValueError("Preview dimensions are too small for a useful review")

    bpy.ops.wm.open_mainfile(filepath=str(blend))
    source_fps = bpy.context.scene.render.fps
    source_fps_base = bpy.context.scene.render.fps_base
    if not args.keep_detail:
        before, after = apply_proxy_scene()
        print(f"PLAYBLAST_PROXY objects={before}->{after}", flush=True)
    configure(bpy.context.scene, args)
    if args.save_proxy:
        # Interactive playback evaluates the original 1–1200 keyframes, so keep
        # its native 30 fps instead of the frame-skipped movie encoding rate.
        bpy.context.scene.render.fps = source_fps
        bpy.context.scene.render.fps_base = source_fps_base
        bpy.context.scene.frame_step = 1
        destination = args.save_proxy.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(destination), check_existing=False)
        print(f"PLAYBLAST_BLEND_DONE {destination}", flush=True)
        return
    if args.viewport:
        bpy.ops.render.opengl(animation=True, view_context=False)
    else:
        bpy.ops.render.render(animation=True)
    print(f"PLAYBLAST_DONE {args.output.resolve()}", flush=True)

    # Opening is deliberately deferred until the complete file exists.
    if args.open and sys.platform == "darwin":
        import subprocess

        subprocess.run(["open", str(args.output.resolve())], check=False)
    if args.quit:
        bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
