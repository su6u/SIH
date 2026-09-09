#include "swarmroute_control/controller_math.hpp"

#include <chrono>
#include <cmath>
#include <deque>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>

#include "geometry_msgs/msg/pose_stamped.hpp"
#include "geometry_msgs/msg/twist.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "nav_msgs/msg/path.hpp"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/bool.hpp"
#include "std_msgs/msg/int64.hpp"

using namespace std::chrono_literals;

namespace swarmroute_control
{

class RouteExecutor final : public rclcpp::Node
{
public:
  RouteExecutor()
  : Node("route_executor"), last_update_(std::chrono::steady_clock::now())
  {
    control_rate_hz_ = declare_parameter("control_rate_hz", 30.0);
    max_linear_speed_ = declare_parameter("max_linear_speed", 0.75);
    max_angular_speed_ = declare_parameter("max_angular_speed", 1.5);
    max_linear_acceleration_ = declare_parameter("max_linear_acceleration", 0.8);
    max_angular_acceleration_ = declare_parameter("max_angular_acceleration", 2.5);
    position_tolerance_ = declare_parameter("position_tolerance", 0.08);
    rotate_first_threshold_ = declare_parameter("rotate_first_threshold", 0.45);
    odometry_timeout_seconds_ = declare_parameter("odometry_timeout_seconds", 0.5);
    local_safety_timeout_seconds_ = declare_parameter("local_safety_timeout_seconds", 0.35);
    peer_authority_timeout_seconds_ = declare_parameter("peer_authority_timeout_seconds", 0.75);
    require_peer_authority_ = declare_parameter("require_peer_authority", true);
    world_origin_x_ = declare_parameter("world_origin_x", 0.0);
    world_origin_y_ = declare_parameter("world_origin_y", 0.0);
    world_origin_yaw_ = declare_parameter("world_origin_yaw", 0.0);
    if (control_rate_hz_ <= 0.0 || local_safety_timeout_seconds_ <= 0.0 ||
      peer_authority_timeout_seconds_ <= 0.0)
    {
      throw std::invalid_argument("control, safety, and authority rates must be positive");
    }

    command_publisher_ = create_publisher<geometry_msgs::msg::Twist>("cmd_vel", 10);
    odometry_subscription_ = create_subscription<nav_msgs::msg::Odometry>(
      "odometry", rclcpp::SensorDataQoS(),
      [this](nav_msgs::msg::Odometry::ConstSharedPtr message) {
        std::scoped_lock lock(mutex_);
        odometry_ = *message;
        last_odometry_ = std::chrono::steady_clock::now();
        have_odometry_ = true;
      });
    auto route_qos = rclcpp::QoS(rclcpp::KeepLast(1)).reliable();
    route_subscription_ = create_subscription<nav_msgs::msg::Path>(
      "route", route_qos,
      [this](nav_msgs::msg::Path::ConstSharedPtr message) {
        std::scoped_lock lock(mutex_);
        route_.assign(message->poses.begin(), message->poses.end());
      });
    global_safety_subscription_ = create_subscription<std_msgs::msg::Bool>(
      "/swarmroute/safety_stop", rclcpp::QoS(1).reliable().transient_local(),
      [this](std_msgs::msg::Bool::ConstSharedPtr message) {
        std::scoped_lock lock(mutex_);
        global_safety_stop_ = message->data;
      });
    local_safety_subscription_ = create_subscription<std_msgs::msg::Bool>(
      "safety_stop", rclcpp::QoS(1).reliable().transient_local(),
      [this](std_msgs::msg::Bool::ConstSharedPtr message) {
        std::scoped_lock lock(mutex_);
        local_safety_stop_ = message->data;
        last_local_safety_ = std::chrono::steady_clock::now();
        have_local_safety_ = true;
      });
    peer_authority_subscription_ = create_subscription<std_msgs::msg::Bool>(
      "authority_lease", rclcpp::QoS(10).reliable(),
      [this](std_msgs::msg::Bool::ConstSharedPtr message) {
        std::scoped_lock lock(mutex_);
        peer_authority_active_ = message->data;
        last_peer_authority_ = std::chrono::steady_clock::now();
        have_peer_authority_ = true;
      });
    progress_publisher_ = create_publisher<std_msgs::msg::Int64>("progress", 10);

    const auto period = std::chrono::duration<double>(1.0 / control_rate_hz_);
    timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(period),
      [this]() { update(); });
  }

private:
  void update()
  {
    std::scoped_lock lock(mutex_);
    const auto steady_now = std::chrono::steady_clock::now();
    const double dt = std::max(
      1e-3, std::chrono::duration<double>(steady_now - last_update_).count());
    last_update_ = steady_now;

    const bool local_safety_stale = !have_local_safety_ ||
      std::chrono::duration<double>(steady_now - last_local_safety_).count() >
      local_safety_timeout_seconds_;
    const bool peer_authority_stale = require_peer_authority_ &&
      (!have_peer_authority_ ||
      std::chrono::duration<double>(steady_now - last_peer_authority_).count() >
      peer_authority_timeout_seconds_);
    if (global_safety_stop_ || local_safety_stop_ || local_safety_stale ||
      (require_peer_authority_ && !peer_authority_active_) || peer_authority_stale)
    {
      publish_stop();
      return;
    }

    if (!have_odometry_ ||
      std::chrono::duration<double>(steady_now - last_odometry_).count() >
      odometry_timeout_seconds_)
    {
      publish_stop();
      return;
    }

    while (!route_.empty()) {
      const auto & target = route_.front();
      const auto local_target = world_to_local(
        target.pose.position.x, target.pose.position.y,
        world_origin_x_, world_origin_y_, world_origin_yaw_);
      const double dx = local_target.x - odometry_.pose.pose.position.x;
      const double dy = local_target.y - odometry_.pose.pose.position.y;
      if (std::hypot(dx, dy) > position_tolerance_) {
        break;
      }
      const rclcpp::Time target_time(target.header.stamp);
      if (get_clock()->now() < target_time) {
        publish_limited_stop(dt);
        return;
      }
      std_msgs::msg::Int64 progress;
      progress.data = target_time.nanoseconds();
      progress_publisher_->publish(progress);
      route_.pop_front();
    }

    if (route_.empty()) {
      publish_limited_stop(dt);
      return;
    }

    const auto & world_target = route_.front().pose.position;
    const auto target = world_to_local(
      world_target.x, world_target.y,
      world_origin_x_, world_origin_y_, world_origin_yaw_);
    const auto & orientation = odometry_.pose.pose.orientation;
    const double yaw = quaternion_yaw(
      orientation.x, orientation.y, orientation.z, orientation.w);
    const double dx = target.x - odometry_.pose.pose.position.x;
    const double dy = target.y - odometry_.pose.pose.position.y;
    const double distance = std::hypot(dx, dy);
    const double heading_error = normalize_angle(std::atan2(dy, dx) - yaw);

    double linear_target = std::min(max_linear_speed_, 1.2 * distance);
    if (std::abs(heading_error) > rotate_first_threshold_) {
      linear_target = 0.0;
    } else {
      linear_target *= std::max(0.0, std::cos(heading_error));
    }
    const double angular_target = std::clamp(
      2.5 * heading_error, -max_angular_speed_, max_angular_speed_);

    geometry_msgs::msg::Twist command;
    command.linear.x = move_towards(
      last_command_.linear.x, linear_target, max_linear_acceleration_ * dt);
    command.angular.z = move_towards(
      last_command_.angular.z, angular_target, max_angular_acceleration_ * dt);
    last_command_ = command;
    command_publisher_->publish(command);
  }

