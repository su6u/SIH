cmake_minimum_required(VERSION 3.16)
project(kinesis_bringup VERSION 0.1.0)

find_package(ament_cmake REQUIRED)
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})
ament_package()
