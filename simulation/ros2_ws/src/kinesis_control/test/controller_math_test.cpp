#include "kinesis_control/controller_math.hpp"

#include <cmath>

#include "gtest/gtest.h"

TEST(ControllerMath, NormalizesAcrossPi)
{
  const double pi = std::acos(-1.0);
  EXPECT_NEAR(kinesis_control::normalize_angle(3.0 * pi), pi, 1e-12);
  EXPECT_NEAR(kinesis_control::normalize_angle(-3.0 * pi), -pi, 1e-12);
}

TEST(ControllerMath, LimitsRateOfChange)
{
  EXPECT_DOUBLE_EQ(kinesis_control::move_towards(0.0, 1.0, 0.2), 0.2);
  EXPECT_DOUBLE_EQ(kinesis_control::move_towards(1.0, 0.0, 0.2), 0.8);
  EXPECT_DOUBLE_EQ(kinesis_control::move_towards(0.9, 1.0, 0.2), 1.0);
}

TEST(ControllerMath, ComputesReactionAndBrakingDistance)
{
  EXPECT_NEAR(kinesis_control::stopping_distance(0.75, 0.1, 1.5), 0.2625, 1e-12);
  EXPECT_DOUBLE_EQ(kinesis_control::stopping_distance(0.0, 0.1, 1.5), 0.0);
}

TEST(ControllerMath, ConvertsBetweenWorldAndLocalFrames)
{
  const double pi = std::acos(-1.0);
  const auto local = kinesis_control::world_to_local(8.0, 2.0, 10.0, 2.0, pi);
  EXPECT_NEAR(local.x, 2.0, 1e-12);
  EXPECT_NEAR(local.y, 0.0, 1e-12);

  const auto world = kinesis_control::local_to_world(local.x, local.y, 10.0, 2.0, pi);
  EXPECT_NEAR(world.x, 8.0, 1e-12);
  EXPECT_NEAR(world.y, 2.0, 1e-12);
}
