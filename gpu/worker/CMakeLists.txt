cmake_minimum_required(VERSION 3.25.2)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

project(he-gpu-worker LANGUAGES CXX)

find_package(fideslib REQUIRED CONFIG)

set(CMAKE_CXX_COMPILER "${FIDESLIB_CXX_COMPILER}")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${FIDESLIB_CXX_FLAGS}")

add_executable(he-gpu-worker src/main.cpp)
target_link_libraries(he-gpu-worker PRIVATE fideslib::fideslib)
