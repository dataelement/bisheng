FROM python:3.11-slim

ARG PANDOC_ARCH=amd64
ENV PANDOC_ARCH=$PANDOC_ARCH
ENV PATH="${PATH}:/root/.local/bin"

WORKDIR /app

# 安装依赖（合并指令、清理缓存、禁用推荐包）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc g++ curl build-essential libreoffice \
    wget procps vim fonts-wqy-zenhei \
    libglib2.0-0 libsm6 libxrender1 libxext6 libgl1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*


# 安装 pandoc
RUN mkdir -p /opt/pandoc && \
    cd /opt/pandoc && \
    wget https://github.com/jgm/pandoc/releases/download/3.6.4/pandoc-3.6.4-linux-${PANDOC_ARCH}.tar.gz && \
    tar xvf pandoc-3.6.4-linux-${PANDOC_ARCH}.tar.gz && \
    cp pandoc-3.6.4/bin/pandoc /usr/bin/ && \
    rm -rf /opt/pandoc

# 安装 uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装 Poetry
#RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.2

# 安装 playwright 及 chromium：playwright 是 Python 包，版本锁定在 pyproject.toml，
# 此处单独安装一次并下载 chromium，后续 Dockerfile 构建时只要该版本不变就命中缓存。
# 注意：如果 playwright 升级，需重新 build base。
ARG PLAYWRIGHT_VERSION=1.57.0
RUN uv pip install playwright==${PLAYWRIGHT_VERSION} --system && \
    playwright install chromium && \
    playwright install-deps && \
    uv pip uninstall playwright --system

