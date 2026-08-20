# syntax=docker/dockerfile:1.7

FROM nvidia/cuda:12.9.1-devel-ubuntu24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

ARG FIDESLIB_ARCH=75-real
ARG BUILD_JOBS=4

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    git \
    libomp-dev \
    patch \
    python3 \
    python3-dev \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# This image contains only FIDESlib and its matching patched OpenFHE. The
# standard openfhe-python dependency used by the CPU image is not copied here.
COPY gpu/third_party/FIDESlib /src/FIDESlib

RUN patch \
      --directory=/src/FIDESlib/deps/openfhe-src \
      --strip=1 \
      --input=/src/FIDESlib/deps/fideslib-ref-1.5.1.1.patch

RUN cmake \
      -S /src/FIDESlib/deps/openfhe-src \
      -B /src/FIDESlib/deps/openfhe-build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/opt/openfhe \
      -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
      -DBUILD_STATIC=ON \
      -DBUILD_SHARED=OFF \
      -DBUILD_UNITTESTS=OFF \
      -DBUILD_EXAMPLES=OFF \
      -DBUILD_BENCHMARKS=OFF \
      -DGIT_SUBMOD_AUTO=OFF

RUN cmake --build /src/FIDESlib/deps/openfhe-build \
      --parallel "${BUILD_JOBS}" \
    && cmake --install /src/FIDESlib/deps/openfhe-build

RUN cmake \
      -S /src/FIDESlib \
      -B /src/FIDESlib/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
      -DFIDESLIB_ARCH="${FIDESLIB_ARCH}" \
      -DFIDESLIB_INSTALL_OPENFHE=OFF \
      -DFIDESLIB_COMPILE_TESTS=OFF \
      -DFIDESLIB_COMPILE_BENCHMARKS=OFF \
      -DFIDESLIB_INSTALL_PREFIX=/opt/fideslib \
      -DOPENFHE_INSTALL_PREFIX=/opt/openfhe

RUN cmake --build /src/FIDESlib/build \
      --target install \
      --parallel "${BUILD_JOBS}"

# Build selected upstream examples as isolated CUDA/FIDESlib checks. They run
# entirely in native C++ and do not use the Python API or serialization bridge.
RUN set -eux; \
    for example in simple serial; do \
      cmake \
        -S "/src/FIDESlib/examples/${example}" \
        -B "/src/FIDESlib/examples/${example}/build" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_PREFIX_PATH="/opt/fideslib;/opt/openfhe"; \
      cmake --build "/src/FIDESlib/examples/${example}/build" \
        --parallel "${BUILD_JOBS}"; \
      install -m 0755 \
        "/src/FIDESlib/examples/${example}/build/${example}" \
        "/usr/local/bin/fides-${example}"; \
    done

COPY gpu/worker /src/worker
COPY gpu/he_sdk_fides /src/he_sdk_fides

RUN cmake \
      -S /src/worker \
      -B /src/worker/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_PREFIX_PATH="/opt/fideslib;/opt/openfhe"

RUN cmake --build /src/worker/build --parallel "${BUILD_JOBS}"

# Build the optional SDK plugin with the exact FIDESlib/patched-OpenFHE/CUDA
# toolchain used by the worker. The core he-sdk wheel remains separate.
RUN python3 -m venv /opt/fides-wheel-build \
    && /opt/fides-wheel-build/bin/python -m pip install \
      --disable-pip-version-check 'build>=1.2,<2'

RUN CMAKE_PREFIX_PATH="/opt/fideslib;/opt/openfhe" \
    /opt/fides-wheel-build/bin/python -m build \
      --wheel \
      --outdir /opt/he-sdk-fides-wheel \
      /src/he_sdk_fides

FROM scratch AS sdk-wheel
COPY --from=builder /opt/he-sdk-fides-wheel/ /

FROM builder AS sdk-worker

ARG VCS_REF=unknown
ARG SOURCE_URL=unknown
ARG BUILD_URL=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    HE_GPU_WORKER=/src/worker/build/he-gpu-worker \
    HE_GPU_DEVICE=0

WORKDIR /app

# The accelerator image consumes the same core wheel as the CPU worker plus
# the CUDA plugin wheel built with this image's patched OpenFHE/FIDES toolchain.
COPY dist/he_looming_sdk-*.whl dist/SHA256SUMS /opt/he-sdk-wheel/
COPY he_worker /app/he_worker
RUN python3 -m venv /opt/venv \
    && cd /opt/he-sdk-wheel \
    && sha256sum -c SHA256SUMS \
    && /opt/venv/bin/pip install --no-cache-dir --no-deps \
        he_looming_sdk-*.whl \
        /opt/he-sdk-fides-wheel/he_sdk_fides-*.whl \
    && /opt/venv/bin/pip install --no-cache-dir 'psycopg[binary]>=3.2,<4' \
    && /opt/venv/bin/python -c \
        'from he_sdk import HESession; from he_sdk_fides import FidesBackend; print("HE GPU worker runtime ready")'

RUN useradd --create-home --uid 10001 worker \
    && chown -R worker:worker /app

LABEL org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.url="${BUILD_URL}"

USER worker

ENTRYPOINT ["python", "-m", "he_worker"]

FROM builder AS runtime

ARG VCS_REF=unknown
ARG SOURCE_URL=unknown
ARG BUILD_URL=unknown

WORKDIR /app
COPY gpu/api /app/api

# Preserve the exact source and pipeline that produced a runtime image. These
# labels make a failure from the GPU cluster traceable to one GitLab commit.
LABEL org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.url="${BUILD_URL}"

ENV HE_GPU_WORKER=/src/worker/build/he-gpu-worker \
    HE_GPU_DEMO_WORKER=/src/worker/build/he-gpu-demo \
    HE_SDK_FIDES_WHEEL_DIR=/opt/he-sdk-fides-wheel \
    HOST=0.0.0.0 \
    PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=3)"]

# This image exposes only FIDESlib and its matching patched OpenFHE. It never
# installs or imports the standard openfhe-python package from the CPU image.
ENTRYPOINT ["python3", "-m", "api.app"]
