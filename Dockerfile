FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    HOST=0.0.0.0 \
    PORT=8080

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        libgomp1 \
        libomp-dev \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# GitLab CI builds this wheel once, verifies it, and downloads the artifact
# into the BuildKit context. Keeping it in the immutable CPU image lets a
# remote server install and test the exact SDK artifact without a compiler or
# access to the GitLab artifact API.
COPY dist/he_sdk-*.whl dist/SHA256SUMS /opt/he-sdk-wheel/
COPY compatibility/he-sdk-v1.toml /opt/he-sdk-wheel/compatibility.toml

COPY api ./api
COPY backends ./backends
COPY client/__init__.py client/cpu_service_demo.py ./client/
COPY common ./common
COPY he_sdk ./he_sdk
COPY openfhe_cpu ./openfhe_cpu

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()"]

CMD ["python", "-m", "api.app"]
