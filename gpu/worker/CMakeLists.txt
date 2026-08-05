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

add_executable(
  he-gpu-worker
  src/fides_backend.cpp
  src/main.cpp
)
target_include_directories(
  he-gpu-worker
  PRIVATE
    src
    "${OpenFHE_INCLUDE}"
    "${OpenFHE_INCLUDE}/third-party/include"
    "${OpenFHE_INCLUDE}/core"
    "${OpenFHE_INCLUDE}/pke"
    "${OpenFHE_INCLUDE}/binfhe"
    "${CUDAToolkit_INCLUDE_DIRS}"
)
target_link_libraries(
  he-gpu-worker
  PRIVATE
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
