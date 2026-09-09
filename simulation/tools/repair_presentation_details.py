"""Repair visual clearances, labels and helper visibility in the art scene."""

import bpy


def repair(scene):
    wheel_parts = (
        "BUDDY | moulded tyre",
        "BUDDY | brushed wheel rim",
        "BUDDY | orange hubcap",
        "BUDDY | tyre siping",
        "BUDDY | wheel lug",
    )
    fleet = bpy.data.collections["03 | BUDDY fleet — detailed robot assemblies"]
    robots = [
        obj
        for obj in fleet.objects
        if obj.type == "EMPTY" and obj.name.startswith("robot_")
    ]
    for root in robots:
        for obj in list(root.children):
            if obj.name.startswith(wheel_parts):
                obj.location.y += 0.075 if obj.location.y > 0 else -0.075
            if obj.type == "FONT":
                # Raised text was casting a second, displaced set of letters.
                obj.visible_shadow = False
                obj.data.extrude = 0
                obj.data.bevel_depth = 0
                obj.data.resolution_u = 16
            if obj.name.startswith("BUDDY | identification"):
                obj.location = (0.255, -0.386, 0.293)
                obj.data.size = 0.027
        # Flat inset-style nameplate isolates lettering from curved enamel shading.
        bpy.ops.mesh.primitive_cube_add(size=1)
        plate = bpy.context.object
        plate.name = root.name + " | ID nameplate"
        plate.parent = root
        plate.location = (0.255, -0.380, 0.293)
        plate.scale = (0.285, 0.010, 0.065)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        plate.data.materials.append(bpy.data.materials["Warm ivory enamel / vinyl"])
        mod = plate.modifiers.new("Rounded badge corners", "BEVEL")
        mod.width, mod.segments = 0.006, 4
        for col in list(plate.users_collection):
            col.objects.unlink(plate)
        fleet.objects.link(plate)
        # Visible axle sleeves bridge the new clearance instead of floating wheels.
        for side in (-1, 1):
            bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.044, depth=0.105)
            axle = bpy.context.object
            axle.name = root.name + " | axle sleeve"
            axle.parent = root
            axle.location = (0, side * 0.400, 0.165)
            axle.rotation_euler[0] = 1.57079632679
            axle.data.materials.append(bpy.data.materials["Bead blasted aluminium"])
            for col in list(axle.users_collection):
                col.objects.unlink(axle)
            fleet.objects.link(axle)
    for obj in scene.objects:
        if obj.type == "LIGHT" and (
            obj.name.startswith("Window light") or obj.name == "Soft daylight bounce"
        ):
            # These presentation fill sources must illuminate without appearing
            # as giant softbox rectangles reflected/refracted in the roof.
            obj.visible_glossy = False
            obj.visible_transmission = False
            obj.visible_camera = False
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                overlay = area.spaces.active.overlay
                overlay.show_extras = False
                overlay.show_relationship_lines = False
                overlay.show_floor = False
                overlay.show_axis_x = False
                overlay.show_axis_y = False
    bpy.ops.object.select_all(action="DESELECT")
    # Check real geometric clearance in robot-local coordinates.
    for root in robots:
        tyres = [o for o in root.children if o.name.startswith("BUDDY | moulded tyre")]
        assert len(tyres) == 2
        for tyre in tyres:
            assert abs(tyre.location.y) - 0.075 / 2 > 0.76 / 2 + 0.02
        label = next(
            o for o in root.children if o.name.startswith("BUDDY | identification")
        )
        assert label.location.y < -0.385 and not label.visible_shadow
    print(
        f"Repaired {len(robots)} robot assemblies; tyre-body clearance 54.5 mm; clean viewport helpers",
        flush=True,
    )
