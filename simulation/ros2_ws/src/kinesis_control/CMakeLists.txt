cmake_minimum_required(VERSION 3.16)
project(kinesis_control VERSION 0.1.0 LANGUAGES CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(ament_cmake REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(route_executor src/route_executor.cpp)
target_include_directories(route_executor PRIVATE include)
target_compile_options(route_executor PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
ament_target_dependencies(route_executor geometry_msgs nav_msgs rclcpp std_msgs)

add_executable(safety_monitor src/safety_monitor.cpp)
target_include_directories(safety_monitor PRIVATE include)
target_compile_options(safety_monitor PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
ament_target_dependencies(safety_monitor diagnostic_msgs nav_msgs rclcpp std_msgs)

add_executable(local_safety_monitor src/local_safety_monitor.cpp)
target_include_directories(local_safety_monitor PRIVATE include)
target_compile_options(local_safety_monitor PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
ament_target_dependencies(local_safety_monitor diagnostic_msgs nav_msgs rclcpp std_msgs)

install(TARGETS route_executor safety_monitor local_safety_monitor DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(controller_math_test test/controller_math_test.cpp)
  target_include_directories(controller_math_test PRIVATE include)
endif()

ament_package()
