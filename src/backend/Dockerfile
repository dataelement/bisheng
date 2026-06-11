FROM dataelement/bisheng-backend:base.v8

WORKDIR /app

# 先装依赖再复制源码，利用 Docker 层缓存：uv.lock 不变时此层命中缓存
COPY ./pyproject.toml ./uv.lock ./
RUN uv sync --frozen --no-dev && uv cache clean
ENV PATH="/app/.venv/bin:$PATH"

# 安装 NLTK 数据（依赖 Python 环境，放在 uv sync 之后）
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab'); nltk.download('averaged_perceptron_tagger'); nltk.download('averaged_perceptron_tagger_eng')"

COPY ./ ./

# dmPython 附带的 dmssl 包含 libssl.so / libcrypto.so 等原生库。
# 将它们移入 bin/ 子目录，然后设置 DM_HOME，驱动即可找到这些库。
# dmPython / dmSQLAlchemy / dmAsync 在 Linux 上由 pyproject.toml 自动包含，
# 已由 base 镜像的 uv sync 安装到 venv，此处仅整理 .so 目录。
RUN SITE=$(python -c "import site; print(site.getsitepackages()[0])") && \
    DMSSL="$SITE/dmssl" && \
    if [ -d "$DMSSL" ]; then \
        mkdir -p "$DMSSL/bin" && \
        mv "$DMSSL"/*.so "$DMSSL/bin/" 2>/dev/null || true; \
    fi

# DM_HOME 指向 venv 内的 dmssl，与 base 镜像的 uv sync venv 路径保持一致。
ENV DM_HOME="/app/.venv/lib/python3.11/site-packages/dmssl/"

CMD ["sh", "entrypoint.sh"]
