cmake_minimum_required(VERSION 3.16)
project(kinesis_gazebo VERSION 0.1.0)

find_package(ament_cmake REQUIRED)
install(DIRECTORY config models worlds DESTINATION share/${PROJECT_NAME})
ament_package()
