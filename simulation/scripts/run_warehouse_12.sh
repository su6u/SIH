#!/usr/bin/env bash
set -eo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_dir="$(cd -- "${script_dir}/../.." && pwd)"
workspace_dir="${repository_dir}/simulation/ros2_ws"
scenario_path="${repository_dir}/simulator/scenarios/fulfillment-large-12.json"

source /opt/ros/jazzy/setup.bash
source "${workspace_dir}/install/setup.bash"
set -u
ros2 launch swarmroute_bringup warehouse_12.launch.py \
  "scenario:=${scenario_path}" \
  headless:=false
