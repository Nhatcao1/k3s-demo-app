cmake_minimum_required(VERSION 3.25.2)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

project(he-gpu-worker LANGUAGES CXX)

find_package(fideslib REQUIRED CONFIG)
find_package(OpenFHE 1.5.1 EXACT REQUIRED CONFIG)
find_package(CUDAToolkit REQUIRED)
find_package(OpenMP REQUIRED COMPONENTS CXX)
find_package(Threads REQUIRED)

set(CMAKE_CXX_COMPILER "${FIDESLIB_CXX_COMPILER}")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${FIDESLIB_CXX_FLAGS}")

add_library(
  he_gpu_backend
  STATIC
  src/fides_backend.cpp
)
set_target_properties(he_gpu_backend PROPERTIES POSITION_INDEPENDENT_CODE ON)

target_include_directories(
  he_gpu_backend
  PUBLIC
    src
    "${OpenFHE_INCLUDE}"
    "${OpenFHE_INCLUDE}/third-party/include"
    "${OpenFHE_INCLUDE}/core"
    "${OpenFHE_INCLUDE}/pke"
    "${OpenFHE_INCLUDE}/binfhe"
    "${CUDAToolkit_INCLUDE_DIRS}"
)
target_link_libraries(
  he_gpu_backend
  PUBLIC
    fideslib::fideslib
    OPENFHEpke_static
    OPENFHEbinfhe_static
    OPENFHEcore_static
    CUDA::cudart
    CUDA::cuda_driver
    OpenMP::OpenMP_CXX
    Threads::Threads
    "${CMAKE_DL_LIBS}"
)

add_executable(he-gpu-worker src/main.cpp)
target_link_libraries(he-gpu-worker PRIVATE he_gpu_backend)

add_executable(he-gpu-demo src/demo_main.cpp)
target_link_libraries(he-gpu-demo PRIVATE he_gpu_backend)
