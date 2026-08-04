# syntax=docker/dockerfile:1.7

FROM nvidia/cuda:12.9.1-devel-ubuntu24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

ARG FIDESLIB_ARCH=86-real
ARG BUILD_JOBS=4

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    git \
    libomp-dev \
    patch \
    && rm -rf /var/lib/apt/lists/*

# This image contains only FIDESlib and its matching patched OpenFHE. The
# standard openfhe-python dependency used by the CPU image is not copied here.
COPY third_party/FIDESlib /src/FIDESlib

RUN patch \
      --directory=/src/FIDESlib/deps/openfhe-src \
      --strip=1 \
      --input=/src/FIDESlib/deps/fideslib-ref-1.5.1.1.patch

RUN cmake \
      -S /src/FIDESlib/deps/openfhe-src \
      -B /src/FIDESlib/deps/openfhe-build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/opt/openfhe \
      -DBUILD_STATIC=ON \
      -DBUILD_SHARED=OFF \
      -DBUILD_UNITTESTS=OFF \
      -DBUILD_EXAMPLES=OFF \
      -DBUILD_BENCHMARKS=OFF

RUN cmake --build /src/FIDESlib/deps/openfhe-build \
      --parallel "${BUILD_JOBS}" \
    && cmake --install /src/FIDESlib/deps/openfhe-build

RUN cmake \
      -S /src/FIDESlib \
      -B /src/FIDESlib/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DFIDESLIB_ARCH="${FIDESLIB_ARCH}" \
      -DFIDESLIB_INSTALL_OPENFHE=OFF \
      -DFIDESLIB_COMPILE_TESTS=OFF \
      -DFIDESLIB_COMPILE_BENCHMARKS=OFF \
      -DFIDESLIB_INSTALL_PREFIX=/opt/fideslib \
      -DOPENFHE_INSTALL_PREFIX=/opt/openfhe

RUN cmake --build /src/FIDESlib/build \
      --target install \
      --parallel "${BUILD_JOBS}"

COPY worker /src/worker

RUN cmake \
      -S /src/worker \
      -B /src/worker/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_PREFIX_PATH="/opt/fideslib;/opt/openfhe"

RUN cmake --build /src/worker/build --parallel "${BUILD_JOBS}"

# Compile and push only. Execute this image later on a GPU-enabled server.
ENTRYPOINT ["/src/worker/build/he-gpu-worker"]
