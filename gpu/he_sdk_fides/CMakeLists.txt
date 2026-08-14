cmake_minimum_required(VERSION 3.25.2)

project(he-sdk-fides LANGUAGES CXX)

find_package(pybind11 CONFIG REQUIRED)

# Compile the same high-level FIDES operation implementation used by the
# existing worker executable. EXCLUDE_FROM_ALL prevents the SDK wheel from
# unnecessarily building the HTTP worker and demo executables.
add_subdirectory(
  "${CMAKE_CURRENT_SOURCE_DIR}/../worker"
  "${CMAKE_CURRENT_BINARY_DIR}/worker"
  EXCLUDE_FROM_ALL
)

pybind11_add_module(_native MODULE native/bindings.cpp)
target_link_libraries(_native PRIVATE he_gpu_backend)
target_compile_features(_native PRIVATE cxx_std_20)

install(TARGETS _native LIBRARY DESTINATION he_sdk_fides)
