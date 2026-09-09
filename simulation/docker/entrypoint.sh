#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/jazzy/setup.bash
source /opt/swarmroute/simulation/ros2_ws/install/setup.bash
set -u
exec "$@"
