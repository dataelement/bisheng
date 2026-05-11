FROM dataelement/bisheng-backend:base.v8

WORKDIR /app

# ── DaMeng DPI native libraries (optional) ───────────────────────────────────
#
# dmPython / dmAsync Python packages are installed automatically from PyPI
# (see pyproject.toml).  They also need DaMeng's DPI shared libraries (.so)
# at runtime.
#
# To build a DaMeng-capable image in CI/CD:
#   1. Upload the DaMeng DPI driver archive to your artifact storage
#      (S3 / MinIO / Nexus / etc.).  The archive must unpack to a directory
#      whose bin/ sub-folder contains libdmdpi.so and siblings.
#   2. Pass the download URL as a build arg:
#
#      docker build \
#        --build-arg DM_DRIVER_URL=https://your-storage/dm_dpi_driver.tar.gz \
#        -t bisheng-backend:dm .
#
# Leave DM_DRIVER_URL empty (default) for a standard MySQL-only build.
# ─────────────────────────────────────────────────────────────────────────────

ARG DM_DRIVER_URL=""

# Pre-configure library paths; harmless when DaMeng is not used.
ENV DM_HOME=/opt/dmdbms
ENV LD_LIBRARY_PATH=/opt/dmdbms/bin:${LD_LIBRARY_PATH}

RUN if [ -n "$DM_DRIVER_URL" ]; then \
        echo "Downloading DaMeng DPI driver from $DM_DRIVER_URL ..." && \
        wget -q -O /tmp/dm_dpi_driver.tar.gz "$DM_DRIVER_URL" && \
        mkdir -p /opt/dmdbms && \
        tar -xzf /tmp/dm_dpi_driver.tar.gz -C /opt/dmdbms && \
        echo "/opt/dmdbms/bin" > /etc/ld.so.conf.d/dameng.conf && \
        ldconfig && \
        rm -f /tmp/dm_dpi_driver.tar.gz && \
        echo "DaMeng DPI libraries installed."; \
    fi

COPY ./ ./

# 生成并安装依赖（dmPython / dmAsync 在 Linux 上由 pyproject.toml 自动包含）
RUN uv pip compile pyproject.toml --upgrade --output-file requirements.txt && \
    uv pip install -r requirements.txt --system --no-cache-dir && \
    uv cache clean && \
    rm -f requirements.txt


CMD ["sh entrypoint.sh"]
