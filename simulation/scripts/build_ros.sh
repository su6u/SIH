#!/usr/bin/env bash
set -eo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(cd -- "${script_dir}/../ros2_ws" && pwd)"

source /opt/ros/jazzy/setup.bash
set -u
cd "${workspace_dir}"
colcon build --symlink-install --event-handlers console_direct+
