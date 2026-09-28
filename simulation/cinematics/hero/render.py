"""Portable, explicit render entry point. No cloud credentials required.

blender -b --factory-startup --python render.py -- --preview --frames 240,450,780,1000,1150
blender -b --factory-startup --python render.py -- --device OPTIX --frames 450
blender -b --factory-startup --python render.py -- --device OPTIX --start 1 --end 1200
"""
from pathlib import Path
import argparse
import json
import math
import sys
import time

import bpy

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--blend',type=Path,default=HERE/'output/kinesis-hero-40s.blend')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--preview',action='store_true')
    parser.add_argument('--format',choices=['EXR','PNG'],default='EXR',
                        help='Final output format. PNG is 16-bit and presentation-ready; EXR is the linear master.')
    parser.add_argument('--resolution',choices=['720p','900p','1080p','1440p','4k'],default='4k')
    parser.add_argument('--samples',type=int,
                        help='Override the saved Cycles maximum sample count.')
    parser.add_argument('--adaptive-threshold',type=float,
                        help='Override the saved Cycles adaptive-noise threshold.')
    parser.add_argument('--time-limit',type=float,
                        help='Maximum Cycles sampling seconds per frame; preprocessing is additional.')
    parser.add_argument('--output-fps',type=int,choices=[24,30],default=30,
                        help='Render at 24 fps by evaluating the original 30 fps animation at subframes.')
    parser.add_argument('--frames',default='')
    parser.add_argument('--start',type=int,default=1)
    parser.add_argument('--end',type=int,default=1200)
    parser.add_argument('--device',choices=['CPU','OPTIX','CUDA','METAL'],default='OPTIX')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()))
    scene=bpy.context.scene
    source_start=scene.frame_start
    source_fps=scene.render.fps/scene.render.fps_base
    duration=(scene.frame_end-scene.frame_start+1)/source_fps
    output_count=round(duration*args.output_fps)
    if not args.frames and args.end==1200 and args.output_fps!=30:args.end=output_count
    frames=[int(value) for value in args.frames.split(',')] if args.frames else list(range(args.start,args.end+1))
    if not frames or min(frames)<1 or max(frames)>output_count:
        raise ValueError(f'Output frames must be between 1 and {output_count}')
    width,height={'720p':(1280,720),'900p':(1600,900),'1080p':(1920,1080),
                  '1440p':(2560,1440),'4k':(3840,2160)}[args.resolution]
    scene.render.resolution_x=width;scene.render.resolution_y=height
    scene.render.resolution_percentage=100
    if args.samples is not None:
        if args.samples<1:raise ValueError('--samples must be positive')
        scene.cycles.samples=args.samples
        scene.cycles.adaptive_min_samples=min(scene.cycles.adaptive_min_samples,max(8,args.samples//4))
    if args.adaptive_threshold is not None:
        if args.adaptive_threshold<=0:raise ValueError('--adaptive-threshold must be positive')
        scene.cycles.adaptive_threshold=args.adaptive_threshold
    if args.time_limit is not None:
        if args.time_limit<=0:raise ValueError('--time-limit must be positive')
        scene.cycles.time_limit=args.time_limit
    scene.render.fps=args.output_fps;scene.render.fps_base=1
    scene.render.use_persistent_data=True
    scene.cycles.sampling_pattern='BLUE_NOISE'
    scene.cycles.use_animated_seed=True
    scene.cycles.use_denoising=True
    scene.cycles.denoiser='OPENIMAGEDENOISE'
    if hasattr(scene.cycles,'denoising_input_passes'):
        scene.cycles.denoising_input_passes='RGB_ALBEDO_NORMAL'
    if hasattr(scene.cycles,'denoising_prefilter'):
        scene.cycles.denoising_prefilter='ACCURATE'
    output=(args.output or HERE/'output'/('review' if args.preview else 'frames')).resolve()
    output.mkdir(parents=True,exist_ok=True)
    if args.device!='CPU':
        preferences=bpy.context.preferences.addons['cycles'].preferences
        preferences.compute_device_type=args.device
        preferences.get_devices()
        devices=[d for d in preferences.devices if d.type==args.device]
        if not devices:raise RuntimeError(f'No {args.device} GPU available; explicitly choose CPU if intended')
        for d in preferences.devices:d.use=d.type==args.device
        scene.cycles.device='GPU'
        if hasattr(scene.cycles,'denoising_use_gpu'):scene.cycles.denoising_use_gpu=True
        if hasattr(scene.render,'compositor_device'):scene.render.compositor_device='GPU'
        print('GPU_DEVICES '+', '.join(d.name for d in devices),flush=True)
    else:scene.cycles.device='CPU'
    extension='exr' if args.format=='EXR' else 'png'
    if args.format=='PNG':
        scene.render.image_settings.file_format='PNG'
        scene.render.image_settings.color_depth='16'
        scene.render.image_settings.color_mode='RGB'
    if args.preview:
        scene.render.resolution_percentage=25
        scene.cycles.samples=24
        scene.cycles.adaptive_min_samples=8
        scene.cycles.adaptive_threshold=.08
        scene.render.image_settings.file_format='PNG'
        scene.render.image_settings.color_depth='8'
        scene.render.image_settings.color_mode='RGB'
        extension='png'
    timings=[]
    print('RENDER_CONFIG '+json.dumps(dict(resolution=[scene.render.resolution_x,scene.render.resolution_y],
          output_fps=args.output_fps,output_frames=output_count,samples=scene.cycles.samples,
          adaptive_threshold=scene.cycles.adaptive_threshold,time_limit=scene.cycles.time_limit,
          persistent_data=scene.render.use_persistent_data,
          denoiser=scene.cycles.denoiser,
          sampling_pattern=scene.cycles.sampling_pattern,
          animated_seed=scene.cycles.use_animated_seed)),flush=True)
    for frame in frames:
        destination=output/f'hero_{frame:04d}.{extension}'
        if destination.exists():
            print('SKIP '+str(destination),flush=True)
            continue
        source_frame=source_start+(frame-1)*source_fps/args.output_fps
        source_whole=math.floor(source_frame)
        scene.frame_set(source_whole,subframe=source_frame-source_whole)
        scene.render.filepath=str(destination)
        started=time.monotonic()
        bpy.ops.render.render(write_still=True)
        seconds=round(time.monotonic()-started,3)
        timings.append(dict(frame=frame,source_frame=round(source_frame,4),seconds=seconds,file=str(destination)))
        print('FRAME_DONE '+json.dumps(timings[-1]),flush=True)
    suffix=f'{frames[0]:04d}-{frames[-1]:04d}'
    (output/f'timings-{suffix}.json').write_text(json.dumps(timings,indent=2)+'\n')


if __name__=='__main__':main()
