# Isolation-environment image: backend venv + office binaries + runner HTTP.
# Build from the repository root (same Dockerfile for amd64 / arm64):
#   docker build -f docker/bisheng-sandbox/Dockerfile -t dataelement/bisheng-sandbox:v3.0.0-beta1 .
#
# Derived from src/backend/base.Dockerfile: full uv.lock venv, LibreOffice, pandoc,
# fonts, ffmpeg. Does NOT copy platform code, config.yaml, entrypoint.sh, or
# Chromium. Build-time compilers / wget are purged before the final layer.
#
# CI: pass HTTP(S)_PROXY build-args (GitHub / Debian). Do not bake proxy into ENV —
# the running sandbox has no outbound (AC-12).

FROM python:3.11-slim

ARG TARGETARCH
ARG http_proxy
ARG https_proxy
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG no_proxy
ARG NO_PROXY

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NLTK_DATA=/usr/local/share/nltk_data \
    PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

# Official debian images wipe apt caches after each RUN; drop that so the
# BuildKit apt mounts actually survive to the next CI build on this host.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc g++ build-essential wget curl ca-certificates \
        libreoffice-writer libreoffice-impress libreoffice-calc \
        libreoffice-java-common default-jre-headless \
        fonts-wqy-zenhei fontconfig \
        ffmpeg \
        libglib2.0-0 libsm6 libxrender1 libxext6 libgl1 \
    && fc-cache -f

# pandoc 3.6.4 → /usr/bin/pandoc. TARGETARCH matches Docker (amd64 / arm64).
RUN arch="${TARGETARCH:-amd64}" && \
    wget -q "https://github.com/jgm/pandoc/releases/download/3.6.4/pandoc-3.6.4-linux-${arch}.tar.gz" \
        -O /tmp/pandoc.tar.gz && \
    tar -xzf /tmp/pandoc.tar.gz -C /tmp && \
    cp /tmp/pandoc-3.6.4/bin/pandoc /usr/bin/pandoc && \
    rm -rf /tmp/pandoc.tar.gz /tmp/pandoc-3.6.4

# uv from PyPI (tuna). Do not download the official installer from GitHub.
RUN pip install --no-cache-dir uv

# Full third-party venv, same lock as backend. --no-install-project keeps
# FastAPI / Celery / Linsight sources out of the image (AC-15 / AC-28).
COPY src/backend/pyproject.toml src/backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    mkdir -p /usr/local/share/nltk_data && \
    uv sync --frozen --no-dev --no-install-project && \
    python -c "import os, nltk; d=os.environ['NLTK_DATA']; nltk.download('punkt', download_dir=d); nltk.download('punkt_tab', download_dir=d); nltk.download('averaged_perceptron_tagger', download_dir=d); nltk.download('averaged_perceptron_tagger_eng', download_dir=d)" && \
    apt-get purge -y --auto-remove gcc g++ build-essential wget curl && \
    chmod -R a+rX /app /usr/local/share/nltk_data

# Playwright Python package arrives via uv.lock; do NOT install Chromium.

COPY --chmod=0555 src/sandbox-runner /opt/sandbox-runner
ENV PYTHONPATH="/opt/sandbox-runner"

WORKDIR /opt/sandbox-runner
USER 65534

# Runner is PID 1. Compose must not publish 8080 to the host.
CMD ["python", "serve.py"]
