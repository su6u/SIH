"""Authored cinematic choreography, in metres and presentation seconds.

This is an explanatory sequence, not output from the distributed scheduler.
The independent validation measures clearance of the baked motion itself.
"""
import math

FPS = 30
FRAMES = 1200
WHEEL_RADIUS = 0.165
TRACK_WIDTH = 0.944
BODY_RADIUS = 0.70  # conservative enclosing circle, including projecting wheels


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * x * (x * (x * 6 - 15) + 10)


def angle_delta(a, b):
    return (b - a + math.pi) % math.tau - math.pi


def route(start, segments, initial_yaw=0):
    """A segment is (start second, arrival second, destination x/y).

    Translation uses quintic easing, so velocity and acceleration are zero at
    every endpoint. Heading changes happen while stopped BEFORE translation.
    """
    result = []
    position, yaw, previous_end = start, initial_yaw, 0
    for begin, end, goal in segments:
        target_yaw = math.atan2(goal[1] - position[1], goal[0] - position[0])
        turn = angle_delta(yaw, target_yaw)
        turn_duration = abs(turn) / 0.9 * 1.875
        if abs(turn) > .001 and begin - previous_end < turn_duration - .001:
            raise ValueError(f"Turn needs {turn_duration:.2f}s before {begin}s: {position}->{goal}")
        result.append((begin, end, position, goal, yaw, yaw + turn, turn_duration))
        position, yaw, previous_end = goal, yaw + turn, end

    def sample(t):
        position, yaw = start, initial_yaw
        for begin, end, a, b, before_yaw, after_yaw, turn_duration in result:
            if t < begin:
                turn_alpha = ease((t - begin + turn_duration) / max(turn_duration, .00001))
                return (*a, before_yaw + (after_yaw - before_yaw) * turn_alpha)
            if t <= end:
                u = ease((t - begin) / (end - begin))
                return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, after_yaw)
            position, yaw = b, after_yaw
        return (*position, yaw)
    return sample


def build_tracks():
    # Three proposed paths meet at (21, 6). Motion freezes before the zone.
    # The resolution intentionally leaves room for real braking and pivot turns.
    tracks = {
        'robot_01': route((12, 6), [(0, 10, (18, 6)), (22, 31, (27, 6))]),
        'robot_02': route((21, -3), [(0, 10, (21, 3)), (33, 40, (21, 9))], math.pi / 2),
        'robot_03': route((30, 6), [(0, 10, (24, 6)), (22, 26, (21, 6)), (30, 36, (15, 6))], math.pi),
        'robot_04': route((38, 9), [(24, 32, (33, 9))], math.pi),
        'robot_05': route((39, 6), [(34, 40, (36, 6))], math.pi),
    }
    # C is replaced below by a real detour with zero-radius differential-drive
    # turns. A moves first, B yields, C backs off to a parallel lane.
    tracks['robot_03'] = route((30, 6), [(0, 10, (24, 6)),
        (21.3, 25.3, (24, 4.5)), (28.6, 35, (18, 4.5))], math.pi)
    # Background traffic stays in disjoint cross-aisles. Same editorial freeze
    # applies to all robots, with stationary, acceleration-continuous endpoints.
    for i, (x, y, direction) in enumerate([
        (-8, 6, 1), (-8, 18, 1), (10, 18, 1), (30, 18, 1),
        (48, 6, 1), (48, 29, -1), (4, 29, 1)
    ], 6):
        yaw = 0 if direction > 0 else math.pi
        tracks[f'robot_{i:02}'] = route((x, y), [(0, 10, (x + direction * 4, y)),
            (23, 40, (x + direction * 12, y))], yaw)
    return tracks


# All cameras are BELOW the intact roof (z=7.94) and inside the footprint.
# Top oblique shots account for 30 of the 40 seconds.
SHOTS = [
    dict(name='01 Interior overhead approach', first=1, last=180, lens=22, fstop=8,
         start=(21, -3, 7.45), end=(21, 1, 7.45), target_start=(21, 6, .3), target_end=(21, 6, .3)),
    dict(name='02 Mochi tracking insert', first=181, last=300, lens=42, fstop=4,
         follow='robot_01', offset=(-2.7, -2.5, 1.6)),
    dict(name='03 Predicted conflict overhead', first=301, last=540, lens=22, fstop=8,
         start=(21, 3.1, 7.5), end=(21, 3.65, 7.5), target_start=(21, 6, .2), target_end=(21, 6, .2)),
    dict(name='04 Peer agreement overhead', first=541, last=660, lens=22, fstop=8,
         start=(21, 3.65, 7.5), end=(21, 3.8, 7.5), target_start=(21, 6, .2), target_end=(21, 6, .2)),
    dict(name='05 Crossing and local detour', first=661, last=930, lens=19, fstop=8,
         start=(21, 3.8, 7.5), end=(23, 3.8, 7.5), target_start=(21, 6, .2), target_end=(23, 6, .2)),
    dict(name='06 Controlled stop insert', first=931, last=1110, lens=38, fstop=4.5,
         follow='robot_04', offset=(-2.5, -3.2, 1.75)),
    dict(name='07 Task handoff interior overview', first=1111, last=1200, lens=19, fstop=8,
         start=(34.5, 3.5, 7.5), end=(34.5, 4, 7.5), target_start=(34.5, 8, .2), target_end=(34.5, 8, .2)),
]


def camera_pose(shot, t, tracks):
    if 'follow' in shot:
        x, y, _ = tracks[shot['follow']](t)
        offset = shot['offset']
        return (x + offset[0], y + offset[1], offset[2]), (x, y, .35)
    u = ease((t * FPS + 1 - shot['first']) / max(1, shot['last'] - shot['first']))
    def mix(a, b):
        return tuple(x + (y - x) * u for x, y in zip(a, b))
    return mix(shot['start'], shot['end']), mix(shot['target_start'], shot['target_end'])
