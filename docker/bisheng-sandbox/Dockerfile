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
# BuildKit .deb cache survives across CI builds. Do NOT cache /var/lib/apt —
# a failed proxy response there sticks as NODATA/NOSPLIT on the next build.
#
# deb.debian.org through the CI proxy returns invalid Release signatures; use
# tuna and keep the mirror on no_proxy (build-arg) so apt does not MITM.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' \
        /etc/apt/sources.list.d/debian.sources; \
    fi && \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g; s/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' \
        /etc/apt/sources.list; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc g++ build-essential wget curl ca-certificates \
        libreoffice-writer libreoffice-impress libreoffice-calc \
        libreoffice-java-common default-jre-headless \
        fonts-wqy-zenhei fontconfig \
        tini \
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

# Session uids (10000-10999) need passwd / group entries, or getpass.getuser()
# and pwd.getpwuid() raise KeyError inside user code. Written at build time:
# the runtime root filesystem is read-only.
RUN for uid in $(seq 10000 10999); do \
      echo "sandbox${uid}:x:${uid}:${uid}::/nonexistent:/usr/sbin/nologin" >> /etc/passwd; \
      echo "sandbox${uid}:x:${uid}:" >> /etc/group; \
    done

# matplotlib's default sans-serif list has no CJK glyphs, so Chinese titles
# render as boxes. The runner passes MATPLOTLIBRC through to user code.
RUN printf '%s\n' \
      'font.family: sans-serif' \
      'font.sans-serif: WenQuanYi Zen Hei, DejaVu Sans' \
      'axes.unicode_minus: False' \
      > /etc/matplotlibrc && chmod 0644 /etc/matplotlibrc
ENV MATPLOTLIBRC=/etc/matplotlibrc

WORKDIR /opt/sandbox-runner
USER 65534

# tini is PID 1 and reaps orphans that user code leaves behind (soffice's gpg
# helpers, fork loops); python as PID 1 never reaps them and the pids limit
# fills up. Compose must not set init: true on top (that would make tini PID 2).
# Compose must not publish 8080 to the host.
ENTRYPOINT ["tini", "--"]
CMD ["python", "serve.py"]