  void publish_limited_stop(double dt)
  {
    geometry_msgs::msg::Twist command;
    command.linear.x = move_towards(
      last_command_.linear.x, 0.0, max_linear_acceleration_ * dt);
    command.angular.z = move_towards(
      last_command_.angular.z, 0.0, max_angular_acceleration_ * dt);
    last_command_ = command;
    command_publisher_->publish(command);
  }

  void publish_stop()
  {
    last_command_ = geometry_msgs::msg::Twist{};
    command_publisher_->publish(last_command_);
  }

  std::mutex mutex_;
  std::deque<geometry_msgs::msg::PoseStamped> route_;
  nav_msgs::msg::Odometry odometry_;
  geometry_msgs::msg::Twist last_command_;
  bool have_odometry_{false};
  bool have_local_safety_{false};
  bool have_peer_authority_{false};
  bool global_safety_stop_{false};
  bool local_safety_stop_{true};
  bool peer_authority_active_{false};
  bool require_peer_authority_{true};
  double control_rate_hz_;
  double max_linear_speed_;
  double max_angular_speed_;
  double max_linear_acceleration_;
  double max_angular_acceleration_;
  double position_tolerance_;
  double rotate_first_threshold_;
  double odometry_timeout_seconds_;
  double local_safety_timeout_seconds_;
  double peer_authority_timeout_seconds_;
  double world_origin_x_;
  double world_origin_y_;
  double world_origin_yaw_;
  std::chrono::steady_clock::time_point last_odometry_;
  std::chrono::steady_clock::time_point last_local_safety_;
  std::chrono::steady_clock::time_point last_peer_authority_;
  std::chrono::steady_clock::time_point last_update_;
  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr command_publisher_;
  rclcpp::Publisher<std_msgs::msg::Int64>::SharedPtr progress_publisher_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odometry_subscription_;
  rclcpp::Subscription<nav_msgs::msg::Path>::SharedPtr route_subscription_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr global_safety_subscription_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr local_safety_subscription_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr peer_authority_subscription_;
  rclcpp::TimerBase::SharedPtr timer_;
};

}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<swarmroute_control::RouteExecutor>());
  rclcpp::shutdown();
  return 0;
}
