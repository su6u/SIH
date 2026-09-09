"""Export the complete authored warehouse—without the animated robot fleet—to GLB."""

from __future__ import annotations

import bpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "presentation/public/models/warehouse-full.glb"
INCLUDE = {
    "01 | Imported warehouse and physical layout",
    "02 | GLASS ROOF — toggle collection eye for cutaway",
    "04 | Package stickers and warehouse character",
}

bpy.ops.object.select_all(action="DESELECT")
selected = set()
for name in INCLUDE:
    collection = bpy.data.collections.get(name)
    if collection is None:
        raise RuntimeError(f"Required collection is missing: {name}")
    # These authored collections are intentionally flat. Blender 4.2 on macOS
    # can crash while iterating Collection.all_objects in background mode.
    for obj in list(collection.objects):
        if obj.type in {"MESH", "CURVE", "FONT"}:
            obj.hide_viewport = False
            obj.hide_render = False
            obj.select_set(True)
            selected.add(obj)

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
print(f"Exported {len(selected)} full-detail warehouse objects to {OUTPUT}")
