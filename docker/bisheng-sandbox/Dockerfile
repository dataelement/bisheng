# Isolation-environment image: backend venv + office binaries + runner HTTP.
# Build from the repository root (same Dockerfile for amd64 / arm64):
#   docker build -f docker/bisheng-sandbox/Dockerfile -t dataelement/bisheng-sandbox:v3.0.0-beta1 .
#
# Derived from src/backend/base.Dockerfile: full uv.lock venv, LibreOffice, pandoc,
# fonts, ffmpeg. Does NOT copy platform code, config.yaml, entrypoint.sh, or
# Chromium. Build-time compilers / wget are purged before the final layer.

FROM python:3.11-slim

ARG TARGETARCH
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NLTK_DATA=/usr/local/share/nltk_data \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Runtime office / media / fonts, plus compilers / wget / curl needed only to build.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc g++ build-essential wget curl ca-certificates \
        libreoffice-writer libreoffice-impress libreoffice-calc \
        libreoffice-java-common default-jre-headless \
        fonts-wqy-zenhei fontconfig \
        ffmpeg \
        libglib2.0-0 libsm6 libxrender1 libxext6 libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

# pandoc 3.6.4 → /usr/bin/pandoc. TARGETARCH matches Docker (amd64 / arm64).
RUN arch="${TARGETARCH:-amd64}" && \
    mkdir -p /opt/pandoc && \
    wget -q "https://github.com/jgm/pandoc/releases/download/3.6.4/pandoc-3.6.4-linux-${arch}.tar.gz" \
        -O /opt/pandoc/pandoc.tar.gz && \
    tar -xzf /opt/pandoc/pandoc.tar.gz -C /opt/pandoc && \
    cp /opt/pandoc/pandoc-3.6.4/bin/pandoc /usr/bin/pandoc && \
    rm -rf /opt/pandoc

# Same uv installer as src/backend/base.Dockerfile; removed after sync.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:/app/.venv/bin:$PATH"

# Full third-party venv, same lock as backend. --no-install-project keeps
# FastAPI / Celery / Linsight sources out of the image (AC-15 / AC-28).
COPY src/backend/pyproject.toml src/backend/uv.lock ./
RUN mkdir -p /usr/local/share/nltk_data && \
    uv sync --frozen --no-dev --no-install-project && uv cache clean && \
    python -c "import os, nltk; d=os.environ['NLTK_DATA']; nltk.download('punkt', download_dir=d); nltk.download('punkt_tab', download_dir=d); nltk.download('averaged_perceptron_tagger', download_dir=d); nltk.download('averaged_perceptron_tagger_eng', download_dir=d)" && \
    apt-get purge -y --auto-remove gcc g++ build-essential wget curl && \
    rm -rf /root/.cache /root/.local /var/lib/apt/lists/*
ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin"

# Playwright Python package arrives via uv.lock; do NOT install Chromium.

COPY src/sandbox-runner /opt/sandbox-runner
ENV PYTHONPATH="/opt/sandbox-runner"

RUN chmod -R a+rX /app /opt/sandbox-runner /usr/local/share/nltk_data

WORKDIR /opt/sandbox-runner
USER 65534

# Runner is PID 1. Compose must not publish 8080 to the host.
CMD ["python", "serve.py"]
