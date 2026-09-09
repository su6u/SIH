"""Export one presentation-ready BUDDY robot from the authored Blender scene."""

from __future__ import annotations

import bpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "presentation/public/models/buddy.glb"

root = next(obj for obj in bpy.data.objects if obj.name.startswith("robot_01 /"))
root.location = (0.0, 0.0, 0.0)

bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
for child in root.children_recursive:
    child.select_set(True)
bpy.context.view_layer.objects.active = root

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=str(OUTPUT),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_yup=True,
    export_materials="EXPORT",
    export_cameras=False,
    export_lights=False,
)
print(f"Exported {len(root.children_recursive) + 1} objects to {OUTPUT}")
