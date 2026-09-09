#include "swarmroute_control/controller_math.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "diagnostic_msgs/msg/diagnostic_array.hpp"
#include "diagnostic_msgs/msg/diagnostic_status.hpp"
#include "diagnostic_msgs/msg/key_value.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/bool.hpp"

using namespace std::chrono_literals;

namespace swarmroute_control
{

struct LocalObservation
{
  double x{0.0};
  double y{0.0};
  double velocity_x{0.0};
  double velocity_y{0.0};
  std::chrono::steady_clock::time_point received_at{};
  bool received{false};
};

class LocalSafetyMonitor final : public rclcpp::Node
{
public:
  LocalSafetyMonitor()
  : Node("local_safety_monitor")
  {
    local_robot_ = declare_parameter("local_robot", std::string{});
    robot_names_ = declare_parameter<std::vector<std::string>>(
      "robot_names", std::vector<std::string>{});
    world_origin_xs_ = declare_parameter<std::vector<double>>(
      "world_origin_xs", std::vector<double>{});
    world_origin_ys_ = declare_parameter<std::vector<double>>(
      "world_origin_ys", std::vector<double>{});
    world_origin_yaws_ = declare_parameter<std::vector<double>>(
      "world_origin_yaws", std::vector<double>{});
    robot_radius_ = declare_parameter("robot_radius", 0.59);
    localization_error_ = declare_parameter("localization_error", 0.05);
    reaction_seconds_ = declare_parameter("reaction_seconds", 0.1);
    maximum_deceleration_ = declare_parameter("maximum_deceleration", 1.5);
    separation_margin_ = declare_parameter("separation_margin", 0.1);
    stale_after_seconds_ = declare_parameter("stale_after_seconds", 0.2);
    if (local_robot_.empty() || robot_names_.empty() ||
      std::find(robot_names_.begin(), robot_names_.end(), local_robot_) == robot_names_.end() ||
      robot_radius_ <= 0.0 || localization_error_ < 0.0 || reaction_seconds_ < 0.0 ||
      maximum_deceleration_ <= 0.0 || separation_margin_ < 0.0 || stale_after_seconds_ <= 0.0)
    {
      throw std::invalid_argument("local safety parameters are invalid");
    }
    if (world_origin_xs_.size() != robot_names_.size() ||
      world_origin_ys_.size() != robot_names_.size() ||
      world_origin_yaws_.size() != robot_names_.size())
    {
      throw std::invalid_argument("world origin arrays must match robot_names");
    }

    stop_publisher_ = create_publisher<std_msgs::msg::Bool>(
      "safety_stop", rclcpp::QoS(1).reliable().transient_local());
    diagnostics_publisher_ = create_publisher<diagnostic_msgs::msg::DiagnosticArray>(
      "/swarmroute/diagnostics", 10);
    for (std::size_t index = 0; index < robot_names_.size(); ++index) {
      const auto & name = robot_names_[index];
      observations_.emplace(name, LocalObservation{});
      subscriptions_.push_back(create_subscription<nav_msgs::msg::Odometry>(
        "/" + name + "/odometry", rclcpp::SensorDataQoS(),
        [this, name, index](nav_msgs::msg::Odometry::ConstSharedPtr message) {
          auto & observation = observations_.at(name);
          const auto world = local_to_world(
            message->pose.pose.position.x, message->pose.pose.position.y,
            world_origin_xs_[index], world_origin_ys_[index], world_origin_yaws_[index]);
          observation.x = world.x;
          observation.y = world.y;
          const auto & orientation = message->pose.pose.orientation;
          const double yaw = world_origin_yaws_[index] + quaternion_yaw(
            orientation.x, orientation.y, orientation.z, orientation.w);
          const double cosine = std::cos(yaw);
          const double sine = std::sin(yaw);
          observation.velocity_x =
            cosine * message->twist.twist.linear.x - sine * message->twist.twist.linear.y;
          observation.velocity_y =
            sine * message->twist.twist.linear.x + cosine * message->twist.twist.linear.y;
          observation.received_at = std::chrono::steady_clock::now();
          observation.received = true;
        }));
    }
    timer_ = create_wall_timer(100ms, [this]() { inspect(); });
  }

private:
  void inspect()
  {
    const auto now = std::chrono::steady_clock::now();
    const auto & local = observations_.at(local_robot_);
    std::size_t stale_count = 0;
    for (const auto & name : robot_names_) {
      const auto & observation = observations_.at(name);
      if (!observation.received ||
        std::chrono::duration<double>(now - observation.received_at).count() >
        stale_after_seconds_)
      {
        ++stale_count;
      }
    }

    double closest_distance = std::numeric_limits<double>::infinity();
    double required_separation =
      2.0 * (robot_radius_ + localization_error_) + separation_margin_;
    double smallest_clearance = std::numeric_limits<double>::infinity();
    std::string closest_peer = "none";
    if (local.received) {
      for (const auto & name : robot_names_) {
        if (name == local_robot_) {
          continue;
        }
        const auto & peer = observations_.at(name);
        if (!peer.received) {
          continue;
        }
        const double offset_x = peer.x - local.x;
        const double offset_y = peer.y - local.y;
        const double distance = std::hypot(offset_x, offset_y);
        const double inverse_distance = distance > 1e-9 ? 1.0 / distance : 0.0;
        const double direction_x = offset_x * inverse_distance;
        const double direction_y = offset_y * inverse_distance;
        const double local_closing_speed = std::max(
          0.0, local.velocity_x * direction_x + local.velocity_y * direction_y);
        const double peer_closing_speed = std::max(
          0.0, -peer.velocity_x * direction_x - peer.velocity_y * direction_y);
        const double pair_required =
          2.0 * (robot_radius_ + localization_error_) + separation_margin_ +
          stopping_distance(local_closing_speed, reaction_seconds_, maximum_deceleration_) +
          stopping_distance(peer_closing_speed, reaction_seconds_, maximum_deceleration_);
        const double clearance = distance - pair_required;
        if (clearance < smallest_clearance) {
          smallest_clearance = clearance;
          closest_distance = distance;
          required_separation = pair_required;
          closest_peer = name;
        }
      }
    }

    const bool stop = stale_count > 0 || smallest_clearance < 0.0;
    std_msgs::msg::Bool stop_message;
    stop_message.data = stop;
    stop_publisher_->publish(stop_message);

    diagnostic_msgs::msg::DiagnosticStatus status;
    status.name = "swarmroute/local_safety/" + local_robot_;
    status.hardware_id = local_robot_;
    if (stale_count > 0) {
      status.level = diagnostic_msgs::msg::DiagnosticStatus::STALE;
      status.message = "local safety observation is incomplete or stale";
    } else if (smallest_clearance < 0.0) {
      status.level = diagnostic_msgs::msg::DiagnosticStatus::ERROR;
      status.message = "local dynamic separation envelope violated";
    } else {
      status.level = diagnostic_msgs::msg::DiagnosticStatus::OK;
      status.message = "local safety envelope healthy";
    }
    status.values.push_back(value("closest_peer", closest_peer));
    status.values.push_back(value("closest_distance_m", std::to_string(closest_distance)));
    status.values.push_back(value("required_separation_m", std::to_string(required_separation)));
    status.values.push_back(value("stale_robot_count", std::to_string(stale_count)));
    diagnostic_msgs::msg::DiagnosticArray diagnostics;
    diagnostics.header.stamp = get_clock()->now();
    diagnostics.status.push_back(std::move(status));
    diagnostics_publisher_->publish(diagnostics);
  }

  static diagnostic_msgs::msg::KeyValue value(std::string key, std::string item)
  {
    diagnostic_msgs::msg::KeyValue result;
    result.key = std::move(key);
    result.value = std::move(item);
    return result;
  }

  std::string local_robot_;
  std::vector<std::string> robot_names_;
  std::vector<double> world_origin_xs_;
  std::vector<double> world_origin_ys_;
  std::vector<double> world_origin_yaws_;
  std::map<std::string, LocalObservation> observations_;
  std::vector<rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr> subscriptions_;
  double robot_radius_;
  double localization_error_;
  double reaction_seconds_;
  double maximum_deceleration_;
  double separation_margin_;
  double stale_after_seconds_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr stop_publisher_;
  rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr diagnostics_publisher_;
  rclcpp::TimerBase::SharedPtr timer_;
};

}  // namespace swarmroute_control

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<swarmroute_control::LocalSafetyMonitor>());
  rclcpp::shutdown();
  return 0;
}
