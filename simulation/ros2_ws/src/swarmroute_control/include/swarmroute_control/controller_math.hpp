#pragma once

#include <algorithm>
#include <cmath>

namespace swarmroute_control
{

struct Point2D
{
  double x;
  double y;
};

inline double normalize_angle(double radians)
{
  return std::atan2(std::sin(radians), std::cos(radians));
}

inline double move_towards(double current, double target, double maximum_delta)
{
  return current + std::clamp(target - current, -maximum_delta, maximum_delta);
}

inline double stopping_distance(double speed, double reaction_seconds, double deceleration)
{
  const double magnitude = std::abs(speed);
  return magnitude * reaction_seconds + magnitude * magnitude / (2.0 * deceleration);
}

inline double quaternion_yaw(double x, double y, double z, double w)
{
  const double sin_yaw = 2.0 * (w * z + x * y);
  const double cos_yaw = 1.0 - 2.0 * (y * y + z * z);
  return std::atan2(sin_yaw, cos_yaw);
}

inline Point2D world_to_local(
  double world_x, double world_y, double origin_x, double origin_y, double origin_yaw)
{
  const double dx = world_x - origin_x;
  const double dy = world_y - origin_y;
  const double cosine = std::cos(origin_yaw);
  const double sine = std::sin(origin_yaw);
  return {cosine * dx + sine * dy, -sine * dx + cosine * dy};
}

inline Point2D local_to_world(
  double local_x, double local_y, double origin_x, double origin_y, double origin_yaw)
{
  const double cosine = std::cos(origin_yaw);
  const double sine = std::sin(origin_yaw);
  return {
    origin_x + cosine * local_x - sine * local_y,
    origin_y + sine * local_x + cosine * local_y};
}

}
