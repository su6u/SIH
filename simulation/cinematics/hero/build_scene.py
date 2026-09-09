"""Build the self-contained 40 second Cycles hero film from the existing art file.

Run with Blender 4.2: blender -b --factory-startup --python build_scene.py
All runtime animation is baked; rendering requires no handlers or external code.
"""
from pathlib import Path
import json
import math
import sys

import bpy
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'simulation/tools'))
from motion import FPS, FRAMES, WHEEL_RADIUS, TRACK_WIDTH, SHOTS, build_tracks, camera_pose, ease
from validate import run as validate_motion
from detail_fulfillment import box, curve, shader, cylinder

OUT = HERE / 'output'
BASE = ROOT / 'simulation/previews/swarmroute-fulfillment-cinematic-fixed.blend'
DEST = OUT / 'swarmroute-hero-40s.blend'
MONO_FONT_CANDIDATES = (
    Path('/System/Library/Fonts/SFNSMono.ttf'),
    Path('/System/Library/Fonts/Supplemental/Andale Mono.ttf'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'),
)
HERO_FONT = None


def collection(name):
    result = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(result)
    return result


def linear_keys(block):
    if block.animation_data and block.animation_data.action:
        for fcurve in block.animation_data.action.fcurves:
            for key in fcurve.keyframe_points:
                key.interpolation = 'LINEAR'


def window(obj, start, end, fade=7):
    # Scale animation is frame-safe in offline render jobs and viewport playback.
    if obj.type=='CURVE':
        coords=[Vector(point.co[:3]) for spline in obj.data.splines for point in spline.points]
        if coords:
            center=sum(coords,Vector())/len(coords)
            obj.data.transform(Matrix.Translation(-center))
            obj.location += obj.rotation_euler.to_matrix() @ Vector((center.x*obj.scale.x,center.y*obj.scale.y,center.z*obj.scale.z))
    original = obj.scale.copy()
    for frame, amount in [(1,0),(max(1,start-1),0),(start+fade,1),
                           (end-fade,1),(end+1,0),(FRAMES,0)]:
        obj.scale = original * max(amount, .00001)
        obj.keyframe_insert(data_path='scale', frame=frame)
    linear_keys(obj)


def key_transform(obj, frame):
    obj.keyframe_insert(data_path='location', frame=frame)
    obj.keyframe_insert(data_path='rotation_euler', frame=frame)


def rig_robot(root, track, rig_collection):
    prefixes = ('BUDDY | moulded tyre','BUDDY | brushed wheel rim',
                'BUDDY | orange hubcap','BUDDY | tyre siping','BUDDY | wheel lug')
    parts = list(root.children)
    pivots = {}
    for side in (-1,1):
        pivot = bpy.data.objects.new(root.name + f' / wheel axle {side:+}', None)
        rig_collection.objects.link(pivot)
        pivot.parent = root
        pivot.location = (0, side * TRACK_WIDTH/2, WHEEL_RADIUS)
        for part in parts:
            if part.name.startswith(prefixes) and (1 if part.location.y>0 else -1)==side:
                old_local = part.matrix_local.copy()
                part.parent = pivot
                part.matrix_parent_inverse = Matrix.Identity(4)
                part.matrix_basis = Matrix.Translation(-pivot.location) @ old_local
        pivots[side] = pivot
    wheel_angle = {-1:0.0,1:0.0}
    previous = track(0)
    for frame in range(1, FRAMES+1):
        t = (frame-1)/FPS
        x,y,yaw = track(t)
        px,py,pyaw = previous
        distance = (x-px)*math.cos((yaw+pyaw)/2)+(y-py)*math.sin((yaw+pyaw)/2)
        dyaw=yaw-pyaw
        root.location=(x,y,0)
        root.rotation_euler=(0,0,yaw)
        key_transform(root,frame)
        for side,pivot in pivots.items():
            wheel_angle[side] += (distance-side*TRACK_WIDTH/2*dyaw)/WHEEL_RADIUS
            pivot.rotation_euler[1]=wheel_angle[side]
            pivot.keyframe_insert(data_path='rotation_euler',frame=frame)
        previous=(x,y,yaw)
    linear_keys(root)
    for pivot in pivots.values(): linear_keys(pivot)
    # Gentle OLED blinks, absent during the analytical freeze.
    for part in parts:
        if part.name.startswith('BUDDY | friendly cyan LED eye'):
            scale=part.scale.copy()
            for f in [1,175,178,181,700,703,706,1190,1193,1196,1200]:
                part.scale=scale.copy()
                if f in (178,703,1193): part.scale.z *= .18
                part.keyframe_insert(data_path='scale',frame=f)
            linear_keys(part)
    root['Motion'] = 'Quintic acceleration/braking; distance-driven differential wheel axles'
    return pivots


def add_camera(shot, tracks, cameras):
    data=bpy.data.cameras.new(shot['name'])
    camera=bpy.data.objects.new(shot['name'],data)
    cameras.objects.link(camera)
    data.lens=shot['lens'];data.sensor_width=36
    data.clip_start=.04;data.clip_end=300
    data.dof.use_dof=True;data.dof.aperture_fstop=shot['fstop'];data.dof.aperture_blades=9
    for frame in range(shot['first'],shot['last']+1):
        location,target=camera_pose(shot,(frame-1)/FPS,tracks)
        camera.location=location
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        data.dof.focus_distance=(Vector(target)-camera.location).length
        data.keyframe_insert(data_path='dof.focus_distance',frame=frame)
        key_transform(camera,frame)
    linear_keys(camera);linear_keys(data)
    marker=bpy.context.scene.timeline_markers.new(shot['name'],frame=shot['first'])
    marker.camera=camera
    return camera


def annotation(name, text, position, color, start, end, cameras, col, size=.20):
    data=bpy.data.curves.new(name,'FONT');data.body=text;data.size=size
    if HERO_FONT is not None:data.font=HERO_FONT
    data.align_x='CENTER';data.align_y='CENTER';data.space_line=1.25
    data.extrude=0;data.resolution_u=16
    obj=bpy.data.objects.new(name,data);col.objects.link(obj)
    obj.location=position;obj.data.materials.append(color)
    obj.visible_shadow=False
    for shot,camera in cameras:
        first=max(start,shot['first']);last=min(end,shot['last'])
        if first>last:continue
        for frame in range(first,last+1):
            # Camera-facing label plane; rotations baked so workers need no driver.
            location,target=camera_pose(shot,(frame-1)/FPS,TRACKS)
            obj.rotation_euler=(Vector(target)-Vector(location)).to_track_quat('-Z','Y').to_euler()
            obj.keyframe_insert(data_path='rotation_euler',frame=frame)
    window(obj,start,end)
    return obj


def route_line(name, points, material, start, end, col, radius=.018):
    obj=curve(name,[(x,y,.032) for x,y in points],radius,material,col)
    obj.visible_shadow=False
    window(obj,start,end)
    # Drawing the route is separate from its final opacity/scale window.
    for f,v in [(1,0),(start,0),(start+14,1),(end,1)]:
        obj.data.bevel_factor_end=v;obj.data.keyframe_insert(data_path='bevel_factor_end',frame=f)
    linear_keys(obj.data)
    return obj


def arrow(name, x,y,heading,material,start,end,col):
    points=[(-.32,.15,0),(0,0,0),(-.32,-.15,0)]
    obj=curve(name,points,.017,material,col)
    obj.location=(x,y,.046);obj.rotation_euler.z=heading
    window(obj,start,end)
    return obj


def ring(name, position, radius, material, start,end,col, pulse=False):
    points=[(radius*math.cos(i*math.tau/96),radius*math.sin(i*math.tau/96),0) for i in range(97)]
    obj=curve(name,points,.018,material,col);obj.location=position
    window(obj,start,end)
    if pulse:
        for f in range(start+8,end-8,3):
            scale=1+((f-start)%30)/30*.45
            obj.scale=(scale,scale,1);obj.keyframe_insert(data_path='scale',frame=f)
        linear_keys(obj)
    return obj


def add_effects(cameras, col):
    mint=shader('Hero overlay / confirmed mint',(.12,.82,.57),glow=2.0)
    white=shader('Hero overlay / neutral white',(.8,.92,1),glow=1.1)
    red=shader('Hero overlay / prediction red',(1,.075,.025),glow=2.0)
    amber=shader('Hero overlay / yielding amber',(1,.50,.08),glow=1.6)
    muted=shader('Hero overlay / released route',(.28,.34,.37),glow=.6)
    # Projected intentions in the approach, followed by a red shared-zone warning.
    intentions=[('A',[(18,6),(24,6)],0),('B',[(21,3),(21,9)],math.pi/2),('C',[(24,6),(18,6)],math.pi)]
    for name,points,heading in intentions:
        route_line(name+' / proposed route',points,white,280,540,col)
        arrow(name+' / direction',*(points[0]),heading,white,300,540,col)
    ring('Predicted conflict / red pulse',(21,6,.045),.92,red,361,540,col,True)
    ring('Predicted conflict / core',(21,6,.045),.76,red,361,540,col)
    route_line('Red intersection X',[(20.45,5.45),(21.55,6.55)],red,361,540,col)
    route_line('Red intersection X cross',[(20.45,6.55),(21.55,5.45)],red,361,540,col)
    # Wire silhouettes are clearly future-position markers, not physical robots.
    for i,(x,y,heading) in enumerate([(20.7,6,0),(21,5.6,math.pi/2),(21.5,6,math.pi)]):
        ghost=box('Prediction ghost '+str(i),(x,y,.28),(.97,.94,.40),red,col,.055)
        ghost.rotation_euler.z=heading
        wire=ghost.modifiers.new('Future footprint wire','WIREFRAME');wire.thickness=.009
        window(ghost,375,532)
    annotation('Prediction label','PREDICTED CONFLICT\nSHARED SPACE + TIME',(21,7.75,.5),white,365,532,cameras,col,.22)
    leader=curve('Prediction leader',[(21,6,.08),(21.1,7.2,.6),(21,7.45,.6)],.009,white,col);window(leader,365,532)
    for identifier,label,pos in [('robot_01','01 / MOCHI',(17.6,7,.55)),('robot_02','02 / PIP',(20.3,2.4,.55)),('robot_03','03 / BEAN',(24.3,7.1,.55))]:
        annotation(identifier+' intent',label,pos,white,370,536,cameras,col,.17)
    # Communication pulses travel robot-to-robot. No central decision hub drawn.
    for index,(a,b) in enumerate([((18,6),(21,3)),((21,3),(24,6)),((24,6),(18,6))]):
        points=[(*a,.7),((a[0]+b[0])/2,(a[1]+b[1])/2,1.35),(*b,.7)]
        line=curve('Peer intent channel '+str(index),points,.009,white,col);window(line,541,626)
        dot=cylinder('Peer message '+str(index),(*a,.7),.05,.05,mint,col,vertices=24)
        for f in range(541,627):
            u=((f-541+index*12)%40)/39
            dot.location=(a[0]+(b[0]-a[0])*u,a[1]+(b[1]-a[1])*u,.7+math.sin(u*math.pi)*.65)
            dot.keyframe_insert(data_path='location',frame=f)
        window(dot,541,626);linear_keys(dot)
    annotation('Lease granted','01 / ZONE RESERVED',(19,7.6,.6),mint,566,660,cameras,col,.21)
    annotation('Yield instruction','02 / YIELD',(20.7,2.3,.65),amber,566,660,cameras,col,.21)
    annotation('Detour instruction','03 / LOCAL DETOUR',(24.1,7.7,.6),mint,580,680,cameras,col,.21)
    route_line('A confirmed',[(18,6),(27,6)],mint,562,931,col)
    route_line('B wait',[(21,3),(21,4.0)],amber,562,988,col)
    route_line('B confirmed',[(21,3),(21,9)],mint,989,1200,col)
    route_line('C detour',[(24,6),(24,4.5),(18,4.5)],mint,580,1060,col)
    for x in range(19,28):
        tile=curve('A reserved footprint '+str(x),[(x-.36,5.64,.038),(x+.36,5.64,.038),(x+.36,6.36,.038),(x-.36,6.36,.038),(x-.36,5.64,.038)],.012,mint,col)
        crossing=next((f for f in range(661,931) if TRACKS['robot_01']((f-1)/FPS)[0]>x+.7),931)
        window(tile,585+(x-19)*5,crossing)
    # The failed robot is empty: this token denotes an uncollected assignment.
    ring('04 safe stop boundary',(33,9,.04),.85,amber,957,1200,col)
    route_line('04 cancelled assignment',[(33,9),(36,9),(36,6)],muted,969,1050,col)
    annotation('04 isolated','04 / SAFE-STOP\nFOOTPRINT HELD',(33,9,1.08),amber,969,1110,cameras,col,.13)
    annotation('Uncollected task','UNPICKED ORDER\nREASSIGNED TO 05',(34.4,8,.72),white,1111,1190,cameras,col,.22)
    route_line('05 reassigned route',[(39,6),(36,6)],mint,1030,1193,col)
    for index in range(3):
        dot=cylinder('Assignment token '+str(index),(33,9,1),.055,.06,mint,col,vertices=32)
        for f in range(1010,1140):
            u=ease((f-1010-index*8)/85)
            bx,by,_=TRACKS['robot_05']((f-1)/FPS)
            dot.location=(33+(bx-33)*u,9+(by-9)*u,1+.6*math.sin(math.pi*u))
            dot.keyframe_insert(data_path='location',frame=f)
        window(dot,1010+index*8,1130+index*2);linear_keys(dot)


def lighting(scene):
    # Preserve all original procedural materials, glass, microgeometry and decals.
    for obj in list(scene.objects):
        if obj.type=='LIGHT':
            if obj.name.startswith('High bay'):
                obj.data.color=(1,.87,.71);obj.data.energy=300
            elif obj.name.startswith('Window light | warm'):
                obj.data.color=(1,.79,.55);obj.data.energy=2200
            elif obj.name.startswith('Window light | cool'):
                obj.data.color=(.78,.87,1);obj.data.energy=1600
    col=collection('HERO 04 | motivated white-gold lighting')
    for name,pos,target,energy,color,size in [
        ('Hero warm key',(18,5,7.25),(21,6,0),950,(1,.78,.52),4),
        ('Hero neutral fill',(24,4,7.3),(21,6,0),700,(.86,.92,1),4),
        ('Hero stop softbox',(34,7,7.3),(33,9,0),900,(1,.86,.65),4),
    ]:
        data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.shape='DISK';data.size=size;data.color=color
        obj=bpy.data.objects.new(name,data);col.objects.link(obj);obj.location=pos
        obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
        obj.visible_camera=False;obj.visible_glossy=False;obj.visible_transmission=False
    scene.view_settings.view_transform='AgX'
    scene.view_settings.look='AgX - Medium High Contrast'
    for frame,exposure in [(1,-.45),(349,-.45),(370,-.95),(536,-.95),(568,-.45),(1200,-.45)]:
        scene.view_settings.exposure=exposure
        scene.keyframe_insert(data_path='view_settings.exposure',frame=frame)
    scene.render.engine='CYCLES';scene.cycles.device='GPU'
    scene.cycles.samples=768;scene.cycles.use_adaptive_sampling=True;scene.cycles.adaptive_threshold=.006
    scene.cycles.adaptive_min_samples=64
    scene.cycles.use_denoising=True;scene.cycles.denoiser='OPENIMAGEDENOISE'
    scene.cycles.denoising_input_passes='RGB_ALBEDO_NORMAL'
    scene.cycles.denoising_prefilter='ACCURATE'
    scene.cycles.preview_samples=16
    scene.cycles.max_bounces=16;scene.cycles.diffuse_bounces=6
    scene.cycles.glossy_bounces=8;scene.cycles.transmission_bounces=12;scene.cycles.transparent_max_bounces=24
    scene.render.use_simplify=False
    scene.render.use_motion_blur=True;scene.render.motion_blur_shutter=.35
    scene.render.resolution_x=3840;scene.render.resolution_y=2160;scene.render.resolution_percentage=100
    scene.render.fps=FPS;scene.render.fps_base=1
    scene.render.image_settings.file_format='OPEN_EXR'
    scene.render.image_settings.color_depth='16';scene.render.image_settings.color_mode='RGBA'
    scene.render.image_settings.exr_codec='ZIP'
    scene.render.filepath='//frames/hero_'
    scene.render.film_transparent=False
    scene.render.use_file_extension=True
    scene.render.use_overwrite=False
    scene.render.use_compositing=True
    scene.use_nodes=True
    nodes=scene.node_tree.nodes;nodes.clear()
    layers=nodes.new('CompositorNodeRLayers')
    glare=nodes.new('CompositorNodeGlare');glare.glare_type='FOG_GLOW';glare.quality='HIGH';glare.threshold=2.5;glare.mix=-.96
    output=nodes.new('CompositorNodeComposite')
    scene.node_tree.links.new(layers.outputs['Image'],glare.inputs['Image'])
    scene.node_tree.links.new(glare.outputs['Image'],output.inputs['Image'])


def animate_practicals(roots):
    # Separate material for a single stopped unit, to avoid changing the fleet.
    amber=shader('04 / warning diffuser amber',(1,.35,.025),glow=2)
    for part in roots['robot_04'].children:
        if part.name.startswith('Parcel |'):
            part.hide_render=True;part.hide_set(True)
        if part.name.startswith('BUDDY | status light diffuser'):
            material=part.data.materials[0].copy()
            part.data=part.data.copy();part.data.materials.clear();part.data.materials.append(material)
            bsdf=material.node_tree.nodes.get('Principled BSDF')
            if bsdf:
                for f,color,strength in [(1,(.1,.8,.6,1),1.8),(957,(.1,.8,.6,1),1.8),(963,(1,.35,.025,1),2.5),(1200,(1,.35,.025,1),2.5)]:
                    bsdf.inputs['Emission Color'].default_value=color;bsdf.inputs['Emission Color'].keyframe_insert('default_value',frame=f)
                    bsdf.inputs['Emission Strength'].default_value=strength;bsdf.inputs['Emission Strength'].keyframe_insert('default_value',frame=f)
    for part in roots['robot_05'].children:
        if part.name.startswith('Parcel |'):
            part.hide_render=True;part.hide_set(True)
    bpy.data.materials.remove(amber)


def audit_baked(scene, roots, report):
    # Verify the Blender data, not just the pure trajectory generator.
    for frame in [1,180,300,360,450,540,660,780,930,969,1111,1200]:
        scene.frame_set(frame)
        for identifier,root in roots.items():
            x,y,yaw=TRACKS[identifier]((frame-1)/FPS)
            assert (root.location-Vector((x,y,0))).length<1e-4
            assert abs(root.rotation_euler.z-yaw)<1e-4
    report['baked_root_keys']=sum(len(root.animation_data.action.fcurves[0].keyframe_points) for root in roots.values())
    report['wheel_axles']=24
    report['source_blend']=str(BASE.relative_to(ROOT))
    report['render_engine']=scene.render.engine
    report['resolution']=[3840,2160]
    report['source_geometry_simplified']=False
    report['scene_objects']=len(scene.objects)


TRACKS=build_tracks()


def main():
    global HERO_FONT
    report=validate_motion()
    OUT.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(BASE))
    scene=bpy.context.scene
    font_path=next((path for path in MONO_FONT_CANDIDATES if path.exists()),None)
    if font_path is None:
        raise FileNotFoundError('No supported monospaced font found; install DejaVu Sans Mono')
    HERO_FONT=bpy.data.fonts.load(str(font_path),check_existing=True)
    scene.animation_data_clear()
    scene.frame_start=1;scene.frame_end=FRAMES
    scene.timeline_markers.clear()
    fleet=bpy.data.collections['03 | BUDDY fleet — detailed robot assemblies']
    roots={obj.name.split(' /')[0]:obj for obj in list(fleet.objects) if obj.type=='EMPTY' and obj.name.startswith('robot_')}
    assert len(roots)==12
    rig=collection('HERO 01 | baked physical motion')
    for identifier,root in roots.items():
        rig_robot(root,TRACKS[identifier],rig)
    print('Baked twelve robots and 24 differential wheel axles',flush=True)
    cameras_col=collection('HERO 02 | seven interior camera shots')
    cameras=[(shot,add_camera(shot,TRACKS,cameras_col)) for shot in SHOTS]
    scene.camera=cameras[0][1]
    effects=collection('HERO 03 | predictive analysis and reservations')
    add_effects(cameras,effects)
    animate_practicals(roots)
    lighting(scene)
    audit_baked(scene,roots,report)
    scene['Hero sequence']='40 seconds / 1200 frames / interior only / 75 percent overhead'
    scene['Evidence scope']='Authored explanatory choreography; independent clearance check. Not a measured distributed-run result.'
    scene['Editorial freeze']='12–18 seconds; fleet and wheels hold while camera creeps and analysis animates.'
    scene['Task reassignment']='Robot 04 safe-stops before pickup; empty Robot 05 receives its unpicked order.'
    scene['Physical animation']='No staged physical impact. Predicted overlap appears only as red wire ghosts.'
    scene['Overlay typography']=f'Monospaced technical labels / {HERO_FONT.name} / packed into this file'
    for shot in SHOTS:
        assert shot['first']<=shot['last']<=1200
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.region_3d.view_perspective='CAMERA'
                area.spaces.active.shading.type='MATERIAL'
                area.spaces.active.overlay.show_overlays=False
    scene.frame_set(1)
    bpy.ops.object.select_all(action='DESELECT')
    # The untouched source remains separate. All animation lives in this output.
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(DEST))
    (OUT/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    (OUT/'shots.json').write_text(json.dumps(SHOTS,indent=2)+'\n')
    print('HERO_SAVED '+str(DEST),flush=True)
    print(json.dumps(report),flush=True)


if __name__=='__main__': main()
