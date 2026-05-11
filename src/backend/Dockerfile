FROM dataelement/bisheng-backend:base.v8

WORKDIR /app

# ── DaMeng DPI native libraries (optional) ───────────────────────────────────
#
# dmPython / dmAsync Python packages are installed automatically from PyPI
# (see pyproject.toml).  They also need DaMeng's DPI shared libraries (.so)
# at runtime.  Two ways to provide them:
#
# Mode A — build-time inclusion (fully self-contained image):
#   1. Download the DaMeng DPI driver package from https://eco.dameng.com
#      and rename / place it as  dm_dpi_driver.tar.gz  next to this Dockerfile.
#      Expected layout inside the archive: bin/libdmdpi.so  (and siblings).
#   2. Build:  docker build --build-arg WITH_DAMENG=true -t bisheng:dm .
#
# Mode B — runtime mount (keeps the base image database-agnostic):
#   docker run \
#     -v /path/to/dameng/driver/bin:/opt/dmdbms/bin \
#     -e BISHENG_DATABASE_URL="dm+dmPython://..." \
#     bisheng:latest
#
# In both modes the env vars below are pre-set so the driver is found once
# the .so files are present.
# ─────────────────────────────────────────────────────────────────────────────

ARG WITH_DAMENG=false

# Always configure the expected library path; harmless when DaMeng is unused.
ENV DM_HOME=/opt/dmdbms
ENV LD_LIBRARY_PATH=/opt/dmdbms/bin:${LD_LIBRARY_PATH}

# Mode A only: extract DPI libs from the archive placed in the build context.
RUN --mount=type=bind,source=.,target=/build_ctx \
    if [ "$WITH_DAMENG" = "true" ]; then \
        archive=/build_ctx/dm_dpi_driver.tar.gz; \
        if [ ! -f "$archive" ]; then \
            echo "ERROR: WITH_DAMENG=true but dm_dpi_driver.tar.gz not found beside Dockerfile" >&2; \
            exit 1; \
        fi; \
        mkdir -p /opt/dmdbms && \
        tar -xzf "$archive" -C /opt/dmdbms && \
        echo "/opt/dmdbms/bin" > /etc/ld.so.conf.d/dameng.conf && \
        ldconfig && \
        echo "DaMeng DPI libraries installed."; \
    fi

COPY ./ ./

# 生成并安装依赖（dmPython / dmAsync 在 Linux 上由 pyproject.toml 自动包含）
RUN uv pip compile pyproject.toml --upgrade --output-file requirements.txt && \
    uv pip install -r requirements.txt --system --no-cache-dir && \
    uv cache clean && \
    rm -f requirements.txt


CMD ["sh entrypoint.sh"]
