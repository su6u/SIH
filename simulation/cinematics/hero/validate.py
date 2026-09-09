"""Independent subframe clearance, speed, acceleration and camera checks."""
import json
import math
from pathlib import Path
from motion import BODY_RADIUS, SHOTS, build_tracks, camera_pose

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'simulation/ros2_ws/src/swarmroute_gazebo/config/fulfillment_contract.json'


def inside(point, sections, margin=0):
    return any(x1 + margin <= point[0] <= x2 - margin and y1 + margin <= point[1] <= y2 - margin
               for x1, y1, x2, y2 in sections)


def run():
    contract = json.loads(CONTRACT.read_text())
    tracks = build_tracks()
    sections = contract['layout']['floor_sections']
    obstacles = [i['bounds'] for i in contract['instances']]
    minimum = math.inf
    closest = None
    max_speed = max_acceleration = max_yaw_speed = 0
    previous, velocities = {}, {}
    for sample in range(40 * 120 + 1):
        t = sample / 120
        poses = {identifier: track(t) for identifier, track in tracks.items()}
        for identifier, (x, y, yaw) in poses.items():
            assert inside((x, y), sections, BODY_RADIUS), (identifier, t, 'outside footprint')
            for x1, y1, x2, y2 in obstacles:
                distance = math.hypot(max(x1 - x, 0, x - x2), max(y1 - y, 0, y - y2))
                assert distance >= BODY_RADIUS, (identifier, t, 'obstacle', distance)
            if identifier in previous:
                px, py, pyaw = previous[identifier]
                vx, vy = (x - px) * 120, (y - py) * 120
                speed = math.hypot(vx, vy)
                max_speed = max(max_speed, speed)
                max_yaw_speed = max(max_yaw_speed, abs(yaw - pyaw) * 120)
                if identifier in velocities:
                    pvx, pvy = velocities[identifier]
                    max_acceleration = max(max_acceleration, math.hypot(vx - pvx, vy - pvy) * 120)
                velocities[identifier] = (vx, vy)
            previous[identifier] = (x, y, yaw)
        ids = list(poses)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                distance = math.dist(poses[a][:2], poses[b][:2])
                if distance < minimum:
                    minimum, closest = distance, (a, b, t)
                assert distance >= BODY_RADIUS * 2, (a, b, t, distance)
        for shot in SHOTS:
            frame = t * 30 + 1
            if shot['first'] <= frame <= shot['last']:
                location, _ = camera_pose(shot, t, tracks)
                assert inside(location, sections, .1) and .15 < location[2] < 7.75, (shot['name'], location)
                # Racks reach ~5.5m. Validate low insert cameras against AABBs.
                if location[2] < 5.6:
                    for x1,y1,x2,y2 in obstacles:
                        assert not (x1-.12 < location[0] < x2+.12 and y1-.12 < location[1] < y2+.12), (shot['name'],'camera inside asset',t)
    assert max_speed <= 2.0, max_speed
    assert max_acceleration <= 1.0, max_acceleration
    assert max_yaw_speed <= .91, max_yaw_speed
    for track in tracks.values():
        assert track(12) == track(18), 'editorial freeze must hold all fleet motion'
    return dict(kind='authored cinematic kinematics, not scheduler benchmark', seconds=40, fps=30,
                frames=1200, robots=len(tracks), sample_rate_hz=120,
                minimum_center_separation_m=round(minimum,4), conservative_body_radius_m=BODY_RADIUS,
                minimum_envelope_gap_m=round(minimum-2*BODY_RADIUS,4), closest_pair=closest,
                maximum_speed_m_s=round(max_speed,4), maximum_acceleration_m_s2=round(max_acceleration,4),
                maximum_yaw_speed_rad_s=round(max_yaw_speed,4), camera_paths_inside_building=True,
                collisions=0, shots=len(SHOTS))


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
