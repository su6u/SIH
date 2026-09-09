from __future__ import annotations

import json
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


ROBOT_NAMES = tuple(f"robot_{index:02d}" for index in range(1, 13))


def generate_launch_description() -> LaunchDescription:
    gazebo_share = get_package_share_directory("swarmroute_gazebo")
    bringup_share = get_package_share_directory("swarmroute_bringup")
    ros_gz_share = get_package_share_directory("ros_gz_sim")
    world = os.path.join(gazebo_share, "worlds", "warehouse_fulfillment.sdf")
    with open(
        os.path.join(gazebo_share, "config", "fulfillment_contract.json")
    ) as stream:
        contract = json.load(stream)
    robot_initial_poses = contract["spawns"]
    grid = contract["layout"]["grid"]
    models = os.path.join(gazebo_share, "models")
    bridge = os.path.join(gazebo_share, "config", "bridge.yaml")
    lidar_bridge = os.path.join(gazebo_share, "config", "lidar_bridge.yaml")
    websocket_launch = os.path.join(gazebo_share, "config", "websocket.gzlaunch")
    control = os.path.join(bringup_share, "config", "control.yaml")

    scenario = LaunchConfiguration("scenario")
    headless = LaunchConfiguration("headless")
    enable_lidar_bridge = LaunchConfiguration("enable_lidar_bridge")
    enable_web_visualization = LaunchConfiguration("enable_web_visualization")
    use_distributed = LaunchConfiguration("use_distributed")
    state_directory = LaunchConfiguration("state_directory")
    gz_launch = os.path.join(ros_gz_share, "launch", "gz_sim.launch.py")
    gz_config_path = os.pathsep.join(
        path for path in ("/usr/share/gz", os.environ.get("GZ_CONFIG_PATH", "")) if path
    )

    actions = [
        DeclareLaunchArgument(
            "scenario",
            description="Absolute path to a SwarmRoute scenario JSON file.",
        ),
        DeclareLaunchArgument("headless", default_value="false"),
        DeclareLaunchArgument("enable_lidar_bridge", default_value="false"),
        DeclareLaunchArgument("enable_web_visualization", default_value="true"),
        DeclareLaunchArgument(
            "use_distributed",
            default_value="true",
            description=(
                "Run one authenticated peer per AMR; false selects the baseline coordinator."
            ),
        ),
        DeclareLaunchArgument(
            "state_directory",
            default_value="/tmp/swarmroute-state",
            description="Private per-peer durable-state directory.",
        ),
        SetEnvironmentVariable("GZ_CONFIG_PATH", gz_config_path),
        SetEnvironmentVariable("GZ_SIM_RESOURCE_PATH", models),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(gz_launch),
            launch_arguments={"gz_args": f"-r -s {world}"}.items(),
            condition=IfCondition(headless),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(gz_launch),
            launch_arguments={"gz_args": f"-r {world}"}.items(),
            condition=UnlessCondition(headless),
        ),
        ExecuteProcess(
            cmd=["gz", "launch", "-v", "2", websocket_launch],
            condition=IfCondition(enable_web_visualization),
            output="screen",
        ),
        Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            name="gazebo_bridge",
            parameters=[{"config_file": bridge}],
            output="screen",
        ),
        Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            name="lidar_bridge",
            parameters=[{"config_file": lidar_bridge}],
            condition=IfCondition(enable_lidar_bridge),
            output="screen",
        ),
        Node(
            package="swarmroute_coordinator",
            executable="coordinator",
            name="coordinator",
            parameters=[
                {
                    "scenario": scenario,
                    "use_sim_time": True,
                    "cell_resolution": grid["resolution"],
                    "origin_x": float(grid["origin"][0]),
                    "origin_y": float(grid["origin"][1]),
                    "tick_seconds": 5.0,
                    "max_ticks": contract["layout"]["max_ticks"],
                }
            ],
            condition=UnlessCondition(use_distributed),
            output="screen",
        ),
        Node(
            package="swarmroute_control",
            executable="safety_monitor",
            name="safety_monitor",
            parameters=[
                {
                    "use_sim_time": True,
                    "robot_names": list(ROBOT_NAMES),
                    "world_origin_xs": [
                        float(robot_initial_poses[name][0]) for name in ROBOT_NAMES
                    ],
                    "world_origin_ys": [
                        float(robot_initial_poses[name][1]) for name in ROBOT_NAMES
                    ],
                    "world_origin_yaws": [
                        float(robot_initial_poses[name][2]) for name in ROBOT_NAMES
                    ],
                    "robot_radius": 0.59,
                    "localization_error": 0.05,
                    "reaction_seconds": 0.1,
                    "maximum_deceleration": 1.5,
                    "separation_margin": 0.1,
                    "stale_after_seconds": 0.2,
                }
            ],
            output="screen",
        ),
    ]
    actions.extend(
        Node(
            package="swarmroute_peer",
            executable="peer_node",
            namespace=robot_name,
            name="peer",
            parameters=[
                {
                    "scenario": scenario,
                    "robot_id": robot_name,
                    "use_sim_time": True,
                    "cell_resolution": grid["resolution"],
                    "grid_origin_x": float(grid["origin"][0]),
                    "grid_origin_y": float(grid["origin"][1]),
                    "world_origin_x": float(robot_initial_poses[robot_name][0]),
                    "world_origin_y": float(robot_initial_poses[robot_name][1]),
                    "world_origin_yaw": float(robot_initial_poses[robot_name][2]),
                    "tick_seconds": 5.0,
                    "max_ticks": contract["layout"]["max_ticks"],
                    "message_ttl_ms": 1_000,
                    "maximum_clock_skew_ms": 1_000,
                    "membership_reconfiguration_grace_seconds": 5.0,
                    "state_directory": state_directory,
                }
            ],
            condition=IfCondition(use_distributed),
            output="screen",
        )
        for robot_name in ROBOT_NAMES
    )
    actions.extend(
        Node(
            package="swarmroute_control",
            executable="local_safety_monitor",
            namespace=robot_name,
            name="local_safety_monitor",
            parameters=[
                {
                    "use_sim_time": True,
                    "local_robot": robot_name,
                    "robot_names": list(ROBOT_NAMES),
                    "world_origin_xs": [
                        float(robot_initial_poses[name][0]) for name in ROBOT_NAMES
                    ],
                    "world_origin_ys": [
                        float(robot_initial_poses[name][1]) for name in ROBOT_NAMES
                    ],
                    "world_origin_yaws": [
                        float(robot_initial_poses[name][2]) for name in ROBOT_NAMES
                    ],
                    "robot_radius": 0.59,
                    "localization_error": 0.05,
                    "reaction_seconds": 0.1,
                    "maximum_deceleration": 1.5,
                    "separation_margin": 0.1,
                    "stale_after_seconds": 0.2,
                }
            ],
            output="screen",
        )
        for robot_name in ROBOT_NAMES
    )
    actions.extend(
        Node(
            package="swarmroute_control",
            executable="route_executor",
            namespace=robot_name,
            name="route_executor",
            parameters=[
                control,
                {
                    "world_origin_x": float(robot_initial_poses[robot_name][0]),
                    "world_origin_y": float(robot_initial_poses[robot_name][1]),
                    "world_origin_yaw": float(robot_initial_poses[robot_name][2]),
                    "local_safety_timeout_seconds": 0.35,
                    "peer_authority_timeout_seconds": 0.75,
                    "require_peer_authority": ParameterValue(
                        use_distributed, value_type=bool
                    ),
                },
            ],
            output="screen",
        )
        for robot_name in ROBOT_NAMES
    )
    return LaunchDescription(actions)
