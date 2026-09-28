FROM ros:jazzy-ros-base-noble

SHELL ["/bin/bash", "-c"]
ARG GZ_LAUNCH_VERSION=7.1.2-1~noble

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL https://packages.osrfoundation.org/gazebo.gpg \
       -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] https://packages.osrfoundation.org/gazebo/ubuntu-stable noble main" \
       > /etc/apt/sources.list.d/gazebo-stable.list \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gz-launch7-cli=${GZ_LAUNCH_VERSION} \
        python3-colcon-common-extensions \
        python3-pip \
        ros-jazzy-ament-cmake-gtest \
        ros-jazzy-ament-flake8 \
        ros-jazzy-ament-pep257 \
        ros-jazzy-diagnostic-msgs \
        ros-jazzy-geometry-msgs \
        ros-jazzy-nav-msgs \
        ros-jazzy-ros-gz-bridge \
        ros-jazzy-ros-gz-sim \
        ros-jazzy-std-msgs \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' gz-launch7-cli)" ge 7.1.2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/kinesis
RUN install -d -m 0750 /var/lib/kinesis
COPY simulator ./simulator
RUN python3 -m pip install --break-system-packages ./simulator

COPY simulation/ros2_ws ./simulation/ros2_ws
RUN source /opt/ros/jazzy/setup.bash \
    && cd /opt/kinesis/simulation/ros2_ws \
    && colcon build --merge-install --cmake-args -DBUILD_TESTING=ON
RUN source /opt/ros/jazzy/setup.bash \
    && source /opt/kinesis/simulation/ros2_ws/install/setup.bash \
    && cd /opt/kinesis/simulation/ros2_ws \
    && colcon test --merge-install --event-handlers console_direct+ \
    && colcon test-result --verbose
RUN source /opt/ros/jazzy/setup.bash \
    && SDF_PATH=/opt/kinesis/simulation/ros2_ws/install/share/kinesis_gazebo/models \
       gz sdf -k /opt/kinesis/simulation/ros2_ws/install/share/kinesis_gazebo/worlds/warehouse_fulfillment.sdf

COPY simulation/docker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "kinesis_bringup", "warehouse_12.launch.py", "scenario:=/opt/kinesis/simulator/scenarios/fulfillment-large-12.json", "headless:=true"]
